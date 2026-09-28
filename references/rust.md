# Rust compression idioms

Run `cargo clippy` before starting — it drives most of the automated
detection, and `scripts/dead_code_scan.sh` will point at it for unused code.

## Idioms, roughly in order of typical impact

- **Iterator combinators** (`map`/`filter`/`fold`/`collect` chains) over
  manual `for` loops with mutable accumulators — the single most common
  loop-bloat collapse in Rust. Stop chaining when the pipeline needs a
  comment to explain what it does; a clear 4-line loop beats a cryptic
  one-liner (see anti-patterns.md: terseness isn't the goal).
- **`?` operator over manual error matching** — `match result { Ok(v) => v,
  Err(e) => return Err(e) }` repeated after every fallible call collapses to
  `?`. Usually the biggest single win in CLI/backend Rust codebases.
- **`derive` macros over hand-written trait impls** — `#[derive(Debug, Clone,
  PartialEq, Serialize)]` instead of manual `impl` blocks for `Debug`/
  `Clone`/`Eq`/`serde::Serialize`. Hand-written `Default`/`Display` impls
  that just repeat field defaults are also candidates.
- **`enum` + `match` dispatch** instead of type-tag + `if kind == ...`
  sprawl (Rust's equivalent of the classic copy-paste-per-type pattern that
  `find_duplicates.py --normalize-literals` is tuned to catch).
- **Builder pattern / `Default::default()` + struct update syntax** (`..Default::default()`)
  over long constructor functions with 10 optional parameters.
- **Extension traits / generic helpers** over near-identical per-type
  functions — but only when both call sites exist today; a trait with one
  implementation is speculative abstraction (Tier 2 judgment call, flag it).
- **`slice`/`str` methods** (`split_at`, `windows`, `chunks`, `iter().zip()`)
  over manual index bookkeeping.

## Careful with (these are Tier 2/3, not Tier 1 — see risk-classification.md)

- **Ownership/borrow changes that look like simplifications.** Cloning less,
  returning references instead of values, or merging two structs' lifetimes
  can silently change *when* moves happen — and move semantics aren't
  observable in tests that only check outputs until they hit a use-after-move
  the compiler previously prevented. Any change to `.clone()` placement,
  `&` vs `&mut`, or `Cow` usage is Tier 2 minimum; changing what's moved vs
  copied across a branch is Tier 3.
- **`unsafe` blocks and `Send`/`Sync` bounds.** Never "simplify" these
  during compression — any refactor touching `unsafe`, raw pointers, or
  auto-trait bounds needs explicit sign-off regardless of what the diff
  looks like.
- **`Copy` type conversions.** Switching a struct from `Clone` to `Copy`
  (or vice versa) changes move/copy semantics at every call site — not
  compression, a behavior-adjacent change.

## Tooling recap (see metrics-and-tooling.md for full detail)

| Task | Command |
|------|---------|
| Lint + style (drives detection) | `cargo clippy --all-targets` |
| Unused dependencies | `cargo udeps` (nightly) or `cargo machete` |
| Complexity (external cross-check) | `npx lizard <path>` or `cargo complexity` |
| Duplication | `python3 scripts/find_duplicates.py <path> --normalize-literals` |
| LOC cross-check | `tokei <path>` or `cloc <path>` |
| Tests | `cargo test` |
