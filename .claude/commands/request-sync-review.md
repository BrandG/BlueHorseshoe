You are evaluating whether repository synchronization or git state changes are required.

Follow the Claude Operational Policy strictly.

This is a READ-ONLY analysis.

Do NOT:

* execute any git commands that modify state
* pull, fetch, merge, rebase, checkout, switch, or reset
* modify any files
* delete or move anything

---

## Task

Determine whether the current worktree is in a state that requires human intervention for synchronization or git operations.

---

## Steps

1. Identify current branch
2. Inspect working tree status
3. Inspect recent commits
4. Inspect diff summary
5. Determine whether:

   * the branch appears behind or out-of-sync
   * there are uncommitted changes that may block progress
   * the current worktree state is inconsistent with expectations
   * a merge or rebase may be required soon

---

## Output Format

# Sync Review

## Current Branch

<branch name>

## Working Tree Status

<clean / dirty / summary>

## Observations

* <observation>
* <observation>

## Sync Needed

Yes / No

## Recommended Action

If NO: <short explanation>

If YES:
Describe the required action clearly.

---

## If Sync is Required

You MUST NOT perform the action.

Instead, emit:

# Action Request

owner: human
scope: git-state
approval_required: yes

## Requested Action

<exact command or sequence>

## Reason

<why this is necessary>

## Risk Level

low / medium / high

---

## Critical Rule

You are diagnosing git state.

You are NOT allowed to fix it.


