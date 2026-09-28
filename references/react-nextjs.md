# React / Next.js compression idioms

## Idioms, roughly in order of typical impact

- **Consolidate near-identical components** into one component with props
  (`<UserCard variant="compact" />` instead of `<UserCardCompact />` +
  `<UserCardFull />` as separate files with 80% duplicated JSX).
- **Custom hooks** to extract repeated stateful logic (the same
  `useState`+`useEffect`+fetch pattern copy-pasted across 6 components → one
  `useFetchX` hook).
- **Compound/render-prop patterns collapsed** when they were built for a
  single concrete use case — over-engineered generic components used exactly
  once are bloat; inline them or simplify to what's actually needed (Tier 2 —
  flag this as a judgment call rather than silently deciding, per
  risk-classification.md).
- **Next.js file-based routing/layouts** instead of hand-rolled routing logic
  or repeated per-page boilerplate (shared `<Layout>` via `layout.tsx` instead
  of copy-pasted wrapper markup in every page).
- **Server Components (App Router) for data-fetching-only components**
  instead of a Client Component with a `useEffect` fetch — removes the
  loading-state boilerplate entirely where interactivity isn't actually
  needed. Only apply this where the component genuinely has no client-only
  behavior (event handlers, browser APIs, hooks like `useState`) — converting
  an interactive component to a Server Component is a behavior change, not
  compression.
- **Tailwind/utility classes or CSS variables** instead of repeated inline
  style objects or near-duplicate CSS-in-JS blocks per component.
- **Colocate small, tightly-coupled components** instead of
  one-file-per-9-line-component sprawl that costs more in import boilerplate
  than it saves in organization — but don't merge components with genuinely
  independent reuse elsewhere in the app.
- **`React.memo`/context consolidation** to replace prop-drilling boilerplate
  that copies the same 5 props through 4 layers of components — but confirm
  re-render behavior doesn't change in a way that affects visible output
  (Tier 2/3 depending on complexity — see verification.md's React notes).

## Hard correctness rules — never violate these while "simplifying"

- **Hook call order must stay identical.** Never move a hook behind a
  conditional or a loop when merging/refactoring components. This is a
  correctness bug (React relies on call order), not a style choice, and it's
  an easy mistake to introduce when consolidating two similar components into
  one with a branch inside.
- **`useEffect`/`useMemo`/`useCallback` dependency arrays** must be re-verified
  after any logic move — a dependency array bug is often invisible until a
  specific state change stops re-triggering behavior that used to work. This
  is exactly the kind of thing `references/verification.md`'s "interaction
  walkthrough, not just render snapshot" requirement is for.

## Tooling recap

| Task | Command |
|------|---------|
| Duplication | `npx jscpd <path>` or `python3 scripts/find_duplicates.py <path>` |
| Unused components/exports | `npx knip` (catches unused files across a whole Next.js/React app well) |
| Visual/interaction regression | Playwright/Cypress if present; React Testing Library for logic-level checks; manual before/after screenshots as a minimum bar (say so explicitly if that's all you did) |
