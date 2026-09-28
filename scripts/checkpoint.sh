#!/usr/bin/env bash
# checkpoint.sh — thin git wrapper enforcing the shrinkcode batch discipline:
# every batch of changes is committed on a dedicated branch with a message
# that records what category of change it was and what verification passed,
# so any regression is bisectable and any batch is independently revertible.
#
# Usage:
#   ./checkpoint.sh start                 # create/switch to shrinkcode/<date> branch
#   ./checkpoint.sh save "<message>"      # commit staged+unstaged changes as one batch
#   ./checkpoint.sh list                  # show all batches made so far on this branch
#   ./checkpoint.sh revert <commit-sha>   # revert one specific batch, keep the rest
#
# This does not push, force anything, or touch remotes — everything is local
# until the user reviews and pushes themselves.

set -euo pipefail
CMD="${1:-}"

require_git_repo () {
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Not a git repository. Run 'git init' first — shrinkcode requires git" >&2
    echo "so every batch is checkpointed and revertible. This is not optional" >&2
    echo "for anything beyond a trivial single-file job." >&2
    exit 1
  fi
}

case "$CMD" in
  start)
    require_git_repo
    if [ -n "$(git status --porcelain)" ]; then
      echo "Working tree has uncommitted changes. Commit or stash them first," >&2
      echo "so the shrinkcode branch starts from a clean, known-good state." >&2
      exit 1
    fi
    branch="shrinkcode/$(date +%Y%m%d-%H%M%S)"
    git checkout -b "$branch"
    echo "Created and switched to $branch"
    echo "All compression batches will be committed here. Merge/PR when satisfied."
    ;;
  save)
    require_git_repo
    msg="${2:-}"
    if [ -z "$msg" ]; then
      echo "Usage: $0 save \"<category>: <what changed> [verified: <how>]\"" >&2
      echo 'Example: $0 save "dedup: merged validate_user/validate_admin [verified: pytest 42/42 pass]"' >&2
      exit 1
    fi
    git add -A
    if git diff --cached --quiet; then
      echo "No changes to checkpoint."
      exit 0
    fi
    git commit -m "shrinkcode: $msg"
    echo "Batch committed: $(git rev-parse --short HEAD)"
    ;;
  list)
    require_git_repo
    branch=$(git rev-parse --abbrev-ref HEAD)
    echo "Batches on $branch:"
    git log --oneline --grep="^shrinkcode:" || echo "  (no shrinkcode batches committed yet)"
    ;;
  revert)
    require_git_repo
    sha="${2:-}"
    if [ -z "$sha" ]; then
      echo "Usage: $0 revert <commit-sha>" >&2
      exit 1
    fi
    git revert --no-edit "$sha"
    echo "Reverted batch $sha (as a new commit — history preserved for the record)"
    ;;
  *)
    echo "Usage: $0 {start|save \"<message>\"|list|revert <sha>}"
    exit 1
    ;;
esac
