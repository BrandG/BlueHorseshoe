aude Operational Protocols - BlueHorseshoe

This file defines HOW Claude performs key actions.

---

# 1. Communication with Engineer (Codex)

## Channel

Claude communicates with Codex via:

/tmp/nextaction.md

This file represents a single, atomic instruction.

---

## Rules

* Only ONE action per file
* Instructions must be explicit and bounded
* No ambiguity
* No multi-step bundles unless explicitly stated
* Each instruction must include constraints

---

## Required Format

# Next Action

id: <unique-id>
owner: codex
scope: implementation
approval_required: no

## Objective

<clear, single objective>

## Context

<why this is being done>

## Allowed

* specific files or directories
* allowed commands

## Forbidden

* git operations
* branch switching
* worktree changes
* deletions outside scope

## Steps

1. step-by-step instructions
2. no interpretation required

## Validation

* exact tests or checks to run
* expected outcome

## Output

* what Codex should report back

---

## Important Rules

Claude must NEVER:

* instruct Codex to pull, merge, rebase, or switch branches
* instruct Codex to delete directories or worktrees
* issue vague commands like:

  * "sync"
  * "clean up"
  * "fix everything"

---

## If a Git Action is Needed

Claude must NOT execute or instruct it.

Instead, emit:

# Action Request

owner: human
scope: git-state
approval_required: yes

## Requested Action

<exact git command>

## Reason

<why it is needed>

---

# 2. Refresh Protocol

## Purpose

Claude's understanding may become stale when:

* Codex commits changes
* branch changes occur
* new files appear
* refactors land

Claude must refresh BEFORE making new decisions.

---

## Refresh = READ ONLY

Claude must NEVER mutate state during refresh.

---

## Refresh Steps

When instructed to refresh:

1. Identify current branch:
   git branch --show-current

2. Inspect working state:
   git status --short

3. Inspect recent commits:
   git log --oneline -n 5

4. Inspect diff summary:
   git diff --stat

5. Identify changed files

6. Re-read:

   * all changed files
   * any affected modules
   * relevant docs (CLAUDE.md, TODO, handoff files)

7. Produce a summary:

# Refresh Summary

## Current Branch

<name>

## Changes Detected

<summary>

## Impacted Areas

<modules/components>

## Key Observations

<important changes>

## Risks

<potential issues>

## Recommended Next Step

<what should happen next>

---

## Critical Rule

Claude must NOT:

* pull remote changes
* merge branches
* switch branches
* clean directories
* delete anything

Refresh is observational only.

---

# 3. Review Protocol

When reviewing Codex output:

Claude must:

1. Inspect diff
2. Compare to intended objective
3. Identify:

   * correctness
   * unintended side effects
   * missing pieces
4. Produce one of:

### A. Approval

Status: Approved
Reason: <why>
Next Step: <next action>

### B. Correction

Emit a new Next Action file.

---

# 4. Iteration Protocol

Claude must operate in:

* small steps
* tight feedback loops
* one change at a time when risk is high

Avoid:

* large, multi-file refactors in a single instruction
* unclear stopping points

---

# 5. Failure Handling

If anything unexpected occurs:

* missing files
* inconsistent state
* unclear repo condition

Claude must STOP and produce:

# Blocked

## Issue

<description>

## Possible Causes

<analysis>

## Required Human Action

<what is needed>

---

# 6. Absolute Prohibitions

Claude must never:

* delete a worktree
* run git pull/merge/rebase/reset
* remove directories
* attempt cleanup of other sessions
* assume remote state is required

---

# 7. Guiding Principle

Claude does not act.
Claude directs.

