# Session Bootstrap Protocol — {{PROJECT_NAME}}

## Overview

Claude Code agents have no memory between sessions. This protocol ensures every session starts with the right context, whether you are bootstrapping a new project, continuing a sprint, or starting fresh.

---

## First-Time Project Setup

If this is a **new project** created from the template, follow these steps before Sprint 1.

### Step 0: Initialize the Template

```bash
chmod +x bin/init-project.sh
bin/init-project.sh
```

This replaces all `{{PLACEHOLDER}}` values, installs dependencies, and verifies with `npm run ci`.

### Step 1: Project Inception (`/plan project`)

Run `/plan project` to create the **Project Charter**. This is the most important document in the project — it defines:

- **Mission statement** — the squad's decision-making compass
- **Problem statement** — what you're solving and for whom
- **Goals & north star metric** — how you measure success
- **Anti-goals** — what you explicitly won't build
- **Target users & use cases** — who needs what
- **Constraints** — technical, resource, compliance, external
- **MVP definition** — what's in the first release, what's deferred
- **Architecture decisions** — foundational technical choices
- **Squad composition** — which specialist agents and why
- **Sprint allocation strategy** — how to balance features vs debt vs security
- **Risk register** — what could go wrong and how to mitigate

The charter is saved to `docs/PROJECT_CHARTER.md` and becomes the reference for all future sprint planning.

### Step 2: Initialize Project Artifacts

After the charter is complete:

1. **KANBAN.md** — populate backlog from charter's MVP use cases
2. **PROJECT_CONTEXT.md** — fill in architecture, infrastructure, environments
3. **MEMORY.md** — add key project decisions, environment details, tool references
4. **CLAUDE.md** — add project-specific scripts, commands, and hard rules

### Step 3: Start Sprint 1

Follow the sprint start checklist:

```bash
# Read the checklist
cat docs/process/SPRINT_START_CHECKLIST.md

# Or use the skill
/sprint-start
```

Select initial backlog items aligned with the charter's MVP definition and Sprint 1-3 allocation strategy (typically 70% features, 10% foundation, 10% security, 10% testing/docs).

### Quick Reference: New Project

```
1. bin/init-project.sh              # Initialize template
2. /plan project                     # Create Project Charter (interactive)
3. Populate KANBAN.md, PROJECT_CONTEXT.md, MEMORY.md, CLAUDE.md
4. /sprint-start                     # Begin Sprint 1
```

---

## Auto-Loaded Context

These files are loaded automatically at the start of every Claude Code session:

| File | Content | Size Limit |
|------|---------|-----------|
| `CLAUDE.md` | Project rules, scripts, code style, commands | No hard limit, keep focused |
| `MEMORY.md` | Lessons learned, current state, key patterns | 200 lines max |

**You do not need to explicitly read these files.** They are injected into the agent's context automatically.

---

## On-Demand Context

Read these files when needed based on what you are doing:

| File | When to Read |
|------|-------------|
| `docs/PROJECT_CHARTER.md` | When making architectural or scope decisions — the project compass |
| `TODO.md` | When working on sprint tasks — shows current DoD and progress |
| `docs/sprints/SPRINT{N}_HANDOVER.md` | When resuming work from a previous session — read the latest one |
| `docs/process/PROJECT_CONTEXT.md` | When you need architecture overview or infrastructure details |
| `docs/process/KANBAN.md` | When planning a new sprint or checking backlog |

---

## Session Start: Continuing a Sprint

If you are resuming work on an active sprint:

1. **Context is auto-loaded** (CLAUDE.md + MEMORY.md)
2. **Read TODO.md** — identify which tasks are done, which are in progress
3. **Read the latest handover** — if the sprint has a handover from a previous session
4. **Identify the next task** — find the first unchecked task with no unmet dependencies
5. **Check the branch** — verify you are on the correct feature branch

```bash
# Verify branch and state
git branch --show-current
git status
npm run ci
```

---

## Session Start: Starting a New Sprint

If you are beginning a new sprint:

1. **Context is auto-loaded** (CLAUDE.md + MEMORY.md)
2. **Follow SPRINT_START_CHECKLIST.md** — do not skip any steps
3. **Read KANBAN.md** — review backlog and tech debt
4. **Read the previous sprint's handover** — understand what was done and what was deferred
5. **Plan the sprint** — write task specs in TODO.md

---

## Session Recovery: Interrupted Work

If a previous session was interrupted mid-task:

1. **Context is auto-loaded** (CLAUDE.md + MEMORY.md)
2. **Read TODO.md** — find the task that was in progress (partially checked DoD)
3. **Check git state:**
   ```bash
   git branch --show-current    # What branch are we on?
   git status                   # Any uncommitted changes?
   git log --oneline -5         # Recent commits?
   ```
4. **Assess the situation:**
   - If changes are committed but DoD is incomplete: continue from where it stopped
   - If changes are uncommitted: review them, decide whether to keep or discard
   - If on wrong branch: stash changes, switch to correct branch, apply
5. **Resume the task** — pick up from the first unchecked DoD item

---

## Context Refresh

When context feels stale or you are unsure about the current state:

```bash
# Quick state check
git branch --show-current
git status
git log --oneline -10
npm run ci
```

Then read:
1. `TODO.md` — sprint progress
2. `docs/process/PROJECT_CONTEXT.md` — overall project state
3. Latest `docs/sprints/SPRINT{N}_HANDOVER.md` — recent changes

---

## MEMORY.md Maintenance

MEMORY.md has a 200-line limit. When it grows too large:

1. **Move detailed content** into topic-specific files under a `memory/` directory
   - Example: `memory/tools-reference.md`, `memory/architecture-notes.md`
2. **Keep MEMORY.md as an index** — brief entries pointing to topic files
3. **Prune outdated entries** — remove lessons that are no longer relevant
4. **Consolidate similar entries** — merge related lessons into single entries

---

## Quick Reference

### "I just opened a new session and need to continue working"
```
1. (Auto-loaded: CLAUDE.md, MEMORY.md)
2. Read TODO.md
3. git branch --show-current && git status
4. Find next unchecked task
5. Start working
```

### "I'm starting a brand new project"
```
1. bin/init-project.sh
2. /plan project (interactive — creates Project Charter)
3. Populate KANBAN.md, PROJECT_CONTEXT.md, MEMORY.md, CLAUDE.md
4. /sprint-start (Sprint 1)
```

### "I need to start a new sprint"
```
1. (Auto-loaded: CLAUDE.md, MEMORY.md)
2. Read KANBAN.md
3. Read latest sprint handover
4. Follow SPRINT_START_CHECKLIST.md (or /sprint-start)
```

### "I need to check if we're still on track"
```
1. /plan roadmap
2. Review goal progress, backlog health, sprint allocation
3. Update charter if needed
```

### "I am not sure what is going on"
```
1. (Auto-loaded: CLAUDE.md, MEMORY.md)
2. git status && git log --oneline -10
3. Read TODO.md
4. Read PROJECT_CONTEXT.md
5. Read latest sprint handover
```
