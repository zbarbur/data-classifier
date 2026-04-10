---
name: sprint-end
description: Close the current sprint. Reads status from YAML items, writes handover doc, updates PROJECT_CONTEXT.md and MEMORY.md, cleans up branches.
---

# Sprint End Skill

You are closing a sprint. The user invoked `/sprint-end $ARGUMENTS`.

## Prerequisites

**Read `.claude/sprint-config.yaml`** to get project-specific commands. All commands below use config references like `{ci_command}`, `{backlog_commands.list}`, etc. — substitute with actual values from the config.

Determine the current sprint number from `current_sprint` in the config, or from the branch name, or by checking which sprint has doing items:

```bash
{backlog_commands.list_doing}
```

## Phase 1: Verify & Ship

1. Run `{ci_command}` — report results
2. Check git status — warn about uncommitted changes

## Phase 2: Update Tracking

### Check Item Status

List all items for the current sprint:

```bash
{backlog_commands.list_doing}
{backlog_commands.list_done}
```

For each doing item, check its acceptance criteria by expanding details:

```bash
{backlog_commands.show} <item-id>
```

Report: which items are complete (all acceptance criteria met), which are still in progress.

Verify item phases are appropriate before closing:
- Done items should have phase `review` or `build` (work was completed)
- If phase is still `plan` or `spec`, ask if the item was actually implemented

For incomplete items, ask: move to done (if actually complete) or defer to next sprint (move back to backlog)?

### Move Completed Items

```bash
{backlog_commands.move} <item-id> --status done
```

### Move Deferred Items

```bash
{backlog_commands.move} <item-id> --status backlog
{backlog_commands.edit} <item-id> --sprint 0  # clear sprint target
```

## Phase 2b: Issue Reconciliation

Check for GitHub issues referenced in sprint commits:

```bash
git log --oneline --grep="Fixes #" --grep="closes #"
```

If issues found, check their status and offer to close them.

## Phase 3: Knowledge Transfer

### Sprint Handover

Create `{docs.handover_dir}SPRINT{N}_HANDOVER.md` with:

Gather information by:
- Running `{backlog_commands.list_done}` filtered by sprint
- Running `git log --oneline` for commit history
- Reading recent changes

Generate the handover with:
- Sprint Theme
- Completed tasks (from YAML items — goal, complexity, key files)
- Deferred items (if any, with reasons)
- Key Decisions (ask the user)
- Architecture Changes
- Known Issues (ask the user)
- Lessons Learned (ask the user)
- Test Coverage (pytest count)
- Recommendations for Next Sprint

### PROJECT_CONTEXT.md

Update `{docs.project_context}`:
- Status -> "Sprint {N+1} Planning"
- Last Sync -> today's date
- Test count -> from pytest output
- Sprint History table -> add current sprint

### MEMORY.md — Audit & Update

Run a structured memory audit, then update:

**1. Staleness check** — read every memory file listed in MEMORY.md:
- [ ] Project memories: does the sprint number match `current_sprint` in sprint-config.yaml?
- [ ] Feedback memories: do they still apply? (check if referenced patterns/conventions still exist)
- [ ] Reference memories: do linked resources still exist?
- [ ] File references in memories: do the files/paths mentioned still exist?

**2. Clean up:**
- Remove or update any stale memories
- Fix mismatched filenames (name should reflect content)
- Delete duplicates

**3. Add new content:**
- Update sprint status memory with completed sprint summary
- Ask user: "Any lessons learned, feedback, or patterns worth remembering?"
- Save new feedback/project memories if the user provides any

**4. Verify MEMORY.md index** matches actual files in the memory directory.

## Phase 3b: Code Review (MANDATORY before merge)

**This phase is mandatory — never skip it.** Run a code review on the full sprint diff before creating the PR.

### Review the Sprint Diff

```bash
git diff main...HEAD --stat
git diff main...HEAD
```

Use the `superpowers:requesting-code-review` skill or the `review` skill to perform a two-stage review:

1. **Spec compliance** — does each item's implementation satisfy its acceptance criteria?
2. **Code quality** — style, naming, XSS safety (html.escape), test coverage, no regressions, no dead code

### Report Findings

Present findings to the user:
- Critical issues (must fix before merge)
- Warnings (should fix, but not blocking)
- Notes (informational)

**If critical issues exist:** fix them, re-run CI, then proceed to merge.
**If no critical issues:** proceed to Phase 4.

## Phase 4: Clean Slate

### Merge and Cleanup

```bash
# Create PR and merge
gh pr create --title "Sprint N: <theme>" --body "..."
gh pr merge --merge --delete-branch

# Switch to main
git checkout main && git pull
```

### Final Verification

```bash
git branch --show-current  # main
git status                 # clean
{backlog_commands.list_doing}  # should be empty
{ci_command}  # all green
```

### Next Sprint

Check backlog for next sprint candidates:

```bash
{backlog_commands.list_backlog}
```

Report: "Sprint {N} is closed. Ready for Sprint {N+1} planning — run `/sprint-start`."

## Important Rules

- YAML items are the single source of truth — read from backlog commands, not TODO.md
- NEVER trust docs over code — verify completion by checking the codebase
- ALWAYS ask the user for lessons learned and known issues
- Write the handover doc even if the sprint was small
