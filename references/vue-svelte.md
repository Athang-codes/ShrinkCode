# Vue / Svelte compression idioms

## Vue

- **Composables** (`use*` functions, Vue's equivalent of React hooks) to
  extract repeated stateful/reactive logic copy-pasted across multiple
  components — usually the single biggest win in a Vue codebase, same as
  custom hooks in React.
- **`<script setup>` syntax** instead of the verbose Options API
  (`data()`/`methods`/`computed` boilerplate) — a mechanical, low-risk
  conversion when the component doesn't rely on Options-API-specific behavior
  like `this` binding tricks; verify no code depends on `this` referencing the
  component instance in a way `<script setup>` changes.
- **Consolidate near-identical components with props/slots** the same way as
  the React guidance in `react-nextjs.md` — the pattern is language-agnostic,
  only the syntax differs.
- **Global state (Pinia/Vuex) consolidation** instead of the same prop-drilled
  state copied through multiple component layers.
- **Scoped `<style>` + CSS variables** instead of repeated inline `:style`
  bindings or duplicated scoped style blocks across components.

**Careful with:** `watch` vs `watchEffect` dependency tracking changes when
refactoring — same class of bug as a React `useEffect` dependency array
mistake (Tier 2/3, verify per risk-classification.md).

## Svelte

- **Consolidate near-identical components with props** — same principle as
  React/Vue.
- **Stores (`writable`/`derived`)** instead of the same reactive state pattern
  duplicated across components via props/events.
- **`$:` reactive statements** to replace verbose manual recomputation logic
  triggered from multiple event handlers — but verify the reactive statement's
  dependency tracking actually fires on the same triggers as the original
  manual calls; Svelte's dependency inference is stricter than it looks.
- **Slots** instead of near-duplicate wrapper components that only differ in
  their inner content.

**Careful with:** reactive statement (`$:`) dependency inference is
implicit — Svelte determines dependencies by static analysis of the
statement's referenced variables. Restructuring a `$:` block (e.g. extracting
part of it into a function call) can silently break dependency tracking if
the extracted function's own reads aren't visible to Svelte's compiler
analysis. Treat any `$:` restructuring as Tier 2 minimum.

## Tooling recap

| Task | Command |
|------|---------|
| Duplication | `npx jscpd <path>` (works fine on `.vue`/`.svelte` files) or `python3 scripts/find_duplicates.py <path> --ext .vue,.svelte` |
| Unused components/exports | `npx knip` (has Vue/Svelte plugin support — check current docs for the plugin package name) |
| Tests | `npx vitest run` (standard for both ecosystems); Vue Test Utils / `@testing-library/svelte` for component-level checks |
