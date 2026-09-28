# Compression plan template

For any job beyond a single small file, produce this plan and share it with the
user before executing Phase 4 (Execute) — it's the equivalent of a PR
description written before the PR exists. Skipping this for a "just vibe with
me" small job is fine if the user says so explicitly; for anything the user
called "10k lines" or handed you a whole repo/directory for, write the plan.

```markdown
# Shrinkcode plan: <project/directory name>

## Baseline (Phase 1-2 output)
- Current size: <N> code lines across <M> files (scripts/loc_report.py output)
- Duplication found: <N> exact clusters, <N> near-duplicate pairs
- Complexity: avg <X>, max <Y>, <N> functions over complexity 10
- Dead code candidates: <N> (pre-confirmation — see caveats below)
- Test baseline: <N> existing tests passing / <N> characterization tests added
  for previously-untested paths

## Planned changes

| # | Category | Files | Tier | Est. lines saved | Verification plan |
|---|----------|-------|------|-------------------|--------------------|
| 1 | dedup    | a.py, b.py | 1 | ~40 | re-run test suite |
| 2 | dead-code| c.js       | 1 | ~15 | grep-confirmed zero refs + test suite |
| 3 | abstraction | factory.ts | 2 | ~80 | characterization tests for both call sites + user sign-off (judgment call: this factory only has one implementation, but might be intentional future-proofing) |
| 4 | async-order | api/handler.ts | 3 | ~10 | explicit sign-off required: converts 3 sequential awaits to Promise.all, changes fail-fast semantics — needs a rejection-path characterization test first |

## Estimated outcome
- Projected size: ~<N> code lines (<X>% reduction)
- If `targetReductionPercent` is set in `shrinkcode.config.json` (see
  `config-schema.md`), state here whether the projection meets it: e.g.
  "target 30%, honest safe estimate is 22% — flagging before starting." If
  no config target exists, compare against any target the user stated.
- If this doesn't reach the user's target, say so here explicitly rather than
  finding out at the end — e.g. "target was 5k, honest safe estimate is 6.2k;
  reaching 5k would require Tier 3 changes not currently justified by the
  codebase's actual duplication/bloat — flagging before starting rather than
  quietly falling short."

## Items requiring explicit user confirmation before execution
- Item #3 (judgment call on intent)
- Item #4 (Tier 3 semantic risk)

## Items NOT being touched, and why
- <e.g. "the plugin loader in plugins/ looks like unused abstraction but uses
  dynamic imports by string name — static analysis can't confirm it's dead,
  leaving it alone">
```

## Machine-readable companion: `plan.json`

The markdown above is what you show the user. Alongside it, write a `plan.json`
with the same changes in machine-readable form — `scripts/partition_batches.py`
(parallel Tier-1 execution, `references/parallel-execution.md`) reads it, and it's
what makes "these changes are independent" checkable instead of vibes.

Keep the two in sync: same ids, same tiers, same files. `generate_report.py
--plan` still takes the **markdown** (it renders your "Items NOT being touched"
prose verbatim), so this isn't a replacement — it's the same plan, addressed to a
different reader.

```json
{
  "project": "billing-service",
  "changes": [
    {
      "id": 1,
      "category": "dedup",
      "tier": 1,
      "files": ["src/api/invoices.py"],
      "description": "drop the copied _normalize_amount, call the shared helper",
      "target": "src/api/invoices.py:88",
      "duplicateCluster": ["src/api/invoices.py:88", "src/lib/money.py:41"],
      "estLinesSaved": 26,
      "verification": "pytest tests/test_invoices.py -q"
    },
    {
      "id": 2,
      "category": "dead-code",
      "tier": 1,
      "files": ["src/api/reports.py"],
      "description": "remove build_legacy_report, zero static references",
      "estLinesSaved": 41,
      "verification": "grep-confirmed zero refs + full pytest run"
    }
  ]
}
```

Field notes:

- `id` — matches the `#` column of the markdown table. Unique; the partitioner
  rejects duplicates rather than guessing.
- `tier` — the integer from Phase 3's classification (`1`/`2`/`3`). Required.
  Only Tier 1 is ever considered for parallel groups; Tier 2/3 are reported as
  deferred and run serially.
- `files` — repo-relative paths, one entry per file the change touches. Empty is
  allowed but means "independence unprovable": the change runs serially.
- `target` — the block being changed, as `"path:line"` (or `{"path": …, "line": …}`,
  the shape `find_duplicates.py --json` prints).
- `duplicateCluster` — every block in the cluster the target belongs to, taken
  from `find_duplicates.py --json`. This is the field that catches "two fixes to
  blocks that are copies of each other" across different files; leaving it out
  silently narrows the conflict check, and the partitioner warns when you do.
- `estLinesSaved` / `verification` — optional, carried through to the groups so
  each subagent knows its own budget and bar.

## Notes on using this template

- Keep the table to real numbers from the actual scripts, not guesses — run
  `loc_report.py`, `find_duplicates.py`, and `complexity_report.py` first and
  paste their real output into the baseline section.
- The "Est. lines saved" column is a plan, not a promise — the final report
  (end of SKILL.md's workflow) reconciles plan vs. actual.
- For jobs small enough that this feels like overkill (a single file, a
  handful of obvious duplicate blocks), it's fine to collapse this into a
  short inline summary in the conversation instead of a full document — the
  content matters more than the format ceremony. Use judgment on ceremony
  proportional to job size, same as everything else in this skill.
