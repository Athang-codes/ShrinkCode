#!/usr/bin/env python3
"""
find_duplicates.py — locate exact and near-duplicate code blocks across a
codebase, language-agnostic (text/line based, not AST). This is the highest-
leverage detector for shrinkcode: most 10k -> 5k line reductions come from
consolidating blocks this script surfaces.

It is deliberately simple (stdlib only, no tree-sitter/AST dependency) so it
runs anywhere. For deeper structural duplicate detection on large JS/TS repos,
also consider running `jscpd` (see references/metrics-and-tooling.md) — this
script is the zero-install first pass, jscpd is the higher-fidelity second pass.

Method:
  1. Split each file into sliding windows of N consecutive non-blank,
     normalized lines (whitespace collapsed, string/number literals optionally
     masked with --normalize-literals to catch "same logic, different value"
     duplicates).
  2. Hash each window. Windows sharing a hash are exact-duplicate candidates.
  3. For near-duplicates (line hash doesn't match), report clusters found via
     difflib ratio above --similarity between windows in the same size bucket
     -- capped for performance, see --max-compare.

Usage:
    python3 find_duplicates.py <path> [--min-lines 5] [--similarity 0.85]
                                       [--normalize-literals] [--ext .py,.ts]
                                       [--json] [--canonicalize]
"""
import argparse
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shrinkcode_config import load_config, matches_exclude, resolve, utf8_stdout

SKIP_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", "__pycache__",
    ".venv", "venv", "coverage", ".turbo", "out",
}
DEFAULT_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".css", ".scss", ".html",
    # hard-language expansion (shrinkcode v2 #6)
    ".rs", ".go", ".java", ".kt", ".cs", ".cpp", ".hpp", ".h",
}

# Extensions whose comments are stripped before windowing. Only the NEW
# (v2 #6) extensions are listed: existing languages keep byte-identical
# pre-v2 behavior (their detection output must not change — regression
# guarantee from the original build's test cases), while the C-family
# additions all share `//` + `/* */` comment syntax.
C_COMMENT_EXTS = {".rs", ".go", ".java", ".kt", ".cs", ".cpp", ".hpp", ".h"}
LINE_COMMENT = "//"
BLOCK_COMMENT = ("/*", "*/")

STRING_RE = re.compile(r"""(['"]).*?\1""")
NUMBER_RE = re.compile(r"\b\d+(\.\d+)?\b")


def strip_c_comments(lines):
    """Remove `//` line comments and `/* */` block comments (C-family).

    Conservative: string literals containing // or /* are left alone unless
    the comment marker appears outside quotes — good enough for windowing,
    not a parser (same honesty bar as loc_report.py's comment counting).
    """
    out = []
    in_block = False
    for raw in lines:
        line = raw
        if in_block:
            end = line.find(BLOCK_COMMENT[1])
            if end == -1:
                out.append("\n" if raw.endswith("\n") else "")
                continue
            in_block = False
            line = line[end + 2:]
        # repeated line-comment strip (only outside quotes, cheap check)
        if LINE_COMMENT in line:
            # find // not inside a quoted string on this line
            for m in re.finditer(r"""('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")|//""", line):
                if m.group(1) is None:
                    line = line[:m.start()]
                    break
        # block comment start (outside quotes)
        for m in re.finditer(r"""('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")|/\*""", line):
            if m.group(1) is None:
                close = line.find(BLOCK_COMMENT[1], m.start() + 2)
                if close == -1:
                    line = line[:m.start()]
                    in_block = True
                else:
                    line = line[:m.start()] + line[close + 2:]
                break
        out.append(line)
    return out


def normalize(line, mask_literals):
    line = line.strip()
    line = re.sub(r"\s+", " ", line)
    if mask_literals:
        line = STRING_RE.sub("STR", line)
        line = NUMBER_RE.sub("NUM", line)
    return line


def iter_files(root, exts, exclude_patterns=None):
    exclude_patterns = exclude_patterns or []
    if os.path.isfile(root):
        if os.path.splitext(root)[1] in exts:
            yield root
        return
    base = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if os.path.splitext(fn)[1] in exts:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, base)
                if matches_exclude(rel, exclude_patterns):
                    continue
                yield full


def load_windows(path, min_lines, mask_literals):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            raw_lines = f.readlines()
    except OSError:
        return []
    if os.path.splitext(path)[1] in C_COMMENT_EXTS:
        raw_lines = strip_c_comments(raw_lines)
    norm = [normalize(l, mask_literals) for l in raw_lines]
    # keep track of original line numbers alongside non-blank normalized lines
    non_blank = [(i + 1, n) for i, n in enumerate(norm) if n]
    windows = []
    for start in range(0, max(0, len(non_blank) - min_lines + 1)):
        chunk = non_blank[start:start + min_lines]
        if len(chunk) < min_lines:
            break
        line_no = chunk[0][0]
        text = "\n".join(t for _, t in chunk)
        windows.append((path, line_no, text))
    return windows


def display_path(path):
    """The text pass reports paths relative to the scanned root while
    js_analyze.mjs reports absolute ones; showing both shapes in one list reads
    like a bug. Make absolute paths that live under the cwd relative, and leave
    relative paths byte-identical to pre-v2 output."""
    text = str(path)
    if not os.path.isabs(text):
        return text
    try:
        rel = os.path.relpath(text)
    except ValueError:            # different drive on Windows
        return text
    return text if rel.startswith("..") else rel


JS_EXTS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def run_js_analyzer(path, min_lines, similarity, exclude_patterns, canonicalize=False):
    """Shell out to js_analyze.mjs for AST-level JS/TS duplicate detection.

    Returns the parsed JSON ({exact_clusters, near_pairs}) or None when Node
    or the analyzer's deps aren't available — caller degrades to a hint
    instead of crashing. `canonicalize` turns on the opt-in deep pass (statement
    order + loop/array-pipeline spelling folded together).
    """
    script = os.path.join(SCRIPT_DIR, "js_analyze.mjs")
    if not os.path.isfile(script):
        return None
    has_js = False
    if os.path.isfile(path):
        has_js = os.path.splitext(path)[1] in JS_EXTS
    else:
        for _ in iter_files(path, JS_EXTS, exclude_patterns):
            has_js = True
            break
    if not has_js:
        return None
    cmd = ["node", script, path, "--mode", "duplicates",
           "--min-lines", str(min_lines), "--similarity", str(similarity)]
    if canonicalize:
        cmd.append("--canonicalize")
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
    return data.get("duplicates")


def merge_clusters(text_clusters, ast_clusters):
    """Union text-based and AST-based clusters sharing any file:line location.

    A renamed-variable copy the text pass only sees as near-duplicate gets
    promoted into an exact structural cluster when the AST pass catches it —
    one unified report, not two the user has to mentally combine.
    """
    combined = []
    for cluster in list(text_clusters) + list(ast_clusters):
        locs = set()
        for loc in cluster:
            if isinstance(loc, dict):
                locs.add((loc["path"], loc["line"]))
            else:
                locs.add((loc[0], loc[1]))
        combined.append(locs)

    # union clusters that share a location
    merged = []
    for locs in combined:
        hit = [m for m in merged if m & locs]
        for m in hit:
            merged.remove(m)
            locs = locs | m
        merged.append(locs)

    merged = [c for c in merged if len(c) > 1]
    merged.sort(key=lambda c: -len(c))
    return [[(p, l) for p, l in sorted(c)] for c in merged]


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description="Find exact + near-duplicate code blocks")
    ap.add_argument("path")
    ap.add_argument("--min-lines", type=int, default=None,
                     help="minimum consecutive non-blank lines per block (default 5, or duplication.minLines in config)")
    ap.add_argument("--similarity", type=float, default=None,
                     help="difflib ratio threshold for near-duplicates (default 0.85, or duplication.similarity in config)")
    ap.add_argument("--normalize-literals", action="store_true",
                     help="mask string/number literals so 'same shape, different value' blocks match")
    ap.add_argument("--ext", default=",".join(sorted(DEFAULT_EXTS)))
    ap.add_argument("--max-compare", type=int, default=4000,
                     help="cap pairwise near-duplicate comparisons for performance")
    ap.add_argument("--top", type=int, default=25, help="max clusters to print")
    ap.add_argument("--canonicalize", action="store_true",
                     help="opt-in deep scan for JS/TS code: the AST pass also folds statement "
                          "order, loop vs. array-pipeline spelling, commutative operands and "
                          "symmetric comparisons into one canonical form (slower; produces "
                          "candidates a human still has to confirm)")
    ap.add_argument("--json", action="store_true",
                     help="emit {exact_clusters, near_pairs} JSON instead of the "
                          "human-readable report (same shape js_analyze.mjs emits; "
                          "consumed by generate_report.py / ci_diff_report.py)")
    args = ap.parse_args()

    # Precedence: explicit CLI flag > shrinkcode.config.json > built-in default
    config = load_config(args.path)
    min_lines = resolve(args.min_lines, config.get("duplication", {}).get("minLines"), 5)
    similarity = resolve(args.similarity, config.get("duplication", {}).get("similarity"), 0.85)
    exclude = config.get("excludePaths")

    exts = {e if e.startswith(".") else f".{e}" for e in args.ext.split(",")}
    all_windows = []
    for path in iter_files(args.path, exts, exclude):
        all_windows.extend(load_windows(path, min_lines, args.normalize_literals))

    # --- exact duplicates ---
    by_hash = defaultdict(list)
    for path, line_no, text in all_windows:
        h = hashlib.sha1(text.encode("utf-8")).hexdigest()
        by_hash[h].append((path, line_no))

    exact_clusters = [locs for locs in by_hash.values() if len(locs) > 1]
    exact_clusters.sort(key=lambda locs: -len(locs))

    # --- AST-based structural pass for JS/TS (unified into this report) ---
    js_result = run_js_analyzer(args.path, min_lines, similarity, exclude, args.canonicalize)
    if js_result is not None:
        exact_clusters = merge_clusters(exact_clusters, js_result.get("exact_clusters", []))
    elif not args.json and not os.path.isfile(args.path) and any(
        os.path.splitext(f)[1] in JS_EXTS for f in iter_files(args.path, JS_EXTS, exclude)
    ):
        print("(JS/TS files found but js_analyze.mjs unavailable — structural "
              "duplicate detection skipped. Install Node + run "
              "`npm install @babel/parser @babel/traverse` in the skill folder.)")

    # The analyzer echoes `"canonicalize": true` in its payload when the deep
    # pass actually ran — key off that, not off the flag, so the report never
    # claims a deeper scan than the analyzer performed.
    if not args.json and js_result is not None and js_result.get("canonicalize"):
        print("(JS/TS AST pass ran with --canonicalize: function bodies compared in "
              "canonical statement order, loop/array-pipeline spellings folded together, "
              "commutative and symmetric operands sorted. Deeper and slower — every hit "
              "is a merge candidate to confirm by hand, not a verdict.)\n")

    if not args.json:
        print(f"Scanned {len(all_windows)} candidate blocks (min {min_lines} lines) "
              f"across files under {args.path}\n")
        print(f"=== Exact duplicate clusters ({len(exact_clusters)} found) ===")
        for cluster in exact_clusters[:args.top]:
            print(f"  {len(cluster)}x duplicate block:")
            for path, line_no in cluster:
                print(f"    {display_path(path)}:{line_no}")
        if len(exact_clusters) > args.top:
            print(f"  ... and {len(exact_clusters) - args.top} more")

    # --- near duplicates (only among non-exact-matched unique texts, capped) ---
    uniq_texts = []
    seen_hashes = set()
    for path, line_no, text in all_windows:
        h = hashlib.sha1(text.encode("utf-8")).hexdigest()
        if h in seen_hashes:
            continue
        seen_hashes.add(h)
        uniq_texts.append((path, line_no, text))

    near_pairs = []
    n = len(uniq_texts)
    compared = 0
    for i in range(n):
        if compared > args.max_compare:
            break
        for j in range(i + 1, n):
            if compared > args.max_compare:
                break
            compared += 1
            a, b = uniq_texts[i][2], uniq_texts[j][2]
            if abs(len(a) - len(b)) > max(len(a), len(b)) * 0.4:
                continue  # cheap pre-filter
            ratio = difflib.SequenceMatcher(None, a, b).ratio()
            if ratio >= similarity:
                near_pairs.append((ratio, uniq_texts[i], uniq_texts[j]))

    near_pairs.sort(key=lambda t: -t[0])

    if args.json:
        # Same shape js_analyze.mjs --mode duplicates emits (plus `compared`),
        # so consumers — generate_report.py, ci_diff_report.py — merge both
        # without special-casing where a cluster came from.
        report = {
            "exact_clusters": [[{"path": p, "line": l} for p, l in c]
                               for c in exact_clusters],
            "near_pairs": [{"ratio": round(r, 2),
                            "a": {"path": p1, "line": l1},
                            "b": {"path": p2, "line": l2}}
                           for r, (p1, l1, _), (p2, l2, _) in near_pairs],
            "compared": compared,
        }
        print(json.dumps(report, indent=2))
        return

    print(f"\n=== Near-duplicate pairs >= {similarity} similarity "
          f"({len(near_pairs)} found, {compared} pairs compared) ===")
    for ratio, (p1, l1, _), (p2, l2, _) in near_pairs[:args.top]:
        print(f"  {ratio:.2f}  {display_path(p1)}:{l1}  <->  "
              f"{display_path(p2)}:{l2}")
    if len(near_pairs) > args.top:
        print(f"  ... and {len(near_pairs) - args.top} more")

    if compared >= args.max_compare:
        print(f"\n(Comparison cap of {args.max_compare} pairs reached — for a large "
              f"codebase, run per-directory or raise --max-compare, or switch to jscpd.)")


if __name__ == "__main__":
    main()
