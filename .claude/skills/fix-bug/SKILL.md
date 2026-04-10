---
name: fix-bug
description: Investigate and fix a bug from the backlog — load details, diagnose root cause, implement fix after approval, run CI, and update item status.
---

# Fix Bug Skill

You are investigating and fixing a bug. The user invoked `/fix-bug $ARGUMENTS`.

## Prerequisites

**Read `.claude/sprint-config.yaml`** to get project-specific commands. All commands below use config references like `{backlog_commands.show}`, `{ci_command}`, etc. — substitute with actual values from the config.

`$ARGUMENTS` should contain a bug item ID. If not provided, list open bugs and ask the user to select one:

```bash
{backlog_commands.list_bugs}
```

## Step 1: Load Bug Details

Fetch the full bug item:

```bash
{backlog_commands.show} <item-id>
```

Extract and present:
- Title and description
- Steps to reproduce
- Expected vs actual behavior
- Priority/severity
- Any related files noted during report

## Step 2: Investigate Root Cause

Invoke systematic debugging (use the `superpowers:systematic-debugging` skill approach):

1. **Reproduce** — verify the bug exists by examining the code path described in steps to reproduce
2. **Hypothesize** — form 2-3 hypotheses about the root cause
3. **Narrow** — explore code to confirm or eliminate each hypothesis
4. **Identify** — pinpoint the exact root cause with file and line reference

Present findings to the user:
- **Root cause** — what is broken and why
- **Affected files** — which files need changes
- **Blast radius** — what else could be affected by a fix
- **Proposed fix** — high-level approach

## Step 3: Wait for Approval

**Do not implement until the user approves the proposed fix.**

Ask: "Shall I proceed with this fix?"

## Step 4: Implement Fix

After approval:

1. Implement the fix in the identified files
2. Add or update tests to cover the bug scenario
3. Run CI to verify:

```bash
{ci_command}
```

4. If CI fails, diagnose and fix before proceeding

## Step 5: Commit and Update Status

Commit with a reference to the bug item:

```bash
git add <changed-files>
git commit -m "fix: <short description>

Fixes backlog item <item-id>"
```

Move the item to review phase:

```bash
{backlog_commands.edit} <item-id> --phase review
```

## Step 6: Summary

Present:
- What was fixed and why
- Files changed
- Tests added/updated
- CI status
- Item status update

## Important Rules

- Always present analysis before implementing — never fix without user approval
- Always run `{ci_command}` after implementing
- Always reference the bug item ID in the commit message
- Use `{backlog_commands.*}` for all backlog operations
- Move item to review phase, not done — the user verifies done
