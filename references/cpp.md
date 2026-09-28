# C++ compression idioms

Run `clang-tidy` and `cppcheck` first — they drive most of the automated
detection for C++.

## Idioms, roughly in order of typical impact

- **RAII over manual resource cleanup** — `std::lock_guard`/`std::unique_ptr`
  / `std::ifstream` in scope instead of hand-rolled
  `open(); ...; close()` on every early-return path. This is the C++
  equivalent of Python's context-manager collapse and usually the biggest
  win: it deletes entire cleanup blocks *and* the early-return copies of
  them. New RAII wrappers from scratch are Tier 2 (an abstraction someone
  may have deliberately avoided); using existing types (`unique_ptr`,
  `scoped_lock`) is Tier 1.
- **STL algorithms over manual loops** — `std::find_if`, `std::any_of`,
  `std::transform`, `std::sort`, `std::copy_if` replace 10-line manual
  loops. Same readability rule as everywhere: stop chaining when a lambda
  pipeline needs a comment to parse.
- **Range-based for + structured bindings** (`for (auto& [key, value] : map)`)
  over iterator-boilerplate `for (auto it = m.begin(); it != m.end(); ++it)`
  — deletes the iterator ceremony entirely.
- **`constexpr`/`auto` for obvious type spellings** — `auto` for long
  iterator typedefs is a genuine line-count win; don't use it where it
  hides a non-obvious type conversion.
- **String/stream building with `std::format` (C++20) / `ostringstream`**
  over manual `+`/`std::to_string` concatenation chains — check the
  project's standard (`CMakeLists.txt` `CXX_STANDARD`) first.
- **Default member initializers + default arguments** instead of repeated
  constructor-initializer boilerplate across overloads.

## Careful with (these are Tier 2/3, not Tier 1 — see risk-classification.md)

- **Manual memory management changes are inherently Tier 3.** Never
  "simplify" ownership/lifetime code — converting raw pointers to
  `unique_ptr`, changing `new`/`delete` pairs, moving objects across
  containers, or touching custom allocators — without explicit sign-off.
  Ownership changes can introduce double-frees, leaks, or dangling
  references that only surface under specific runtime paths. This is the
  most on-theme risk in the whole language for this skill's tier system.
- **Copy vs move semantics.** Adding `std::move`, removing a copy, or
  changing a parameter from value to reference alters when copies happen —
  observable if the type has side-effecting copy ctors (or resource
  ownership). Tier 2 minimum; Tier 3 if the type owns a resource.
- **`inline`/ODR and header placement.** Moving definitions between
  headers and `.cpp` files changes linkage/ODR behavior — not compression.
- **Floating-point reassociation.** "Simplifying" arithmetic
  (reassociating `(a + b) + c` → `a + (b + c)`) changes results under
  IEEE-754 — a real behavior change even though it looks algebraically
  identical.

## Tooling recap (see metrics-and-tooling.md for full detail)

| Task | Command |
|------|---------|
| Lint / refactor checks (drives detection) | `clang-tidy <path> -- <flags>` |
| Static analysis (bugs + style) | `cppcheck --enable=warning,style,performance <path>` |
| Include bloat | `include-what-you-use <file>` |
| Complexity (external cross-check) | `npx lizard <path>` |
| Duplication | `python3 scripts/find_duplicates.py <path> --normalize-literals` |
| Tests | `ctest` / `ctest --test-dir build` / project runner |
