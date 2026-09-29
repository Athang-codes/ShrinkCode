#!/usr/bin/env python3
"""selftest.py — one-command verification of the shipped shrinkcode skill.

Runs the bundled tooling against the curated inputs in ``fixtures/`` and pins
the behavior every README claim depends on: metrics are computed, duplicates
(including JS/TS structural ones) are found, config ``excludePaths`` are
honored, the plan partitioner accepts/rejects the right plans, the HTML report
stays self-contained, the CI report degrades on first run, and non-ASCII
identifiers survive the Node analyzer on a cp1252 Windows console.

    python3 scripts/selftest.py          # from the skill root (any OS)

Exit code 0 = everything usable (skips allowed for genuinely optional
prerequisites: Node + @babel for the AST passes, git for the CI report, bash
for the dead-code scan). Exit code 1 = at least one real failure; the details
print under the failing line.

Everything runs in temp directories — the skill tree is never written to, so
this is safe to run before every push.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
FIX = os.path.join(ROOT, "fixtures")
EMOJI = "\U0001F600"  # the non-ASCII fixture directory: fixtures/emoji-😀

PASSED = []
FAILED = []
SKIPPED = []


def report(ok, name, detail=""):
    """Record one assertion and print its line."""
    line = f"{'PASS' if ok else 'FAIL'}  {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    (PASSED if ok else FAILED).append((name, detail))


def skip(name, why):
    print(f"SKIP  {name} — {why}")
    SKIPPED.append((name, why))


def check(name, cond, detail=""):
    report(bool(cond), name, detail)
    return bool(cond)


def run_py(script, *args, cwd=ROOT, env_extra=None, drop_env=(), timeout=300):
    """Run a bundled script; return (rc, stdout, stderr), decoded as UTF-8.

    ``drop_env`` strips variables like PYTHONUTF8 so the child sees the same
    locale-encoding conditions a real user's shell would — that is exactly the
    condition the shared analyzer runner has to survive.
    """
    env = {k: v for k, v in os.environ.items() if k not in drop_env}
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, script), *args],
        capture_output=True, encoding="utf-8", errors="replace",
        cwd=cwd, env=env, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def run_raw(cmd, cwd=ROOT, timeout=300, env_extra=None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(cmd, capture_output=True, encoding="utf-8",
                          errors="replace", cwd=cwd, env=env, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def probe_analyzer():
    """True when the JS/TS AST pass can actually run end to end."""
    node = shutil.which("node") or shutil.which("node.exe")
    analyzer = os.path.join(SCRIPTS, "js_analyze.mjs")
    deps = os.path.join(ROOT, "node_modules", "@babel", "parser", "package.json")
    if not (node and os.path.isfile(analyzer) and os.path.isfile(deps)):
        return False
    rc, out, _ = run_raw([node, analyzer, os.path.join(FIX, "jsproj"),
                          "--mode", "functions"])
    try:
        return rc == 0 and isinstance(json.loads(out).get("functions"), list)
    except ValueError:
        return False


def probe(tool):
    """Locate an optional external tool (git/node/bash)."""
    if tool == "bash":
        found = shutil.which("bash") or shutil.which("bash.exe")
        if found:
            return found
        guess = r"C:\Program Files\Git\bin\bash.exe"
        return guess if os.path.isfile(guess) else None
    return shutil.which(tool) or shutil.which(tool + ".exe")


def dup_json(*args):
    rc, out, err = run_py("find_duplicates.py", *args, "--json")
    if rc != 0:
        return rc, None, err
    try:
        return rc, json.loads(out), None
    except ValueError:
        return rc, None, f"non-JSON output: {out[:300]}"


def counts(data):
    return (len(data.get("exact_clusters") or []),
            len(data.get("near_pairs") or []))


def save_snapshot(script, path, dest, *extra):
    """Run a metrics script's --save mode and return the parsed snapshot."""
    rc, out, err = run_py(script, path, "--save", dest, *extra)
    if rc != 0 or not os.path.isfile(dest):
        raise RuntimeError(f"{script} --save failed rc={rc} {err[:300]}")
    with open(dest, encoding="utf-8") as fh:
        return json.load(fh)


def test_compile():
    py_files = sorted(
        os.path.join(dp, f)
        for dp, _, files in os.walk(SCRIPTS) for f in files if f.endswith(".py"))
    bad = []
    for path in py_files:
        try:
            with open(path, encoding="utf-8") as fh:
                compile(fh.read(), path, "exec")
        except (SyntaxError, UnicodeDecodeError) as exc:
            bad.append(f"{os.path.basename(path)}: {exc}")
    check("compile: every scripts/*.py parses", not bad,
          "; ".join(bad) or f"{len(py_files)} files")

    node = probe("node")
    if not node:
        skip("compile: node --check", "node not installed")
        return
    bad = []
    for rel in ("scripts/js_analyze.mjs", ".github/shrinkcode-comment-sync.js",
                "fixtures/cifix/test_comment_sync.js"):
        rc, _, err = run_raw([node, "--check", os.path.join(ROOT, rel)])
        if rc != 0:
            bad.append(f"{rel}: {(err or 'syntax error')[:120]}")
    check("compile: node --check on the three JS files", not bad,
          "; ".join(bad) or "3 files")


def test_cli_help():
    clis = ("loc_report.py", "find_duplicates.py", "complexity_report.py",
            "generate_report.py", "ci_diff_report.py", "partition_batches.py",
            "coverage_gap_scaffold.py")
    bad = []
    for cli in clis:
        rc, out, err = run_py(cli, "--help")
        if rc != 0 or "usage:" not in (out + err).lower():
            bad.append(f"{cli} rc={rc}")
    check("cli: --help works on all 7 CLIs", not bad, "; ".join(bad) or "7 CLIs")

    bash = probe("bash")
    if not bash:
        skip("cli: checkpoint.sh usage", "bash not available")
    else:
        rc, out, err = run_raw([bash, os.path.join(SCRIPTS, "checkpoint.sh")])
        check("cli: checkpoint.sh prints usage without args",
              rc == 1 and "Usage" in (out + err), f"rc={rc}")


def test_config_excludes(tmp):
    dest = os.path.join(tmp, "loc_proj.json")
    snap = save_snapshot("loc_report.py", os.path.join(FIX, "proj"), dest)
    files = sorted(snap["per_file"])
    check("config: loc_report honors excludePaths (vendor/ gone)",
          len(files) == 1 and "src" in files[0],
          f"files={files}")

    # Control run: identical tree, config removed -> vendor/ must reappear,
    # proving the exclusion came from shrinkcode.config.json and nothing else.
    no_cfg = os.path.join(tmp, "proj_noconfig")
    if os.path.isdir(no_cfg):
        shutil.rmtree(no_cfg)
    shutil.copytree(os.path.join(FIX, "proj"), no_cfg)
    os.remove(os.path.join(no_cfg, "shrinkcode.config.json"))
    snap2 = save_snapshot("loc_report.py", no_cfg,
                          os.path.join(tmp, "loc_noconfig.json"))
    files2 = sorted(snap2["per_file"])
    check("config: without shrinkcode.config.json vendor/ is included",
          len(files2) == 2 and any("vendor" in f for f in files2),
          f"files={files2}")

    rc, data, err = dup_json(os.path.join(FIX, "proj"))
    check("config: find_duplicates honors excludePaths",
          rc == 0 and data is not None and "vendor" not in json.dumps(data),
          f"rc={rc} {err or ''}")


def test_duplicates(ast):
    def pins(name, args, expected_exact, expected_near):
        rc, data, err = dup_json(*args)
        if rc != 0 or data is None:
            check(name, False, f"rc={rc} {err or ''}")
            return
        exact, near = counts(data)
        want = expected_exact if isinstance(expected_exact, int) \
            else expected_exact(ast)
        check(name, exact == want and near == expected_near,
              f"exact={exact} (want {want}), near={near} (want {expected_near})")

    # Rust fixtures: comment stripping is a pure-text concern, so these pins
    # hold with or without Node.
    pins("dup: rust comment stripping (hard/)", [os.path.join(FIX, "hard")], 2, 0)
    # Python duplicates behind the fixture's excludePaths config.
    pins("dup: python fixture, vendor excluded",
         [os.path.join(FIX, "proj")], 0, 9)
    # Three independent modules: the cluster refs the plan fixtures cite.
    pins("dup: partfix/repo --min-lines 5",
         [os.path.join(FIX, "partfix", "repo"), "--min-lines", "5"], 6, 8)
    # JS/TS: near pairs come from the text pass (always pinned); the exact
    # cluster for the renamed twins exists only when the AST pass runs.
    pins("dup: jsproj (text pass / AST)", [os.path.join(FIX, "jsproj")],
         lambda ok: 1 if ok else 0, 7)
    pins("dup: emoji fixture (text pass / AST)",
         [os.path.join(FIX, "emoji-" + EMOJI)],
         lambda ok: 1 if ok else 0, 21)

    rc, data, err = dup_json(os.path.join(FIX, "emoji-" + EMOJI))
    blob = json.dumps(data, ensure_ascii=False) if data else ""
    check("dup: non-ASCII fixture path survives JSON round trip",
          rc == 0 and EMOJI in blob, f"rc={rc} emoji_in_json={EMOJI in blob}")


def test_semantic(ast):
    """--canonicalize acceptance: true pairs cluster, controls do not."""
    rc, data, err = dup_json(os.path.join(FIX, "semantic"), "--min-lines", "5")
    exact, near = counts(data) if data else (None, None)
    check("semantic: default pass finds no structural cluster",
          rc == 0 and exact == 0 and near == 23,
          f"rc={rc} exact={exact} near={near}")

    if not ast:
        skip("semantic: --canonicalize pins", "JS analyzer unavailable")
        return
    for label, folder, want_exact in (
            ("positive pairs cluster", "semantic", 3),
            ("literal-only boundary clusters", "semantic-boundary", 1),
            ("genuinely different guards do NOT cluster", "semantic-guards", 0)):
        rc, data, err = dup_json(os.path.join(FIX, folder), "--min-lines", "5",
                                 "--canonicalize")
        exact = counts(data)[0] if data else None
        check(f"semantic: {label}", rc == 0 and exact == want_exact,
              f"rc={rc} exact={exact} (want {want_exact})")


def test_complexity(ast, tmp):
    snap = save_snapshot("complexity_report.py", os.path.join(FIX, "proj"),
                         os.path.join(tmp, "cx_proj.json"))
    totals = snap.get("totals", {})
    check("complexity: python fixture totals (vendor excluded)",
          totals.get("functions") == 2 and totals.get("total_complexity") == 8
          and "vendor" not in json.dumps(snap),
          f"totals={totals}")

    if not ast:
        skip("complexity: jsproj JS pin", "JS analyzer unavailable")
    else:
        snap = save_snapshot("complexity_report.py", os.path.join(FIX, "jsproj"),
                             os.path.join(tmp, "cx_js.json"))
        totals = snap.get("totals", {})
        check("complexity: jsproj JS totals (AST pass)",
              totals.get("functions") == 3
              and totals.get("total_complexity") == 12,
              f"totals={totals}")

    # The cp1252 regression test: a Japanese identifier plus an emoji path must
    # come back intact from the Node analyzer, decoded as UTF-8, no crash.
    rc, out, _ = run_py("complexity_report.py",
                        os.path.join(FIX, "emoji-" + EMOJI),
                        drop_env=("PYTHONUTF8", "PYTHONIOENCODING"))
    identifier = "\u691c\u8a3c\u30e6\u30cb\u30c3\u30c8\u5024"  # 検証ユニット値
    check("complexity: non-ASCII identifier survives (no cp1252 crash)",
          rc == 0 and "\ufffd" not in out and (identifier in out or not ast),
          f"rc={rc} identifier={identifier in out} "
          f"analyzer={'on' if ast else 'off'}")


def _plan_payload(*args):
    rc, out, err = run_py("partition_batches.py", *args, "--json")
    try:
        return rc, (json.loads(out) if out.strip().startswith("{") else {}), err
    except ValueError:
        return rc, {}, err or out


def test_partition():
    rc, data, err = _plan_payload(os.path.join(FIX, "partfix", "plan3.json"))
    groups = (data or {}).get("groups") or []
    check("partition: 3 independent changes -> one parallel group",
          rc == 0 and data.get("groupCount") == 1 and len(groups) == 1
          and groups[0].get("changeIds") == [1, 2, 3]
          and not data.get("conflicts") and not data.get("deferred"),
          f"rc={rc} groups={data.get('groupCount')} "
          f"ids={groups[0].get('changeIds') if groups else None} "
          f"conflicts={data.get('conflicts')}")
    check("partition: final serial re-verification is mandatory",
          data.get("finalSerialVerification") == "required",
          f"value={data.get('finalSerialVerification')}")

    rc, data, err = _plan_payload(os.path.join(FIX, "partfix", "plan4.json"))
    conflicts = (data or {}).get("conflicts") or []
    same_file = any(c.get("a") == 1 and c.get("b") == 4 for c in conflicts)
    id4_alone = all(4 not in g.get("changeIds", []) or g.get("changeIds") == [4]
                    for g in (data or {}).get("groups", []))
    check("partition: same-file conflict is split, not parallelized",
          rc == 0 and data.get("groupCount") == 2 and same_file and id4_alone,
          f"rc={rc} groups={None if data is None else data.get('groupCount')} "
          f"conflicts={conflicts}")

    rc, data, err = _plan_payload(os.path.join(FIX, "partfix",
                                               "plan_cluster.json"))
    group_of = {cid: g["index"] for g in (data or {}).get("groups", [])
                for cid in g.get("changeIds", [])}
    split = all(group_of.get(i) != group_of.get(j)
                for i, j in ((10, 11), (10, 12), (11, 12)))
    reasons = " ".join(c.get("reason", "") for c in (data or {}).get("conflicts", []))
    check("partition: duplicate-cluster overlap splits cross-file changes",
          rc == 0 and split and "cluster" in reasons
          and any("duplicateCluster" in w for w in data.get("warnings", [])),
          f"rc={rc} group_of={group_of} reasons={reasons[:80]}")

    rc, data, err = _plan_payload(os.path.join(FIX, "partfix", "plan_tier.json"))
    deferred_ids = {d.get("id") for d in (data or {}).get("deferred", [])}
    check("partition: only Tier 1 is parallelized, rest deferred",
          rc == 0 and deferred_ids == {21, 22, 23}
          and data.get("groupCount") == 1,
          f"rc={rc} deferred={sorted(deferred_ids)} "
          f"groups={None if data is None else data.get('groupCount')}")

    rc, data, err = _plan_payload(os.path.join(FIX, "partfix", "plan_bad.json"))
    check("partition: invalid plan exits 2, never a silent partition",
          rc == 2 and not data and "tier" in err and "appears twice" in err,
          f"rc={rc} err={(err or '')[:120]}")


def test_report(tmp):
    """End-to-end before/after HTML report from freshly generated snapshots."""
    before = os.path.join(FIX, "proj")
    after = os.path.join(tmp, "after_proj")
    if os.path.isdir(after):
        shutil.rmtree(after)
    shutil.copytree(before, after)
    # Compress the fixture the way Phase 4 would: the two duplicated validators
    # collapse into one role-parameterized function (strictly fewer code lines).
    merged = ('import os\n'
              '\n'
              'def validate_person(name, email, admin=False):\n'
              '    if not name:\n'
              '        raise ValueError("name required")\n'
              '    if not email or "@" not in email:\n'
              '        raise ValueError("bad email")\n'
              '    person = {"name": name, "email": email}\n'
              '    if admin:\n'
              '        person["admin"] = True\n'
              '    return person\n'
              '\n'
              'RESULT = []\n'
              'for i in range(3):\n'
              '    if i % 2 == 0:\n'
              '        RESULT.append(i)\n')
    with open(os.path.join(after, "src", "app.py"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write(merged)

    work = os.path.join(tmp, "report")
    os.makedirs(work, exist_ok=True)
    loc_b = save_snapshot("loc_report.py", before, os.path.join(work, "loc_b.json"))
    loc_a = save_snapshot("loc_report.py", after, os.path.join(work, "loc_a.json"))
    save_snapshot("complexity_report.py", before, os.path.join(work, "cx_b.json"))
    save_snapshot("complexity_report.py", after, os.path.join(work, "cx_a.json"))
    for tag, target in (("b", before), ("a", after)):
        rc, data, err = dup_json(target)
        if rc != 0 or data is None:
            check("report: duplicate snapshots", False, f"rc={rc} {err or ''}")
            return
        with open(os.path.join(work, f"dup_{tag}.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(data, fh)

    out_html = os.path.join(work, "report.html")
    rc, out, err = run_py(
        "generate_report.py",
        "--loc-before", os.path.join(work, "loc_b.json"),
        "--loc-after", os.path.join(work, "loc_a.json"),
        "--complexity-before", os.path.join(work, "cx_b.json"),
        "--complexity-after", os.path.join(work, "cx_a.json"),
        "--duplicates", os.path.join(work, "dup_b.json"),
        "--duplicates-after", os.path.join(work, "dup_a.json"),
        "--batches", os.path.join(FIX, "reportfix", "batches.json"),
        "--plan", os.path.join(FIX, "reportfix", "plan.md"),
        "--output", out_html)
    html = ""
    if os.path.isfile(out_html):
        with open(out_html, encoding="utf-8") as fh:
            html = fh.read()
    check("report: generate_report writes the HTML file",
          rc == 0 and bool(html), f"rc={rc} bytes={len(html)} {err[:120]}")

    external = re.findall(r"https?://|<script[^>]+src=|<link[^>]+href=", html)
    check("report: HTML is self-contained (no network, no external refs)",
          bool(html) and not external, f"offenders={external[:3]}")
    check("report: batch manifest and plan both rendered",
          "9f2c1ab7" in html and "greet() looks trivially" in html
          and "plan.md" in html,
          f"batch_sha={'9f2c1ab7' in html} "
          f"plan_bullet={'greet() looks trivially' in html} "
          f"input_listed={'plan.md' in html}")
    before_lines = loc_b.get("totals", {}).get("code")
    after_lines = loc_a.get("totals", {}).get("code")
    check("report: before/after snapshots show a real reduction",
          isinstance(before_lines, int) and isinstance(after_lines, int)
          and after_lines < before_lines,
          f"code lines {before_lines} -> {after_lines}")

    # First-run style inputs: baseline only, no batches, no plan -> still renders.
    minimal = os.path.join(work, "minimal.html")
    rc, _, err = run_py("generate_report.py",
                        "--loc-before", os.path.join(work, "loc_b.json"),
                        "--output", minimal)
    check("report: minimal inputs degrade gracefully",
          rc == 0 and os.path.isfile(minimal) and os.path.getsize(minimal) > 500,
          f"rc={rc} {err[:120]}")


def test_ci_diff(tmp):
    git = probe("git")
    if not git:
        skip("ci: two-commit report", "git not available")
        return
    repo = os.path.join(tmp, "ci_repo")
    if os.path.isdir(repo):
        shutil.rmtree(repo)
    os.makedirs(repo)

    def git_in(*args):
        return run_raw([git, "-C", repo, "-c", "user.name=selftest",
                        "-c", "user.email=selftest@example.invalid",
                        "-c", "commit.gpgsign=false", *args])

    rc, _, err = git_in("init", "-b", "main")
    if rc != 0:
        rc, _, err = git_in("init")
    check("ci: temp git fixture initialized", rc == 0, err[:120])

    # Large enough that the duplicate clears the default --min-lines threshold,
    # so the PR comment really has a cluster to report.
    base_src = ("def greet(name):\n"
                "    if not name:\n"
                "        raise ValueError('name required')\n"
                "    return f'hello {name}'\n"
                "\n"
                "def unused_helper(x):\n"
                "    if x < 0:\n"
                "        return 0\n"
                "    return x * 2\n"
                "\n"
                "def farewell(name):\n"
                "    return f'bye {name}'\n")
    with open(os.path.join(repo, "app.py"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(base_src)
    git_in("add", "app.py")
    git_in("commit", "-m", "base")

    with open(os.path.join(repo, "app_copy.py"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(base_src)  # exact duplicate of app.py -> duplication delta
    git_in("add", "app_copy.py")
    git_in("commit", "-m", "add duplicated file")

    body = os.path.join(tmp, "comment.md")
    rc, out, err = run_py("ci_diff_report.py", "--base", "HEAD~1",
                          "--head", "HEAD", "--path", repo, "--output", body)
    text = ""
    if os.path.isfile(body):
        with open(body, encoding="utf-8") as fh:
            text = fh.read()
    check("ci: delta report for a two-commit diff",
          rc == 0 and "<!-- shrinkcode-bot -->" in text and "| Metric |" in text,
          f"rc={rc} marker={'<!-- shrinkcode-bot -->' in text} {err[:120]}")
    check("ci: duplicated file shows up in the report",
          "app_copy.py" in text, f"in_body={'app_copy.py' in text}")

    rc, out, err = run_py("ci_diff_report.py", "--base", "HEAD", "--head",
                          "HEAD", "--path", repo, "--output", body)
    text2 = ""
    if os.path.isfile(body):
        with open(body, encoding="utf-8") as fh:
            text2 = fh.read()
    check("ci: first run (nothing to compare) still succeeds",
          rc == 0 and "<!-- shrinkcode-bot -->" in text2,
          f"rc={rc} {err[:120]}")


def test_comment_sync():
    node = probe("node")
    if not node:
        skip("comment-sync: idempotent PR comment", "node not installed")
        return
    rc, out, err = run_raw([node, os.path.join(FIX, "cifix",
                                               "test_comment_sync.js"),
                            os.path.join(ROOT, ".github",
                                         "shrinkcode-comment-sync.js")])
    check("comment-sync: create/update/cleanup simulation",
          rc == 0 and "all assertions passed" in (out + err),
          f"rc={rc} {(out + err)[:160]}")


def test_coverage_scaffold(tmp):
    work = os.path.join(tmp, "covfix")
    if os.path.isdir(work):
        shutil.rmtree(work)
    shutil.copytree(os.path.join(FIX, "covfix"), work)
    stubs = os.path.join(work, "stubs")

    def scaffold():
        rc, out, err = run_py("coverage_gap_scaffold.py",
                              os.path.join(work, "sample.py"),
                              "--no-coverage-run", "--json",
                              "--emit-dir", stubs)
        try:
            return rc, json.loads(out), err
        except ValueError:
            return rc, None, err or out

    rc, summary, _ = scaffold()
    written = [f for f in os.listdir(stubs) if f.endswith(".py")] \
        if os.path.isdir(stubs) else []
    check("coverage: fully-covered module gets no stubs",
          rc == 0 and isinstance(summary, dict) and summary.get("python") == []
          and not written,
          f"rc={rc} stubs={written}")

    # Flip one function to zero coverage: the scaffold must now emit a stub
    # for exactly that function, carrying the no-fabrication TODO marker.
    cov_path = os.path.join(work, "coverage.json")
    with open(cov_path, encoding="utf-8") as fh:
        cov = json.load(fh)
    entry = cov["files"]["sample.py"]
    entry["executed_lines"] = [ln for ln in entry["executed_lines"]
                               if ln not in (19, 20, 21)]
    entry["functions"]["uncovered_second"]["executed_lines"] = []
    cov["totals"]["covered_lines"] -= 3
    with open(cov_path, "w", encoding="utf-8") as fh:
        json.dump(cov, fh)

    rc, summary, err = scaffold()
    first = ((summary or {}).get("python") or [{}])[0]
    stub_file = first.get("stub") or ""
    ok = (rc == 0 and first.get("action") == "written"
          and first.get("uncovered") == ["uncovered_second"]
          and os.path.isfile(stub_file))
    check("coverage: zero-coverage function gets a scoped stub", ok,
          f"rc={rc} entry={first} {err if isinstance(err, str) else ''}")
    if ok:
        with open(stub_file, encoding="utf-8") as fh:
            stub_src = fh.read()
        compiles = True
        try:
            compile(stub_src, stub_file, "exec")
        except SyntaxError as exc:
            compiles = False
            stub_src = str(exc)
        check("coverage: stub carries the TODO marker and compiles",
              "TODO(shrinkcode)" in stub_src and compiles,
              stub_src[:120])


def test_dead_code_scan():
    bash = probe("bash")
    if not bash:
        skip("dead-code: dead_code_scan.sh", "bash not available")
        return
    target = os.path.join(FIX, "jsproj").replace(os.sep, "/")
    rc, out, err = run_raw([bash, os.path.join(SCRIPTS, "dead_code_scan.sh"),
                            target])
    check("dead-code: scan runs to completion",
          rc == 0 and "Done." in (out + err), f"rc={rc} {(out + err)[:160]}")


def test_hygiene():
    """Nothing published may carry a machine-specific path or local name."""
    git = probe("git")
    if not git:
        skip("hygiene: no machine paths in tracked files", "git not available")
        return
    rc, out, err = run_raw([git, "-C", ROOT, "ls-files"])
    if rc != 0:
        check("hygiene: git ls-files", False, err[:120])
        return
    # Needles are assembled at runtime so this file's own detector patterns
    # can never match this file (the checker must not flag itself).
    needles = ("C:" + "\\" + "Users", "NA" + "IK")
    bad = []
    for rel in out.splitlines():
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable — not a text-hygiene concern
        if any(needle in text for needle in needles):
            bad.append(rel)
    check("hygiene: no machine-specific paths in tracked files",
          not bad, f"offenders={bad}")


def main():
    print(f"shrinkcode selftest — {ROOT}")
    if not os.path.isdir(FIX):
        print("FAIL  fixtures/ is missing — run this from a full checkout")
        return 1
    ast = probe_analyzer()
    print(f"environment: js analyzer {'ON' if ast else 'OFF'} · "
          f"git {'yes' if probe('git') else 'no'} · "
          f"bash {'yes' if probe('bash') else 'no'}")
    print()

    tmp = tempfile.mkdtemp(prefix="shrinkcode-selftest-")
    try:
        test_compile()
        test_cli_help()
        test_config_excludes(tmp)
        test_duplicates(ast)
        test_semantic(ast)
        test_complexity(ast, tmp)
        test_partition()
        test_report(tmp)
        test_ci_diff(tmp)
        test_comment_sync()
        test_coverage_scaffold(tmp)
        test_dead_code_scan()
        test_hygiene()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("-" * 60)
    for name, detail in FAILED:
        print(f"FAIL  {name} — {detail}")
    print(f"{len(PASSED)} passed, {len(FAILED)} failed, {len(SKIPPED)} skipped")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())

