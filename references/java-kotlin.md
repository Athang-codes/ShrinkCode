# Java / Kotlin compression idioms

Run your linter first — PMD (Java) and detekt (Kotlin) drive most of the
automated detection; `scripts/dead_code_scan.sh` currently targets
Python/JS/TS stacks, so for JVM projects run the tools in the table below
manually.

## Idioms, roughly in order of typical impact

- **Streams API** (`stream().filter().map().collect()`) over manual
  for-loop-with-accumulator — the classic Java loop-bloat collapse. Same
  rule as everywhere: stop chaining when the pipeline needs a comment to
  parse.
- **Records (Java 16+) / Kotlin data classes** over hand-written POJOs with
  explicit constructors, getters, `equals`/`hashCode`/`toString`. Usually
  the single biggest boilerplate win — a 60-line POJO becomes a 1-line
  record. Check the project's language level (`maven-compiler-plugin`/
  `sourceCompatibility`) before using records; Kotlin data classes are
  always available.
- **Lombok if already in use** (`@Data`, `@Builder`, `@Value`) — never add
  Lombok to a project that doesn't have it (new dependency = not
  compression), but replace hand-written boilerplate it already supports
  with the annotation.
- **`var` (Java 10+ / Kotlin idiomatic)** instead of repeated generic type
  names on obvious locals — only where the initializer makes the type
  unambiguous; `var x = new HashMap<String, List<Integer>>()` style wins
  are real, `var x = compute()` losses are not (hurts readability for zero
  complexity gain).
- **Switch expressions (Java 14+) / Kotlin `when`** over `if/else if` chains
  dispatching on a value — Tier 1 for the mechanical rewording, Tier 2 if
  fall-through semantics change.
- **Optional/guard clauses consolidation** — repeated null-check + throw
  blocks at the top of methods collapse into one shared validation helper
  or bean-validation annotations if the project already uses them
  (`@Valid`, `@NotNull`).
- **Kotlin scope functions** (`let`, `apply`, `run`) over manual null-guard
  nesting — but only over one nesting level each; chained `let{}.let{}` is
  worse than the if-chain it replaced.

## Careful with (these are Tier 2/3, not Tier 1 — see risk-classification.md)

- **`equals`/`hashCode` contracts.** Switching a class from identity
  equality (record-style or data class) to value equality (or vice versa)
  changes HashMap/HashSet behavior at every call site. Tier 3 if the type
  is ever used as a map key or in a collection — confirm with the user.
- **Stream vs loop side-effect ordering.** Sequential streams preserve
  encounter order; `parallelStream()` / `Collectors.toList()` on unordered
  collectors can reorder — same class of risk as `Promise.all` (Tier 3).
- **Kotlin null-safety surface.** Converting `T!` platform types to
  non-null or changing `?.` to `.` changes where NPEs appear. Not
  compression.

## Tooling recap (see metrics-and-tooling.md for full detail)

| Task | Command |
|------|---------|
| Complexity (Java + most C-family) | `pmd check -R rulesets/java/cyclomaticcomplexity.xml <path>` or `npx lizard <path>` |
| Copy-paste detection (Java) | `pmd check -R rulesets/java/copypaste.xml <path>` |
| Style (Java) | `checkstyle -c <config> <path>` |
| Complexity/lint (Kotlin) | `detekt <path>` |
| Duplication (cross-check) | `python3 scripts/find_duplicates.py <path> --normalize-literals` |
| Tests | `mvn test` / `gradle test` / `./gradlew test` |
