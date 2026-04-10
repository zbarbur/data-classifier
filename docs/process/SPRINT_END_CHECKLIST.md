# Sprint End Checklist — data_classifier

Follow this checklist when closing a sprint. Every step is required.

---

## Phase 1: Verify & Ship

### Quality Gate

- [ ] All tests pass: `pytest tests/ -v`
- [ ] Lint clean: `ruff check .`
- [ ] Format clean: `ruff format --check .`
- [ ] CI green on GitHub Actions (all Python versions)
- [ ] No regressions in golden fixture tests

### Code Review

For each task delivered, verify:

- [ ] **Logging** — operations log at appropriate levels, no print statements
- [ ] **Error handling** — required operations raise, best-effort operations catch-and-continue
- [ ] **Edge cases** — empty inputs, None values, single-element lists handled
- [ ] **Validation** — validators run on matched patterns, confidence in [0, 1]
- [ ] **Test coverage** — new code has tests, existing tests still pass
- [ ] **Security** — no secrets in committed files, credential examples XOR-encoded
- [ ] **Quality** — no dead code, no commented-out blocks, no debug prints
- [ ] **Spec compliance** — behavior matches CLIENT_INTEGRATION_GUIDE.md

---

## Phase 2: Update Tracking

### Backlog

- [ ] Mark completed items as done: `agile-backlog move {id} --status done`
- [ ] Unfinished items remain in backlog (not moved back)
- [ ] New items discovered during sprint added to backlog
- [ ] Sprint status: `agile-backlog sprint-status`

### Documentation

- [ ] CLIENT_INTEGRATION_GUIDE.md updated if API changed
- [ ] ROADMAP.md updated if scope changed
- [ ] PATTERN_SOURCES.md updated if patterns added
- [ ] Pattern HTML reference regenerated if patterns changed

---

## Phase 3: Knowledge Transfer

### Handover Document

Create `docs/sprints/SPRINT{N}_HANDOVER.md` with:

- [ ] **Delivered** — what was built, with specifics
- [ ] **Deferred** — what was planned but not completed, and why
- [ ] **Known Issues** — bugs, limitations, workarounds
- [ ] **Decisions Made** — design choices and rationale
- [ ] **Commits** — list of commits with descriptions

### Context Updates

- [ ] Update `docs/process/PROJECT_CONTEXT.md` with:
  - Sprint history row
  - Test count
  - Pattern count (if changed)
  - New modules (if added)
- [ ] Update `.claude/MEMORY.md` with:
  - Key decisions
  - Lessons learned
  - Any changed conventions

---

## Phase 4: Merge & Clean

### Merge to Main

```bash
git checkout main
git merge sprint{N}/main
git push origin main
```

- [ ] Sprint branch merged to main
- [ ] CI passes on main after merge
- [ ] Sprint branch deleted: `git branch -d sprint{N}/main`

### Final Verification

```bash
ruff check . && ruff format --check . && pytest tests/ -v
python -c "from data_classifier import classify_columns, ColumnInput"
```

- [ ] Full CI passes on main
- [ ] Package imports work
- [ ] Handover doc committed

---

## Quick Reference

```bash
# Quality gate
ruff check . && ruff format --check . && pytest tests/ -v

# Close backlog items
agile-backlog move {id} --status done
agile-backlog sprint-status

# Merge
git checkout main && git merge sprint{N}/main && git push origin main

# Verify
python -c "from data_classifier import classify_columns"
```
