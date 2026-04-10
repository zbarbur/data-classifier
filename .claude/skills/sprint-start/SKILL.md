---
name: sprint-start
description: Initialize a new sprint. Uses agile-backlog CLI to select scope, write task specs to YAML items, tag with sprint number, and create sprint branch.
---

# Sprint Start Skill

You are initializing a new sprint. The user invoked `/sprint-start $ARGUMENTS`.

## Prerequisites

**Read `.claude/sprint-config.yaml`** to get project-specific commands. All commands below use config references like `{ci_command}`, `{backlog_commands.list}`, etc. — substitute with actual values from the config.

If an argument is provided, use it as the sprint number. Otherwise, determine the next sprint number from the latest handover in `{docs.handover_dir}` or from MEMORY.md.

## Step 1: Check Flagged Comments

Run the flagged comments check before any planning work:

```bash
{backlog_commands.flagged}
```

- [ ] Reviewed all flagged comments

If flagged comments exist, present them to the user for review. The user must acknowledge each flagged comment (resolve, defer, or convert to backlog item) before proceeding to sprint planning.

If no flagged comments, note "No flagged comments — proceeding to sprint planning."

## Step 2: Review Previous Sprint Handover

Check for the latest handover doc in `{docs.handover_dir}`:

```bash
ls -1t {docs.handover_dir}SPRINT*_HANDOVER.md | head -1
```

If a handover exists, read it and summarize:
- Key decisions and lessons learned from the previous sprint
- Recommendations for this sprint
- Any known issues carried forward

This context helps inform sprint scoping decisions.

## Step 3: Verify Clean Slate

```bash
git branch --show-current    # should be: main
git status                   # should be: clean working tree
```

- [ ] On `main` branch
- [ ] Working tree clean
- [ ] Previous sprint items are done (`{backlog_commands.list_doing}` should be empty)
- [ ] CI passing on main (`gh run list --limit 1` should show success)

Run `{ci_command}` and report pass/fail. Also check GitHub CI:

```bash
gh run list --limit 1
```

If CI is failing, diagnose and fix before proceeding.

## Step 4: Bug Triage

Check for open bugs:

```bash
{backlog_commands.list_bugs}
```

If bugs exist, ask which to include in sprint scope.

## Step 5: Select Sprint Scope

Show the backlog:

```bash
{backlog_commands.list_backlog}
```

Also offer the board for visual selection: `agile-backlog serve`

Ask the user:
- Which items to pull into this sprint?
- What is the sprint theme?

The user may also move items to "doing" via the board UI directly.

## Step 6: Write Task Specs to YAML

For each selected item, use `{backlog_commands.edit}` to populate the task definition:

```bash
{backlog_commands.edit} <item-id> \
  --sprint N \
  --goal "One sentence — what this delivers" \
  --complexity M \
  --acceptance-criteria "Verifiable criterion 1" \
  --acceptance-criteria "Verifiable criterion 2" \
  --acceptance-criteria "Tests pass ({test_command})" \
  --acceptance-criteria "Lint clean ({lint_command})" \
  --technical-specs "File: src/path.py — what to change" \
  --technical-specs "File: tests/test_path.py — what to test" \
  --test-plan "tests/test_x.py: test description" \
  --phase plan
```

Present each task spec to the user for review. Adjust as needed.

After speccing all items, update their phase to `spec`:
```bash
{backlog_commands.edit} <item-id> --phase spec
```

**Move items to doing with phase:**

```bash
{backlog_commands.move} <item-id> --status doing --phase plan
```

## Step 7: Validate Completeness

For each sprint item, verify via `{backlog_commands.show} <item-id>`:
- Has goal
- Has complexity (S/M/L)
- Has at least 2 acceptance criteria
- Has at least 2 technical specs
- Has test plan
- Has sprint_target set to current sprint
- Phase is set

Report any gaps and suggest fixes.

## Step 8: Create Sprint Branch

```bash
git add backlog/
git commit -m "chore: start Sprint N — <theme>"
git checkout -b {branch_pattern}  # replace {N} with sprint number
git push -u origin {branch_pattern}
```

**Update sprint config:**

Update `current_sprint` in `.claude/sprint-config.yaml` to the new sprint number.

Move items to `build` phase as implementation begins:
```bash
{backlog_commands.edit} <item-id> --phase build
```

## Step 9: Confirm Ready

Present a summary:
- Sprint number and theme
- Number of tasks with complexity breakdown
- Sprint branch name
- CI status

## Important Rules

- YAML items are the single source of truth — do NOT write to TODO.md
- Use `{backlog_commands.edit}` to populate task specs, not manual file editing
- Always set sprint_target and phase when moving items to doing
- Always tag items with the sprint number
- DoD items must be independently verifiable
