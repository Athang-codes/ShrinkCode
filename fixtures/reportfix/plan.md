# Shrinkcode plan: reportfix sample

## Baseline (Phase 1-2 output)
- Current size: 41 code lines across 3 files (scripts/loc_report.py output)
- Duplication found: 1 exact cluster, 1 near-duplicate pair

## Planned changes

| # | Category | Files | Tier | Est. lines saved | Verification plan |
|---|----------|-------|------|------------------|--------------------|
| 1 | dedup    | app.py | 1 | ~10 | pytest 42/42 pass |

## Items NOT being touched, and why
- greet() looks trivially inline-able — but it is a public API used by the templates, no caller inventory yet
- util.py keeps a defensive `str()` coercion on input — static analysis can't prove every caller passes a string
