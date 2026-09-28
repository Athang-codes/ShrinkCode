# TypeScript / JavaScript compression idioms

## Idioms, roughly in order of typical impact

- **Zod / Yup / Valibot schema validation** instead of repeated manual
  `if (!x) throw` validation blocks scattered across handlers — usually the
  single biggest win in an API codebase; look for this pattern first.
- **Shared generic types/interfaces** instead of near-duplicate type
  definitions scattered across files (`UserA`, `UserB`, `UserResponse` that
  are 90% the same shape — use a base type + `Omit`/`Pick`/`Partial`).
- **Utility types** (`Partial`, `Pick`, `Omit`, `Record`, `ReturnType`,
  `Parameters`) instead of hand-written variant interfaces.
- **Optional chaining (`?.`) and nullish coalescing (`??`)** instead of
  verbose manual null-guard chains — but don't chain so deep it hides a real
  logic branch that used to be an explicit, readable check.
- **Array methods (`map`/`filter`/`reduce`/`find`/`some`/`every`)** instead of
  manual for-loops with accumulator variables, where it doesn't hurt
  readability.
- **A single generic API-call wrapper/hook** (handles loading/error/retry
  once) instead of the same fetch-try-catch-setState pattern copy-pasted per
  call site.
- **Middleware/HOF wrappers** for cross-cutting concerns (auth check,
  logging, error handling) repeated at the top of many route handlers/
  functions — in Express/Fastify/Next.js API routes alike.
- **Destructuring with defaults** instead of multiple `const x = obj.x || default`
  lines.
- **Template literal types / discriminated unions** instead of repeated
  string-literal validation logic scattered across the codebase.

## Careful with (these are Tier 2/3, not Tier 1 — see risk-classification.md)

- **`Promise.all` vs sequential `await`** is a behavior change if original
  ordering, or fail-fast-on-first-rejection semantics, mattered. Verify with a
  characterization test where one promise rejects before "simplifying" this.
- **`==` vs `===`.** Don't "helpfully" tighten equality checks while
  compressing — that's a behavior change (type coercion edge cases), not
  compression, even when `===` looks obviously more correct.
- **Truthiness shortcuts.** Collapsing `if (x !== null && x !== undefined)` to
  `if (x)` changes behavior for `x = 0`, `x = ""`, or `x = false` — only
  safe if you've confirmed those values can't legitimately occur here.

## Tooling recap (see metrics-and-tooling.md for full detail)

| Task | Command |
|------|---------|
| Duplication (bundled AST structural pass — first choice) | `python3 scripts/find_duplicates.py <path>` (auto-runs `js_analyze.mjs` for JS/TS) |
| Duplication (independent cross-check) | `npx jscpd <path>` |
| Complexity (bundled, same formula as Python) | `python3 scripts/complexity_report.py <path>` |
| Complexity (external cross-check) | `npx lizard <path>` or `npx eslint --rule 'complexity: ["error", 10]'` |
| Unused exports | `npx ts-prune -p tsconfig.json` or `npx knip` |
| Unused dependencies | `npx depcheck` |
| Circular deps / orphan files | `npx madge --circular <path>` / `npx madge --orphans <path>` |
| Tests | `npx vitest run` or `npx jest` |
