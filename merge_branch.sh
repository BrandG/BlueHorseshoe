#!/usr/bin/env bash
# Merge a topic branch into master via a --no-ff merge commit, then delete
# the local branch. Optional --push to also push master to origin.
#
# Usage:
#   ./merge_branch.sh <branch-name>           # merge + delete local branch
#   ./merge_branch.sh <branch-name> --push    # merge + delete + push to origin
#
# Refuses to proceed if:
#   - the target branch does not exist locally
#   - you are currently ON the target branch
#   - master has uncommitted changes
#   - the merge produces conflicts (branch is preserved for manual resolution)

set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "Usage: $0 <branch-name> [--push]"
    exit 1
fi

BRANCH="$1"
PUSH="${2:-}"

if [[ -n "$PUSH" && "$PUSH" != "--push" ]]; then
    echo "Error: second argument must be '--push' if present, got: $PUSH"
    exit 1
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

# Verify the target branch exists locally
if ! git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    echo "Error: branch '$BRANCH' does not exist locally."
    echo "Available local branches:"
    git branch --list
    exit 1
fi

# Refuse to merge onto self
CURRENT_BRANCH="$(git branch --show-current)"
if [[ "$CURRENT_BRANCH" == "$BRANCH" ]]; then
    echo "Error: currently on '$BRANCH'. Switch off it first (e.g. git checkout master)."
    exit 1
fi

# Switch to master
if [[ "$CURRENT_BRANCH" != "master" ]]; then
    echo "==> Switching from $CURRENT_BRANCH to master"
    git checkout master
fi

# Master must have a clean working tree before we merge
if [[ -n "$(git status --porcelain)" ]]; then
    echo "Error: master has uncommitted changes. Stash or commit before merging."
    git status --short
    exit 1
fi

# Show what's about to land
echo "==> Commits on '$BRANCH' that will land on master:"
git log --oneline "master..$BRANCH"
echo

# Merge with --no-ff to force a merge commit (matches project convention)
echo "==> Merging $BRANCH into master with --no-ff"
git merge --no-ff "$BRANCH" -m "Merge branch '$BRANCH'"

# Delete the merged branch (-d is safe; refuses if not merged)
echo "==> Deleting local branch $BRANCH"
git branch -d "$BRANCH"

# Optional push
if [[ "$PUSH" == "--push" ]]; then
    echo "==> Pushing master to origin"
    git push
else
    echo "==> Skipping push. Run with --push, or 'git push' manually when ready."
fi

echo
echo "==> Done. Recent commits:"
git log --oneline -3
