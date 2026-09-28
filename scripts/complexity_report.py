#!/usr/bin/env python3
"""
complexity_report.py — per-function cyclomatic complexity, so you can prove
that a compression pass reduced real complexity, not just line count. A file
can drop from 200 to 100 lines by cramming logic onto fewer lines while
complexity stays identical or gets worse — that's not a shrinkcode win.

Python: uses `radon` if installed (pip install radon --break-system-packages),
falls back to a stdlib `ast`-based cyclomatic complexity counter if radon
isn't available (counts branches: if/elif/for/while/except/with/bool-ops/
comprehension-ifs, +1 base per function — same definition radon uses).

JS/TS/JSX/TSX: no bundled analyzer here (would need a JS parser). Prints the
exact command to run `eslint` with the complexity rule, or `npx lizard`, which
supports JS/TS/C-family languages out of the box.

Usage:
    python3 complexity_report.py <path>              # current snapshot
    python3 complexity_report.py <path> --save x.json
    python3 complexity_report.py <path> --diff x.json
"""
import argparse
import ast
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shrinkcode_config import load_config, matches_exclude, utf8_stdout

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

SKIP_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", "__pycache__",
    ".venv", "venv", "coverage", ".turbo", "out",
}
JS_LIKE_EXTS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}


class ComplexityVisitor(ast.NodeVisitor):
    """Cyclomatic complexity per function: 1 (base path) + 1 per decision point."""

    def __init__(self):
        self.results = []  # (qualified_name, lineno, complexity)
        self._stack = []

    def _score_node(self, node):
        score = 1
        for n in ast.walk(node):
            if isinstance(n, (ast.If, ast.For, ast.AsyncFor, ast.While,
                               ast.ExceptHandler, ast.With, ast.AsyncWith)):
                score += 1
            elif isinstance(n, ast.BoolOp):
                score += max(len(n.values) - 1, 0)
            elif isinstance(n, (ast.comprehension,)):
                score += len(n.ifs)
        return score

    def visit_FunctionDef(self, node):
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node):
        self._visit_func(node)

    def _visit_func(self, node):
        qualname = ".".join(self._stack + [node.name])
        self.results.append((qualname, node.lineno, self._score_node(node)))
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    def visit_ClassDef(self, node):
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()


def analyze_python_stdlib(path):
    out = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            src = f.read()
        tree = ast.parse(src, filename=path)
    except (SyntaxError, OSError, ValueError):
        return out
    v = ComplexityVisitor()
    v.visit(tree)
    for qualname, lineno, score in v.results:
        out.append({"file": path, "function": qualname, "line": lineno, "complexity": score})
    return out


def analyze_python_radon(paths):
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "radon", "cc", "-j", *paths],
            capture_output=True, text=True, timeout=120,
        )
        data = json.loads(proc.stdout)
    except Exception:
        return None
    out = []
    for file, entries in data.items():
        for e in entries:
            out.append({"file": file, "function": e.get("name"),
                        "line": e.get("lineno"), "complexity": e.get("complexity")})
    return out


def has_radon():
    try:
        subprocess.run([sys.executable, "-m", "radon", "--version"],
                        capture_output=True, timeout=10)
        return True
    except Exception:
        return False


def find_python_files(root, exclude_patterns=None):
    exclude_patterns = exclude_patterns or []
    if os.path.isfile(root):
        return [root] if root.endswith(".py") else []
    files = []
    base = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".py"):
                full = os.path.join(dirpath, fn)
                if matches_exclude(os.path.relpath(full, base), exclude_patterns):
                    continue
                files.append(full)
    return files


def has_js_ts(root):
    if os.path.isfile(root):
        return os.path.splitext(root)[1] in JS_LIKE_EXTS
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(tuple(JS_LIKE_EXTS)):
                return True
    return False


# v2 #6: hard-language expansion — these get external-tool hints (lizard
# spans nearly all of them; dead-code/lint is one tool per language)
HARD_LANG_EXTS = {
    ".rs": "Rust", ".go": "Go", ".java": "Java", ".kt": "Kotlin",
    ".cs": "C#", ".cpp": "C++", ".hpp": "C++", ".h": "C/C++",
}
LANG_TOOL_HINTS = {
    "Rust": "cargo clippy",
    "Go": "gocyclo (or golangci-lint with gocyclo enabled)",
    "Java": "pmd check -R rulesets/java/cyclomaticcomplexity.xml",
    "Kotlin": "detekt",
    "C#": "npx lizard (or Roslyn complexity analyzers)",
    "C++": "npx lizard (or clang-tidy)",
    "C/C++": "npx lizard (or clang-tidy)",
}


def detect_hard_languages(root):
    """Return {language_name: True} for hard-language files under root."""
    found = {}
    if os.path.isfile(root):
        name = HARD_LANG_EXTS.get(os.path.splitext(root)[1])
        return {name: True} if name else {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            name = HARD_LANG_EXTS.get(os.path.splitext(fn)[1])
            if name:
                found[name] = True
    return found


def analyze_js_ts(path, exclude_patterns=None):
    """Run js_analyze.mjs over the target and return merged complexity entries.

    Returns [] when Node or the analyzer's deps are unavailable (caller then
    falls back to the external-tool hint rather than crashing).
    """
    script = os.path.join(SCRIPT_DIR, "js_analyze.mjs")
    if not os.path.isfile(script) or not has_js_ts(path):
        return None
    cmd = ["node", script, path, "--mode", "complexity"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    entries = data.get("complexity", {}).get("per_function", [])
    if exclude_patterns:
        entries = [e for e in entries
                   if not matches_exclude(os.path.relpath(e["file"], path)
                                          if os.path.isdir(path) else e["file"],
                                          exclude_patterns)]
    return entries


def display_path(path):
    """Same reason as find_duplicates.display_path: the Python walk reports
    relative paths, js_analyze.mjs reports absolute ones. Normalize only the
    absolute ones, so Python-only output stays byte-identical to pre-v2."""
    text = str(path)
    if not os.path.isabs(text):
        return text
    try:
        rel = os.path.relpath(text)
    except ValueError:
        return text
    return text if rel.startswith("..") else rel


def summarize(results):
    if not results:
        return {"functions": 0, "total_complexity": 0, "avg_complexity": 0.0, "max_complexity": 0}
    total = sum(r["complexity"] for r in results)
    return {
        "functions": len(results),
        "total_complexity": total,
        "avg_complexity": round(total / len(results), 2),
        "max_complexity": max(r["complexity"] for r in results),
    }


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description="Cyclomatic complexity report (Python; hints for JS/TS)")
    ap.add_argument("path")
    ap.add_argument("--save")
    ap.add_argument("--diff")
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    config = load_config(args.path)
    exclude = config.get("excludePaths")
    warn_threshold = config.get("complexity", {}).get("warnThreshold")

    py_files = find_python_files(args.path, exclude)
    results = []
    if py_files:
        if has_radon():
            results = analyze_python_radon(py_files) or []
        if not results:
            for f in py_files:
                results.extend(analyze_python_stdlib(f))

    # JS/TS: first-class analysis via js_analyze.mjs (merged into the same
    # report). None = analyzer unavailable -> hint printed at the end.
    js_entries = analyze_js_ts(args.path, exclude)
    if js_entries:
        results.extend(js_entries)

    totals = summarize(results)

    if args.save:
        with open(args.save, "w") as f:
            json.dump({"per_function": results, "totals": totals}, f, indent=2)
        print(f"Saved complexity snapshot ({totals['functions']} functions) to {args.save}")
    elif args.diff:
        with open(args.diff) as f:
            baseline = json.load(f)
        b = baseline["totals"]
        print("Metric              Before      After     Delta")
        for key in ("functions", "total_complexity", "avg_complexity", "max_complexity"):
            before, after = b[key], totals[key]
            print(f"{key:<19} {before:>8} {after:>10} {after - before:>+8}")
    else:
        if results:
            py_count = sum(1 for r in results if r["file"].endswith(".py"))
            js_count = len(results) - py_count
            label = []
            if py_count:
                label.append(f"{py_count} Python")
            if js_count:
                label.append(f"{js_count} JS/TS")
            if js_count:
                print(f"Functions analyzed: {totals['functions']} ({', '.join(label)})")
            else:
                # original wording, kept verbatim so Python-only output is
                # byte-identical to pre-v2 (regression guarantee)
                print(f"Python functions analyzed: {totals['functions']}")
            print(f"Total complexity: {totals['total_complexity']}  "
                  f"Average: {totals['avg_complexity']}  Max: {totals['max_complexity']}")
            print()
            print(f"Top {args.top} most complex functions:")
            for r in sorted(results, key=lambda r: -r["complexity"])[:args.top]:
                print(f"  {r['complexity']:>3}  {display_path(r['file'])}:"
                      f"{r['line']}  {r['function']}")
            if warn_threshold is not None:
                over = [r for r in results if r["complexity"] > warn_threshold]
                if over:
                    print()
                    print(f"Over warnThreshold ({warn_threshold}) from shrinkcode.config.json: {len(over)} function(s)")
                    for r in sorted(over, key=lambda r: -r["complexity"]):
                        print(f"  {r['complexity']:>3}  "
                              f"{display_path(r['file'])}:{r['line']}  "
                              f"{r['function']}")
        else:
            if has_js_ts(args.path):
                print("No Python or JS/TS functions found under this path.")
            else:
                # original wording, kept verbatim for pre-v2 byte-compatibility
                print("No Python files found under this path.")

    # Hint only when JS/TS files exist but the bundled analyzer couldn't run
    # (Node/deps missing) — JS/TS complexity is first-class when it can run.
    if not args.save and not args.diff and has_js_ts(args.path) and js_entries is None:
        print()
        print("JS/TS files detected but js_analyze.mjs couldn't run (Node or its")
        print("deps unavailable). Install Node + `npm install @babel/parser")
        print("@babel/traverse` in the skill folder, or run externally:")
        print("  npx lizard <path>                      # cyclomatic complexity, works on JS/TS/JSX/TSX")
        print("  npx eslint --rule 'complexity: [\"error\", 10]' <path>   # flags functions over threshold")

    # v2 #6: hard languages — print the right external command per language
    # (this script doesn't parse them; lizard is the one tool that spans
    # nearly all of them, vs a different dead-code/lint tool per language)
    if not args.save and not args.diff:
        hard = detect_hard_languages(args.path)
        if hard:
            print()
            print("Hard-language files detected (not parsed directly by this script).")
            print("Run one of:")
            print("  npx lizard <path>    # complexity for Rust/Go/Java/Kotlin/C#/C++ — spans all of them")
            for lang in sorted(hard):
                print(f"  {lang}: {LANG_TOOL_HINTS.get(lang, 'see references/')}  # language-specific")
            print("  (per-language detail: references/rust.md, go.md, java-kotlin.md, csharp.md, cpp.md)")


if __name__ == "__main__":
    main()
