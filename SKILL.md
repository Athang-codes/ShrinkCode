---
name: shrinkcode
description: >
  Compress bloated codebases into fewer lines WITHOUT changing behavior — same
  inputs, same outputs, same edge cases, just leaner code, with real metrics
  (duplication, complexity, dead code) and tiered verification to prove it.
  Use this whenever the user asks to "shrink", "compress", "condense",
  "de-bloat", "slim down", "reduce line count", "refactor to be shorter", or
  says something like "make this 10k lines into 5k lines but it should work
  exactly the same." Covers the full web stack: Python, HTML, CSS,
  TypeScript/JavaScript, React/Next.js, Vue/Svelte, and Node.js backends
  (Express/Fastify/NestJS) — plus Rust, Go, Java/Kotlin, C#, and C++ via the
  hard-language reference files. Trigger this even if the user just says "this file
  feels bloated, can you clean it up" or "there's a lot of duplication here" —
  those are compression requests in disguise. Do NOT use this for adding
  features, changing behavior, or general code review — this skill is
  strictly behavior-preserving compression, enforced with tooling and
  git-checkpointed batches, not vibes.
---

# Shrinkcode

A rigorous, tool-backed method for taking a codebase (or file) and reducing its
line count substantially — commonly 30-50%+ — while **proving** it behaves
identically: same inputs produce same outputs, same edge cases, same errors,
same side effects, same ordering guarantees. This is not "write terser/uglier
code." It's "eliminate the bloat that accumulates as codebases grow" —
duplication, dead code, over-engineered abstractions, hand-rolled boilerplate
the language/framework already collapses for you — measured with real tooling
and checkpointed so nothing ships unverified.

**The non-negotiable rule:** never accept a compression until it passes the
verification bar its risk tier requires (see Phase 3). Line count is a
side-effect of good design, not the goal itself. A user who wants "10k → 5k
lines that exactly functions like the 10k" is asking for two things, and
correctness always wins if they trade off. If the honest, safely-verifiable
compression is 7k lines, ship 7k and say why — don't force a number by cutting
verification corners.

## Bundled tools

```
scripts/
├── loc_report.py         # code/blank/comment line counts, before/after diff — stdlib only
├── find_duplicates.py    # exact + near-duplicate block detector, language-agnostic — stdlib only
│                         #   (auto-runs js_analyze.mjs for AST-level JS/TS duplicates;
│                         #   --canonicalize opts into the opt-in deep scan)
├── complexity_report.py  # cyclomatic complexity (Python via radon/AST fallback; JS/TS via js_analyze.mjs)
├── js_analyze.mjs        # JS/TS/JSX/TSX AST analyzer: structural dups + complexity (needs Node + @babel deps)
├── coverage_gap_scaffold.py  # zero-coverage functions -> characterization-test stubs (coverage.py / lcov)
├── generate_report.py    # optional: one self-contained HTML before/after report (Phase 6)
├── ci_diff_report.py     # optional: the same metrics as a PR comment (changed files only) — Phase 6
├── partition_batches.py  # optional: split a plan.json into independent Tier-1 batches (Phase 4)
├── dead_code_scan.sh     # auto-detects stack, runs vulture/ts-prune/depcheck/madge, degrades gracefully
├── checkpoint.sh         # git branch + per-batch commit/revert discipline
└── shrinkcode_config.py  # shared module: config loading, path excludes, UTF-8 stdout (no CLI)
```

All run with zero required setup (stdlib/bash + git only) except `js_analyze.mjs`
(one-time `npm install @babel/parser @babel/traverse`); they reach for better
external tools (radon, jscpd, knip) when available and degrade gracefully with a
manual-command hint when not. Full tool reference: `references/metrics-and-tooling.md`.

The `.github/` folder holds the optional always-on version of this same
measurement: `workflows/shrinkcode.yml` runs `ci_diff_report.py` on every pull
request and posts/updates a single PR comment with the delta for the files that
PR touched (`shrinkcode-comment-sync.js` does the find-by-marker-and-edit).
Comment-only by default; it only fails a check when a team opts in. Details and
the verified sample comment: `references/metrics-and-tooling.md`.

## The pipeline

Six phases. Don't skip Phase 2 (baseline) or Phase 3 (plan) for anything
beyond a single small file "just vibe with me" job — they're what make Phase 5
(verify) a real claim instead of an assertion.

### Phase 0 — Setup

```bash
bash scripts/checkpoint.sh start
```

Requires a git repo with a clean working tree (see `references/git-workflow.md`
for the no-git fallback). This creates a dedicated `shrinkcode/<timestamp>`
branch — the user's main branch stays untouched until they review and merge.
Every batch from here on gets its own commit on this branch.

### Phase 1 — Analyze

Read the whole target before touching anything — don't compress function #1
while still ignorant of function #40; duplication patterns and
framework-can-do-this-for-you opportunities only become visible once you've
seen the whole shape of the code. Then run the detectors:

```bash
python3 scripts/loc_report.py <path>
python3 scripts/find_duplicates.py <path> --min-lines 5 --normalize-literals
# if that looks suspiciously clean on a copy-paste-heavy JS/TS codebase, opt
# into the deeper canonicalized scan (see references/metrics-and-tooling.md):
#   python3 scripts/find_duplicates.py <path> --canonicalize
python3 scripts/complexity_report.py <path>
bash scripts/dead_code_scan.sh <path>
```

Build the inventory from real output, not impression: what's duplicated
(exact vs. near), what's dead (cross-check every "unused" flag — see
`references/metrics-and-tooling.md`'s warning about static-analysis
candidates vs. verdicts), what's needlessly complex, what's hand-rolled that a
library/built-in already provides (per-language idioms in
`references/python.md`, `typescript-js.md`, `react-nextjs.md`, `html-css.md`,
`vue-svelte.md`, `nodejs-backend.md`).

### Phase 2 — Baseline

Before any edits, snapshot both the metrics and the behavior:

```bash
python3 scripts/loc_report.py <path> --save before_loc.json
python3 scripts/complexity_report.py <path> --save before_complexity.json
```

Then establish the behavior baseline — existing tests run + recorded
pass/fail, or, if none exist, a set of **characterization tests** you write
that pin down current behavior (not "should" behavior) for the main paths and
every gnarly edge case. This step is not optional because there's no test
suite — the absence of tests is exactly why you write characterization tests
first. If a coverage tool is available, let the bundled scaffolder find the
zero-coverage functions and write the stubs (it calls the project's coverage
command, then emits one test per uncovered function with a TODO instead of an
invented assertion):

```bash
python3 scripts/coverage_gap_scaffold.py <path>      # or an explicit file list
```

Run those stubs, pin the ACTUAL values they print, re-run to watch the stub
set shrink. Full detail, including the pin-loop contract and stack-specific
baselines (React needs rendered output + interaction, not just function
returns; Node backends need request/response pairs including error paths):
`references/verification.md`.

### Phase 3 — Plan

Classify every candidate change into a risk tier before touching code:

- **Tier 1 (mechanical)** — provably safe deletions/merges/built-in swaps.
- **Tier 2 (structural)** — consolidations/replacements that depend on you
  having read intent correctly, not just current text.
- **Tier 3 (semantic)** — anything where order/timing/failure behavior could
  shift even though the logic looks equivalent (async ordering, hook order,
  CSS cascade, exception handling, memoization boundaries).

Full tier definitions and examples: `references/risk-classification.md` —
read this before classifying anything, the boundary between Tier 1 and Tier 2
is not always obvious.

For anything beyond a trivial single-file job, write this up as a compression
plan (table: change / files / tier / est. lines saved / verification plan) and
share it with the user before executing — template and a worked example in
`references/compression-plan-template.md`. If the honest projected outcome
falls short of a target the user stated, say so in the plan, before starting,
not at the end. Write the plan's machine-readable `plan.json` companion too
(same ids/tiers/files) — it's what `scripts/partition_batches.py` reads to show
which Tier-1 batches are actually independent, and it costs a minute.

Anything requiring a judgment call about intent (a Tier 2 abstraction that
might be deliberate future-proofing) or carrying semantic risk (any Tier 3
item) gets flagged as an explicit line item needing the user's sign-off — see
"Flag, don't silently decide" in `references/risk-classification.md`.

### Phase 4 — Execute, in tier order, in checkpointed batches

Order: all Tier 1 changes first (highest safety-to-effort ratio, often gets
you most of the way to target on its own), then Tier 2 one file/module at a
time, then Tier 3 one change at a time with sign-off already obtained in
Phase 3. If the target is met after Tier 1 + 2, stop — don't reach into Tier 3
for marginal reduction the user didn't ask you to risk.

After each batch:

```bash
bash scripts/checkpoint.sh save "<category>: <what changed> [verified: <how>]"
```

Categories: `dedup` / `dead-code` / `boilerplate` / `merge` / `abstraction` /
`async-order` (or another that fits). One batch = roughly one file's worth of
Tier 1 changes, or one individual Tier 2/3 change — never bundle unrelated
changes into one commit; see `references/git-workflow.md` for why this
matters for bisectability, not just tidiness.

In Claude Code/Cowork with subagents available, see
`references/parallel-execution.md` for running independent Tier 1 batches
concurrently — including the final full-suite serial re-verification that stays
mandatory regardless (it's the safety net that makes the rest acceptable).

### Phase 5 — Verify, at the bar the tier requires

Re-run the behavior baseline after **every batch**, not just once at the end —
you want to know which batch broke something, not have to bisect the whole
diff later.

| Tier | Minimum bar |
|------|-------------|
| 1 | Full test suite once per batch |
| 2 | Full test suite + relevant characterization tests, per individual change + UI visual/interaction check if applicable |
| 3 | Everything in Tier 2, plus a characterization test for the specific edge case the change affects, plus the sign-off already obtained in Phase 3 |

On any failure: stop, isolate the specific batch (this is exactly why batches
are committed individually), fix or `bash scripts/checkpoint.sh revert <sha>`
that one batch. Never keep compressing on top of a broken baseline. Full
stack-specific verification techniques: `references/verification.md`.

### Phase 6 — Report

```bash
python3 scripts/loc_report.py <path> --diff before_loc.json
python3 scripts/complexity_report.py <path> --diff before_complexity.json
bash scripts/checkpoint.sh list
```

**Optional, recommended when the result is worth showing off:** turn those
numbers into a shareable artifact — one self-contained `.html` file with
metric cards, proportional before/after bars, the batch table (tier badges
from `batches.json`) and the plan's "not touched" items:

```bash
python3 scripts/generate_report.py \
  --loc-before before_loc.json --loc-after after_loc.json \
  --complexity-before before_complexity.json --complexity-after after_complexity.json \
  --duplicates dups_before.json --batches batches.json \
  --output shrinkcode_report.html
```

Opens straight from disk — inline styles, no scripts, no network. Nice-to-have,
never a blocking step: for a small job the numbers in the conversation are
enough. `batches.json` format: `references/git-workflow.md`.

**Optional: stop it growing back.** The same measurements can guard every future
PR — locally, with no CI involved, this is exactly what the Action runs:

```bash
python3 scripts/ci_diff_report.py --base origin/main --head HEAD \
  --output shrinkcode-comment.md      # --json and --fail-on-regression also exist
```

It scopes to the files the PR changed, comment-only by default, and falls back to
absolute whole-tree numbers (with a note) when the base ref won't resolve on a
brand-new repo instead of inventing a delta. Opt into failing the check with
`--fail-on-regression` or `ci.failOnRegression` in `shrinkcode.config.json`. The
bundled workflow and a verified sample comment: `references/metrics-and-tooling.md`.

Tell the user, backed by these real numbers, not impressions:

- Original → final line count and the real percentage reduction (code lines
  specifically — not blank/comment lines, which don't count as compression;
  see `references/anti-patterns.md`)
- Complexity delta (avg/max cyclomatic complexity before vs. after) —
  proves the reduction wasn't achieved by cramming logic onto fewer lines
- What categories of compression were applied, with rough line counts and
  batch commits per category
- Anything deliberately NOT compressed and why (an abstraction that looked
  intentional, a flagged-but-unconfirmed "dead" export left alone out of
  caution)
- Exactly what verification was run, at what tier bar, and its result — never
  claim "functions identically" without pointing to what you actually checked
- The branch name and batch list, so the user can review batch-by-batch
  (`git log -p`) before merging — this is their call, not something to
  merge/push automatically

## Reference files

Read the ones relevant to the job — don't load all of them for a
single-language task:

- `references/metrics-and-tooling.md` — **read early.** What each bundled
  script measures, the external tools they point to (jscpd, vulture, ts-prune,
  knip, depcheck, madge, radon, lizard, cloc), and why every result is a
  candidate, not a verdict.
- `references/risk-classification.md` — **read before Phase 3, every time.**
  The three-tier system that decides how much verification a change needs.
- `references/verification.md` — how to build a behavior baseline and verify
  against it, per stack, including UI-specific visual/interaction checks.
- `references/git-workflow.md` — the checkpoint/batch/revert discipline and
  why batches (not one giant diff) are what make this auditable.
- `references/compression-plan-template.md` — the plan artifact to produce
  before executing on any non-trivial job (markdown for the user, `plan.json`
  for the tooling).
- `references/parallel-execution.md` — only if you're in Claude Code/Cowork
  **and** the plan has many independent Tier 1 batches: how to partition them
  into parallel groups, sequence the commits, and why the final full-suite
  serial re-verification is mandatory rather than nice-to-have.
- `references/python.md`, `typescript-js.md`, `react-nextjs.md`,
  `html-css.md`, `vue-svelte.md`, `nodejs-backend.md` — per-stack compression
  idioms, ordered by typical impact, with the Tier-2/3 gotchas specific to
  each.
- `references/rust.md`, `go.md`, `java-kotlin.md`, `csharp.md`, `cpp.md` —
  hard-language compression idioms (iterator/loop collapses, derive/record
  swaps, RAII/LINQ/streams), each with its own careful-with section —
  ownership/borrow (Rust), goroutine timing (Go), memory management (C++)
  are Tier 2/3 by definition — and tooling recap.
- `references/anti-patterns.md` — what NOT to do: fake compression tricks,
  silently "fixing" behavior mid-compression, trusting one tool's say-so,
  batching everything into one unbisectable diff, claiming verification you
  didn't run.

---

ShrinkCode 2.0.1 — this skill content (`SKILL.md`, `references/`) is licensed
**CC BY 4.0**: reuse, adapt and redistribute it, including commercially, with
attribution (see `LICENSE-SKILL`). The bundled scripts in `scripts/` are MIT
(see `LICENSE`). Source: <https://github.com/Athang-codes/ShrinkCode>

