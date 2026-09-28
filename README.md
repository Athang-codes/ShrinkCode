# shrinkcode

A Claude Skill that compresses bloated codebases into fewer lines — **without
changing behavior.** Same inputs, same outputs, same edge cases, same error
handling, same ordering guarantees. Just leaner code, proven with real
tooling instead of vibes.

Turns "take this 10k-line project and make it 5k lines but it has to work
exactly the same" from a hope into a repeatable, auditable, git-checkpointed
pipeline.

## Why this is different from "just ask an LLM to refactor"

- **Tiered risk model.** Every change is classified Mechanical / Structural /
  Semantic before it's made, and the verification bar scales with the tier —
  a provably-dead import gets a quick test-suite run, an async-ordering change
  gets an explicit sign-off requirement and a rejection-path test.
- **Real metrics, not impressions.** Bundled scripts measure line count
  (code/blank/comment separated), duplication (exact + near-duplicate
  detection), and cyclomatic complexity — before and after — so "smaller" and
  "simpler" are both provable, and cramming logic onto fewer lines can't be
  disguised as a win.
- **Git-checkpointed batches.** Every verified change lands as its own commit
  with a message recording what changed and how it was verified. Nothing is
  ever one giant unreviewable diff; any regression is instantly bisectable and
  any single batch is independently revertible.
- **A written plan before execution**, for anything beyond a trivial job —
  the equivalent of a PR description written before the PR exists, so you
  approve the approach before the AI starts rewriting your codebase.
- **Optional always-on guard.** The bundled GitHub Action runs the same metrics
  on every pull request and keeps one comment (updated in place, not spammed)
  showing the duplication/complexity/LOC delta for the files that PR touched.
  Comment-only by default — it only fails a check if you opt in.

## What it does

1. **Analyze** — inventories the codebase with bundled + external tooling
   (duplicate block detection, dead-code/unused-export scanning, complexity
   scoring).
2. **Baseline** — snapshots metrics AND behavior (existing tests, or
   generated characterization tests) before touching anything.
3. **Plan** — classifies every candidate change into a risk tier, estimates
   savings, flags anything needing your explicit sign-off.
4. **Execute** — applies changes safest-first, in small git-checkpointed
   batches.
5. **Verify** — re-runs the baseline after every batch, at the bar its tier
   requires.
6. **Report** — before/after metrics, what was and wasn't touched and why,
   and exactly what verification backs the "identical behavior" claim.

Covers the full web stack: Python, HTML, CSS, TypeScript/JavaScript,
React/Next.js, Vue/Svelte, and Node.js backends (Express/Fastify/NestJS) — plus
hard-language idiom references for Rust, Go, Java/Kotlin, C#, and C++.

Optional extras when the job is big enough to want them: a self-contained HTML
before/after report, a CI bloat guard for future PRs, and parallel execution of
independent Tier-1 batches in subagent-capable environments (Claude Code /
Cowork) with a mandatory final serial re-verification.

## Bundled tooling

No required installs — everything runs on stdlib + bash + git (except the JS/TS
analyzer, which wants a one-time `npm install`), and reaches for better external
tools (`radon`, `jscpd`, `knip`, `vulture`, `ts-prune`, `depcheck`, `madge`,
`lizard`) when available, with graceful manual-command fallback when not.

```
scripts/
├── loc_report.py             # code/blank/comment line counts, before/after diff
├── find_duplicates.py        # exact + near-duplicate block detector (any language;
│                             #   --canonicalize for the opt-in deep JS/TS scan)
├── complexity_report.py      # cyclomatic complexity, Python + JS/TS
├── js_analyze.mjs            # JS/TS/JSX/TSX AST analyzer: structural dups + complexity
├── coverage_gap_scaffold.py  # zero-coverage functions -> characterization-test stubs
├── generate_report.py        # optional: one self-contained HTML before/after report
├── ci_diff_report.py         # optional: the same metrics as a PR comment (CI)
├── partition_batches.py      # optional: split plan.json into independent Tier-1 batches
├── dead_code_scan.sh         # auto-detects stack, runs the right dead-code tool
├── checkpoint.sh             # git branch + per-batch commit/revert discipline
└── shrinkcode_config.py      # shared config loader (shrinkcode.config.json)

.github/
├── workflows/shrinkcode.yml  # the PR bloat guard (runs ci_diff_report.py)
└── shrinkcode-comment-sync.js # finds/updates the single shrinkcode PR comment
```

Try them standalone, right now, on any project:

```bash
python3 scripts/loc_report.py /path/to/project
python3 scripts/find_duplicates.py /path/to/project --min-lines 5 --normalize-literals
python3 scripts/complexity_report.py /path/to/project
python3 scripts/coverage_gap_scaffold.py /path/to/project/src/thing.py
bash scripts/dead_code_scan.sh /path/to/project

# the PR bloat report, locally, exactly as CI runs it:
python3 scripts/ci_diff_report.py --base origin/main --head HEAD --output comment.md
```

## Use it as a GitHub Action

`.github/workflows/shrinkcode.yml` runs on `pull_request` (and on demand via
`workflow_dispatch` with a `strict` input) and needs no configuration:

- it checks out with `fetch-depth: 0`, sets up Python + Node, and runs
  `ci_diff_report.py` against `origin/<base branch>...HEAD`;
- metrics cover **only the files that PR changed**, so the comment is about this
  PR rather than the repo's whole history;
- the comment is found by a hidden `<!-- shrinkcode-bot -->` marker and edited in
  place, so pushing again updates it instead of stacking comments;
- on a brand-new repo with no resolvable base it reports absolute numbers with a
  note and exits 0 — never a made-up delta, never a red check;
- it fails nothing by default. Opt into enforcement by setting
  `"ci": { "failOnRegression": true }` in `shrinkcode.config.json` (or pass
  `--fail-on-regression` locally).

## Configuration (optional)

`shrinkcode.config.json` at the project root is picked up automatically by the
scripts (nearest file wins; CLI flags always override). All fields, defaults and
an annotated example: `shrinkcode.config.example.json` and
`references/config-schema.md`.

```json
{
  "excludePaths": ["generated/**", "**/migrations/**"],
  "duplication": { "minLines": 5, "similarity": 0.85 },
  "complexity": { "warnThreshold": 10 },
  "testCommand": "pytest -q",
  "targetReductionPercent": 30,
  "ci": { "failOnRegression": false }
}
```

## Install

Drop the `shrinkcode/` folder — or the packaged `shrinkcode.skill` file —
into your Claude Skills directory, or upload it directly in claude.ai /
Claude Code. Then just ask Claude to shrink, compress, or de-bloat a project.

## Structure

```
shrinkcode/
├── SKILL.md                          # the six-phase workflow
├── scripts/                          # the tools above
├── shrinkcode.config.example.json    # optional config, every field annotated
├── package.json                      # only for the JS/TS analyzer's @babel deps
├── .github/
│   ├── workflows/shrinkcode.yml      # the PR bloat guard
│   └── shrinkcode-comment-sync.js    # single-comment find/update (idempotent)
├── CHANGELOG.md                      # what changed in 2.0.0
├── LICENSE                           # MIT — the scripts and the workflow
├── LICENSE-SKILL                     # CC BY 4.0 — SKILL.md and references/
└── references/
    ├── metrics-and-tooling.md        # what each tool measures, external tool reference
    ├── risk-classification.md        # the Mechanical/Structural/Semantic tier system
    ├── verification.md               # how to prove "exactly like before", per stack
    ├── git-workflow.md               # the checkpoint/batch/revert discipline
    ├── compression-plan-template.md  # the plan artifact (+ machine-readable plan.json)
    ├── config-schema.md              # shrinkcode.config.json fields and defaults
    ├── parallel-execution.md         # independent Tier-1 batches, and the mandatory final pass
    ├── python.md
    ├── typescript-js.md
    ├── react-nextjs.md
    ├── vue-svelte.md
    ├── html-css.md
    ├── nodejs-backend.md
    ├── rust.md / go.md / java-kotlin.md / csharp.md / cpp.md
    └── anti-patterns.md              # what NOT to do — fake compression tricks
```

## What's in v2

- **JS/TS structural analysis** — `js_analyze.mjs` (babel-based) catches
  renamed-variable duplicates and per-function complexity that the text pass
  misses, and feeds both `find_duplicates.py` and `complexity_report.py`.
- **Optional deep scan** (`--canonicalize`) — normalizes statement order and
  commutative operands so a `for` loop and a `.map()` chain can match; measured
  at ~+19% runtime, so it's opt-in rather than default.
- **Coverage-gap characterization tests** — `coverage_gap_scaffold.py` finds
  functions with zero coverage and generates runnable stubs to pin behavior
  *before* compressing them.
- **The GitHub Action** — every PR gets one updated-in-place comment with the
  bloat delta for the files it touched.
- **`shrinkcode.config.json`** — excludes, thresholds, test commands and
  `ci.failOnRegression`, honored by every script, still zero-config by default.
- **Hard-language references** — Rust, Go, Java/Kotlin, C#, C++ idiom guides,
  each with its own "careful with" section.
- **HTML before/after report** — `generate_report.py` writes one self-contained
  file (no scripts, no network) with metric cards, proportional bars, the batch
  table and what was deliberately left alone.
- **Parallel Tier-1 batches** — `partition_batches.py` + `plan.json` split
  independent Tier-1 changes into groups for subagent-capable environments,
  with a mandatory full-suite serial re-verification at the end.

## License

ShrinkCode is dual-licensed by content type:

- **Code** — `scripts/`, `.github/`, `package.json`: **MIT**, see [`LICENSE`](LICENSE).
  Drop the tooling into your own product, fork it, ship it.
- **Skill content** — `SKILL.md`, `references/**`, this README: **CC BY 4.0**,
  see [`LICENSE-SKILL`](LICENSE-SKILL). Reuse, adapt and redistribute it,
  including commercially, with attribution.

The split exists so the measurement tooling can be vendored like normal code
while the skill guide stays reusable with credit.

Source: <https://github.com/Athang-codes/ShrinkCode> · changes: [`CHANGELOG.md`](CHANGELOG.md)

