# Node.js backend (Express / Fastify / NestJS / API routes) compression idioms

## Idioms, roughly in order of typical impact

- **Middleware consolidation** for cross-cutting concerns (auth checks,
  request logging, error formatting, CORS headers) currently copy-pasted at
  the top of many route handlers — almost always the biggest single win in a
  hand-rolled Express/Fastify codebase.
- **Centralized error-handling middleware** instead of repeated
  `try { ... } catch (err) { res.status(...).json(...) }` blocks scattered
  across every route handler.
- **Schema validation (Zod/Joi/class-validator)** at the route boundary
  instead of manual field-by-field validation duplicated per endpoint — same
  principle as the frontend Zod guidance in `typescript-js.md`, and often the
  same schemas can be shared between frontend and backend if the project is a
  monorepo.
- **A single generic repository/query-builder layer** instead of near-
  identical hand-written database query functions per entity (one
  `findById(table, id)` instead of `findUserById`, `findPostById`,
  `findCommentById` that are 90% identical) — verify each entity's function
  didn't have entity-specific side effects (soft-delete filtering, tenant
  scoping) buried inside before consolidating; those must move into the
  shared layer's parameters, not get silently dropped.
- **Route/controller consolidation** for CRUD endpoints that follow the same
  shape per resource — a generic CRUD router factory instead of five
  near-identical route files, common in NestJS/Express codebases that grew by
  copy-pasting one resource's routes to create the next.
- **Config/env loading consolidated to one module** instead of `process.env.X`
  scattered and re-parsed/re-validated across many files.

## Careful with (these are Tier 2/3, not Tier 1 — see risk-classification.md)

- **Async ordering and transaction boundaries.** Consolidating sequential
  database calls into `Promise.all` changes both ordering guarantees and, in
  many ORMs, transaction/connection-pool behavior — verify with a
  characterization test covering the failure path (one query rejecting)
  before treating this as safe, same as the general JS/TS guidance.
- **Middleware ordering.** Express/Fastify middleware runs in registration
  order; consolidating or reordering middleware can change which handler sees
  a modified request first (e.g. auth must run before a handler that reads
  `req.user`). Treat any middleware reordering as Tier 3.
- **Error status codes and response shapes.** When consolidating error
  handling, confirm the unified handler still returns the exact same status
  code and JSON shape each route previously returned for each error type —
  API consumers may depend on the current (even if inconsistent) shape.

## Tooling recap

| Task | Command |
|------|---------|
| Duplication | `npx jscpd <path>` or `python3 scripts/find_duplicates.py <path>` |
| Unused exports/routes | `npx knip` or `npx ts-prune -p tsconfig.json` |
| Unused dependencies | `npx depcheck` |
| API contract regression | If OpenAPI/Swagger spec exists, diff generated spec before/after; otherwise a recorded request/response characterization suite (see verification.md) covering every route + its error paths is the minimum bar |
