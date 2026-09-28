# Anti-patterns: what "compression" is NOT

These reduce character/line count without reducing real complexity, and actively
hurt maintainability, or they cut corners on the verification this skill exists to
guarantee. Never do these in the name of shrinkcode:

- **Cramming multiple statements onto one line** with semicolons/commas just to
  cut line count. This is not compression, it's obfuscation, and it doesn't even
  help — the user's goal is a smaller, equally-functional *codebase*, not a
  smaller line counter output. `loc_report.py` separates code/blank/comment
  precisely so this can't be disguised as a real reduction.
- **Deleting all comments/whitespace/blank lines wholesale.** A few genuinely
  redundant or stale comments can go if they've clearly rotted, but comments
  explaining *why* (not *what*) are load-bearing documentation, not bloat.
- **Renaming meaningful variables to single letters** (`userAccountBalance` →
  `x`). Saves near-zero real lines and destroys readability.
- **Minifying source files.** That's a build step, not a code-design skill — if
  the user wants minified output for production, that's a bundler's job, not
  this.
- **Nesting ternaries or chaining so many operators that a single line hides 4
  branches of logic.** If you can't explain the line in one sentence, it's not
  compression, it's compaction of complexity into unreadable form — and it will
  usually *increase* the cyclomatic complexity score even as line count drops,
  which is exactly why `complexity_report.py` tracks this metric separately.
- **Silently "fixing" behavior while compressing** — e.g. tightening a loose
  equality check, removing what looks like a redundant null-check, deduping what
  looks like an accidental duplicate call, parallelizing sequential awaits,
  narrowing a bare `except:`. Any of these might be a deliberate (if ugly)
  behavior the user depends on. If you spot something that looks like a bug
  rather than bloat, flag it to the user separately — don't fix it as part of a
  "behavior-preserving" compression pass. This is exactly what the Tier
  classification in `risk-classification.md` exists to prevent by requiring
  explicit sign-off on anything semantic.
- **Chasing a specific target percentage/number at the expense of correctness.**
  If the honest safe compression is 35% not 50%, report 35% and say why in the
  compression plan (`compression-plan-template.md`) — don't force the rest
  through by cutting corners on verification or reaching into Tier 3 changes the
  user didn't ask you to risk.
- **Trusting a single static-analysis tool's "unused" verdict without
  cross-checking.** `vulture`/`ts-prune`/`madge --orphans` all produce
  candidates, not proof — a flagged "dead" export can be a public API entry
  point, a dynamically-invoked handler, or a framework convention file (Next.js
  page, CLI entry point). Deleting on a single tool's say-so, without a grep
  cross-check, is how "verified" compressions quietly ship real regressions.
  See `metrics-and-tooling.md`'s "don't act on a single tool's say-so" section.
- **Batching unrelated changes into one giant commit/diff.** This isn't a
  cosmetic nit — it's what makes a regression unbisectable three weeks later.
  Every batch gets its own checkpoint per `git-workflow.md`; skipping this to
  save a few minutes is a false economy on any job beyond a single trivial file.
- **Claiming verification you didn't run.** "Tests pass" when you mean "I read
  the code and it looks like tests would pass," or "functions identically" with
  no characterization test for the one edge case that mattered — this is the
  single worst failure mode for this skill, because the whole premise is that
  the user can trust "smaller AND identical" as a joint claim, not just take
  your word for the second half.
