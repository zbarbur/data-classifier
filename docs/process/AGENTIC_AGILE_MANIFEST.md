# Agentic Agile Manifest — {{PROJECT_NAME}}

## Philosophy

This document defines how {{TEAM_NAME}} builds software using **agentic development** — a methodology where Claude Code specialist agents serve as skilled team members, each bringing domain expertise to sprint tasks. The human orchestrator sets direction; agents execute with discipline.

---

## Core Principles

### 1. Agents Are Team Members, Not Tools

Each specialist agent (node-architect, devsecops-expert, frontend-developer, etc.) operates with deep domain knowledge. They are assigned tasks matching their expertise, just like human team members. They follow the same Definition of Done, the same branch discipline, and the same quality gates.

### 2. Sprint-Based Iteration with Kanban Backlog

Work is organized in **short sprints** (1-2 weeks equivalent). Between sprints, a kanban board (`KANBAN.md`) holds the backlog and tech debt. Sprint planning pulls items from the kanban into `TODO.md` with full task specifications.

### 3. Context Is Everything

Agents have no memory between sessions. Context management is therefore a first-class concern:

| File | Purpose | When Loaded |
|------|---------|-------------|
| `CLAUDE.md` | Project rules, scripts, conventions | Auto-loaded every session |
| `MEMORY.md` | Lessons learned, current state, key patterns | Auto-loaded every session |
| `PROJECT_CONTEXT.md` | Architecture, infra, test counts, sprint history | On-demand |
| `TODO.md` | Active sprint tasks with DoD checkboxes | On-demand |
| `docs/sprints/SPRINT{N}_HANDOVER.md` | Sprint-specific knowledge transfer | On-demand (latest) |

### 4. One Task, One Commit, One Branch

Every task gets its own feature branch. Every task produces exactly one commit. Branches merge via PR — even for solo work — to create a review trail.

### 5. Verify by Code, Not by Docs

Documentation can drift. Before reporting any task as complete, **grep the codebase** to verify the implementation exists. TODO.md checkboxes are updated immediately upon task completion, not batched at sprint end.

---

## Workflow

```
KANBAN Backlog
    |
    v
Sprint Planning ──> TODO.md (task specs with DoD)
    |
    v
Task Execution ──> Feature branch per task
    |                  |
    |                  v
    |              Quality Gates (lint, typecheck, test)
    |                  |
    |                  v
    |              PR + Merge to main
    |
    v
Sprint Closure ──> Handover doc + KANBAN update + MEMORY update
```

### Planning Phase
1. Review KANBAN backlog and tech debt
2. Select scope for the sprint (consider dependencies)
3. Write full task specifications in TODO.md using TASK_TEMPLATE.md
4. Assign specialist agents to each task
5. Validate: every task has DoD, specs, test plan, dependency chain

### Execution Phase
1. Create feature branch: `sprint{N}/{task-slug}`
2. Implement according to technical specs
3. Write tests (test plan from task spec)
4. Pass all quality gates
5. Check off DoD items in TODO.md
6. Open PR and merge

### Review Phase
1. Architect-reviewer validates cross-cutting concerns
2. Security-auditor reviews security-sensitive changes
3. CI pipeline passes (lint + typecheck + test)
4. Staging deployment verified (when applicable)

### Closure Phase
1. All TODO.md items checked off or explicitly deferred
2. KANBAN.md updated (Done, new backlog items)
3. Sprint handover document written
4. PROJECT_CONTEXT.md refreshed
5. MEMORY.md updated with lessons learned

---

## Quality Gates

Every PR must pass these gates before merge:

| Gate | Command | Description |
|------|---------|-------------|
| Lint | `npm run lint` | Biome v2 — zero warnings, zero errors |
| Typecheck | `npm run typecheck` | TypeScript strict — no type errors |
| Test | `npm test` | All tests pass, no skipped tests |
| CI | `npm run ci` | Combined lint + typecheck + test |
| Staging | Deploy script | Deployed and manually verified on staging |

Security-sensitive changes additionally require:
- Security audit sign-off
- No new vulnerabilities introduced
- Auth/authz paths tested

---

## Branch Discipline

### Naming Convention
```
sprint{N}/{feature-slug}
```
Examples: `sprint5/user-auth`, `sprint5/api-rate-limiting`, `sprint5/fix-dashboard-crash`

### Rules
- **Never commit directly to `main`** — always use feature branches
- **One commit per task** — squash if needed before merge
- **PR before merge** — even for solo work, the PR creates a review trail
- **Delete branches after merge** — keep the branch list clean
- **No force pushes to main** — ever

---

## Communication Protocol

### During a Sprint
- **TODO.md checkboxes** are the real-time status board
- Check off items immediately upon completion
- Add blockers as comments in TODO.md

### Between Sprints
- **Sprint handover doc** (`docs/sprints/SPRINT{N}_HANDOVER.md`) captures everything the next session needs
- **MEMORY.md** gets updated with permanent lessons
- **KANBAN.md** gets updated with new backlog items discovered during the sprint

### Session Recovery
- Read CLAUDE.md (auto-loaded)
- Read MEMORY.md (auto-loaded)
- Read TODO.md for current sprint state
- Read latest sprint handover for recent context
- See `BOOTSTRAP.md` for full protocol

---

## Squad Composition

See `SQUAD_PLANNING.md` for detailed specialist definitions and assignment guidance.

The core squad for a full-stack project:

| Role | Primary Responsibility |
|------|----------------------|
| node-architect | System design, data models, core logic |
| frontend-developer | UI components, user flows, client state |
| api-designer | Endpoint design, request/response contracts |
| devops-engineer | Infrastructure, deployment, monitoring |
| devsecops-expert | Security hardening, auth, secrets management |
| security-auditor | Audit reviews, vulnerability assessment |
| architect-reviewer | Cross-cutting review, architecture consistency |

---

## Anti-Patterns to Avoid

1. **Batching TODO updates** — Update checkboxes immediately, not at sprint end
2. **Trusting docs over code** — Always verify by grepping the codebase
3. **Skipping task specs** — Every task needs full DoD and technical specs before work begins
4. **Combining tasks in one commit** — One task, one commit, one branch
5. **Skipping staging verification** — "It works locally" is not a quality gate
6. **Ignoring demo data impact** — New features may require demo data updates
7. **Starting without context** — Always follow the bootstrap protocol at session start
