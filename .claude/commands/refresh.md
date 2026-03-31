You are refreshing your understanding of the current BlueHorseshoe worktree.

Follow the Refresh Protocol exactly as defined in `CLAUDE_PROTOCOLS.md`.

This is a READ-ONLY operation.

Do not:
- modify any source files
- modify any markdown files
- run any git mutation commands
- pull, fetch, merge, rebase, checkout, switch, reset, or clean
- delete, move, or rename any files or directories
- create or remove worktrees

Your job is to reconcile your understanding with the current local repo state only.

Perform these steps in order:

1. Read `CLAUDE_ROLE.md`
2. Read `CLAUDE_PROTOCOLS.md`
3. Read `SESSION_HANDOFF.md`
4. Read `TODO.md`

Then inspect the current repository state using read-only commands only:

5. Determine the current branch
6. Inspect current working tree status
7. Inspect the most recent commits
8. Inspect a diff summary
9. Identify changed files
10. Re-read all changed files
11. Re-read any obviously impacted related modules
12. Re-read any relevant handoff or todo notes affected by those changes

After that, produce a response in exactly this format:

# Refresh Summary

## Current Branch
<branch name>

## Working Tree Status
<clean / dirty / summary>

## Recent Commits
- <commit summary>
- <commit summary>
- <commit summary>

## Changes Detected
<summary of changed files and recent code changes>

## Impacted Areas
- <module or subsystem>
- <module or subsystem>

## Key Observations
- <important observation>
- <important observation>

## Risks
- <risk or "None currently identified">

## Recommended Next Step
<single best next step>

If repo state is unclear, inconsistent, or missing expected files, stop and output:

# Blocked

## Issue
<what is wrong>

## Possible Causes
<likely explanation>

## Required Human Action
<what I need the human to do>

