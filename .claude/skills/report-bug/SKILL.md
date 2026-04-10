---
name: report-bug
description: Report a bug with structured details, auto-create a backlog item, tag with current sprint, and explore related code.
---

# Report Bug Skill

You are creating a structured bug report. The user invoked `/report-bug $ARGUMENTS`.

## Prerequisites

**Read `.claude/sprint-config.yaml`** to get project-specific commands and the current sprint number. All commands below use config references like `{backlog_commands.add}`, `{current_sprint}`, etc. — substitute with actual values from the config.

## Step 1: Gather Bug Details

If `$ARGUMENTS` contains a description, use it as the starting point. Otherwise, ask the user for:

- **Title** — short, descriptive summary
- **Severity** — critical (blocks work), high (major feature broken), medium (feature degraded), low (cosmetic/minor)
- **Steps to reproduce** — numbered steps
- **Expected behavior** — what should happen
- **Actual behavior** — what happens instead
- **Environment** — OS, Python version, browser (if relevant)

## Step 2: Map Severity to Priority

| Severity | Priority |
|----------|----------|
| critical | p0 |
| high | p1 |
| medium | p2 |
| low | p3 |

## Step 3: Explore Related Code

Search the codebase for code related to the bug:
- Identify likely source files based on the bug description
- Search for relevant function names, error messages, or UI elements
- Note related test files

Present findings to the user: "I found these potentially related files: ..."

## Step 4: Create Backlog Item

Create the bug item in the backlog:

```bash
{backlog_commands.add} --category bug --priority {mapped_priority}
```

Then edit to add structured details:

```bash
{backlog_commands.edit} <new-item-id> \
  --sprint {current_sprint} \
  --description "Steps to reproduce:\n1. ...\n2. ...\n\nExpected: ...\nActual: ..." \
  --tags "bug,sprint-{current_sprint}"
```

## Step 5: Confirm and Suggest Next Steps

Present a summary:
- Bug title and ID
- Severity/priority
- Sprint assignment
- Related files found

Suggest next steps:
- `/fix-bug <id>` to investigate and fix
- Add to current sprint scope if critical/high severity
- Defer to next sprint if medium/low severity

## Important Rules

- The backlog item is the single source of truth for bug tracking
- Always tag with the current sprint number from `{current_sprint}`
- Always set priority based on severity mapping
- Use `{backlog_commands.*}` for all backlog operations
- Do not create GitHub Issues unless the user explicitly asks for external visibility
