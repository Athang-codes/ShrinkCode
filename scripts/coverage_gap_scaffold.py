#!/usr/bin/env python3
"""
coverage_gap_scaffold.py — find exactly which lines/functions have zero
coverage in the files about to be compressed, and generate stub
characterization-test files targeting just those gaps.

Shrinkcode Phase 2 requires a characterization test for every code path
being compressed. This script automates finding the gaps and scaffolding
the stubs; you (the AI) then run the stubs once and pin the REAL output —
the script never invents an expected value, because a fabricated assertion
would silently encode a guess as "current behavior."

Python path: shells out to `coverage run -m pytest && coverage json`
(or config coverageCommand), parses coverage.json, and walks target functions
with the same ast logic as complexity_report.py. A suite that collects no tests
yet is treated as an empty (all-uncovered) baseline rather than a broken run.

JS/TS path: runs `vitest --coverage` or `jest --coverage` (config
coverageCommand wins), parses lcov.info, and maps function hits/ranges onto the
function list from `js_analyze.mjs --mode functions`.

Usage:
    python3 coverage_gap_scaffold.py <path> [more files...] \
        [--runner pytest|vitest|jest] [--emit-dir test] [--no-coverage-run]

Re-running is safe and only ever shrinks the generated stub set: a stub you
have already pinned is never rewritten, a generated-but-unpinned stub is held
out of the coverage run (so its own placeholder call can't make its target look
covered and delete the TODO you still have to fill in), and a stub with no
uncovered function left is removed.
"""
import argparse
import ast
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shrinkcode_config import (load_config, matches_exclude, run_js_analyzer,
                               utf8_stdout)

TODO_MARKER = "TODO(shrinkcode): run this once, record the ACTUAL output below as the pinned expected value - never invent an expected value"
TODO_COMMENT = f"# {TODO_MARKER}"


# ---------------------------------------------------------------------------
# Python coverage: run coverage + pytest, parse coverage.json
# ---------------------------------------------------------------------------

PYTEST_NO_TESTS_CODES = {5}  # pytest: "no tests collected" — an empty baseline
EMPTY_BASELINE_MARKERS = ("no data to report", "no data was collected")


def run_python_coverage(test_cmd, cwd, hold_out=()):
    """(coverage_map | None, reason | None) for the configured coverage command.

    `&&`-joined commands (the documented config example) are split and run in
    sequence so they work in PowerShell 5.1 as well as POSIX shells. Any
    pre-existing coverage.json is removed first and the sequence stops at the
    first non-zero exit: a suite that aborts mid-collection still leaves
    partial line data behind (and an older coverage.json may be sitting on
    disk), and deriving gaps from that would invent work that isn't real.

    `hold_out` lists unpinned scaffold stubs to exclude from the run (via
    PYTEST_ADDOPTS `--ignore`) so they can't count as coverage for their target.
    """
    json_paths = [os.path.join(cwd, "coverage.json"), os.path.join(cwd, ".coverage.json")]
    for path in json_paths:
        try:
            os.remove(path)
        except OSError:
            pass
    env = dict(os.environ)
    if hold_out and "pytest" in str(test_cmd):
        # An unpinned scaffold stub calls the target functions itself, so leaving
        # it visible would make the module look covered and drop TODOs that still
        # need pinning. pytest honors PYTEST_ADDOPTS; paths are made relative and
        # forward-slashed because shlex-based parsing eats Windows backslashes.
        ignores = []
        for path in hold_out:
            try:
                rel = os.path.relpath(path, cwd)
            except ValueError:  # different drive — pytest can still take an abs path
                rel = path
            rel = rel.replace(os.sep, "/")
            if not rel.startswith(".") and not os.path.isabs(rel):
                rel = "./" + rel
            ignores.append(f'--ignore="{rel}"')
        env["PYTEST_ADDOPTS"] = (env.get("PYTEST_ADDOPTS", "") + " "
                                 + " ".join(ignores)).strip()
    proc = None
    empty_baseline = False
    steps = [p.strip() for p in str(test_cmd).split("&&") if p.strip()]
    for step in steps:
        try:
            proc = subprocess.run(step, shell=True, cwd=cwd, env=env,
                                  capture_output=True, text=True, timeout=900)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"(coverage command step failed: {exc})")
            return None, f"coverage command could not run ({exc})"
        if proc.returncode != 0:
            combined = ((proc.stdout or "") + (proc.stderr or "")).lower()
            if proc.returncode in PYTEST_NO_TESTS_CODES and "pytest" in step:
                # pytest exits 5 for "no tests collected" — that's the empty
                # baseline this tool is most often pointed at, not a broken run,
                # and the coverage data it leaves behind is accurate (nothing ran,
                # so nothing is covered).
                print(f"(`{step}` collected no tests (exit 5) — treating the baseline "
                      "as empty; every function will look uncovered, which is the truth)")
                continue
            if any(marker in combined for marker in EMPTY_BASELINE_MARKERS):
                print(f"(`{step}` had no coverage data to write — the baseline is empty, "
                      "so nothing is covered yet)")
                empty_baseline = True
                continue
            print(f"(step failed with exit code {proc.returncode}: {step})")
            print(proc.stdout[-2000:] if proc.stdout else "")
            print(proc.stderr[-2000:] if proc.stderr else "")
            return None, (f"`{step}` exited {proc.returncode} - a test run that fails "
                          "or aborts measures nothing reliable")
    for candidate in json_paths:
        if os.path.isfile(candidate):
            try:
                with open(candidate, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError) as exc:
                return None, f"could not parse {os.path.basename(candidate)} ({exc})"
            return {os.path.abspath(os.path.join(cwd, k)): set(v.get("executed_lines", []))
                    for k, v in data.get("files", {}).items()}, None
    if empty_baseline:
        return {}, None
    print("(coverage.json not produced — install it with `pip install coverage`, "
          "or set coverageCommand in shrinkcode.config.json. Command output follows "
          "for diagnosis)")
    print(proc.stdout[-2000:] if proc and proc.stdout else "")
    print(proc.stderr[-2000:] if proc and proc.stderr else "")
    return None, "no coverage.json was produced"


def uncovered_python_functions(py_file, executed_lines):
    """Functions in py_file whose BODY has no overlap with coverage.

    The body range starts at the first statement, not at the `def` line:
    importing a module marks its `def` statements as executed even when the
    function is never called, so including the signature line would report
    every function as covered. A function with any executed body line counts
    as covered — partial coverage still means someone pinned some of its
    behavior; the remaining branches are covered by the "gnarliest edge
    cases" rule in references/verification.md.
    """
    try:
        with open(py_file, "r", encoding="utf-8", errors="ignore") as f:
            src = f.read()
        tree = ast.parse(src, filename=py_file)
    except (SyntaxError, OSError, ValueError):
        return []

    uncovered = []

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = f"{prefix}.{child.name}" if prefix else child.name
                end = getattr(child, "end_lineno", child.lineno)
                body_start = getattr(child.body[0], "lineno", child.lineno) if child.body else child.lineno
                if not any(ln in executed_lines for ln in range(body_start, end + 1)):
                    uncovered.append((qual, child))
                walk(child, qual)  # nested funcs checked independently
            elif isinstance(child, ast.ClassDef):
                qual = f"{prefix}.{child.name}" if prefix else child.name
                walk(child, qual)
            else:
                walk(child, prefix)

    walk(tree, "")
    return uncovered


# ---------------------------------------------------------------------------
# placeholder argument inference (type hints first, param-name heuristics after)
# ---------------------------------------------------------------------------

NAME_HEURISTICS = [
    (r"email", '"user@example.com"'),
    (r"(^|_)(name|label|tag)$", '"placeholder"'),
    (r"password", '"placeholder-password"'),
    (r"(^|_)(age|count|num|number|qty|quantity|id|year|index|offset|size|length"
     r"|limit|max|min|retries|attempts|tries|depth|width|height|port|total|amount"
     r"|price|score)$", "0"),
    (r"^(is|has|should|can|did|use|allow|enable|include|verify|with)", "True"),
    (r"(^|_)(flag|ok|valid|enabled|checked|active)$", "True"),
    (r"(^|_)(url|uri|link)$", '"https://example.com"'),
    (r"(^|_)(path|file|filename)$", '"placeholder.txt"'),
    (r"(^|_)(data|payload|body|obj|item|record|row)$", "{}"),
    (r"(^|_)(list|items|seq|values)$", "[]"),
    (r"(^|_)(date|time|timestamp)$", '"2000-01-01"'),
    (r"(^|_)(text|str|string|message|msg|content|title)$", '"placeholder"'),
]

TYPE_HINT_VALUES = {
    "str": '"placeholder"',
    "int": "0",
    "float": "0.0",
    "bool": "True",
    "list": "[]",
    "dict": "{}",
    "List": "[]",
    "Dict": "{}",
    "Any": "None",
    "Optional": "None",
}


def _ast_literal(node):
    try:
        return repr(ast.literal_eval(node))
    except (ValueError, SyntaxError):
        return "None"


def infer_placeholder_args(fn_node):
    """Build a call-argument string from the function signature.

    Type hints win; otherwise a param-name heuristic (email -> email
    string, etc.). Anything unmatched becomes None — a clearly-placeholder
    value beats a plausible-looking fabricated one.
    """
    parts = []
    args = fn_node.args
    all_args = list(getattr(args, "posonlyargs", [])) + list(args.args)
    defaults = list(args.defaults)
    default_offset = len(all_args) - len(defaults)  # defaults align to tail
    for i, arg in enumerate(all_args):
        name = arg.arg
        if name == "self":
            continue
        if i >= default_offset:
            parts.append(f"{name}={_ast_literal(defaults[i - default_offset])}")
            continue
        hint = ast.unparse(arg.annotation) if arg.annotation is not None else None
        if hint and hint in TYPE_HINT_VALUES:
            parts.append(f"{name}={TYPE_HINT_VALUES[hint]}")
            continue
        if hint and hint.startswith("Optional"):
            parts.append(f"{name}=None")
            continue
        matched = None
        for pattern, value in NAME_HEURISTICS:
            if re.search(pattern, name, re.IGNORECASE):
                matched = value
                break
        parts.append(f"{name}={matched or 'None'}")
    if args.vararg:
        parts.append(f"*{args.vararg.arg}()")
    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}={{}}")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# JS/TS coverage: run vitest/jest --coverage, parse lcov.info
# ---------------------------------------------------------------------------

RUNNER_DEFAULTS = {
    "vitest": "npx vitest run --coverage --coverage.reporter=lcov --coverage.reporter=json-summary",
    "jest": "npx jest --coverage --coverageReporters=lcov",
}
LCOV_CANDIDATES = ("coverage/lcov.info", "lcov.info", "coverage/js/lcov.info",
                   "coverage/lcov/lcov.info")


def parse_lcov(lcov_text, base_dir=None):
    """Parse lcov.info -> {abs_file: {"lines": set(covered), "fn_hits": {name: hits}}}.

    Both the DA (line hit) and FN/FNDA (function hit) records are read:
    FNDA gives an exact "was this function ever called" answer, while DA is
    the fallback for tools/configs that don't emit function records. Relative
    SF paths are resolved against `base_dir` (the directory the coverage
    command ran in), not the scaffolder's own working directory.
    """
    out = {}
    current = None
    for line in lcov_text.splitlines():
        line = line.strip()
        if line.startswith("SF:"):
            raw = line[3:].strip()
            if not os.path.isabs(raw):
                raw = os.path.join(base_dir or os.getcwd(), raw)
            current = os.path.abspath(raw)
            out.setdefault(current, {"lines": set(), "fn_hits": {}})
        elif line.startswith("DA:") and current is not None:
            try:
                lineno, hits = line[3:].split(",")[:2]
                if int(hits) > 0:
                    out[current]["lines"].add(int(lineno))
            except ValueError:
                continue
        elif line.startswith("FNDA:") and current is not None:
            try:
                hits, name = line[5:].split(",", 1)
                out[current]["fn_hits"][name.strip()] = int(hits)
            except ValueError:
                continue
    return out


def find_lcov_file(cwd):
    for rel in LCOV_CANDIDATES:
        candidate = os.path.join(cwd, rel.replace("/", os.sep))
        if os.path.isfile(candidate):
            return candidate
    # fall back to a shallow search (monorepos put it under packages/*/coverage)
    for base, dirs, files in os.walk(cwd):
        depth = os.path.relpath(base, cwd).count(os.sep)
        if depth > 3 or any(d in ("node_modules", ".git") for d in base.split(os.sep)):
            dirs[:] = []
            continue
        if "lcov.info" in files:
            return os.path.join(base, "lcov.info")
    return None


def run_js_coverage(test_cmd, cwd, hold_out=()):
    """Run the JS coverage command, parse lcov.info -> {abs_file: lines} | None.

    `hold_out` lists unpinned scaffold stubs; they are renamed to `.pending`
    around the run (no runner flag excludes a single test file without also
    dropping the project's own ignore patterns) and restored afterwards, so a
    stub's placeholder call can't masquerade as real coverage. On restore
    failure the file is left as `.pending` with a printed recovery hint —
    nothing is deleted.
    """
    if not test_cmd:
        return None
    held = []
    for path in hold_out:
        if os.path.isfile(path):
            pending = path + ".pending"
            try:
                os.replace(path, pending)
                held.append((pending, path))
            except OSError as exc:
                print(f"(could not hold {os.path.basename(path)} out of the run: {exc})")
    if held:
        print(f"(held {len(held)} unpinned scaffold stub(s) out of the coverage run; "
              "they are restored right after)")
    try:
        try:
            proc = subprocess.run(test_cmd, shell=True, cwd=cwd,
                                  capture_output=True, text=True, timeout=900)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"(JS coverage command failed to run: {exc})")
            return None
    finally:
        for pending, original in held:
            try:
                os.replace(pending, original)
            except OSError as exc:
                print(f"(restore failed: rename {pending} back to {original} by hand — {exc})")
    lcov = find_lcov_file(cwd)
    if not lcov:
        print("(no lcov.info produced — the coverage run must emit the lcov "
              "reporter, e.g. `vitest run --coverage --coverage.reporter=lcov`. "
              "Command output follows for diagnosis)")
        print(proc.stdout[-2000:] if proc.stdout else "")
        print(proc.stderr[-2000:] if proc.stderr else "")
        return None
    try:
        with open(lcov, "r", encoding="utf-8", errors="ignore") as f:
            return parse_lcov(f.read(), cwd)
    except OSError as exc:
        print(f"(could not read {lcov}: {exc})")
        return None


def detect_js_runner(target):
    """Best-effort runner detection: package.json deps/scripts, config files."""
    root = target if os.path.isdir(target) else os.path.dirname(target)
    pkg = os.path.join(root, "package.json")
    if os.path.isfile(pkg):
        try:
            with open(pkg, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        deps = {}
        for key in ("dependencies", "devDependencies"):
            deps.update(data.get(key) or {})
        if "vitest" in deps:
            return "vitest"
        if "jest" in deps:
            return "jest"
    for name, runner in (("vitest.config.ts", "vitest"), ("vitest.config.js", "vitest"),
                         ("vitest.config.mts", "vitest"), ("jest.config.js", "jest"),
                         ("jest.config.ts", "jest"), ("jest.config.cjs", "jest")):
        if os.path.isfile(os.path.join(root, name)):
            return runner
    return "vitest"  # shrinkcode's default suggestion for new projects


def js_functions_via_analyzer(target):
    """Call js_analyze.mjs --mode functions; return list | None if unavailable.

    The analyzer call goes through the shared runner in shrinkcode_config.py,
    so stdout is always decoded as UTF-8 (non-ASCII function names and paths
    survive on a cp1252 console) and Node resolution happens in one place.
    """
    def show_failure(_hint, stderr):
        print("(js_analyze.mjs --mode functions failed — run "
              "`npm install` in the skill folder. stderr follows)")
        print((stderr or "")[-1500:])

    data = run_js_analyzer([target, "--mode", "functions"],
                           on_error=show_failure)
    return None if data is None else data.get("functions", [])


def uncovered_js_functions(functions, entry):
    """Filter js_analyze.mjs function entries down to zero-coverage ones.

    `entry` is one parse_lcov() value ({"lines", "fn_hits"}), or None/{} when
    no lcov data exists for the file — in that case nothing can be scoped and
    every function is reported as a gap (the caller decides whether to write
    stubs in that situation).
    """
    lines = (entry or {}).get("lines") or set()
    fn_hits = (entry or {}).get("fn_hits") or {}
    gaps = []
    for fn in functions:
        name = fn.get("function") or "(anonymous)"
        start = fn.get("line") or 0
        end = fn.get("endLine") or start
        if "(anonymous)" in name:
            # inner callbacks aren't reachable from a test, and the enclosing
            # function's own stub exercises them — scaffolding them separately
            # would only add entries nobody can pin
            continue
        hits = fn_hits.get(name)
        if hits is None:
            hits = fn_hits.get(name.split(".")[-1])
        if hits is not None:
            # exact answer from lcov function records
            if hits > 0:
                continue
        elif any(ln in lines for ln in range(start + 1, end + 1)):
            # fallback: any executed line inside the body (line+1 skips the
            # declaration line, which istanbul marks covered at module load)
            continue
        if not start:
            continue
        gaps.append(fn)
    return gaps


JS_NAME_HEURISTICS = [
    (r"email", '"user@example.com"'),
    (r"(^|_)(name|label|tag|title|message|text|content)$", '"placeholder"'),
    (r"password", '"placeholder-password"'),
    (r"(^|_)(age|count|num|number|qty|quantity|id|year|index|offset|size|length"
     r"|limit|max|min|retries|attempts|tries|depth|width|height|port|total|amount"
     r"|price|score)$", "0"),
    (r"^(is|has|should|can|did|use|allow|enable|include|verify|with)", "true"),
    (r"(^|_)(flag|ok|valid|enabled|checked|active)$", "true"),
    (r"(^|_)(url|uri|link|href)$", '"https://example.com"'),
    (r"(^|_)(path|file|filename)$", '"placeholder.txt"'),
    (r"(^|_)(list|items|arr|array|values|rows)$", "[]"),
    (r"(^|_)(data|payload|body|obj|options|config|record|item)$", "{}"),
]


def js_placeholder_args(params):
    """Placeholder positional args for a JS function — same no-fabrication rule.

    Names ending in `data`/`options` style shape get `{}`, booleans get `true`,
    everything unmatched gets `null` (obvious placeholder beats a plausible
    guess that hides a type error).
    """
    parts = []
    for name in params:
        if name.startswith("..."):
            parts.append("/* TODO(shrinkcode): rest param — pass more args if needed */")
            continue
        if name in ("(destructured)", "(complex)"):
            parts.append("null /* TODO(shrinkcode): build the real shape */")
            continue
        value = "null"
        for pattern, replacement in JS_NAME_HEURISTICS:
            if re.search(pattern, name, re.IGNORECASE):
                value = replacement
                break
        parts.append(f"{value} /* {name} */")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# stub emission
# ---------------------------------------------------------------------------

STUB_HEADER_MARK = "Characterization tests scaffolded by shrinkcode"


def python_stub_source(target_root, py_file, gaps, executed_ok, stub_dir=None):
    """Full text of the pytest characterization stub for one module."""
    rel_module = os.path.relpath(py_file, target_root).replace(os.sep, "/")
    module_name = f"shrinkcode_target_{_ident(os.path.splitext(os.path.basename(py_file))[0])}"
    where = stub_dir or os.path.dirname(py_file)
    lines = [
        '"""',
        "Characterization tests scaffolded by shrinkcode (scripts/coverage_gap_scaffold.py).",
        "",
        f"Target module: {rel_module}",
        f"Uncovered functions at scaffold time: {len(gaps)}"
        + ("" if executed_ok else " (coverage data unavailable - see console output)"),
        "",
        "These tests intentionally assert NOTHING yet. Shrinkcode never invents an",
        "expected value: a fabricated assertion would silently encode a guess as",
        '"current behavior". Run the test once, read the printed ACTUAL value (or the',
        "recorded exception), then pin it where the TODO says to. After that this file",
        "is a real tripwire for the compression pass.",
        '"""',
        "import importlib.util",
        "import sys",
        "from pathlib import Path",
        "",
        f"_MODULE_PATH = (Path(__file__).resolve().parent / {_posix_rel(py_file, where)!r}).resolve()",
        "",
        "",
        "def _load_target():",
        f"    spec = importlib.util.spec_from_file_location({module_name!r}, _MODULE_PATH)",
        "    module = importlib.util.module_from_spec(spec)",
        "    sys.modules[spec.name] = module",
        "    spec.loader.exec_module(module)",
        "    return module",
        "",
    ]
    for qual, node in gaps:
        test_name = f"test_{_ident(qual.replace('.', '_'))}"
        arg_str = infer_placeholder_args(node)
        lines.extend([
            "",
            f"def {test_name}():",
            f"    {TODO_COMMENT}",
        ])
        if "." in qual:
            kind = "method" if _is_method(node) else "nested function"
            lines.extend([
                f"    # shrinkcode: this is a {kind} - a test can't call it without its",
                "    # receiver/outer inputs. Build them for real, call it, then pin the",
                "    # result with `assert actual == expected`.",
                f'    print("SKIPPED: {qual} needs a hand-built receiver - see the TODO above")',
            ])
        else:
            lines.extend([
                "    module = _load_target()",
                "    try:",
                f"        actual = module.{qual.split('.')[-1]}({arg_str})",
                "    except Exception as exc:  # recording the exception IS the behavior",
                '        print("ACTUAL: raised", type(exc).__name__, exc)',
                "        return",
                '    print("ACTUAL:", repr(actual))',
                "    # shrinkcode scaffold - replace the two commented lines with what you saw:",
                "    # expected = <value from ACTUAL above>",
                "    # assert actual == expected",
            ])
    return "\n".join(lines) + "\n"


def _is_method(node):
    args = node.args
    all_args = list(getattr(args, "posonlyargs", [])) + list(args.args)
    return bool(all_args) and all_args[0].arg in ("self", "cls")


def _ident(name):
    return re.sub(r"\W", "_", name) or "unnamed"


def _posix_rel(target_file, from_dir):
    """Forward-slash relative path from from_dir to target_file (pathlib-safe)."""
    return os.path.relpath(target_file, from_dir).replace(os.sep, "/")


def js_stub_source(target_root, js_file, gaps, runner, stub_dir):
    """Full text of the vitest/jest characterization stub for one module."""
    rel_module = os.path.relpath(js_file, target_root).replace(os.sep, "/")
    import_path = _posix_rel(js_file, stub_dir)
    if not import_path.startswith("."):
        import_path = "./" + import_path
    header = [
        "// Characterization tests scaffolded by shrinkcode",
        "// (scripts/coverage_gap_scaffold.py).",
        "//",
        f"// Target module: {rel_module}",
        f"// Uncovered functions at scaffold time: {len(gaps)}",
        "//",
        "// These tests intentionally assert NOTHING yet: shrinkcode never invents an",
        "// expected value, because a fabricated expectation silently encodes a guess as",
        '// "current behavior". Run once, read the logged ACTUAL value (or recorded',
        "// error), then pin it where the TODO says to.",
        "",
    ]
    if runner == "vitest":
        header.append('import { describe, it } from "vitest";')
        header.append("")
    header.append(f'import * as target from "{import_path}";')
    header.append("")
    lines = header
    for fn in gaps:
        name = fn.get("function") or "(anonymous)"
        lines.extend([
            "",
            f'describe("{name} (uncovered)", () => {{',
            '  it("pins current behavior", () => {',
            f"    // {TODO_MARKER}",
        ])
        if "." in name:
            lines.extend([
                f"    // shrinkcode: {name} is a class/object member - a test can't call it",
                "    // off the module. Build the receiver for real, call it, then pin the",
                "    // result with expect(actual).toEqual(<value from ACTUAL above>);",
                f'    console.log("SKIPPED: {name} needs a hand-built receiver - see the TODO above");',
            ])
        else:
            lines.extend([
                "    let actual;",
                "    try {",
                f"      actual = target.{name}({js_placeholder_args(fn.get('params') or [])});",
                "    } catch (err) {",
                "      actual = `${err.name}: ${err.message}`;",
                "    }",
                '    console.log("ACTUAL:", actual);',
                "    // shrinkcode scaffold - replace the commented line with what you saw:",
                "    // expect(actual).toEqual(<value from ACTUAL above>);",
            ])
        lines.extend(["  });", "});"])
    return "\n".join(lines) + "\n"


STUB_PINNED_PATTERNS = (
    re.compile(r"^\s*assert\s"),
    re.compile(r"^\s*expected\s*="),
    re.compile(r"^\s*expect\("),
)

SKIP_DIRS_SCAFFOLD = {
    "node_modules", ".git", "dist", "build", ".next", "__pycache__",
    ".venv", "venv", "coverage", ".turbo", "out", ".mypy_cache",
}
JS_EXTS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}


def stub_state(path):
    """('missing'|'generated'|'pinned', text) for an existing stub file."""
    if not os.path.isfile(path):
        return "missing", ""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except OSError:
        return "missing", ""
    if STUB_HEADER_MARK not in text:
        return "pinned", text  # hand-written file — never touch it
    for pattern in STUB_PINNED_PATTERNS:
        for line in text.splitlines():
            if pattern.match(line):
                return "pinned", text
    return "generated", text


def write_stub(path, source):
    """Write/refresh a generated stub; report what happened.

    Re-running only ever shrinks the stub set: a stub the user has already
    pinned is preserved, and modules that are now fully covered get their
    generated stub removed instead of regenerated.
    """
    state, _ = stub_state(path)
    if state == "pinned":
        return "preserved (already has pinned assertions)"
    with open(path, "w", encoding="utf-8") as f:
        f.write(source)
    return "written" if state == "missing" else "refreshed"


def prune_stub(path):
    """Delete a generated stub that no longer has any uncovered function."""
    state, _ = stub_state(path)
    if state == "generated":
        try:
            os.remove(path)
            return "removed (fully covered now)"
        except OSError:
            return "could not remove"
    if state == "pinned":
        return "kept (has pinned assertions)"
    return ""


def read_existing_coverage_json(cwd):
    """Parse a coverage.json already on disk (--no-coverage-run path)."""
    candidate = os.path.join(cwd, "coverage.json")
    if not os.path.isfile(candidate):
        return None
    try:
        with open(candidate, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as exc:
        print(f"(could not read existing coverage.json: {exc})")
        return None
    return {os.path.abspath(os.path.join(cwd, k)): set(v.get("executed_lines", []))
            for k, v in raw.get("files", {}).items()}


def _is_test_like(name):
    """True for test files — scaffolding characterization tests for tests is noise."""
    base = name.lower()
    return (base.startswith("test_") or base.endswith(("_test.py", "_test.js", "_test.ts",
                                                       "_test.jsx", "_test.tsx",
                                                       ".test.js", ".test.ts", ".test.jsx",
                                                       ".test.tsx", ".spec.js", ".spec.ts",
                                                       ".spec.jsx", ".spec.tsx"))
            or base == "conftest.py" or ".characterization." in base)


def collect_targets(paths, root, exclude):
    """Split the requested paths into (.py targets, JS/TS targets)."""
    py_targets, js_targets = [], []
    for raw in paths:
        target = os.path.abspath(raw)
        if os.path.isdir(target):
            for base, dirs, files in os.walk(target):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS_SCAFFOLD]
                for name in files:
                    if _is_test_like(name):
                        continue
                    full = os.path.join(base, name)
                    rel = os.path.relpath(full, root)
                    if matches_exclude(rel, exclude):
                        continue
                    ext = os.path.splitext(name)[1].lower()
                    if ext == ".py":
                        py_targets.append(full)
                    elif ext in JS_EXTS:
                        js_targets.append(full)
        else:
            if _is_test_like(os.path.basename(target)):
                continue
            ext = os.path.splitext(target)[1].lower()
            if ext == ".py":
                py_targets.append(target)
            elif ext in JS_EXTS:
                js_targets.append(target)
    return py_targets, js_targets


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(
        description="Scaffold characterization tests for zero-coverage target files")
    ap.add_argument("paths", nargs="+",
                    help="target files (or dirs) about to be compressed")
    ap.add_argument("--runner", choices=["pytest", "vitest", "jest"],
                    help="test runner override (default: auto-detect for JS)")
    ap.add_argument("--emit-dir", help="where to write stubs (default: next to each target)")
    ap.add_argument("--no-coverage-run", action="store_true",
                    help="don't run coverage; use the coverage.json/lcov.info already on disk")
    ap.add_argument("--json", action="store_true", help="machine-readable summary")
    args = ap.parse_args()

    root = os.path.abspath(args.paths[0])
    if os.path.isfile(root):
        root = os.path.dirname(root)
    config = load_config(root)
    exclude = config.get("excludePaths") or []

    py_targets, js_targets = collect_targets(args.paths, root, exclude)
    summary = {"python": [], "js": [], "notes": []}
    cwd = root
    stub_dir_arg = os.path.abspath(args.emit_dir) if args.emit_dir else None

    # --- Python path --------------------------------------------------------
    python_coverage_ok = False
    if py_targets:
        cmd = config.get("coverageCommand") or (
            "coverage run -m pytest -q && coverage json -o coverage.json")
        # Stub paths are computed up front: an unpinned generated stub calls its
        # target functions, so it has to be held out of the run that decides what
        # is covered (otherwise the scaffold would delete TODOs it just created).
        py_plan = []
        for py_file in py_targets:
            stub_dir = stub_dir_arg or os.path.dirname(py_file)
            base = _ident(os.path.splitext(os.path.basename(py_file))[0])
            py_plan.append((py_file, stub_dir, os.path.join(
                stub_dir, f"test_characterization_{base}.py")))
        hold_out = [stub for _, _, stub in py_plan if stub_state(stub)[0] == "generated"]
        if hold_out:
            summary["notes"].append(
                f"{len(hold_out)} unpinned scaffold stub(s) were excluded from the "
                "coverage run, so their own placeholder calls can't mark a target as "
                "covered. Pin their assertions to make them count.")
        data = None
        reason = None
        if args.no_coverage_run:
            data = read_existing_coverage_json(cwd)
            if data is None:
                reason = "--no-coverage-run was passed and no coverage.json is on disk"
        else:
            print(f"Running Python coverage: {cmd}")
            data, reason = run_python_coverage(cmd, cwd, hold_out)
        if data is None:
            summary["notes"].append(
                f"Python coverage unavailable ({reason}) — stubs were generated for ALL "
                "functions, so the gap list is a superset. Fix the run, or set "
                "coverageCommand in shrinkcode.config.json.")
            print(f"WARNING: Python coverage unavailable — {reason}. Every function in the "
                  "target files is being treated as a coverage gap.")
            data = {}
        else:
            python_coverage_ok = True
        for py_file, stub_dir, stub_path in py_plan:
            executed = data.get(os.path.abspath(py_file), set())
            gaps = uncovered_python_functions(py_file, executed)
            rel_module = os.path.relpath(py_file, root).replace(os.sep, "/")
            if not gaps:
                pruned = prune_stub(stub_path)
                if pruned:
                    summary["python"].append({"module": rel_module, "stub": stub_path,
                                              "action": pruned, "uncovered": []})
                continue
            os.makedirs(stub_dir, exist_ok=True)
            source = python_stub_source(root, py_file, gaps, python_coverage_ok, stub_dir)
            summary["python"].append({
                "module": rel_module,
                "stub": stub_path,
                "action": write_stub(stub_path, source),
                "uncovered": [q for q, _ in gaps],
            })

    # --- JS/TS path ---------------------------------------------------------
    if js_targets:
        runner = args.runner if args.runner in ("vitest", "jest") else detect_js_runner(root)
        functions = js_functions_via_analyzer(root)
        if functions is None:
            summary["notes"].append(
                "js_analyze.mjs unavailable — JS/TS stubs can't be scoped to gaps "
                "(`npm install` in the skill folder to enable).")
        else:
            js_plan = {}
            for js_file in sorted(set(os.path.abspath(p) for p in js_targets)):
                stub_dir = stub_dir_arg or os.path.dirname(js_file)
                base = _ident(os.path.splitext(os.path.basename(js_file))[0])
                js_plan[js_file] = (stub_dir, os.path.join(
                    stub_dir, f"{base}.characterization.test.js"))
            js_hold_out = [stub for _, stub in js_plan.values()
                           if stub_state(stub)[0] == "generated"]
            js_data = None
            if args.no_coverage_run:
                lcov = find_lcov_file(cwd)
                if lcov:
                    try:
                        with open(lcov, "r", encoding="utf-8", errors="ignore") as f:
                            js_data = parse_lcov(f.read(), cwd)
                    except OSError as exc:
                        print(f"(could not read {lcov}: {exc})")
            else:
                cmd = config.get("coverageCommand") or RUNNER_DEFAULTS.get(runner)
                print(f"Running JS/TS coverage: {cmd}")
                js_data = run_js_coverage(cmd, cwd, js_hold_out)
                if js_hold_out:
                    summary["notes"].append(
                        f"{len(js_hold_out)} unpinned JS/TS scaffold stub(s) were renamed "
                        "out of the coverage run and restored afterwards, so their own "
                        "placeholder calls can't mark a target as covered.")
            if js_data is None:
                summary["notes"].append(
                    "JS/TS coverage unavailable — no stubs written (run the "
                    "runner with an lcov reporter first, e.g. "
                    "`vitest run --coverage --coverage.reporter=lcov`).")
            js_data = js_data or {}
            target_set = {os.path.abspath(p) for p in js_targets}
            by_file = {}
            for fn in functions:
                file_key = os.path.abspath(fn.get("file") or "")
                if file_key in target_set:
                    by_file.setdefault(file_key, []).append(fn)
            for js_file, fns in sorted(by_file.items()):
                # no lcov entry for this file at all -> it wasn't measured
                # (not imported by any test), so every function is a gap
                entry = js_data.get(js_file, {})
                gaps = uncovered_js_functions(fns, entry)
                stub_dir, stub_path = js_plan.get(
                    js_file, (os.path.dirname(js_file), os.path.join(
                        os.path.dirname(js_file),
                        f"{_ident(os.path.splitext(os.path.basename(js_file))[0])}"
                        ".characterization.test.js")))
                rel_module = os.path.relpath(js_file, root).replace(os.sep, "/")
                if not gaps:
                    pruned = prune_stub(stub_path)
                    if pruned:
                        summary["js"].append({"module": rel_module, "stub": stub_path,
                                              "action": pruned, "runner": runner,
                                              "uncovered": []})
                    continue
                os.makedirs(stub_dir, exist_ok=True)
                source = js_stub_source(root, js_file, gaps, runner, stub_dir)
                summary["js"].append({
                    "module": rel_module,
                    "stub": stub_path,
                    "action": write_stub(stub_path, source),
                    "runner": runner,
                    "uncovered": [f.get("function") for f in gaps],
                })

    # --- report -------------------------------------------------------------
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        total = 0
        for entry in summary["python"] + summary["js"]:
            total += len(entry["uncovered"])
            print(f"{entry['action']:<34} {entry['stub']}")
            for name in entry["uncovered"]:
                print(f"    - uncovered: {name}")
        print()
        print(f"{len(summary['python'])} Python + {len(summary['js'])} JS/TS stub "
              f"file(s) touched, {total} uncovered function(s) total.")
        if not summary["python"] and not summary["js"]:
            print("Nothing to scaffold: every target function already has coverage "
                  "(or coverage data was unavailable and no gaps could be scoped).")
        for note in summary["notes"]:
            print(f"note: {note}")
        print()
        print("Next: run these stubs once, read each ACTUAL line, and replace the "
              "TODO with the real pinned value — shrinkcode never invents it for you.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
