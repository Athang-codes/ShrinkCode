# Config schema: `shrinkcode.config.json`

Every threshold in shrinkcode used to be a CLI flag typed fresh each run or
implicit in how the assistant behaves. `shrinkcode.config.json` lets a team
set it once and have it stick — and CI (`ci_diff_report.py`) reads the same
file instead of "whatever flags happened to be typed that day."

## Precedence

```
explicit CLI flag  >  shrinkcode.config.json  >  built-in defaults
```

A CLI flag always wins (e.g. `--min-lines 8` beats `duplication.minLines: 5`)
— config never silently overrides something you typed. With **no config file
present, every script behaves exactly as it always has**; this is a hard
regression guarantee, not a nice-to-have.

## Discovery

Looked up at the target path's root, walking **upward up to 3 levels** if not
found there — same convention as `.eslintrc` / `pyproject.toml` discovery. A
file found at any of those levels applies to the run. A malformed file is
ignored with a warning, never a crash.

## Format

Strict JSON with `_comment` sibling keys for inline notes (there is no JSONC
parser — `//` comments would break `json.load`). Rules:

- `_comment` / `_comment.<name>` keys are allowed on **objects** and are
  ignored by the loader.
- Never put a `_comment` string **inside an array** — array elements are all
  read as values (it would become a glob pattern, tier entry, etc.).

## Fields

| Field | Type | Consumed by | Meaning |
|-------|------|-------------|---------|
| `excludePaths` | `string[]` (globs) | `loc_report.py`, `find_duplicates.py`, `complexity_report.py`, `dead_code_scan.sh`, `js_analyze.mjs` | Paths to skip everywhere: generated code, vendored deps, migrations. Matched with `fnmatch` against the relative path; `dir/**` skips the directory and everything under it; a bare segment pattern like `node_modules` matches at any depth. |
| `testCommand` | `string` | SKILL.md Phase 2/5 workflow, `coverage_gap_scaffold.py` | How to run this project's test suite, so verification doesn't have to guess or ask. |
| `coverageCommand` | `string` | `coverage_gap_scaffold.py` | How to produce a coverage report. Example: `coverage run -m pytest && coverage json -o coverage.json`. |
| `duplication.minLines` | `int` | `find_duplicates.py`, `js_analyze.mjs` | Default minimum block size; overridden by `--min-lines`. |
| `duplication.similarity` | `float` 0–1 | `find_duplicates.py`, `js_analyze.mjs` | Default near-duplicate threshold; overridden by `--similarity`. |
| `complexity.warnThreshold` | `int` | `complexity_report.py`, `js_analyze.mjs` | Functions scoring above this are flagged in reports (same "1 + decision points" scale for Python and JS/TS). |
| `riskOverrides` | `[{pattern, tier}]` | Phase 3 risk classification (assistant-consumed) | Force listed paths to **at-least** the given tier (1/2/3) regardless of what static analysis suggests — a safety valve for teams who know their own risk areas (e.g. `payments/**` never auto-classified Tier 1). "At least" means a Tier-2 override on a path the heuristics call Tier 3 stays Tier 3; overrides can only raise risk, never lower it. |
| `targetReductionPercent` | `int` | `references/compression-plan-template.md` (assistant-consumed) | Optional target; the plan states upfront whether it looks achievable instead of finding out at the end. |
| `ci.failOnRegression` | `bool` | `ci_diff_report.py`, `.github/workflows/shrinkcode.yml` | Default `false`: comment-only, never fails the check (bloat going up shouldn't block a merge unless the team opts in). Set `true` to fail CI when metrics regress. |

## Example

See `shrinkcode.config.example.json` at the repo root — it demonstrates every
field with realistic values and inline `_comment` notes. Copy it to
`shrinkcode.config.json` in the target project and edit.
