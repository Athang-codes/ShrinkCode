#!/usr/bin/env bash
# dead_code_scan.sh — best-effort dead code / unused export detection.
#
# Detects which stacks are present in <path> and runs the appropriate
# specialized tool for each, installing it into a throwaway location if
# missing and the user's environment allows network access. Never fails hard:
# if a tool can't be installed or run, it prints what command the user should
# run manually and moves on to the next stack.
#
# Usage: ./dead_code_scan.sh <path>
#
# Tools used (see references/metrics-and-tooling.md for what each one does):
#   Python          -> vulture
#   JS/TS           -> ts-prune (TS projects with tsconfig.json) or knip
#   package.json    -> depcheck (unused npm dependencies)
#   JS/TS (modules) -> madge --circular (circular deps) + madge --orphans

set -uo pipefail
TARGET="${1:-.}"

# --- shrinkcode.config.json support (optional; silent no-op when absent) ---
# Prints two lines: (1) comma-separated globs for vulture, (2) a regex
# alternation for tools that take regexes (ts-prune/madge). Empty when no
# config exists or python3 is unavailable — behavior then matches today.
read -r VULTURE_EXCLUDES IGNORE_REGEX < <(
  python3 - "$TARGET" <<'PYEOF' 2>/dev/null || echo " "
import json, os, re, sys
patterns = []
start = os.path.abspath(sys.argv[1])
if os.path.isfile(start):
    start = os.path.dirname(start)
cur = start
for _ in range(4):
    cfg = os.path.join(cur, "shrinkcode.config.json")
    if os.path.isfile(cfg):
        try:
            with open(cfg) as f:
                data = json.load(f)
            patterns = data.get("excludePaths") or []
        except Exception:
            patterns = []
        break
    parent = os.path.dirname(cur)
    if parent == cur:
        break
    cur = parent
globs = ",".join(patterns)
regex = "|".join(re.escape(p).replace(r"\*\*", ".*").replace(r"\*", "[^/]*") for p in patterns)
print(globs or " ", regex or " ")
PYEOF
)
VULTURE_EXCLUDES="${VULTURE_EXCLUDES:- }"
IGNORE_REGEX="${IGNORE_REGEX:- }"
[ -z "${VULTURE_EXCLUDES// }" ] && VULTURE_EXCLUDES=""
[ -z "${IGNORE_REGEX// }" ] && IGNORE_REGEX=""

echo "=== Dead code / unused export scan: $TARGET ==="
echo

has_py=$(find "$TARGET" -name "*.py" -not -path "*/node_modules/*" -not -path "*/.venv/*" 2>/dev/null | head -1)
has_ts=$(find "$TARGET" \( -name "*.ts" -o -name "*.tsx" \) -not -path "*/node_modules/*" 2>/dev/null | head -1)
has_js=$(find "$TARGET" \( -name "*.js" -o -name "*.jsx" \) -not -path "*/node_modules/*" 2>/dev/null | head -1)
has_pkg=$(find "$TARGET" -maxdepth 2 -name "package.json" -not -path "*/node_modules/*" 2>/dev/null | head -1)

run_or_hint () {
  # Availability is already checked by the caller before invoking this, so a
  # nonzero exit here almost always means "the tool ran and found issues"
  # (normal linter behavior for vulture/ts-prune/depcheck), not "tool missing".
  # We print output either way and never treat it as a skip.
  local label="$1"; shift
  echo "--- $label ---"
  "$@"
  echo
}

if [ -n "$has_py" ]; then
  VULTURE_ARGS=("$TARGET" --min-confidence 80)
  if [ -n "$VULTURE_EXCLUDES" ]; then
    VULTURE_ARGS+=(--exclude "$VULTURE_EXCLUDES")  # excludePaths from shrinkcode.config.json
  fi
  if command -v vulture >/dev/null 2>&1; then
    run_or_hint "Python dead code (vulture)" vulture "${VULTURE_ARGS[@]}"
  elif pip install vulture --quiet --break-system-packages 2>/dev/null; then
    run_or_hint "Python dead code (vulture, just installed)" vulture "${VULTURE_ARGS[@]}"
  else
    echo "--- Python dead code ---"
    echo "  vulture not available and could not be installed automatically."
    echo "  Run manually: pip install vulture --break-system-packages && vulture $TARGET"
    echo
  fi
fi

if [ -n "$has_pkg" ]; then
  DEPCHECK_ARGS=()
  if [ -n "$VULTURE_EXCLUDES" ]; then
    IFS=',' read -ra _excludes <<< "$VULTURE_EXCLUDES"
    DEPCHECK_ARGS+=(--ignore "${_excludes[@]}")  # excludePaths from shrinkcode.config.json
  fi
  if command -v depcheck >/dev/null 2>&1 || npx --yes depcheck --version >/dev/null 2>&1; then
    run_or_hint "Unused npm dependencies (depcheck)" npx --yes depcheck "$(dirname "$has_pkg")" "${DEPCHECK_ARGS[@]}"
  else
    echo "--- Unused npm dependencies ---"
    echo "  depcheck not available. Run manually: npx depcheck $(dirname "$has_pkg")"
    echo
  fi
fi

if [ -n "$has_ts" ]; then
  tsconfig=$(find "$TARGET" -maxdepth 3 -name "tsconfig.json" -not -path "*/node_modules/*" 2>/dev/null | head -1)
  if [ -n "$tsconfig" ]; then
    TS_PRUNE_ARGS=(-p "$tsconfig")
    if [ -n "$IGNORE_REGEX" ]; then
      TS_PRUNE_ARGS+=(-i "$IGNORE_REGEX")  # excludePaths from shrinkcode.config.json
    fi
    if npx --yes ts-prune --version >/dev/null 2>&1; then
      run_or_hint "Unused TS exports (ts-prune)" npx --yes ts-prune "${TS_PRUNE_ARGS[@]}"
    else
      echo "--- Unused TS exports ---"
      echo "  ts-prune not available. Run manually: npx ts-prune -p $tsconfig"
      echo
    fi
  fi
fi

if [ -n "$has_ts" ] || [ -n "$has_js" ]; then
  MADGE_ARGS=()
  if [ -n "$IGNORE_REGEX" ]; then
    MADGE_ARGS+=(--exclude "$IGNORE_REGEX")  # excludePaths from shrinkcode.config.json
  fi
  if npx --yes madge --version >/dev/null 2>&1; then
    run_or_hint "Circular dependencies (madge)" npx --yes madge --circular "${MADGE_ARGS[@]}" "$TARGET"
    run_or_hint "Orphan modules — never imported anywhere (madge)" npx --yes madge --orphans "${MADGE_ARGS[@]}" "$TARGET"
  else
    echo "--- Circular deps / orphan modules ---"
    echo "  madge not available. Run manually: npx madge --circular $TARGET"
    echo "                        and: npx madge --orphans $TARGET"
    echo
  fi
fi

if [ -z "$has_py$has_ts$has_js" ]; then
  echo "No Python/JS/TS files detected under $TARGET — nothing to scan."
fi

echo "=== Done. Treat every result as a CANDIDATE, not a verdict. ==="
echo "A flagged 'unused' export can still be a public API entry point, a"
echo "dynamically-invoked handler, or used via reflection/string lookup that"
echo "static analysis can't see. Confirm before deleting (see SKILL.md Phase 3)."
