# Changelog

Notable changes to ShrinkCode — the Claude Skill plus its bundled measurement
tooling. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions are the skill package versions.

## Unreleased

### Fixed

- **`scripts/package_skill.py` now runs in a checkout with any folder name** — it
  used to refuse a tree whose folder name disagreed with the skill name, which
  was never part of the upload contract (the *archive root* is, and that comes
  from the frontmatter). GitHub checks the repo out as `ShrinkCode/`, so the
  packager and the packaging pins failed there. A mismatch is a note now, and
  `scripts/selftest.py` pins the renamed case: a `ShrinkCode-main/` ZIP download
  must still package into `shrinkcode/`. The 2.0.1 asset was built from its tag
  before this fix, so rebuilding *that* tag still wants a checkout named
  `shrinkcode/` — the release notes carry the one-line command.

## 2.0.1 — 2026-09-29

Packaging and documentation polish: nothing about how the skill compresses code
changed, so this release is a drop-in replacement for 2.0.0 — but installing it
no longer involves assembling anything by hand.

### Added

- **`shrinkcode.zip` release asset** — the whole skill as one ready-to-upload
  file, with `shrinkcode/` at the archive root and `SKILL.md` inside it, which is
  the layout claude.ai's uploader requires (it rejects an archive whose root
  folder name doesn't match the skill's frontmatter `name`, or that has
  `SKILL.md` at the ZIP root). `shrinkcode.skill` ships alongside it with
  identical bytes.
- **`scripts/package_skill.py`** — builds and validates that asset from the
  committed tree: it checks the `SKILL.md` frontmatter, excludes VCS/build/OS
  cruft and the maintainer-only `dev/` notes, roots the archive at the skill
  name, then re-opens the result to prove the layout. Deterministic output
  (sorted entries, fixed timestamps), so the same commit always rebuilds to the
  same bytes.
- **`assets/demo.svg`** — a terminal capture of the bundled tools' real output
  (the `fixtures/jsproj` duplicate clusters, the complexity ranking, and the
  selftest summary), used at the top of the README.
- **A copy-paste GitHub Action** — the README now carries a self-contained
  workflow that checks the tooling out under `node_modules/shrinkcode` (every
  metric walker skips `node_modules/`, so the tooling never shows up in its own
  report) and posts or updates the bloat comment on the PR.
- **Packaging pins in `scripts/selftest.py`** — three new checks: the skill name
  matches its folder and frontmatter, the built archive is a ZIP rooted at
  `shrinkcode/` with `SKILL.md` inside and no excluded directories, and two
  rebuilds are byte-identical.

### Changed

- **README** — the first line is now the install: download the release asset,
  upload it in claude.ai or unzip it into a Claude Code skills directory.
- **Repo page** — description and topics, and the demo capture above the fold.

## 2.0.0 — 2026-09-28

The release that turns "make this codebase smaller" into a measured,
checkpointed pipeline with an optional always-on guard.

### Added

- **JS/TS structural analysis** — `scripts/js_analyze.mjs` parses JS/TS/JSX/TSX
  with Babel and detects renamed-identifier / stripped-literal duplicates plus
  per-function complexity: exactly the class of copy-paste the text pass misses.
  `find_duplicates.py` and `complexity_report.py` pick its output up
  automatically and fall back to the text pass when Node or the optional
  `@babel/parser` + `@babel/traverse` dependencies are absent.
- **Opt-in deep scan** — `find_duplicates.py --canonicalize` folds commutative
  operand order, symmetric comparisons, independent-statement order and the
  loop-vs-array-chain spelling before fingerprinting, while deliberately keeping
  member names, operators and control flow outside the exact accumulator idiom
  distinct. Measured at +19% runtime on 23 JS files / 48k lines, hence opt-in.
- **Coverage-gap characterization tests** — `scripts/coverage_gap_scaffold.py`
  finds functions with zero coverage (coverage.py or lcov) and emits runnable
  pytest / vitest / jest stubs that pin existing behavior *before* it is
  compressed, for the code no existing test protects.
- **The always-on guard** — `scripts/ci_diff_report.py` plus
  `.github/workflows/shrinkcode.yml` and `.github/shrinkcode-comment-sync.js`
  post one PR comment (found by the hidden `<!-- shrinkcode-bot -->` marker and
  edited in place, never spammed) with the LOC / duplication / complexity delta
  for the files that PR touched. Comment-only by default;
  `ci.failOnRegression` or a manual dispatch opts into failing the check.
- **HTML before/after report** — `scripts/generate_report.py` renders one
  self-contained file (no scripts, no network): metric cards, proportional bars,
  the batch table, and what was deliberately left alone.
- **Parallel Tier-1 batches** — `scripts/partition_batches.py` reads a
  `plan.json` and splits independent Tier-1 changes into non-conflicting groups
  (same file, shared duplicate cluster, target inside another change's cluster,
  Tier 2/3, undeclared files all defer, with the reason recorded), plus
  `references/parallel-execution.md` covering the conflict model and the
  mandatory full-suite serial re-verification at the end.
- **Hard-language guides** — `references/rust.md`, `go.md`, `java-kotlin.md`,
  `csharp.md`, `cpp.md`, each with its own "careful with" section.
- **One-command self-test** — `scripts/selftest.py` runs every bundled tool
  against the curated inputs in `fixtures/` and pins the behavior the docs
  promise: metrics, duplicate clusters (text + AST + `--canonicalize`),
  `excludePaths` honoring, partition acceptance scenarios, the self-contained
  HTML report, the two-commit CI report, comment-sync idempotency, coverage
  stubs, and non-ASCII survival on a cp1252 console. Optional prerequisites
  (Node, git, bash) skip cleanly instead of failing; exit 0 means the skill
  works. `fixtures/README.md` documents each directory.
- **Config file support** — `shrinkcode.config.json` (excludes, duplication and
  complexity thresholds, test/coverage commands, risk overrides, target
  reduction, `ci.failOnRegression`), loaded by `scripts/shrinkcode_config.py`
  and honored by every script. Still zero-config by default;
  `shrinkcode.config.example.json` documents the schema.

### Changed

- Duplicate and complexity reports display every path relative to the scan root,
  so the JS/TS analyzer's absolute paths no longer mix with the Python pass's
  relative ones in one list.
- `references/metrics-and-tooling.md` documents each metric and each tool's
  blind spots, the deep-scan decision with its measurements, and a verified
  sample PR comment.
- `plan.json` joined the plan template as the machine-readable companion to the
  markdown compression plan.

### Fixed

- Piped stdout on Windows (cp1252) raised `UnicodeEncodeError` on the non-Latin-1
  glyphs the reports use (`Δ`, `↳`) — a hard crash, not mojibake. All CLI scripts
  now call the shared `utf8_stdout()` guard from `shrinkcode_config.py`.
- Metric snapshots written by PowerShell (`Out-File`) carry a UTF-8 BOM; the JSON
  loaders read `utf-8-sig` so a BOM can never break a `--diff`.
- The JS/TS analyzer's stdout was decoded with the *locale* encoding
  (`text=True`): on a cp1252 Windows console that raised `UnicodeDecodeError`
  on the first byte cp1252 leaves undefined (Japanese identifiers, emoji
  paths) or silently mojibaked every non-ASCII path — which then defeated the
  path-prefix match and printed absolute paths beside relative ones. All
  analyzer call sites now go through one `run_js_analyzer()` helper that
  forces UTF-8, resolves `node` with `shutil.which`, and returns only object
  payloads so callers can `.get()` unguarded. Pinned by the emoji fixture in
  `scripts/selftest.py`.

### Decided (documented, not built)

- A semantic/embedding duplicate pass was evaluated and deliberately not added:
  the canonicalized AST scan caught every target case in the acceptance fixtures
  at +19% runtime, with unrelated same-shape controls scoring ≤0.30 against the
  0.85 threshold. An embeddings dependency would add an install, a model
  download and per-block inference for no demonstrated JS/TS gap. The exact
  conditions that would justify building it are recorded in
  `references/metrics-and-tooling.md`.

## 1.0.0 — initial release

The original six-phase skill: analyze / baseline / plan / execute / verify /
report, with `loc_report.py`, `find_duplicates.py`, `complexity_report.py`,
`dead_code_scan.sh`, `checkpoint.sh`, the tiered risk model, the verification and
git-workflow references, and the language guides for Python, TypeScript/JS,
React/Next.js, HTML/CSS, Vue/Svelte and Node backends.
