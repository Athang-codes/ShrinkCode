# Go compression idioms

Run `golangci-lint run` before starting — it bundles the unused/duplication
checks that drive most of the automated detection for Go.

## Idioms, roughly in order of typical impact

- **Helper wrapping of repeated error checks, where idiomatic** — the
  `if err != nil { return fmt.Errorf("...: %w", err) }` block repeated 8
  times in a function can often collapse into one wrapped call or a small
  local helper. Judge case-by-case: Go's explicit error handling is
  intentional style, and wrapping *everything* into a `must()` helper that
  panics is a behavior change (panic vs return), not compression.
- **`table-driven tests` consolidation** — near-identical per-case test
  functions (a very common copy-paste pattern) collapse into one table loop;
  `find_duplicates.py --normalize-literals` flags these readily.
- **Struct literals with field names omitted for small positional structs** —
  only for unexported 2-field structs where order is obvious; named fields
  are usually worth their lines. Skip when the struct has >3 fields.
- **`strings.Builder` / `bytes.Buffer`** over `+=` string concatenation in
  loops.
- **`sort.Slice` / `slices` package / `maps` package** (Go 1.21+) over
  hand-rolled sort/find/unique loops — `slices.Contains`, `slices.SortFunc`
  etc. collapse 10-line loops to 1–2.
- **`defer` for cleanup** instead of repeated teardown calls at every early
  return — but see the ordering caveat below.
- **Embedded structs / method promotion** instead of forwarding methods
  (`func (s *Server) Handler() { s.inner.Handler() }` repeated per method) —
  Tier 2: only when the embed relationship is semantically right, not just
  to save lines.

## Careful with (these are Tier 2/3, not Tier 1 — see risk-classification.md)

- **Goroutine/channel timing changes are Tier 3 by definition** — same class
  of risk as the JS `Promise.all` warning in `typescript-js.md`. Collapsing
  sequential goroutine waits, changing `select` ordering, adding/removing a
  buffered channel, or switching `wg.Add/Wait` patterns changes
  race/timing/exit behavior that output-only tests won't catch. Requires a
  concurrency-path characterization test + explicit sign-off.
- **`defer` ordering.** Defers run LIFO; moving cleanup from explicit end-of-
  function calls to `defer` changes order when early returns exist. Tier 2.
- **Error-string edits.** Go tests frequently match `err.Error()` text
  exactly. Never reword an error message while "just compressing" — callers
  and tests may string-match it.

## Tooling recap (see metrics-and-tooling.md for full detail)

| Task | Command |
|------|---------|
| Lint (unused/dup/errors, drives detection) | `golangci-lint run` |
| Complexity | `gocyclo -top 10 <path>` or `npx lizard <path>` |
| Dead code | `deadcode <path>` / `unused` (staticcheck) / `go vet` |
| Duplication | `python3 scripts/find_duplicates.py <path> --normalize-literals` |
| Tests | `go test ./...` |
