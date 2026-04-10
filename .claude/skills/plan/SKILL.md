---
name: plan
description: Planning skill with 4 modes — project inception, roadmap review, sprint allocation, and scope analysis.
---

# Plan Skill

You are running a planning process. The user invoked `/plan $ARGUMENTS`.

## Prerequisites

**Read `.claude/sprint-config.yaml`** to get project-specific commands. All commands below use config references like `{ci_command}`, `{backlog_commands.list}`, etc. — substitute with actual values from the config.

Parse the first word of `$ARGUMENTS` to determine the mode: `project`, `roadmap`, `sprint`, or `scope`.

---

## Mode: `/plan project` — Project Charter

Create a Project Charter for a new project or initiative.

### Steps

1. Ask the user for:
   - Project name and one-line purpose
   - Key stakeholders
   - Success criteria (measurable)
   - Known constraints (time, tech, scope)

2. Scan the codebase for existing context:
   - Read `{docs.project_context}` if it exists
   - Read `CLAUDE.md` for project rules

3. Produce a **Project Charter** document with:
   - **Vision** — one paragraph
   - **Goals** — 3-5 measurable outcomes
   - **Non-goals** — explicit out-of-scope items
   - **Stakeholders** — roles and responsibilities
   - **Constraints** — technical, timeline, resource
   - **Success criteria** — how to measure done
   - **Initial backlog themes** — high-level work areas

4. Save to `{docs.specs_dir}` with date prefix: `YYYY-MM-DD-project-charter.md`

---

## Mode: `/plan roadmap` — Strategic Review

Review project direction every 3-5 sprints. Read from the backlog to assess trajectory.

### Steps

1. Gather current state:

```bash
{backlog_commands.list}
```

```bash
{backlog_commands.list_done}
```

2. Read recent handover docs from `{docs.handover_dir}` (last 3-5 sprints)

3. Read `{docs.project_context}` for high-level status

4. Produce a **Roadmap Review** with:
   - **Velocity trend** — items completed per sprint over last 3-5 sprints
   - **Theme analysis** — what categories of work dominated (features vs bugs vs debt)
   - **Backlog health** — age of oldest items, items without sprint targets
   - **Recommendations** — strategic adjustments for next planning horizon
   - **Proposed themes** — 2-3 themes for the next 3-5 sprints

5. Present to user for discussion. Adjust based on feedback.

---

## Mode: `/plan sprint` — Sprint Allocation Balance

Analyze sprint allocation across work categories to ensure healthy balance.

### Steps

1. Load current sprint items:

```bash
{backlog_commands.list_doing}
```

2. Load backlog candidates:

```bash
{backlog_commands.list_backlog}
```

3. Categorize items by type: feature, bug, chore (tech debt), docs, security

4. Produce an **Allocation Report**:
   - **Current sprint breakdown** — % by category
   - **Recommended balance** — features 60%, bugs 20%, debt/docs 20% (adjust per project maturity)
   - **Gaps** — categories with zero allocation
   - **Suggestions** — specific backlog items to consider adding for balance

5. Present recommendations. Help user adjust sprint scope if needed.

---

## Mode: `/plan scope [feature]` — Scope Analysis

Analyze scope before committing to build a feature. The feature name follows `scope` in `$ARGUMENTS`.

### Steps

1. Search the backlog for related items:

```bash
{backlog_commands.list}
```

2. Explore the codebase for related code:
   - Search for files, modules, and tests related to the feature
   - Identify integration points and dependencies

3. Produce a **Scope Analysis** with:
   - **Feature summary** — what it does, who it serves
   - **Complexity estimate** — S/M/L with justification
   - **Dependencies** — code modules, external services, other backlog items
   - **Risk factors** — unknowns, technical challenges
   - **Suggested breakdown** — decompose into 2-5 smaller tasks
   - **Recommended approach** — build order, key decisions to make first

4. Ask the user: proceed to create backlog items for the breakdown?

If yes, create items via:

```bash
{backlog_commands.add}
```

## Important Rules

- Planning outputs are discussion documents, not commitments
- Always read from the backlog as the source of truth
- Use `{backlog_commands.*}` for all backlog queries, never read YAML files directly
- Save formal documents to `{docs.specs_dir}` or `{docs.plans_dir}` as appropriate
