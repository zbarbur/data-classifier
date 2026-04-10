# Sprint Start Checklist — data_classifier

Follow this checklist at the beginning of every sprint. Do not skip steps.

---

## Pre-Sprint Verification

### 1. Verify Clean Slate

- [ ] On `main` branch: `git branch --show-current` shows `main`
- [ ] Working tree clean: `git status` shows no uncommitted changes
- [ ] CI passes: `ruff check . && ruff format --check . && pytest tests/ -v`
- [ ] No stale branches from previous sprint

```bash
git checkout main
git pull origin main
ruff check . && ruff format --check . && pytest tests/ -v
```

### 2. Review Previous Sprint

- [ ] Read the latest sprint handover: `docs/sprints/SPRINT{N-1}_HANDOVER.md`
- [ ] Check backlog — previous sprint items are marked done: `agile-backlog list --status done`
- [ ] Check `.claude/MEMORY.md` — verify lessons from last sprint are captured
- [ ] Note any carryover items or unresolved issues

---

## Sprint Planning

### 3. Bug Triage

- [ ] Review open bugs: `agile-backlog list --category bug --status backlog`
- [ ] Select bugs to include in sprint scope (if any)

### 4. Select Scope from Backlog

- [ ] Review backlog: `agile-backlog list --status backlog`
- [ ] Prioritize by impact, dependencies, and roadmap alignment
- [ ] Select items for the sprint

**Capacity guideline:**
- Small (S) tasks: 3-4 per sprint
- Medium (M) tasks: 2-3 per sprint
- Large (L) tasks: 1-2 per sprint
- Mix recommended: 1L + 2M + 1S

### 5. Assign Sprint to Backlog Items

```bash
agile-backlog edit {id} --sprint {N}
agile-backlog move {id} --status doing
```

- [ ] Selected items tagged with sprint number
- [ ] Status moved to `doing`

### 6. Validate Task Specs

For every sprint task, verify:

- [ ] Goal is clear (what + why)
- [ ] Complexity is set (S/M/L)
- [ ] Dependencies declared
- [ ] DoD has verifiable checkboxes (see DEFINITION_OF_DONE.md)
- [ ] Technical specs include file paths, models, patterns

---

## Sprint Initialization

### 7. Create Sprint Branch

```bash
git checkout -b sprint{N}/main
```

- [ ] Sprint branch created from latest `main`

### 8. Commit Planning Artifacts

```bash
git add backlog/
git commit -m "Sprint {N}: planning — {theme}"
```

---

## Ready Confirmation

- [ ] `main` is clean and CI passes
- [ ] Sprint items selected and tagged in backlog
- [ ] Sprint branch created
- [ ] Planning committed
- [ ] Begin with the first task that has no dependencies

---

## Quick Reference

```bash
git checkout main && git pull origin main
ruff check . && ruff format --check . && pytest tests/ -v
agile-backlog list --status backlog
# Select and tag items
git checkout -b sprint{N}/main
git add backlog/ && git commit -m "Sprint {N}: planning — {theme}"
```
