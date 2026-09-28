# C# compression idioms

Run `dotnet format --verify-no-changes` and your analyzer set first —
Roslyn analyzers drive most of the automated detection.

## Idioms, roughly in order of typical impact

- **LINQ** (`Where`/`Select`/`OrderBy`/`GroupBy`) over manual
  for-loop-with-accumulator — the classic C# loop-bloat collapse, usually
  the biggest single win. Stop chaining when the pipeline needs a comment
  to parse (same readability rule as everywhere else).
- **Records (C# 9+)** over hand-written DTO/POJO classes with constructor,
  properties, `Equals`/`GetHashCode`, and `ToString` — a 50-line mutable
  DTO class becomes a 1-line `record Person(string Name, string Email);`.
  Check the project's language version in the `.csproj` (`<TargetFramework>`
  / `<LangVersion>`) first.
- **Pattern matching** (`is`, `switch` expressions, property patterns,
  relational patterns) over `as`/`is` cast-then-check chains and long
  `if/else if` type-dispatch ladders:
  `if (o is Point { X: > 0 } p)` replaces 4 lines with 1 while keeping the
  same narrowing semantics.
- **Target-typed `new()` and global usings** (C# 10+) instead of repeated
  full type names — only where the project already enabled them; don't
  flip `<ImplicitUsings>` on as "compression."
- **`record struct` / init-only properties** instead of validation-heavy
  setters for immutable value carriers.
- **Collection expressions** (C# 12: `[1, 2, 3]`) over
  `new List<int> { ... }` boilerplate — check language version first.
- **Null-coalescing/conditional chains** (`?.`, `??`, `??=`) over manual
  null-guard blocks — same truthiness caveat as `typescript-js.md`: `??`
  only checks null, `?.` short-circuits only null — don't "tighten" or
  "loosen" null semantics while compressing.

## Careful with (these are Tier 2/3, not Tier 1 — see risk-classification.md)

- **Reference vs value semantics on records/structs.** Converting a class
  to a `record` or `struct` changes equality (value vs reference), copying,
  and nullability at every usage — Tier 3 unless the type is provably a
  simple DTO with no identity use.
- **LINQ execution deferred vs eager.** `IEnumerable<T>` LINQ is lazy;
  materializing (or removing a `.ToList()`) changes when side effects and
  exceptions happen, and iterating twice re-runs the pipeline. Tier 2.
- **`async`/`await` ordering** — same `Promise.all`-class risk as
  `Task.WhenAll` conversions: fail-fast and ordering semantics can shift.
  Tier 3.

## Tooling recap (see metrics-and-tooling.md for full detail)

| Task | Command |
|------|---------|
| Style + analyzers (drives detection) | `dotnet format --verify-no-changes` + `dotnet build /warnaserror` |
| Complexity / metrics (external) | `npx lizard <path>` or NDepend (if available/licensed) |
| Duplication | `python3 scripts/find_duplicates.py <path> --normalize-literals` |
| Dead code | `dotnet format --analyze` warnings + IDE unused-symbol diagnostics |
| Tests | `dotnet test` |
