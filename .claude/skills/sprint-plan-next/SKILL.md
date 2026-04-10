---
name: sprint-plan-next
description: Pre-plan next sprint scope while the current sprint runs — review untagged backlog items, tag candidates, and balance capacity.
---

# Sprint Plan Next Skill

You are pre-planning the next sprint. The user invoked `/sprint-plan-next $ARGUMENTS`.

## Prerequisites

**Read `.claude/sprint-config.yaml`** to get project-specific commands and the current sprint number (`{current_sprint}`). The next sprint is `{current_sprint} + 1`. All commands below use config references — substitute with actual values from the config.

## Step 1: Current Sprint Status

Show what is in the current sprint to understand remaining capacity and momentum:

```bash
{backlog_commands.list_doing}
```

Note how many items are in progress vs near completion.

## Step 2: Show Untagged Backlog Items

List all backlog items not assigned to any sprint:

```bash
{backlog_commands.list_backlog}
```

Filter for items without a sprint_target (or with sprint_target set to "future"/"none").

## Step 3: Review Open Bugs

Check for bugs that should be prioritized:

```bash
{backlog_commands.list_bugs}
```

Bugs with high/critical priority should be recommended for next sprint.

## Step 4: Categorize Candidates

Group backlog items by category:
- **Features** — new functionality
- **Bugs** — defects to fix
- **Tech debt / Chores** — refactoring, cleanup, infrastructure
- **Docs** — documentation improvements

Present each group with item ID, title, priority, and complexity (if set).

## Step 5: Capacity Check

Reference sprint capacity from config (`{default_sprint_capacity}`):
- Small items: 3-4 per sprint
- Medium items: 2-3 per sprint
- Large items: 1-2 per sprint

Ask the user:
- How many items for next sprint?
- Any themes or focus areas?
- Balance preference (more features vs more debt payoff)?

## Step 6: Tag Selected Items

For each item the user selects, tag it with the next sprint number:

```bash
{backlog_commands.edit} <item-id> --sprint {N+1}
```

Do NOT move items to "doing" — they stay in backlog until the sprint officially starts via `/sprint-start`.

## Step 7: Summary

Present:
- **Next sprint number** — N+1
- **Selected items** — list with IDs, titles, categories
- **Capacity estimate** — total complexity vs capacity
- **Balance** — % features / bugs / debt / docs
- **Deferred items** — notable items left for later with rationale

Remind the user: these are candidates, not commitments. Final scope is set during `/sprint-start`.

## Important Rules

- Do NOT move items to "doing" — only tag with sprint_target
- Do NOT create a sprint branch — that happens in `/sprint-start`
- Items stay in backlog status until the sprint officially begins
- Use `{backlog_commands.*}` for all backlog operations
- Reference `{default_sprint_capacity}` for capacity guidelines
