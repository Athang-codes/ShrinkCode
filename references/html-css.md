# HTML / CSS compression idioms

## Idioms, roughly in order of typical impact

- **CSS variables (custom properties)** instead of the same color/spacing/font
  value repeated across dozens of rules.
- **Shared utility classes** instead of near-identical style blocks repeated
  per element (`.card-a { padding: 16px; border-radius: 8px; ... }`,
  `.card-b { padding: 16px; border-radius: 8px; ... }` → one `.card` class +
  a modifier).
- **CSS Grid/Flexbox** instead of verbose manual positioning (floats +
  clearfixes, manual width percentage math for columns).
- **`:is()`/`:where()` and combined selectors** instead of repeating the same
  declaration block for a long list of near-identical selectors. Note
  `:where()` has zero specificity, which can be exactly the tool you need
  when consolidating without changing cascade weight.
- **`<template>` / component partials** (or framework equivalents — Next.js
  layouts, Vue/Svelte components, server-side includes) instead of the same
  markup block copy-pasted across multiple pages.
- **Shorthand properties** (`margin`, `padding`, `background`, `font`) instead
  of four separate longhand declarations, where it doesn't reduce clarity
  about which sub-value is intentional.
- **PurgeCSS/Tailwind's built-in purge** to remove unused utility classes from
  a build's shipped CSS — this is bundle-size reduction more than
  source-line reduction, but worth reporting alongside code compression if
  the user cares about total footprint, not just source LOC.

## Careful with (these are Tier 2/3, not Tier 1)

- **Selector consolidation can change specificity and cascade order.**
  Merging `.a { color: red }` and `.b { color: red }` into `.a, .b { color: red }`
  is safe, but reordering rules or changing selector specificity while
  merging can silently flip which rule wins when both apply to the same
  element. Verify computed styles (via devtools or a visual diff), not just
  that the source "looks equivalent" (see verification.md).
- **Responsive behavior (media queries, container queries)** is part of
  "behavior" here — check the same breakpoints before and after, not just
  the default viewport.
- **`!important` removal.** If you spot `!important` while consolidating and
  it looks unnecessary, it might be overriding a third-party stylesheet or a
  specificity war you can't see from this file alone — don't remove it as
  part of a "cleanup," flag it separately.

## Tooling recap

| Task | Command |
|------|---------|
| LOC / duplication | `python3 scripts/loc_report.py <path>` / `find_duplicates.py <path> --ext .css,.scss,.html` |
| Unused CSS | `npx purgecss --css styles.css --content index.html` (report-only mode first — don't apply blind) |
| Visual regression | Manual before/after screenshots across breakpoints as a minimum; Percy/Chromatic/Playwright screenshot diffing if the project already has them |
