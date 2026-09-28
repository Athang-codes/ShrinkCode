# Git workflow: checkpoint every batch

A compression job that isn't checkpointed in git is a job you can't safely
recover from if something breaks three batches in. `scripts/checkpoint.sh`
enforces this; use it (or the equivalent manual git commands if the user's
environment doesn't support running the script) for anything beyond a
single, trivial, one-file change.

## Setup

```bash
# Requires the target to already be a git repo with a clean working tree.
# If it isn't a repo yet: git init && git add -A && git commit -m "baseline before shrinkcode"
bash scripts/checkpoint.sh start
```

This creates and checks out a `shrinkcode/<timestamp>` branch. All compression
work happens here — the user's main/default branch is untouched until they
review and merge.

## Committing each batch

After each verified batch (see risk-classification.md for what counts as one
batch — generally: all Tier 1 changes to one file, or one single Tier 2/3
change):

```bash
bash scripts/checkpoint.sh save "dedup: merged validate_user/validate_admin into validate_person(role) [verified: pytest 42/42 pass, characterization tests for both callers pass]"
```

The commit message convention is `<category>: <what changed> [verified: <how>]`
— categories match SKILL.md's technique list (dedup / dead-code / boilerplate /
merge / abstraction). This makes `git log` on the branch a readable audit trail
of the entire job, and makes `git bisect` trivial if a regression surfaces
later that the characterization tests didn't catch.

## batches.json: one manifest entry per checkpoint

Every checkpoint commit also gets one entry in `batches.json` (repo root, kept
on the `shrinkcode/<timestamp>` branch) — the manifest Phase 6's
`scripts/generate_report.py` reads to build the batch table in the HTML
report:

```json
[
  {
    "sha": "9f2c1ab",
    "category": "dedup",
    "tier": 1,
    "summary": "merged validate_user/validate_admin into validate_person(role)",
    "verification": "pytest 42/42 pass, characterization tests for both callers pass"
  }
]
```

Each entry's fields are copied from the commit message you just saved — the
message is the source of truth, not a second story you invent for the
manifest:

- `category` — the `<category>` prefix of `<category>: <what changed> [verified: <how>]`
- `summary` — the `<what changed>` middle part
- `verification` — the `<how>` inside `[verified: …]`
- `sha` — the commit `checkpoint.sh save` just created
- `tier` — the change's risk tier: 1 Mechanical / 2 Structural / 3 Semantic
  (see risk-classification.md)

Same-derived-fields rule means `git log` and the report can't drift into two
conflicting accounts of the job: if a detail is worth putting in
`batches.json`, it belongs in the commit message first (and vice versa —
nothing in the manifest may claim verification the message doesn't record).

## Why batches, not one giant commit

- If verification fails after batch 7 of 12, you revert or fix batch 7
  specifically — you don't have to re-review an undifferentiated diff of the
  whole job to find what broke.
- The user reviewing your PR/diff at the end can review batch-by-batch
  (`git log -p` per commit) instead of one wall of changes, which is both
  more reviewable and more trustworthy — they can see exactly which specific
  change corresponds to which specific verification claim.
- `scripts/checkpoint.sh revert <sha>` reverts exactly one batch, leaving
  every other (already-verified) batch intact.

**Parallel groups:** if you're running Tier-1 batches concurrently in a
subagent-capable environment (`references/parallel-execution.md`), the *commits*
still get sequenced — one `checkpoint.sh save` at a time, in group order.
Concurrent commits to the same branch race on `.git/index` and conflict inside
the shrinkcode branch itself; the parallel part is the edit/verify work, not the
git history. The final full-suite serial re-verification is mandatory there too.

## At the end of the job

Don't merge or push automatically. Report the branch name and batch list
(`bash scripts/checkpoint.sh list`) to the user and let them review/merge on
their own terms — this is their codebase and their call on when it's ready to
land on the main branch.

## If the environment has no git available

Fall back to manual checkpoints: copy the target directory to a timestamped
backup before starting (`cp -r project project.before-shrinkcode`), and after
each batch, note in your final report exactly what changed in that batch so
the user has something to compare against even without commit history. This
is strictly worse than git (no diffing, no partial revert) — say so plainly
rather than silently treating it as equivalent.
