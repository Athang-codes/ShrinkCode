# fixtures

Small, curated inputs for [`scripts/selftest.py`](../scripts/selftest.py) —
nothing else. Every file is hand-sized (the largest is ~5 KB), self-describing,
and free of machine-specific paths, generated output and dependencies. Run the
whole set with:

```bash
python3 scripts/selftest.py        # exit 0 = the skill works as documented
```

Snapshots (LOC/complexity JSON, HTML reports, PR-comment bodies) are **not**
committed here: the self-test regenerates them in a temp directory on every
run, so the assertions always exercise the current scripts rather than a
recorded artifact of a past machine.

| Directory | Exercises |
| --- | --- |
| `jsproj/` | JS/TS structural duplicate + complexity detection (`js_analyze.mjs`): `twins.js` is the renamed-variable pair, `complexity.js` a plain complexity case |
| `emoji-😀/` | Non-ASCII directory **and** a Japanese function name — the Windows cp1252 console regression test for the analyzer's UTF-8 decoding |
| `hard/` | Rust `//` and `/* */` comment stripping in the text duplicate pass |
| `proj/` | Python duplicate detection plus `shrinkcode.config.json` `excludePaths` (the `vendor/` twin must vanish from every report, and reappear when the config is removed) |
| `semantic/` | `--canonicalize` acceptance: reordered checks, loop vs `.map()` pipeline — must cluster together under the deep scan |
| `semantic-boundary/` | Literal-only differences: do not cluster by default, do cluster under `--canonicalize` |
| `semantic-guards/` | Negative control: similar-looking functions doing genuinely different work must **never** cluster (false-positive check) |
| `partfix/` | `partition_batches.py` acceptance scenarios: independent batch, same-file conflict, cross-file duplicate-cluster conflict, tier filtering, invalid plan (exit 2) |
| `reportfix/` | Static inputs for `generate_report.py`: the `batches.json` checkpoint manifest and the markdown compression plan (metrics snapshots are generated at run time) |
| `covfix/` | `coverage_gap_scaffold.py` with `--no-coverage-run`: a fully-covered module gets no stub; flipping one function to zero coverage must produce exactly one TODO-carrying stub |
| `cifix/` | `test_comment_sync.js` — idempotent PR-comment simulation against the real `.github/shrinkcode-comment-sync.js` (create once, update in place, collapse duplicates) |

If a pin in `selftest.py` ever has to change, change it together with the
fixture that produces it — they are a pair.
