# Sprint End Checklist — {{PROJECT_NAME}}

Follow this checklist when closing a sprint. Every step is required.

---

## Phase 1: Verify & Ship

### 1. Final Quality Gate

- [ ] All feature branches merged to sprint branch or `main`
- [ ] CI passes: `npm run ci` exits 0
- [ ] No skipped or pending tests
- [ ] No lint warnings or errors

```bash
npm run ci
```

### 2. Staging Verification

- [ ] Deployed to staging environment
- [ ] Manual smoke test of all new/changed features
- [ ] No console errors in browser
- [ ] API endpoints return expected responses

### 3. Production Deploy (if applicable)

- [ ] Staging verified and stable
- [ ] Production deployment executed via deploy script
- [ ] Post-deploy smoke test passed
- [ ] No error spikes in monitoring

---

## Phase 2: Update Tracking

### 4. TODO.md Final Update

- [ ] All completed tasks have all DoD checkboxes checked
- [ ] Incomplete tasks are clearly marked with reason
- [ ] Any deferred items noted with deferral reason
- [ ] Sprint summary added at top of TODO.md

### 5. KANBAN.md Update

- [ ] **Clear Doing section** — nothing should remain in Doing
- [ ] **Move completed items to Done** — with sprint number reference
- [ ] **Add new backlog items** discovered during the sprint
- [ ] **Add new tech debt items** — when `tracker.type` is `"github"`, create GitHub issues with `tech-debt` label; otherwise add to KANBAN.md Tech Debt section
- [ ] **Create issues from PR review suggestions** — unaddressed PR review suggestions become `tech-debt` issues
- [ ] **Identify next sprint candidates** — star or tag high-priority items

```markdown
## Done
- [Sprint {N}] {Completed item 1}
- [Sprint {N}] {Completed item 2}
```

### 6. Issue Reconciliation

- [ ] Read `.claude/project.json` for tracker config
- [ ] **GitHub mode**: find issue refs in sprint commits (`git log --grep="Fixes #"`)
- [ ] Check which referenced issues are still open
- [ ] Present reconciliation table (issue, status, suggested action)
- [ ] Close approved issues with `gh issue close` + comment
- [ ] Carry unresolved bugs forward to KANBAN backlog

---

## Phase 3: Knowledge Transfer

### 7. Write Sprint Handover

Create `docs/sprints/SPRINT{N}_HANDOVER.md` with:

```markdown
# Sprint {N} Handover — {{PROJECT_NAME}}

## Sprint Theme
{One sentence describing what this sprint was about}

## Completed
- T{N}.1 — {title} — {brief description of what was built}
- T{N}.2 — {title} — {brief description}

## Not Completed / Deferred
- T{N}.X — {title} — {reason for deferral}

## Key Decisions
- {Decision 1 and rationale}
- {Decision 2 and rationale}

## Architecture Changes
- {What changed in the system architecture}
- {New modules, removed modules, changed interfaces}

## Known Issues
- {Issue 1 — severity, workaround if any}

## Lessons Learned
- {Lesson 1 — what happened, what we learned}
- {Lesson 2}

## Recommendations for Next Sprint
- {What should be prioritized}
- {What technical debt is becoming urgent}

## Test Coverage
- Tests before: {N}
- Tests after: {N}
- New test files: {list}
```

### 8. Update PROJECT_CONTEXT.md

- [ ] Update **Status** and **Last Sync** date
- [ ] Update **Test Coverage** numbers
- [ ] Add sprint to **Sprint History** table
- [ ] Update **Current State** description
- [ ] Update **Architecture Summary** if it changed

### 9. Update MEMORY.md

- [ ] Add lessons learned from this sprint
- [ ] Update sprint status (mark current sprint as COMPLETED)
- [ ] Add any new key architecture patterns discovered
- [ ] Update test count
- [ ] Remove outdated information
- [ ] Keep MEMORY.md under 200 lines (move details to topic files)

---

## Phase 3b: Sync Learnings to Template (every 2-3 sprints)

If this project was created from the Agentic Agile Template, periodically sync new learnings back:

- [ ] Review sprint handover for generalizable lessons
- [ ] Generalize: strip project-specific names, URLs, IDs
- [ ] Port new gotchas to template `docs/GOTCHAS.md`
- [ ] Port new patterns to relevant template `docs/guides/*.md`
- [ ] Update template `CHANGELOG.md` with sync source
- [ ] Run `npm run ci` in template repo to verify

> Skip if fewer than 2 sprints since last sync. Check template `CHANGELOG.md` for last sync date.

---

## Phase 4: Clean Slate

### 10. Branch Cleanup

- [ ] Sprint branch merged to `main` via PR
- [ ] Feature branches deleted (local and remote)
- [ ] `main` is up to date

```bash
git checkout main
git pull origin main
git branch -d sprint{N}/main
# Delete any remaining feature branches
```

### 11. Verify Clean State

- [ ] On `main` branch
- [ ] Working tree clean
- [ ] CI passes on `main`
- [ ] No orphaned branches

```bash
git branch --show-current  # should be: main
git status                 # should be: clean
npm run ci                 # should be: all green
git branch                 # should be: only main (+ any future sprint branches)
```

---

## Sprint Closure Summary

Before declaring the sprint closed, confirm:

- [ ] All quality gates passed (CI, staging, production)
- [ ] KANBAN.md is updated (Doing empty, Done populated)
- [ ] Issue reconciliation complete (GitHub issues closed or carried forward)
- [ ] TODO.md reflects final state
- [ ] Sprint handover written at `docs/sprints/SPRINT{N}_HANDOVER.md`
- [ ] PROJECT_CONTEXT.md refreshed
- [ ] MEMORY.md updated with lessons
- [ ] Branches cleaned up
- [ ] `main` is clean and CI passes

**Sprint {N} is closed. Ready for Sprint {N+1} planning.**
