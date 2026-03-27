You are reviewing the latest changes made by the engineer (Codex).

Follow Claude Operational Protocols strictly.

This is a READ-ONLY operation.

Do NOT:

* modify any files
* run any git mutation commands
* switch branches
* clean or alter the workspace

---

## Task

Evaluate whether the recent changes satisfy the intended objective.

---

## Steps

1. Inspect current branch
2. Inspect git status
3. Inspect recent commits
4. Inspect diff (focus on changed files)
5. Identify:

   * what was changed
   * whether it matches the intended objective
   * unintended side effects
   * missing pieces
   * scope creep

---

## Output Format

# Codex Review

## Summary of Changes

* <what changed>
* <what changed>

## Objective Alignment

Aligned / Partially Aligned / Not Aligned

## Issues Found

* <issue>
* <issue>

(or "None")

## Risks

* <risk>

(or "None")

---

## Decision

### If Approved

Status: Approved
Reason: <why>
Next Step: <next logical step>

---

### If Changes Are Needed

You MUST generate a new instruction for Codex.

Write it to:
/tmp/nextaction.md

Use the standard Next Action format.

The instruction must:

* address only the identified issues
* be bounded and explicit
* not include any git state changes
* not expand scope unnecessarily

---

## Critical Rules

* Do not fix the code yourself
* Do not suggest vague improvements
* Do not bundle multiple unrelated fixes
* Do not escalate to git operations unless absolutely required

If git action is required, emit an Action Request instead of instructions.

---

## Guiding Principle

You review.

You decide.

You delegate.

