# Metrics and tooling

Line count alone is a bad target — it can be gamed (cram statements, delete
comments) without reducing real complexity. shrinkcode tracks three numbers, and a
job isn't done until you can show all three moved in the right direction:

| Metric               | What it actually measures                          | Tool (bundled or external) |
|-----------------------|-----------------------------------------------------|-----------------------------|
| Lines of code (real)  | Code lines only, blank/comment separated            | `scripts/loc_report.py` (bundled, stdlib only) |
| Duplication           | Exact + near-duplicate blocks across the codebase   | `scripts/find_duplicates.py` (text pass, any language) + `scripts/js_analyze.mjs` (AST structural pass for JS/TS — catches renamed-variable copies the text pass misses) + `jscpd` for external cross-check |
| Cyclomatic complexity | Decision-point density per function                 | `scripts/complexity_report.py` (bundled: Python directly; JS/TS via bundled `js_analyze.mjs`, same formula so numbers are comparable) + `lizard`/`eslint complexity` as cross-checks |
| Dead code / unused exports | Code with zero live references              | `scripts/dead_code_scan.sh` (wraps vulture/ts-prune/knip/depcheck/madge) |

## Bundled scripts — always run these first, no install required

```bash
# LOC baseline (run before AND after, then diff)
python3 scripts/loc_report.py <path> --save before_loc.json
# ... do the compression ...
python3 scripts/loc_report.py <path> --diff before_loc.json

# Duplicate block detection (drives most of Phase 1's plan)
# — text pass + AST structural pass for JS/TS, one unified report
python3 scripts/find_duplicates.py <path> --min-lines 5 --normalize-literals

# Opt-in deep scan for JS/TS (same report, canonical statement order — see
# "Deep scan: --canonicalize" below before reaching for it)
python3 scripts/find_duplicates.py <path> --canonicalize

# Complexity baseline (Python + JS/TS; prints external-tool hints only when
# the bundled JS analyzer can't run)
python3 scripts/complexity_report.py <path> --save before_complexity.json
# ... do the compression ...
python3 scripts/complexity_report.py <path> --diff before_complexity.json

# Dead code / unused exports / circular deps (auto-detects stack, degrades gracefully)
bash scripts/dead_code_scan.sh <path>
```

## JS/TS: first-class, not a "run it yourself" hint

`scripts/js_analyze.mjs` parses JS/TS/JSX/TSX with `@babel/parser` and:

- **Structural duplicate detection** — normalizes each function (identifiers →
  positional `$1, $2…` placeholders, literals stripped) and hashes it. Copies
  that differ only in variable names come back as **exact** clusters instead
  of a low-confidence near-duplicate guess. `find_duplicates.py` invokes it
  automatically whenever JS/TS files are present and merges the result into
  the same report — you don't run it separately (though you can:
  `node scripts/js_analyze.mjs <path> --mode duplicates`).
- **Complexity with the same formula as Python** — `1 + decision points`
  (if / loops / catch / `&&`/`||`/`??` / ternary / non-default switch case),
  so a Python module at avg 4.0 and a TS module at avg 4.0 are actually
  comparable. `complexity_report.py` invokes it automatically.

Setup: Node ≥18 plus `npm install @babel/parser @babel/traverse` inside the
skill folder (one time). If Node or the deps are missing, both Python scripts
degrade to a clear hint with the install command — never a crash — and the
external-tool fallbacks below still work.

### Deep scan: `--canonicalize` (opt-in, JS/TS)

```bash
node scripts/js_analyze.mjs <path> --mode duplicates --canonicalize
# the same pass through the unified report (prints a note when it ran):
python3 scripts/find_duplicates.py <path> --canonicalize
```

Not part of any default run. It reuses the structural pass but canonicalizes
each function body before hashing, so it clusters computations that are
*equal*, not merely *spelled alike*:

**Folds together (recall):**
- independent statements written in another order — bodies are compared in a
  canonical order that never moves anything past a return/throw/break/continue
  or across a real read/write dependence;
- `for (const u of xs) { if (c) out.push(f(u)) } return out` vs
  `return xs.filter(c).map(f)` (plus the plain `.map` / `.filter` forms) —
  exact accumulator loops fold into the same pipeline marker;
- commutative logical operands (`a && b` vs `b && a`) and symmetric
  comparisons (`null === x` vs `x === null`);
- plus everything the structural pass already folds (renamed identifiers,
  stripped literals).

**Deliberately kept distinct (precision):** member/property names (`.id` vs
`.name`), operators (`a - b` vs `a + b`), scalar flags (`kind`, `computed`,
`optional`), and control flow outside the exact accumulator idiom. In a pass
whose hits may lead to a merge, a false positive costs more than a miss.

**Measured cost** (so "slower, use deliberately" is a number, not a guess):
23 JS files / 48,070 lines of bundled real-world code, best of 5 runs —
default duplicates mode 4,828 ms, `--canonicalize` 5,762 ms: **+19%**. No
model download, no extra install, no per-block inference; the added work is
one more serialization pass per function.

**Measured margin** on the acceptance fixtures: the same-computation pairs
(reordered checks, loop vs `.map`, loop vs `.filter().map()`) come back as
exact clusters (ratio 1.0), while unrelated same-shape controls score **≤0.30**
against the 0.85 threshold — and the `.id`/`.name`, `a-b`/`a+b` guards that
the structural pass merges stay unmerged.

**Known boundary:** literal *values* are stripped, so two validators with the
same shape but different rules (`isValidPhone` vs `isValidHexColor`) still
cluster — deliberate, since that is what lets "same logic, different constant"
copies match, but it means deep-scan hits on validation code always need the
constants checked by hand before anything is merged.

**Why this instead of embeddings:** the upgrade prompt asked for an
evaluation before building an embedding-based `semantic_duplicates.py`. The
canonicalized AST pass caught every target case in the fixtures above at +19%
runtime, so that is what shipped; a sentence-transformers/CodeBERT pass would
add a `pip install`, a one-time model download and per-block inference orders
of magnitude dearer, with no demonstrated JS/TS gap left to fill. Build
`scripts/semantic_duplicates.py` only when a real gap appears: control flow
restructured beyond these folds, cross-language duplicates, or natural-
language similarity.

**When to reach for which detector:**
1. `find_duplicates.py` (text + structural AST) — always first; cheap, and it
   already catches renamed/copied blocks.
2. `--canonicalize` — when (1) comes back suspiciously clean on a codebase
   with heavy copy-paste-and-rename history, or for a targeted "is this logic
   duplicated elsewhere?" audit. Confirm every hit by hand.
3. `jscpd` (below) — for cross-language copy-paste or an independent second
   opinion.

## CI: the same numbers as a pull-request comment (opt-in)

`.github/workflows/shrinkcode.yml` runs these same measurements on every pull
request and keeps **one** comment — found by the hidden `<!-- shrinkcode-bot -->`
marker, so later pushes edit it in place instead of spamming a new one —
up to date with the delta for that PR. `scripts/ci_diff_report.py` is the whole
report; the workflow is deliberately thin:

```bash
python3 scripts/ci_diff_report.py --base origin/main --head HEAD --output body.md
python3 scripts/ci_diff_report.py --base origin/main --head HEAD --json   # machine-readable
python3 scripts/ci_diff_report.py --base origin/main --head HEAD --fail-on-regression
```

How it differs from the Phase 1/6 runs, and why:

- **Scope is the PR's changed files only** (`git diff --name-only
  origin/<base>...HEAD`, three-dot so it diffs against the merge base) — a
  10,000-line repo shouldn't get a fresh whole-tree verdict on every push.
- **Both sides are measured identically**: the base ref is checked out into a
  temporary `git worktree`, so a block that merely *moved* reads as 0 → 0
  instead of showing up as a brand-new duplicate. The workflow therefore needs
  `fetch-depth: 0`.
- **Comment-only by default.** Bloat going up is a team decision, not a tool
  verdict: the check only fails with `--fail-on-regression` or
  `ci.failOnRegression: true` in `shrinkcode.config.json`.
- **First run degrades honestly.** If the base ref can't be resolved (brand-new
  repo, shallow fetch, no merge base) it shows absolute whole-tree numbers with
  an explanatory note and exits 0 — no delta invented from a missing snapshot,
  and `regression` stays `None` (uncomparable) rather than `False` (checked,
  clean).
- **Locations are repo-relative** in the comment (`app2.py:14`), never an
  absolute checkout path.

Verified sample — fixture repo, `feature` adds `app2.py` containing a copy of
`app.py`'s 8-line `validate_email`, base has neither:

    <!-- shrinkcode-bot -->

    ### shrinkcode: bloat report — `feature` vs `main`

    | Metric | Base | PR | Δ |
    | --- | ---: | ---: | --- |
    | Code lines | 0 | 8 | +8 (n/a) ⚠️ |
    | Avg complexity | 0.00 | 4.00 | +4.00 (n/a) ⚠️ |
    | Exact duplicate clusters | 0 | 4 | +4 (n/a) ⚠️ |

    **Duplicate locations** (8 — clusters involving a changed file; the matching copy may predate this PR):

    - `app.py:1`
    - `app2.py:1`
    … (4 overlapping windows × 2 files)

    > ⚠️ Metrics went up — comment-only mode, this check is not failing. Set `ci.failOnRegression` to enforce.

    <sub>scope: changed files only · generated by `scripts/ci_diff_report.py`</sub>

Two reading notes. `Base` reads 0 for the changed file because `app2.py` doesn't
exist at the base commit — `(n/a)` there means "no percentage from a zero
baseline", not "no data". And the cluster count is a sliding-window count, so one
duplicated 8-line function reports as 4 overlapping clusters; read the trend, not
the absolute number. `--json` gives the same fields
(`first_run`, `changed_files`, `loc`/`complexity`/`duplicates` with `base`/`head`,
`regression`, `strict`, `notes`, `marker`) for scripting.

The pull-request comment path is verified with a local two-commit git fixture
(delta math, first-run fallback, exit codes) plus a simulated two-push run
against the real comment-sync code asserting one comment exists and is updated in
place. Workflow YAML is `actionlint`-clean. Posting from a *fork* PR is the one
part that can't be verified outside GitHub: fork runs get a read-only
`GITHUB_TOKEN`, so the comment step fails there while the report still prints in
the job log.

## External tools these scripts point you to (install on demand, not bundled)

- **`jscpd`** — `npx jscpd <path>` — proper AST-aware copy-paste detector for
  JS/TS/many languages. Use after `find_duplicates.py`'s text-based first pass
  flags a hot area, for higher-confidence clusters on large repos.
- **`vulture`** (Python) — `pip install vulture --break-system-packages` — finds
  unused functions/classes/imports/variables via static analysis. Confidence
  score matters: below ~80% confidence, treat as a hint not a fact.
- **`ts-prune`** — `npx ts-prune -p tsconfig.json` — unused TypeScript exports.
  Requires a `tsconfig.json`. Newer alternative: **`knip`** (`npx knip`), which
  also catches unused files, dependencies, and exports in one pass — prefer
  `knip` when the project is large enough to justify the extra setup.
- **`depcheck`** — `npx depcheck` — unused/missing npm dependencies in
  `package.json`. Removing an unused dependency doesn't shrink source LOC but is
  real bloat reduction (install size, attack surface, audit noise) worth
  reporting alongside code compression.
- **`madge`** — `npx madge --circular <path>` and `npx madge --orphans <path>`
  — circular dependency detection and orphan-module detection (files nothing
  imports — strong dead-code-file candidates, but confirm they aren't entry
  points like `main.ts` or a Next.js page file, which are "orphans" by design).
- **`radon`** (Python) — `pip install radon --break-system-packages` — more
  complete cyclomatic + maintainability-index reporting than the stdlib
  fallback in `complexity_report.py`. The bundled script uses it automatically
  if present.
- **`lizard`** — `npx lizard <path>` (or `pip install lizard`) — cyclomatic
  complexity for C-family languages including JS/TS/JSX/TSX, since
  `complexity_report.py` doesn't parse those directly.
- **`cloc`** — `npx cloc <path>` — an alternative, more battle-tested LOC
  counter if you want a cross-check against `loc_report.py`'s output,
  especially on unusual file types.

## Interpreting results — don't act on a single tool's say-so

Every one of these tools produces **candidates**, not verdicts:
- A "dead" export might be a public API entry point external code calls.
- An "orphan" module might be a framework entry point (Next.js page, CLI
  `__main__`, a script referenced only from `package.json`'s scripts, a
  dynamically-`require()`'d plugin).
- High duplication similarity might be intentional (e.g. two API handlers
  that look similar today but are versioned/independent on purpose).

Cross-check flagged items against actual usage (grep for the symbol name
across the whole repo, check build/deploy configs, check for
dynamic/reflection-based invocation) before deleting. This confirmation step
is part of Phase 1 in SKILL.md, not optional due-diligence you can skip under
time pressure.
