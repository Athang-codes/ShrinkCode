#!/usr/bin/env python3
"""
shrinkcode_config.py — shared loader for shrinkcode.config.json.

Precedence (highest wins):
    explicit CLI flag  >  shrinkcode.config.json  >  built-in defaults

Discovery: looks for `shrinkcode.config.json` at the target path's root and
walks upward up to 3 levels (same convention as .eslintrc / pyproject.toml
discovery). Strict JSON with `_comment` sibling keys (no JSONC parser — see
references/config-schema.md).

Every script must still work with zero config file present, exactly as it
does today — load_config() never raises and returns built-in defaults.
"""
import fnmatch
import json
import os
import shutil
import subprocess
import sys

CONFIG_FILENAME = "shrinkcode.config.json"
MAX_UP_LEVELS = 3

DEFAULTS = {
    "excludePaths": [],
    "testCommand": None,
    "coverageCommand": None,
    "duplication": {"minLines": None, "similarity": None},
    "complexity": {"warnThreshold": None},
    "riskOverrides": [],
    "targetReductionPercent": None,
    "ci": {"failOnRegression": False},
}


def utf8_stdout():
    """Make stdout/stderr UTF-8 where the stream allows it.

    Piped stdout on Windows defaults to cp1252, where a glyph the reports use
    (Δ, ↳, ✓, box-drawing) raises UnicodeEncodeError — the script crashes
    instead of printing. Every CLI script calls this first; it's a no-op on
    POSIX and when output is a real console.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
JS_ANALYZER = os.path.join(SCRIPT_DIR, "js_analyze.mjs")
ANALYZER_TIMEOUT = 300


def display_path(path):
    """Normalize only absolute paths, so a mixed-shape list reads consistently.

    The text pass reports paths relative to the scanned root while
    js_analyze.mjs reports absolute ones; showing both shapes in one list reads
    like a bug. Absolute paths under the cwd become relative; relative paths —
    and absolute ones that would need `..` — come back byte-identical to
    pre-v2 output.
    """
    text = str(path)
    if not os.path.isabs(text):
        return text
    try:
        rel = os.path.relpath(text)
    except ValueError:            # different drive on Windows
        return text
    return text if rel.startswith("..") else rel


def run_js_analyzer(args, timeout=ANALYZER_TIMEOUT, on_error=None):
    """Run js_analyze.mjs with `args`; return its parsed JSON object, or None.

    None means "no AST pass" — Node missing, the analyzer's @babel deps not
    installed, a non-zero exit, unparseable or non-object JSON — and every
    caller degrades to the text pass instead of crashing. A non-object payload
    counts as "no pass" too, so callers can call `.get(...)` unguarded.

    stdout is decoded as UTF-8 explicitly. Node always writes UTF-8, but
    `text=True` on its own decodes with the locale encoding (cp1252 on
    Windows), which either crashes on the first byte cp1252 leaves undefined
    (0x81, 0x8D, 0x8F, 0x90, 0x9D — Japanese identifiers, emoji) or silently
    mojibakes every non-ASCII path, which then defeats display_path()'s prefix
    match and prints absolute paths beside relative ones.

    `on_error(hint, stderr)` is called (when given) if the analyzer ran but
    exited non-zero, so a caller can show the detail rather than degrade
    silently.

    Node is resolved with shutil.which first: on Windows a bare "node" works
    only when it happens to be on PATH in exactly the way subprocess expects,
    and a missing binary must land in the "no AST pass" branch, not an
    exception traceback.
    """
    node = shutil.which("node") or shutil.which("node.exe")
    if node is None or not os.path.isfile(JS_ANALYZER):
        return None
    cmd = [node, JS_ANALYZER] + [str(a) for a in args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, ValueError):
        return None
    if proc.returncode != 0:
        if on_error is not None:
            on_error("js_analyze.mjs failed", proc.stderr or "")
        return None
    try:
        data = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def find_config(target_path):
    """Return the config file path at/near target_path, or None."""
    try:
        start = os.path.abspath(target_path)
    except (OSError, ValueError):
        return None
    if os.path.isfile(start):
        start = os.path.dirname(start)
    cur = start
    for _ in range(MAX_UP_LEVELS + 1):
        candidate = os.path.join(cur, CONFIG_FILENAME)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


def _deep_merge(base, override):
    """Merge override into a copy of base; override wins per leaf key."""
    out = dict(base)
    for key, val in override.items():
        if key.startswith("_"):
            continue  # skip _comment sibling keys
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def load_config(target_path):
    """Return the merged config for target_path. Never raises.

    Missing or malformed config files fall back to built-in defaults so a
    bad config can never break a script run (a warning is printed for
    malformed files instead of failing).
    """
    path = find_config(target_path)
    if not path:
        return dict(DEFAULTS)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("top-level JSON value must be an object")
    except (OSError, ValueError) as exc:
        print(f"(shrinkcode: ignoring unreadable config {path}: {exc})")
        return dict(DEFAULTS)
    merged = _deep_merge(DEFAULTS, data)
    return merged


def resolve(cli_value, config_value, default=None):
    """Precedence helper: explicit CLI flag > config value > default.

    Pass cli_value as None when the flag was not given (argparse default),
    so config can take effect; anything else (including False/0/"") counts
    as an explicit override.
    """
    if cli_value is not None:
        return cli_value
    if config_value is not None:
        return config_value
    return default


def matches_exclude(rel_path, patterns):
    """True if rel_path matches any excludePaths glob pattern.

    Patterns are matched with fnmatch against the full relative path and
    against each path segment prefix, so both `vendor/**` and bare `vendor`
    style patterns work on either path separator.
    """
    if not patterns:
        return False
    norm = rel_path.replace(os.sep, "/").lstrip("./")
    parts = norm.split("/")
    for pat in patterns:
        pat = pat.replace(os.sep, "/").lstrip("./")
        if fnmatch.fnmatch(norm, pat):
            return True
        # `dir/**` should also match `dir` itself and any nested file
        if pat.endswith("/**") and (norm == pat[:-3] or norm.startswith(pat[:-2])):
            return True
        # bare segment match: pattern `vendor` skips anything under vendor/
        if "/" not in pat.rstrip("*") and any(fnmatch.fnmatch(seg, pat) for seg in parts):
            return True
    return False
