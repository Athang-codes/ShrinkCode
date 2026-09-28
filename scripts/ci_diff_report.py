#!/usr/bin/env python3
"""
ci_diff_report.py — PR bloat report for the shrinkcode GitHub Action (v2,
prompt #3). Computes LOC / complexity / duplication deltas for the files a
pull request changed, base branch vs PR head, and renders a Markdown comment
body that starts with the hidden `<!-- shrinkcode-bot -->` marker —
.github/workflows/shrinkcode.yml finds an existing comment by that marker and
edits it in place, so pushes never spam a new comment.

Callable standalone (no GitHub required):
    python3 scripts/ci_diff_report.py --base origin/main --head HEAD --output body.md
    python3 scripts/ci_diff_report.py --base origin/main --head HEAD --json

Design notes:
  * Scope: metrics cover the pull request's changed files only (the analysis
    runs over each tree, then results are filtered to the changed set), so the
    comment is about THIS pull request, not the repo's history.
  * First run / brand-new repo: if the base ref can't be resolved (unknown
    ref, no merge base), the report falls back to absolute numbers for the PR
    head plus an explanatory note — never an error, never a fake delta.
  * Strictness: comment-only by default (bloat going up is a team decision,
    not a tool default). Opt in with --fail-on-regression or by setting
    `ci.failOnRegression: true` in shrinkcode.config.json; then a regression
    exits 1 so the check fails.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MARKER = "<!-- shrinkcode-bot -->"

sys.path.insert(0, SCRIPT_DIR)
from shrinkcode_config import load_config, utf8_stdout  # noqa: E402  (path setup above)


# ---------------------------------------------------------------------------
# git plumbing
# ---------------------------------------------------------------------------

def git(*args, cwd=None, timeout=120):
    """Run git; returns (rc, stdout, stderr). Never raises on failure."""
    try:
        proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                              text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return 127, "", str(exc)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def repo_root(path):
    rc, out, _ = git("rev-parse", "--show-toplevel", cwd=path)
    return out if rc == 0 and out else os.path.abspath(path)


def resolve_ref(root, ref):
    """Short sha for a ref, or None when it doesn't resolve (first run)."""
    rc, out, _ = git("rev-parse", "--short", ref, cwd=root)
    return out if rc == 0 and out else None


def changed_files(root, base, head):
    """Repo-relative paths changed between base and head (3-dot: merge base).
    None means the diff itself couldn't be computed (unknown base ref)."""
    rc, out, _ = git("diff", "--name-only", f"{base}...{head}", cwd=root)
    if rc != 0:
        return None
    return [line.strip().replace("\\", "/") for line in out.splitlines()
            if line.strip()]


def make_base_worktree(root, ref):
    """Detached worktree of the base commit. None when git can't create it."""
    target = os.path.join(tempfile.gettempdir(),
                          f"shrinkcode-base-{uuid.uuid4().hex[:10]}")
    rc, _, err = git("worktree", "add", "--detach", target, ref, cwd=root)
    if rc != 0:
        shutil.rmtree(target, ignore_errors=True)
        if err:
            sys.stderr.write(f"ci_diff_report: worktree add failed: {err}\n")
        return None
    return target


def remove_worktree(root, target):
    if not target:
        return
    git("worktree", "remove", "--force", target, cwd=root)
    git("worktree", "prune", cwd=root)
    shutil.rmtree(target, ignore_errors=True)


def norm_rel(path, root):
    """Comparable path key: repo-relative, forward slashes, case-folded
    (Windows checkouts are case-insensitive; git's output is not)."""
    p = os.path.abspath(path)
    r = os.path.abspath(root)
    try:
        rel = os.path.relpath(p, r)
    except ValueError:  # different drives
        rel = p
    if rel.startswith(".."):
        rel = p
    return rel.replace("\\", "/").lower()


def norm_git_path(path):
    return path.replace("\\", "/").lower()


# ---------------------------------------------------------------------------
# collectors: run the existing scripts over one tree, filter to changed files
# ---------------------------------------------------------------------------

def run_script(argv, cwd=None, timeout=600):
    """Run one of the bundled scripts; returns (rc, stdout, stderr)."""
    cmd = [sys.executable, os.path.join(SCRIPT_DIR, argv[0]), *argv[1:]]
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                              timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return 127, "", str(exc)
    return proc.returncode, proc.stdout, proc.stderr


def load_json_file(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def collect_loc(tree_root, changed, tmpdir, tag):
    """{code, files} summed over changed files that exist in this tree."""
    snapshot = os.path.join(tmpdir, f"loc_{tag}.json")
    rc, _, err = run_script(["loc_report.py", tree_root, "--save", snapshot])
    if rc != 0 or not os.path.isfile(snapshot):
        return None, f"loc_report.py failed on {tag}: {err.strip()[:200]}"
    data = load_json_file(snapshot)
    # changed=None (first run, no base diff) -> scope is the whole tree
    wanted = None if changed is None else {norm_git_path(c) for c in changed}
    code = files = 0
    for path, counts in (data.get("per_file") or {}).items():
        if wanted is None or norm_rel(path, tree_root) in wanted:
            code += counts.get("code", 0)
            files += 1
    return {"code": code, "files": files}, None


def _totals_from_functions(entries):
    if not entries:
        return {"functions": 0, "total_complexity": 0, "avg_complexity": 0.0,
                "max_complexity": 0}
    total = sum(e.get("complexity", 0) for e in entries)
    return {
        "functions": len(entries),
        "total_complexity": total,
        "avg_complexity": round(total / len(entries), 2),
        "max_complexity": max(e.get("complexity", 0) for e in entries),
    }


def collect_complexity(tree_root, changed, tmpdir, tag):
    """Per-function complexity for changed files, totals recomputed scoped."""
    snapshot = os.path.join(tmpdir, f"cx_{tag}.json")
    rc, _, err = run_script(["complexity_report.py", tree_root,
                             "--save", snapshot])
    if rc != 0 or not os.path.isfile(snapshot):
        return None, f"complexity_report.py failed on {tag}: {err.strip()[:200]}"
    data = load_json_file(snapshot)
    wanted = None if changed is None else {norm_git_path(c) for c in changed}
    entries = [e for e in (data.get("per_function") or [])
               if wanted is None or norm_rel(e.get("file", ""), tree_root) in wanted]
    return {"totals": _totals_from_functions(entries)}, None


def collect_duplicates(tree_root, changed, tmpdir, tag):
    """Exact clusters / near pairs involving at least one changed file."""
    rc, out, err = run_script(["find_duplicates.py", tree_root, "--json"])
    if rc != 0:
        return None, f"find_duplicates.py failed on {tag}: {err.strip()[:200]}"
    try:
        data = json.loads(out.lstrip("\ufeff"))
    except (ValueError, TypeError):
        return None, f"find_duplicates.py returned no JSON on {tag}"
    wanted = None if changed is None else {norm_git_path(c) for c in changed}

    def touches_cluster(cluster):
        for loc in cluster:
            path = loc.get("path", "") if isinstance(loc, dict) else loc[0]
            if wanted is None or norm_rel(path, tree_root) in wanted:
                return True
        return False

    def touches_pair(pair):
        for side in ("a", "b"):
            loc = pair.get(side) or {}
            if wanted is None or norm_rel(loc.get("path", ""), tree_root) in wanted:
                return True
        return False

    clusters = [c for c in (data.get("exact_clusters") or [])
                if touches_cluster(c)]
    pairs = [p for p in (data.get("near_pairs") or []) if touches_pair(p)]
    locations = []
    seen = set()
    for cluster in clusters:
        for loc in cluster:
            if isinstance(loc, dict):
                path, line = loc.get("path", ""), loc.get("line")
            elif isinstance(loc, (list, tuple)) and len(loc) == 2:
                path, line = loc[0], loc[1]
            else:
                continue
            # repo-relative in the comment: absolute checkout paths are noise
            # (and GitHub can't turn them into links either way)
            rel = os.path.relpath(os.path.abspath(str(path)),
                                  tree_root).replace("\\", "/")
            if rel.startswith(".."):
                rel = str(path)
            entry = f"{rel}:{line}"
            if entry not in seen:
                seen.add(entry)
                locations.append(entry)
    return {"exact_clusters": len(clusters), "near_pairs": len(pairs),
            "locations": locations}, None


# ---------------------------------------------------------------------------
# rendering: Markdown comment body (with the hidden marker)
# ---------------------------------------------------------------------------

def md_number(value, decimals=0):
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.{decimals}f}"
    return f"{int(value):,}"


def md_row(label, base, head, decimals=0, lower_is_better=True):
    """| metric | base | PR | signed delta | — green when it moved the right
    way, warning arrow when it regressed, plain when it didn't move."""
    if base is None or head is None:
        delta = "—"
    else:
        d = head - base
        pct = f"{d / base * 100:+.1f}%" if base else "n/a"
        if d == 0:
            flag = ""
        else:
            good = (d < 0) if lower_is_better else (d > 0)
            flag = " ✅" if good else " ⚠️"
        delta = f"{d:+,.{decimals}f} ({pct}){flag}"
    return (f"| {label} | {md_number(base, decimals)} | "
            f"{md_number(head, decimals)} | {delta} |")


def render_markdown(res, top=10):
    lines = [MARKER, ""]
    if res["first_run"]:
        lines += [
            "### shrinkcode: absolute metrics (first run)", "",
            f"> Base ref `{res['base']}` could not be compared against — new "
            "repository, missing fetch, or no merge base yet. Showing absolute "
            "numbers for this pull request instead of a delta.", "",
        ]
    else:
        lines += [f"### shrinkcode: bloat report — `{res['head']}` vs "
                  f"`{res['base']}`", ""]

    lines += [
        "| Metric | Base | PR | Δ |",
        "| --- | ---: | ---: | --- |",
        md_row("Code lines", res["loc"]["base"], res["loc"]["head"]),
        md_row("Avg complexity", res["complexity"]["base"],
               res["complexity"]["head"], decimals=2),
        md_row("Exact duplicate clusters", res["duplicates"]["base"],
               res["duplicates"]["head"]),
        "",
    ]

    locations = res["duplicates"]["head_locations"]
    if locations:
        lines += [
            f"**Duplicate locations** ({len(locations)} — clusters involving "
            "a changed file; the matching copy may predate this PR):", "",
        ]
        for loc in locations[:top]:
            safe = loc.replace("|", "\\|")
            lines.append(f"- `{safe}`")
        if len(locations) > top:
            lines.append(f"- … and {len(locations) - top} more")
        lines.append("")
    elif not res["first_run"] and res["duplicates"]["head"] is not None:
        lines += ["**Duplicate locations:** none — no exact "
                  "duplicate cluster touches a changed file.", ""]

    if res["regression"] is True:
        if res["strict"]:
            lines += ["> ❌ **Strict mode:** metrics regressed "
                      "(`ci.failOnRegression` / `--fail-on-regression`).", ""]
        else:
            lines += ["> ⚠️ Metrics went up — comment-only mode, this check is "
                      "not failing. Set `ci.failOnRegression` to enforce.", ""]
    elif res["regression"] is False:
        lines += ["> ✅ No bloat regression in this pull request.", ""]

    if res["notes"]:
        lines += ["<details><summary>Notes</summary>", ""]
        lines += [f"- {n}" for n in res["notes"]]
        lines += ["", "</details>", ""]

    scope = ("changed files only" if res["changed_files"] is not None
             else "whole tree (no base diff available)")
    lines.append(f"<sub>scope: {scope} · generated by "
                 "`scripts/ci_diff_report.py`</sub>")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def collect_side(tree_root, changed, tmpdir, tag):
    """All three metrics for one side; returns (results, error notes)."""
    results = {}
    errors = []
    for key, collector in (("loc", collect_loc),
                           ("complexity", collect_complexity),
                           ("duplicates", collect_duplicates)):
        value, err = collector(tree_root, changed, tmpdir, tag)
        results[key] = value
        if err:
            errors.append(err)
    return results, errors


def side_failed(side):
    return side is not None and not any(side.get(k) for k in
                                        ("loc", "complexity", "duplicates"))


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(
        description="PR bloat report: LOC / complexity / duplication deltas vs "
                    "the base branch, rendered as a Markdown comment body "
                    f"(hidden marker {MARKER!r})")
    ap.add_argument("--base", default=None,
                    help="base ref (default: origin/$GITHUB_BASE_REF, else "
                         "origin/main)")
    ap.add_argument("--head", default="HEAD", help="head ref (default: HEAD)")
    ap.add_argument("--path", default=".", help="repository to analyze")
    ap.add_argument("--output", help="write the Markdown body to this file "
                                     "(otherwise it goes to stdout)")
    ap.add_argument("--json", action="store_true",
                    help="emit a machine-readable JSON payload instead")
    ap.add_argument("--fail-on-regression", action="store_true",
                    help="exit 1 when LOC, duplication or average complexity "
                         "went up (config equivalent: ci.failOnRegression)")
    ap.add_argument("--top", type=int, default=10,
                    help="max duplicate locations listed in the body")
    args = ap.parse_args()

    if os.environ.get("GITHUB_BASE_REF") and not args.base:
        base_ref = f"origin/{os.environ['GITHUB_BASE_REF']}"
    else:
        base_ref = args.base or "origin/main"

    root = repo_root(args.path)
    config = load_config(root)
    strict = bool(args.fail_on_regression or
                  (config.get("ci") or {}).get("failOnRegression"))

    notes = []
    first_run = False
    base_tree = None
    changed = None
    base_sha = resolve_ref(root, base_ref)

    if base_sha is None:
        first_run = True
        notes.append(f"Base ref `{base_ref}` does not resolve — brand-new "
                     "repository, shallow fetch, or missing remote. Showing "
                     "absolute numbers instead of a delta.")
    else:
        changed = changed_files(root, base_ref, args.head)
        if changed is None:
            first_run = True
            notes.append(f"No merge base between `{base_ref}` and "
                         f"`{args.head}` — showing absolute numbers instead "
                         "of a delta.")
        else:
            base_tree = make_base_worktree(root, base_sha)
            if base_tree is None:
                first_run = True
                changed = None
                notes.append(f"Could not create a worktree for `{base_ref}` "
                             "— showing absolute numbers instead of a delta.")

    tmpdir = tempfile.mkdtemp(prefix="shrinkcode-ci-")
    try:
        head, head_errors = collect_side(root, changed, tmpdir, "head")
        notes.extend(head_errors)
        base, base_errors = (None, [])
        if base_tree:
            base, base_errors = collect_side(base_tree, changed, tmpdir, "base")
            notes.extend(base_errors)
    finally:
        if base_tree:
            remove_worktree(root, base_tree)
        shutil.rmtree(tmpdir, ignore_errors=True)

    def pick(side, metric, field=None):
        if not side or side.get(metric) is None:
            return None
        value = side[metric]
        return value.get(field) if field else value

    loc_base, loc_head = pick(base, "loc", "code"), pick(head, "loc", "code")
    cx_base = pick(base, "complexity", "totals")
    cx_head = pick(head, "complexity", "totals")
    avg_base = cx_base.get("avg_complexity") if cx_base else None
    avg_head = cx_head.get("avg_complexity") if cx_head else None
    dup_base = pick(base, "duplicates", "exact_clusters")
    dup_head = pick(head, "duplicates", "exact_clusters")
    head_locations = pick(head, "duplicates", "locations") or []

    # A regression is any metric that went up. Only comparable pairs count;
    # first run yields no pairs at all -> None ("cannot tell"), never False.
    comparisons = []
    if loc_base is not None and loc_head is not None:
        comparisons.append(loc_head > loc_base)
    if dup_base is not None and dup_head is not None:
        comparisons.append(dup_head > dup_base)
    if avg_base is not None and avg_head is not None:
        comparisons.append(avg_head > avg_base)
    regression = any(comparisons) if comparisons else None

    failed_analysis = side_failed(head) or (not first_run and side_failed(base))

    payload = {
        "marker": MARKER,
        "base": base_ref,
        "base_sha": base_sha,
        "head": args.head,
        "first_run": first_run,
        "strict": strict,
        "regression": regression,
        "analysis_failed": failed_analysis,
        "changed_files": changed,
        "loc": {"base": loc_base, "head": loc_head},
        "complexity": {"base": avg_base, "head": avg_head},
        "duplicates": {"base": dup_base, "head": dup_head,
                       "head_locations": head_locations},
        "notes": notes,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    elif args.output:
        body = render_markdown(payload, args.top)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(body)
        print(f"shrinkcode: loc {md_number(loc_base)} -> {md_number(loc_head)}, "
              f"clusters {md_number(dup_base)} -> {md_number(dup_head)}, "
              f"regression={regression}, strict={strict} -> {args.output}")
    else:
        sys.stdout.write(render_markdown(payload, args.top))

    # Comment-only by default: fail only under opt-in strict mode, and only
    # when there is something real to fail on (a regression, or an analysis
    # that produced nothing). First-run/uncomparable is never a failure.
    if strict and (regression is True or failed_analysis):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
