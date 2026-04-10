---
name: sprint-execute
description: Execute current sprint items. Reads doing items, dispatches subagents to implement each task, runs CI after each, and marks items as review phase.
---

# Sprint Execute Skill

You are executing sprint tasks. The user invoked `/sprint-execute $ARGUMENTS`.

## Prerequisites

**Read `.claude/sprint-config.yaml`** to get project-specific commands. All commands below use config references like `{ci_command}`, `{backlog_commands.list}`, etc. — substitute with actual values from the config.

Determine the current sprint number from `current_sprint` in the config.

## Step 1: Check Flagged Comments

```bash
{backlog_commands.flagged}
```

- [ ] Reviewed all flagged comments

If flagged comments exist, present them to the user. Resolve, defer, or convert before proceeding.

## Step 2: Gather Sprint Items

List all items currently in doing status:

```bash
{backlog_commands.list_doing}
```

If no doing items exist, report "No items in doing status — nothing to execute. Run `/sprint-start` to begin a sprint." and stop.

## Step 3: Execute Each Item

For each item with status=doing, execute the following pipeline. Process items in priority order (P0 first, then P1, etc.).

### 3a. Review Item Spec

Show item details:

```bash
{backlog_commands.show} <item-id>
```

Verify the item has:
- [ ] Goal (one-sentence description of what it delivers)
- [ ] Acceptance criteria (at least 2, verifiable)
- [ ] Technical specs (files to change, what to change)

**If any are missing:** invoke the `superpowers:brainstorming` skill to help the user fill gaps. Do NOT proceed with implementation until goal, acceptance criteria, and technical specs are present. Ask the user to confirm the spec before continuing.

### 3b. Move to Build Phase

```bash
{backlog_commands.edit} <item-id> --phase build
```

### 3c. Select Specialist

Determine the specialist agent to use for implementation. Follow this precedence:

1. **Explicit field** — if the item YAML has a `specialist` field, use that value
2. **Category mapping** — check `specialist_defaults` in sprint-config.yaml; match on item category or tags (e.g., tag "ui" maps to `frontend-developer`, tag "test" maps to `test-automator`)
3. **Auto-detect from keywords** — scan the item title, goal, and technical specs:
   - ui, frontend, component, nicegui, CSS -> `frontend-developer`
   - test, pytest, coverage -> `test-automator`
   - security, auth, permissions -> `security-auditor`
   - refactor, cleanup, rename -> `refactoring-specialist`
   - docs, documentation, readme -> `documentation-engineer`
   - cli, command, click -> `cli-developer`
   - debug, fix, crash, error -> `debugger`
4. **Default** — use the project's primary language specialist (`python-pro` for this project, derived from `language` in sprint-config.yaml)

Report the selected specialist to the user: "Specialist: <name> (reason: <how it was selected>)"

### 3d. Write Implementation Plan

Invoke the `superpowers:writing-plans` skill to create an implementation plan for this item.

The plan should be saved to `{docs.plans_dir}` with a filename matching the item slug.

- [ ] Implementation plan created and reviewed

### 3e. Execute Plan via Subagent

Invoke the `superpowers:subagent-driven-development` skill (or use the Agent tool directly) to implement the task.

Provide the subagent with:
- The specialist context (from step 3c)
- The full task spec (goal, acceptance criteria, technical specs, test plan)
- The implementation plan (from step 3d)
- Instruction to follow `superpowers:test-driven-development` when applicable (write tests first, then implementation)

The subagent should:
1. Write or update tests based on acceptance criteria
2. Implement the changes described in the plan
3. Run tests locally to verify before returning

### 3f. Run CI

After the subagent completes, run the full CI suite:

```bash
{ci_command}
```

- [ ] CI passes

### 3g. Handle CI Result

**If CI passes:**

Move item to review phase:

```bash
{backlog_commands.edit} <item-id> --phase review
```

Invoke `superpowers:requesting-code-review` to perform a two-stage review:
1. Spec compliance — does the implementation satisfy all acceptance criteria?
2. Code quality — style, tests, no regressions

Report: "Item <item-id> complete — moved to review phase."

**If CI fails (first attempt):**

Read the CI output carefully. Provide the error context to the subagent and retry the fix:

1. Identify the failing test(s) or lint error(s)
2. Dispatch the subagent again with the error output and instructions to fix
3. Run CI again: `{ci_command}`

**If CI fails (second attempt):**

Stop retrying. Mark the item as blocked:

```bash
{backlog_commands.edit} <item-id> --phase blocked
```

Report to the user:
- Which item failed
- The CI error output
- What was attempted
- Ask the user how to proceed (fix manually, skip, or defer)

Move to the next item.

### 3h. Handle Bugs Found During Execution

If a bug is discovered during implementation (not related to the current task), create a new backlog item:

```bash
{backlog_commands.add} "<bug title>" --category bug --priority P1
{backlog_commands.edit} <new-id> --sprint {current_sprint}
```

Tag all bugs found during execution with the current sprint number.

## Step 4: Report Status

After processing all items, present a summary:

```
Sprint {N} Execution Summary
=============================
Total items:     {total}
Completed:       {completed} (moved to review)
Blocked:         {blocked}
Bugs found:      {bugs_found}

CI status:       passing/failing
```

For each item, report:
- Item ID and title
- Final phase (review / blocked)
- Specialist used
- Key files changed

If all items are in review phase: "All sprint items implemented and in review. Run `/sprint-end` when ready to close the sprint."

If some items are blocked: "Some items are blocked — review the blocked items above and decide how to proceed before running `/sprint-end`."

## Important Rules

- **Only sprint-end moves items to "done"** — sprint-execute marks items as "review" at most
- **Tag all bugs with current sprint** — any bugs found during execution get the current sprint number
- **After 2 CI failures on the same task, stop and report** — do not retry indefinitely
- **If a task is blocked, move to the next task** — do not stall the entire sprint on one item
- **YAML items are the single source of truth** — read from backlog commands, not TODO.md
- **Never skip CI** — always run `{ci_command}` after each task implementation
- **Specialist selection is best-effort** — if no clear match, default to the project language specialist
- **Present the plan to the user before executing** — the user should approve the implementation plan
