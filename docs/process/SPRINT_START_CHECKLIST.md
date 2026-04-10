# Sprint Start Checklist — {{PROJECT_NAME}}

Follow this checklist at the beginning of every sprint. Do not skip steps.

---

## Pre-Sprint Verification

### 1. Verify Clean Slate

- [ ] On `main` branch: `git branch --show-current` shows `main`
- [ ] Working tree clean: `git status` shows no uncommitted changes
- [ ] CI passes: `npm run ci` (lint + typecheck + test) exits 0
- [ ] No stale branches from previous sprint (delete merged branches)

```bash
git checkout main
git pull origin main
npm run ci
```

### 2. Review Previous Sprint

- [ ] Read the latest sprint handover: `docs/sprints/SPRINT{N-1}_HANDOVER.md`
- [ ] Check KANBAN.md — previous sprint's "Doing" section should be empty
- [ ] Check MEMORY.md — verify lessons from last sprint are captured
- [ ] Note any carryover items or unresolved tech debt

---

## Sprint Planning

### 3. Bug Triage

- [ ] Read `.claude/project.json` for tracker config
- [ ] **GitHub mode**: `gh issue list --label "bug" --state open` — review open bugs by severity
- [ ] **No tracker**: check KANBAN.md for `[BUG]` entries
- [ ] Select bugs to include in sprint scope (if any)
- [ ] Selected bugs will become task specs in step 4

### 4. Select Scope from KANBAN

- [ ] Open `docs/process/KANBAN.md`
- [ ] Review **Backlog** section — prioritize by impact and dependencies
- [ ] Review **Tech Debt** section — include at least one debt item if list is growing
- [ ] Select items for the sprint (be realistic about capacity)
- [ ] Consider dependencies between selected items — order matters

**Capacity guideline:**
- Small (S) tasks: 3-4 per sprint
- Medium (M) tasks: 2-3 per sprint
- Large (L) tasks: 1-2 per sprint
- Mix recommended: 1L + 2M + 1S, or 3M + 2S

### 5. Write Task Specs in TODO.md

- [ ] Clear TODO.md of previous sprint content (archive if needed)
- [ ] Write sprint header: `## Sprint {N} — {Theme}`
- [ ] For each selected item, create a full task spec using `TASK_TEMPLATE.md`
- [ ] Number tasks sequentially: T{N}.1, T{N}.2, T{N}.3, ...
- [ ] Assign specialists from `SQUAD_PLANNING.md`
- [ ] Set complexity (S/M/L) for each task

### 6. Validate Completeness

For every task in TODO.md, verify:

- [ ] **Goal** is a clear, one-sentence description of what and why
- [ ] **Specialist** is assigned (from SQUAD_PLANNING.md)
- [ ] **Complexity** is set (S/M/L)
- [ ] **Dependencies** are declared (or "None")
- [ ] **DoD** has verifiable checkboxes (see DEFINITION_OF_DONE.md)
- [ ] **Technical Specs** include concrete file paths, endpoints, schemas
- [ ] **Test Plan** describes what tests to write
- [ ] **Demo Data Impact** is assessed

### 7. Dependency Validation

- [ ] No circular dependencies between tasks
- [ ] Dependencies reference valid task IDs
- [ ] Execution order is feasible (dependent tasks come after their prerequisites)

---

## Sprint Initialization

### 8. Update KANBAN Doing Section

- [ ] Move selected items from **Backlog** to **Doing** in KANBAN.md
- [ ] Keep items in **Backlog** that were not selected

### 9. Create Sprint Branch

```bash
git checkout -b sprint{N}/main
```

- [ ] Sprint branch created from latest `main`
- [ ] Branch name follows convention: `sprint{N}/main`

### 10. Commit Planning Artifacts

```bash
git add TODO.md docs/process/KANBAN.md
git commit -m "Sprint {N}: planning — {theme description}"
```

- [ ] TODO.md with full task specs committed
- [ ] Updated KANBAN.md committed

---

## Ready Confirmation

Before beginning work, confirm:

- [ ] `main` is clean and CI passes
- [ ] TODO.md has all task specs with full DoD
- [ ] KANBAN.md Doing section matches TODO.md tasks
- [ ] Sprint branch created
- [ ] Planning artifacts committed
- [ ] Team (you + agents) knows the execution order

**Sprint {N} is ready. Begin with the first task that has no dependencies.**

---

## Quick Reference

```
git checkout main && git pull origin main
npm run ci
# Edit TODO.md and KANBAN.md
git checkout -b sprint{N}/main
git add TODO.md docs/process/KANBAN.md
git commit -m "Sprint {N}: planning — {theme}"
# Start working on T{N}.1
```
