#!/usr/bin/env python3
"""
partition_batches.py — split a Phase 3 plan into independent Tier-1 batches that
can run concurrently (v2, prompt #8).

Reads the machine-readable `plan.json` that accompanies the human plan
(`references/compression-plan-template.md`), builds a conflict graph over the
Tier-1 changes, and greedily colors that graph into the fewest non-conflicting
groups. Two changes conflict when they:

  * touch the same file, or
  * share a duplicate cluster, or
  * have a target block that appears in the other change's duplicate cluster
    (two "fixes" to blocks that are copies of each other are not independent).

    python3 scripts/partition_batches.py plan.json
    python3 scripts/partition_batches.py plan.json --json

Scope is deliberately Tier 1 only: that is the tier where "these changes are
independent" is provable from the plan itself. Tier 2/3 changes — and any change
whose independence can't be shown (no files declared) — are reported under
`deferred` and never placed in a parallel group; they run serially in the normal
Phase 4 order.

A group assignment is a scheduling suggestion, not a safety guarantee. After all
groups land, the mandatory final full-suite serial re-verification still has to
run — see `references/parallel-execution.md`.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shrinkcode_config import utf8_stdout  # noqa: E402  (path setup above)


def norm_path(path):
    """Repo-relative, forward-slashed, case-folded — so two spellings of the
    same file conflict instead of silently passing as independent."""
    text = str(path).strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.casefold()


def norm_block(entry):
    """Canonical `path:line` key for a block reference. Accepts the string form
    (`"pkg/a.py:12"`) and the object form find_duplicates.py prints
    (`{"path": "pkg/a.py", "line": 12}`). Returns None when unusable."""
    if isinstance(entry, dict):
        path, line = entry.get("path"), entry.get("line")
        if path is None:
            return None
        return f"{norm_path(path)}:{line}" if line is not None else norm_path(path)
    if isinstance(entry, (list, tuple)) and len(entry) == 2:
        return f"{norm_path(entry[0])}:{entry[1]}"
    if isinstance(entry, str) and entry.strip():
        text = entry.strip()
        if ":" in text.rsplit("/", 1)[-1]:
            path, _, line = text.rpartition(":")
            return f"{norm_path(path)}:{line.strip()}"
        return norm_path(text)
    return None


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def load_plan(path):
    """Return (changes, warnings, errors). Never raises for bad content — the
    caller prints errors and exits non-zero, because a plan we can't read
    confidently must not silently become an empty partition."""
    errors, warnings, changes = [], [], []
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            plan = json.load(f)
    except FileNotFoundError:
        return [], [], [f"plan file not found: {path}"]
    except (OSError, ValueError) as exc:
        return [], [], [f"could not read {path}: {exc}"]

    raw_changes = plan.get("changes") if isinstance(plan, dict) else plan
    if isinstance(raw_changes, dict):
        # tolerate {"changes": {"1": {...}}} — id-as-key is a natural shape
        raw_changes = [dict(v, id=v.get("id", k))
                       for k, v in raw_changes.items() if isinstance(v, dict)]
    if not isinstance(raw_changes, list) or not raw_changes:
        return [], [], [f"{path}: no `changes` array to partition"]

    seen_ids = {}
    for index, raw in enumerate(raw_changes, start=1):
        if not isinstance(raw, dict):
            errors.append(f"change #{index}: not an object")
            continue
        cid = raw.get("id", index)
        tier = raw.get("tier")
        if not isinstance(tier, int):
            errors.append(f"change {cid!r}: `tier` must be an integer "
                          f"(got {tier!r})")
            continue
        files = [norm_path(p) for p in _as_list(raw.get("files")) if str(p).strip()]
        if not files:
            files = []
        cluster = {b for b in (norm_block(x) for x in
                               _as_list(raw.get("duplicateCluster")
                                        or raw.get("duplicate_cluster")))
                   if b}
        targets = {b for b in (norm_block(x) for x in
                               _as_list(raw.get("target")
                                        or raw.get("targetBlock")
                                        or raw.get("target_block")))
                   if b}
        key = str(cid)
        if key in seen_ids:
            errors.append(f"change id {cid} appears twice "
                          f"(#{seen_ids[key]} and #{index})")
            continue
        seen_ids[key] = index
        changes.append({
            "id": cid,
            "tier": tier,
            "category": raw.get("category") or "?",
            "files": files,
            "cluster": cluster,
            "targets": targets,
            "estLinesSaved": raw.get("estLinesSaved")
            or raw.get("est_lines_saved"),
            "description": raw.get("description") or raw.get("summary") or "",
        })
    if not changes and not errors:
        errors.append(f"{path}: no usable changes after parsing")
    blind = [c["id"] for c in changes if c["tier"] == 1 and not c["cluster"]]
    if blind:
        warnings.append(
            f"{len(blind)} tier-1 change(s) declare no `duplicateCluster` "
            f"(ids: {', '.join(str(i) for i in blind)}) — same-file conflicts "
            "are still caught, but 'two fixes to blocks that are copies of each "
            "other' cannot be detected for them")
    return changes, warnings, errors


def conflict(a, b):
    """(conflicts?, reason) for two changes. Reasons are user-facing text — the
    partition is only trustworthy if each exclusion explains itself."""
    shared = sorted(set(a["files"]) & set(b["files"]))
    if shared:
        return True, f"same file: {shared[0]}"
    overlap = sorted(a["cluster"] & b["cluster"])
    if overlap:
        return True, f"duplicate cluster overlap: {overlap[0]}"
    into_cluster = sorted((a["targets"] & b["cluster"])
                          | (b["targets"] & a["cluster"]))
    if into_cluster:
        return True, ("target block is inside the other change's duplicate "
                      f"cluster: {into_cluster[0]}")
    return False, None


def parallel_candidates(changes):
    """Tier 1 only, and only changes whose independence the plan can support.
    Everything else is deferred with a reason (never dropped silently)."""
    candidates, deferred = [], []
    for change in changes:
        if change["tier"] != 1:
            deferred.append({
                "id": change["id"], "tier": change["tier"],
                "category": change["category"], "files": change["files"],
                "reason": f"tier {change['tier']} is never parallelized "
                          "(parallel execution is scoped to tier 1)",
            })
        elif not change["files"]:
            deferred.append({
                "id": change["id"], "tier": change["tier"],
                "category": change["category"], "files": [],
                "reason": "no files declared — independence cannot be proven, "
                          "so it runs serially",
            })
        else:
            candidates.append(change)
    return candidates, deferred


def greedy_coloring(candidates):
    """First-fit graph coloring: put each change in the lowest-numbered group
    where it conflicts with nobody, else open a new group. Deterministic —
    plan order is preserved, so the same plan always yields the same groups."""
    groups, conflicts = [], []
    for change in candidates:
        placed_index, first_blockers = None, None
        for index, group in enumerate(groups):
            blockers = []
            for member in group["members"]:
                bad, reason = conflict(change, member)
                if bad:
                    blockers.append({"member": member["id"], "reason": reason})
                    conflicts.append({"a": member["id"], "b": change["id"],
                                      "reason": reason})
            if blockers:
                # every group scanned *before* the placement is a real reason
                # this change couldn't go earlier — worth showing the user
                if first_blockers is None:
                    first_blockers = blockers
                continue
            placed_index = index
            break
        if placed_index is None:
            change["blockedBy"] = first_blockers or []
            groups.append({"members": [change]})
        else:
            change["blockedBy"] = []
            groups[placed_index]["members"].append(change)
    for index, group in enumerate(groups, start=1):
        group["index"] = index
        group["files"] = sorted({f for m in group["members"] for f in m["files"]})
    return groups, conflicts


def build_payload(plan_path, groups, deferred, conflicts, warnings):
    return {
        "plan": plan_path,
        "groups": [{
            "index": group["index"],
            "changeIds": [m["id"] for m in group["members"]],
            "files": group["files"],
            "changes": [{
                "id": m["id"], "category": m["category"], "tier": m["tier"],
                "files": m["files"], "estLinesSaved": m["estLinesSaved"],
                "description": m["description"],
                "blockedBy": m.get("blockedBy") or [],
            } for m in group["members"]],
        } for group in groups],
        "deferred": deferred,
        "conflicts": conflicts,
        "warnings": warnings,
        "totalChanges": sum(len(g["members"]) for g in groups) + len(deferred),
        "parallelizable": sum(len(g["members"]) for g in groups),
        "groupCount": len(groups),
        # machine-readable statement of the safety net: after every group has
        # landed and been verified, ONE final full-suite serial verification
        # across the whole codebase is mandatory (file-level conflict checks
        # can't see shared fixtures, global state or import side effects).
        "finalSerialVerification": "required",
    }


def _estimate(value):
    return f" ~{value} lines" if value is not None else ""


def render_text(payload):
    groups, deferred = payload["groups"], payload["deferred"]
    lines = [
        f"shrinkcode: {payload['totalChanges']} planned changes -> "
        f"{payload['groupCount']} parallel group(s), "
        f"{payload['parallelizable']} parallelizable, {len(deferred)} deferred",
        "",
    ]
    if not groups:
        lines += ["No tier-1 change can run in parallel — execute the plan "
                  "serially in the normal Phase 4 order.", ""]
    for group in groups:
        ids = ", ".join(f"#{c['id']}" for c in group["changes"])
        lines.append(f"group {group['index']} — {len(group['changes'])} "
                     f"change(s) [{ids}] ({len(group['files'])} file(s), "
                     "run concurrently with the other groups)")
        for change in group["changes"]:
            lines.append(f"  #{change['id']} {change['category']} "
                         f"{', '.join(change['files'])}"
                         f"{_estimate(change['estLinesSaved'])}")
            for blocker in change["blockedBy"]:
                lines.append(f"      ↳ kept out of an earlier group: after "
                             f"#{blocker['member']} — {blocker['reason']}")
        lines.append("")
    if deferred:
        lines.append("deferred (serial, normal Phase 4 order):")
        for item in deferred:
            where = ", ".join(item["files"]) or "(no files declared)"
            lines.append(f"  #{item['id']} tier {item['tier']} "
                         f"{item['category']} — {where}: {item['reason']}")
        lines.append("")
    for warning in payload["warnings"]:
        lines.append(f"warning: {warning}")
    if payload["warnings"]:
        lines.append("")
    lines += [
        "Group assignment is a scheduling suggestion, not a safety guarantee:",
        "one subagent per group runs Phase 4 + Phase 5 against its own files,",
        "commits are sequenced (one group commits before the next starts), and",
        "**one final full-suite serial re-verification across the whole codebase",
        "is mandatory** once every group has landed — independent-looking files",
        "can still interact through shared fixtures, global state or import side",
        "effects. See references/parallel-execution.md.",
    ]
    return "\n".join(lines) + "\n"


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(
        description="Partition a Phase 3 plan.json into independent Tier-1 "
                    "batches that can run concurrently (see "
                    "references/parallel-execution.md). "
                    "--json emits {groups, deferred, conflicts, warnings, "
                    "finalSerialVerification}.")
    ap.add_argument("plan", help="path to plan.json (see "
                                 "references/compression-plan-template.md)")
    ap.add_argument("--json", action="store_true",
                    help="emit the partition as JSON instead of text")
    args = ap.parse_args()

    changes, warnings, errors = load_plan(args.plan)
    if errors:
        for err in errors:
            print(f"shrinkcode: {err}", file=sys.stderr)
        return 2

    candidates, deferred = parallel_candidates(changes)
    groups, conflicts = greedy_coloring(candidates)
    payload = build_payload(args.plan, groups, deferred, conflicts, warnings)

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        sys.stdout.write(render_text(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
