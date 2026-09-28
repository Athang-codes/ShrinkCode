# Risk classification

Not every compression carries the same risk of silently changing behavior. Treating
"delete a provably unused import" and "parallelize three sequential awaits" with the
same verification effort either wastes time on the former or under-verifies the
latter. Classify every planned change into one of three tiers before executing it,
and apply the verification bar that tier requires — no exceptions, no "this one
feels safe so I'll skip it."

## Tier 1 — Mechanical (low risk)

Changes where a machine can basically prove safety, because there's no
interpretation involved.

**Examples:**
- Deleting an import/variable/function that a static tool confirms has zero
  references anywhere in the repo (and you've manually grep-confirmed it isn't
  invoked dynamically/via string/reflection).
- Merging two byte-for-byte identical blocks (exact duplicates from
  `find_duplicates.py`'s exact-match output) into one.
- Swapping hand-rolled logic for a language/stdlib built-in with textbook-
  identical semantics (e.g. manual `os.path.join` string concat → `pathlib`,
  a manual `try/finally` cleanup → a `with` block that does the same open/close).
- Removing genuinely dead files confirmed via `madge --orphans` AND manually
  confirmed not to be a framework entry point.

**Verification bar:** re-run the full existing test suite once after the batch.
If no tests exist, run the characterization tests you built in Phase 2 for the
touched code paths specifically. No manual UI walkthrough needed for pure-logic
Tier 1 changes.

## Tier 2 — Structural (moderate risk)

Changes where correctness depends on you having understood the code's intent
correctly, not just its current text.

**Examples:**
- Consolidating near-duplicate (not exact) blocks into one parameterized
  function/component — the near-duplicates might differ for a reason you
  haven't spotted yet.
- Merging multiple files/modules into one.
- Replacing a hand-rolled validation/state-management pattern with a
  library (Zod/Pydantic/a custom hook) — the replacement must be checked
  against every validation rule the original enforced, including edge cases
  that aren't obvious from a quick read.
- Simplifying an abstraction (factory/strategy pattern collapsed to a
  concrete implementation) that's currently used in exactly one place but
  might be intentional future-proofing.

**Verification bar:** full existing test suite AND the relevant
characterization tests for every code path touched, run after each individual
change in this tier (not batched together with other Tier 2 changes) — plus,
for UI code, a before/after visual/interaction check per `references/
verification.md`'s stack-specific notes. Report each Tier 2 change to the
user individually if it involved a judgment call about intent (see "flag,
don't silently decide" below).

## Tier 3 — Semantic (high risk)

Changes where the *order*, *timing*, or *failure behavior* of the code could
change even though the "logic" looks equivalent on paper.

**Examples:**
- Sequential `await` → `Promise.all` (changes ordering guarantees and
  fail-fast-on-first-rejection semantics).
- Any reordering of hook calls in React (correctness-critical, not just style).
- CSS selector consolidation that could change cascade/specificity resolution
  order.
- Changing exception handling (broadening/narrowing a `try/except`, changing
  what a bare `except:` swallows).
- Any change to caching/memoization boundaries (`useMemo`/`useCallback`/
  `lru_cache` dependency changes) — can silently change what's considered
  "stale" versus "fresh."
- Deleting something a static tool flags as unused when it's below ~80%
  confidence, or when it's a class/function whose name suggests it might be a
  plugin/handler invoked by name/reflection.

**Verification bar:** everything Tier 2 requires, PLUS: (a) explicit
confirmation from the user before applying — describe the specific semantic
risk in plain language, don't just say "this is a bit risky"; (b) the
characterization tests must specifically include the edge case the semantic
change could affect (e.g., for the `Promise.all` case, a test where the first
promise rejects, to confirm both versions still surface the error the same
way and however-many-ever side effects from later promises are or aren't
prevented, matching the original).

## Flag, don't silently decide

Any change that depends on inferring *intent* rather than just reading current
behavior (a Tier 2 abstraction simplification, an "this early-return looks
redundant" removal) gets reported to the user as a specific line item with
your reasoning — even if you're confident. The user has context you don't
(a planned feature, a business rule, a workaround for a bug in a library).
"I collapsed X because Y — flag if that's wrong" costs one sentence and
prevents silently reintroducing a bug that was actually a deliberate
workaround.

## Ordering your execution plan by tier

Execute Tier 1 first, always, across the whole codebase — it's the highest
safety-to-effort ratio and often gets you a large fraction of the way to the
target line count before you touch anything requiring judgment. Then Tier 2,
one file/module at a time with verification between each. Then Tier 3, one
change at a time, each with explicit user sign-off before applying. If the
user's target line count is met after Tier 1 + Tier 2, stop — don't reach into
Tier 3 for marginal extra reduction the user didn't ask you to risk.
