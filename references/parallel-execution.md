# Parallel execution (Tier 1, subagent-capable environments only)

Phase 4 is serial by default. When the plan has many **independent Tier-1**
changes — a 10k-line job across dozens of files, where most batches are
mechanical dedup/dead-code work in unrelated modules — running them concurrently
is a real speedup. This file is how to do that without giving up the thing that
makes shrinkcode trustworthy.

## When this applies — and when it doesn't

**Applies:** Claude Code / Cowork, or any harness that can run several subagents
with their own context in parallel. The container needs that capability; the plan
and the scripts don't change.

**Does not apply:** claude.ai chat sessions and anything else without subagents.
Keep executing serially there — the partition below is still useful as a *reading*
of the plan (it tells you which batches are independent), but don't fake
parallelism by interleaving edits in one context; that's the same as editing a
shared working tree out of order.

**Not worth it:** small jobs. If the plan has three batches, serial execution is
faster than the coordination overhead below. Reach for this when the batch count
is large and the modules are genuinely unrelated.

## The conflict model (what the partitioner can and can't see)

`scripts/partition_batches.py` reads `plan.json` (see
`references/compression-plan-template.md`) and colors a conflict graph with
first-fit greedy coloring. Two Tier-1 changes are treated as **conflicting** when
they:

1. **touch the same file** — two edits to one file can't be verified
   independently, and they collide on the same working tree;
2. **share a duplicate cluster** — the same block (or its copy) appearing in both
   changes' `duplicateCluster`;
3. **have a target block inside the other's cluster** — e.g. two changes each
   deduping one copy of the *same* duplicated pair. Merging one copy into the
   other is only safe in a defined order, so they're never parallel.

Everything the plan doesn't say, the partitioner can't check. Tier 2/3 changes,
and Tier-1 changes that declare no files, are reported under `deferred` and run
serially. A Tier-1 change with no `duplicateCluster` gets a warning: same-file
conflicts are still caught, but "two fixes to blocks that are copies of each
other" cannot be detected for it. **Independence is only ever as good as the
plan's data.** If you're about to parallelize aggressively, spend the extra
minute filling in `files`, `target` and `duplicateCluster` from
`find_duplicates.py --json` — that's the whole safety margin.

```bash
python3 scripts/partition_batches.py plan.json          # human-readable groups
python3 scripts/partition_batches.py plan.json --json   # for an orchestrator
```

Exit code 2 means the plan couldn't be read confidently (missing file, invalid
`tier`, duplicate ids) — fix the plan rather than shipping an empty partition.

Verified behavior on a fixture repo of three independent modules, each with one
Tier-1 duplicate-merge: all three land in **one** group; adding a fourth change
that touches a file the first group already claimed produces a **second** group
with the reason recorded (`same file: mod_a.py`), never a same-file pair inside
one "parallel" group.

## The workflow

1. **Partition.** `plan.json` → groups (above). Read the groups out loud to the
   user before spawning anything: this is the last cheap moment to notice a bad
   plan.
2. **Spawn one subagent per group.** Each subagent gets: its group's change ids
   and files, the plan entries for those changes, the Phase 4 rules (tier order,
   one batch per logical change) and the Phase 5 bar for Tier 1 (full test suite
   once per batch). Tell it explicitly **not** to touch files outside its group
   — a subagent that "helpfully" fixes a neighbouring duplicate destroys the
   independence the partition was based on.
3. **Each group runs Phase 4 (execute) + Phase 5 (verify) on its own files**,
   reporting back: batches, line counts before/after, complexity delta, what it
   ran, results.
4. **Sequence the commits.** Git mechanics matter here: subagents committing
   concurrently to the same `shrinkcode/*` branch race on `.git/index` and
   produce merge conflicts in the cleanup branch itself — exactly the mess the
   batch discipline exists to avoid. So: *verification work happens in
   parallel; commits happen one at a time.* Practically, either the subagents
   hand back their diffs and the orchestrator commits them in group order
   (`checkpoint.sh save "<category>: … [verified: …]"`), or each subagent
   commits only when it's told its turn has come. Either way one `checkpoint.sh`
   commit per batch, still bisectable, still revertable individually.
5. **Run the final full-suite serial re-verification.** See below. It is not
   optional.

## The final serial re-verification is mandatory

After every group has landed (committed) and passed its own verification, run
**one full-suite verification across the whole codebase, serially, against the
combined result**. Until that passes, the job is not done.

This is the safety net that makes parallelizing the rest acceptable, and it is
mandatory — never "if you have time", never skipped because every group reported
green. File-level conflict detection cannot see the ways independent-looking
changes still interact:

- shared test fixtures, factories and seed data (two groups "fixing" the same
  fixture in different files);
- global/module-level state and singletons, import side effects, monkeypatching;
- test ordering and parallelism — each group's suite passing alone says nothing
  about the combined suite's ordering assumptions;
- configuration, generated files, lockfiles, schema/migration ordering.

If the final serial pass fails: don't patch forward. `bash scripts/checkpoint.sh
revert <sha>` the most recently committed group, re-run, and repeat in reverse
commit order until green — that keeps the failure attributable to one batch
instead of a merged blur. Then fix that group serially and re-run the full pass
before anything else.

## What is never parallelized

- Tier 2 and Tier 3 changes — one at a time, in the normal serial order, with the
  sign-off Phase 3 required. The partitioner defers them automatically.
- Two changes touching the same file, however unrelated they look.
- Two changes to blocks that are duplicates of each other.
- Anything touching shared fixtures, global state or shared config — the
  conflict check can't see it, so keep it in one serial batch by hand.
- Changes with no declared files. If the plan can't say what a change touches,
  it runs alone.

## Is it actually faster?

Only sometimes, and it's worth being honest with the user about which. The
parallel groups get their *edit + verify* cycles overlapped; the final serial
re-verification, the commit sequencing and the plan review are all still serial
and grow with the number of groups. For a deeply independent Tier-1 backlog the
win is real; for a plan of five batches in two modules, it's overhead. Say which
one you're looking at instead of selling parallelism by default.
