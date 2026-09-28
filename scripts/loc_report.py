#!/usr/bin/env python3
"""
loc_report.py — line-of-code inventory for a shrinkcode job.

Counts CODE / BLANK / COMMENT lines per file, so line-count claims are honest
(deleting blank lines and comments is not compression — see anti-patterns.md).

Usage:
    # Single snapshot
    python3 loc_report.py <path> [--ext .py,.ts,.tsx,.js,.jsx,.css,.html]

    # Before/after diff (run once before compressing, once after, then diff)
    python3 loc_report.py <path> --save baseline.json
    python3 loc_report.py <path> --diff baseline.json

No third-party dependencies — stdlib only, so it always runs.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shrinkcode_config import load_config, matches_exclude, utf8_stdout

DEFAULT_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".css", ".scss", ".html", ".vue", ".svelte",
    # hard-language expansion (shrinkcode v2 #6)
    ".rs", ".go", ".java", ".kt", ".cs", ".cpp", ".hpp", ".h",
}

# Very small per-extension comment markers — good enough for an honest estimate,
# not a full parser. Multi-line comments are approximated (see COMMENT_BLOCK).
LINE_COMMENT = {
    ".py": "#", ".js": "//", ".jsx": "//", ".ts": "//", ".tsx": "//",
    ".mjs": "//", ".cjs": "//", ".css": None, ".scss": "//",
    ".html": None, ".vue": None, ".svelte": None,
    ".rs": "//", ".go": "//", ".java": "//", ".kt": "//", ".cs": "//",
    ".cpp": "//", ".hpp": "//", ".h": "//",
}
COMMENT_BLOCK = {
    ".css": ("/*", "*/"), ".js": ("/*", "*/"), ".jsx": ("/*", "*/"),
    ".ts": ("/*", "*/"), ".tsx": ("/*", "*/"), ".scss": ("/*", "*/"),
    ".html": ("<!--", "-->"), ".vue": ("<!--", "-->"),
    ".py": ('"""', '"""'),
    ".rs": ("/*", "*/"), ".go": ("/*", "*/"), ".java": ("/*", "*/"),
    ".kt": ("/*", "*/"), ".cs": ("/*", "*/"), ".cpp": ("/*", "*/"),
    ".hpp": ("/*", "*/"), ".h": ("/*", "*/"),
}

SKIP_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", "__pycache__",
    ".venv", "venv", "coverage", ".turbo", "out",
}


def count_file(path, ext):
    code = blank = comment = 0
    in_block = False
    block_start, block_end = COMMENT_BLOCK.get(ext, (None, None))
    line_marker = LINE_COMMENT.get(ext)
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    blank += 1
                    continue
                if in_block:
                    comment += 1
                    if block_end and block_end in line:
                        in_block = False
                    continue
                if block_start and line.startswith(block_start):
                    comment += 1
                    if block_end and block_end in line[len(block_start):]:
                        pass  # closed on same line
                    else:
                        in_block = True
                    continue
                if line_marker and line.startswith(line_marker):
                    comment += 1
                    continue
                code += 1
    except (UnicodeDecodeError, OSError):
        return None
    return {"code": code, "blank": blank, "comment": comment,
            "total": code + blank + comment}


def walk(root, exts, exclude_patterns=None):
    results = {}
    exclude_patterns = exclude_patterns or []

    def excluded(full_path):
        base = os.path.abspath(root) if os.path.isdir(root) else os.path.dirname(os.path.abspath(root))
        rel = os.path.relpath(full_path, base)
        return matches_exclude(rel, exclude_patterns)

    if os.path.isfile(root):
        ext = os.path.splitext(root)[1]
        if ext in exts and not excluded(root):
            c = count_file(root, ext)
            if c:
                results[root] = c
        return results
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            ext = os.path.splitext(fn)[1]
            if ext in exts:
                full = os.path.join(dirpath, fn)
                if excluded(full):
                    continue
                c = count_file(full, ext)
                if c:
                    results[full] = c
    return results


def summarize(results):
    totals = {"code": 0, "blank": 0, "comment": 0, "total": 0, "files": len(results)}
    for c in results.values():
        for k in ("code", "blank", "comment", "total"):
            totals[k] += c[k]
    return totals


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description="LOC inventory / before-after diff for shrinkcode")
    ap.add_argument("path")
    ap.add_argument("--ext", default=",".join(sorted(DEFAULT_EXTS)),
                     help="comma-separated extensions to include")
    ap.add_argument("--save", help="write this snapshot to a JSON file for later --diff")
    ap.add_argument("--diff", help="compare current snapshot against a saved baseline JSON")
    args = ap.parse_args()

    exts = {e if e.startswith(".") else f".{e}" for e in args.ext.split(",")}
    config = load_config(args.path)
    results = walk(args.path, exts, config.get("excludePaths"))
    totals = summarize(results)

    if args.save:
        with open(args.save, "w") as f:
            json.dump({"per_file": results, "totals": totals}, f, indent=2)
        print(f"Saved snapshot ({totals['files']} files, {totals['code']} code lines) to {args.save}")
        return

    if args.diff:
        with open(args.diff) as f:
            baseline = json.load(f)
        b = baseline["totals"]
        print("Metric        Before      After     Delta        %")
        for key in ("files", "code", "blank", "comment", "total"):
            before, after = b[key], totals[key]
            delta = after - before
            pct = (delta / before * 100) if before else 0.0
            print(f"{key:<12} {before:>8} {after:>10} {delta:>+8}   {pct:>+6.1f}%")
        return

    print(f"Files: {totals['files']}")
    print(f"Code lines:    {totals['code']}")
    print(f"Blank lines:   {totals['blank']}")
    print(f"Comment lines: {totals['comment']}")
    print(f"Total lines:   {totals['total']}")
    print()
    print("Top 10 largest files (by code lines):")
    for path, c in sorted(results.items(), key=lambda kv: -kv[1]["code"])[:10]:
        print(f"  {c['code']:>6}  {path}")


if __name__ == "__main__":
    main()
