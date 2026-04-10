# Definition of Done Guide — {{PROJECT_NAME}}

## Principle

Every DoD checkbox must be **independently verifiable** — by running a command, grepping the codebase, or hitting an endpoint. If you cannot verify a checkbox without reading the implementer's mind, it is not a valid DoD item.

---

## Universal DoD Items

These items appear on **every task**, regardless of type:

```markdown
- [ ] Tests pass (`npm test`)
- [ ] Lint clean (`npm run lint`)
```

For tasks that affect deployed behavior, add:

```markdown
- [ ] Deployed to staging and verified
```

---

## DoD by Task Type

### Backend / API Tasks

```markdown
- [ ] {METHOD} {/api/endpoint} returns {status code} with {expected shape}
- [ ] Error cases return appropriate status codes ({400|401|403|404|429|500})
- [ ] Input validation rejects malformed requests with descriptive errors
- [ ] Tests pass (`npm test`)
- [ ] Lint clean (`npm run lint`)
- [ ] Deployed to staging and verified with curl/API test script
```

**Example — good:**
```markdown
- [ ] GET /api/users/:id returns 200 with { id, name, email, role }
- [ ] GET /api/users/:id returns 404 when user not found
- [ ] POST /api/users returns 400 when email is missing
- [ ] Tests: test/api/users.test.ts covers all 3 cases
```

**Example — bad:**
```markdown
- [ ] Users API works
- [ ] Error handling done
```

### Frontend / UI Tasks

```markdown
- [ ] Component renders correctly with sample data
- [ ] User can complete the flow: {describe specific steps}
- [ ] Loading state displayed while data fetches
- [ ] Error state displayed when API call fails
- [ ] Responsive: renders correctly at 375px and 1440px widths
- [ ] Tests pass (`npm test`)
- [ ] Lint clean (`npm run lint`)
```

**Example — good:**
```markdown
- [ ] User can fill login form and submit (email + password fields)
- [ ] Invalid email shows inline validation error
- [ ] Successful login redirects to /dashboard
- [ ] Failed login shows "Invalid credentials" toast
- [ ] Submit button shows spinner during API call
```

**Example — bad:**
```markdown
- [ ] Login page works
- [ ] Looks good on mobile
```

### Security Tasks

```markdown
- [ ] Vulnerability from {issue/audit reference} is mitigated
- [ ] Exploit path verified as blocked (describe specific test)
- [ ] No regression in existing auth flows
- [ ] Security audit checklist item signed off
- [ ] Tests pass (`npm test`)
- [ ] Lint clean (`npm run lint`)
```

**Example — good:**
```markdown
- [ ] Auth bypass via missing middleware on /api/admin/* is fixed
- [ ] Unauthenticated request to /api/admin/users returns 401
- [ ] Authenticated non-admin request to /api/admin/users returns 403
- [ ] Test: test/auth/admin-routes.test.ts covers both cases
```

**Example — bad:**
```markdown
- [ ] Security issue fixed
- [ ] Auth works now
```

### Infrastructure / DevOps Tasks

```markdown
- [ ] {Resource} provisioned and accessible
- [ ] Configuration stored in {env var / secret manager}
- [ ] Health check returns 200 from deployed instance
- [ ] Rollback path documented and tested
- [ ] CI pipeline passes end-to-end
- [ ] Tests pass (`npm test`)
- [ ] Lint clean (`npm run lint`)
```

**Example — good:**
```markdown
- [ ] Redis instance provisioned on Cloud Memorystore (1GB, us-central1)
- [ ] REDIS_URL env var set in Cloud Run service via Secret Manager
- [ ] Connection pool established on startup (logged: "Redis connected")
- [ ] Graceful fallback to in-memory cache when Redis is unavailable
```

### Refactoring Tasks

```markdown
- [ ] Old code removed (no dead code left behind)
- [ ] All existing tests still pass without modification (or updated with justification)
- [ ] No behavior change from user perspective
- [ ] Import paths updated across all consumers
- [ ] Tests pass (`npm test`)
- [ ] Lint clean (`npm run lint`)
```

---

## Anti-Patterns

### 1. Vague Checkboxes

| Bad | Why | Good |
|-----|-----|------|
| `[ ] Feature implemented` | Not verifiable — what does "implemented" mean? | `[ ] GET /api/feature returns 200 with expected payload` |
| `[ ] Tests written` | How many? Testing what? | `[ ] test/feature.test.ts: 5 tests covering CRUD + error cases` |
| `[ ] Works correctly` | Subjective and unverifiable | `[ ] User flow: click Add > fill form > submit > see item in list` |

### 2. Missing Error Cases

Only testing the happy path is incomplete. Always include:
- What happens on invalid input?
- What happens when the dependency is down?
- What happens for unauthorized users?

### 3. Missing Baseline Items

Every task must include `Tests pass` and `Lint clean`. These are non-negotiable.

### 4. Compound Checkboxes

| Bad | Why | Good |
|-----|-----|------|
| `[ ] Endpoint works and tests pass` | Two things in one checkbox | Split into two separate items |
| `[ ] Deployed to staging and production` | Two environments, two verifications | `[ ] Deployed to staging` + `[ ] Deployed to production` |

### 5. Implementation-Focused Instead of Outcome-Focused

| Bad | Why | Good |
|-----|-----|------|
| `[ ] Added try/catch blocks` | Describes code, not outcome | `[ ] API returns 500 with error body (not stack trace) on unhandled exceptions` |
| `[ ] Used bcrypt for passwords` | Describes tool, not security property | `[ ] Passwords stored as bcrypt hashes (cost factor 12), plaintext never persisted` |

---

## Verification Techniques

| Technique | When to Use | Example |
|-----------|-------------|---------|
| `grep -r "pattern" src/` | Verify code exists | `grep -r "rateLimiter" src/middleware/` |
| `npm test` | Verify tests pass | Run before checking off any test-related DoD |
| `curl` / API test script | Verify endpoint behavior | `curl -s localhost:3000/api/health \| jq .status` |
| Browser manual test | Verify UI flows | Navigate the user flow end-to-end |
| `git diff main..HEAD` | Verify scope of changes | Ensure no unrelated changes snuck in |
| CI pipeline | Verify full quality gate | All checks green before merge |

---

## Checklist for Writing Good DoD

Before finalizing a task's DoD, verify:

- [ ] Every checkbox describes an **observable outcome**, not an implementation detail
- [ ] Every checkbox can be verified **independently** (one command, one check)
- [ ] **Error cases** are covered, not just happy paths
- [ ] **Baseline items** (tests pass, lint clean) are included
- [ ] No checkbox contains **compound conditions** (split them)
- [ ] Checkboxes are **specific enough** that a different person could verify them
