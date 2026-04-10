# Sprint Task Template

Use this template for every task in `TODO.md`. Copy the block below and fill in all fields.

---

## Template

```markdown
### T{SPRINT}.{TASK_NUM} — {Short descriptive title}
- **Goal:** {One sentence — what this task delivers and why}
- **Specialist:** {agent role from SQUAD_PLANNING.md, e.g., node-architect}
- **Complexity:** {S | M | L}
- **Depends on:** {T{SPRINT}.{OTHER} or "None"}
- **DoD:**
  - [ ] {Verifiable checkbox 1}
  - [ ] {Verifiable checkbox 2}
  - [ ] {Verifiable checkbox 3}
  - [ ] Tests pass (`npm test`)
  - [ ] Lint clean (`npm run lint`)
- **Technical Specs:**
  - {Concrete detail: file path, endpoint, schema, config change}
  - {Concrete detail}
- **Test Plan:**
  - {What tests to write and what they verify}
- **Demo Data Impact:**
  - {Does the demo data generator need updating? If so, what changes?}
  - {If no impact, write "None — no new fields or endpoints"}
```

---

## Field Guide

### Goal
One sentence that answers: **what** does this task deliver and **why** does it matter?

| Quality | Example |
|---------|---------|
| Good | "Add rate limiting to the `/api/users` endpoint to prevent abuse (max 100 req/min per API key)" |
| Bad | "Implement rate limiting" |
| Good | "Extract report generation logic from the route handler into a testable module" |
| Bad | "Refactor reports" |

### Specialist
Reference a role from `SQUAD_PLANNING.md`. Use `+` for multi-role tasks.

| Quality | Example |
|---------|---------|
| Good | `devsecops-expert + api-designer` |
| Bad | `developer` |

### Complexity

| Size | Guideline |
|------|-----------|
| **S** | Config change, small bug fix, minor UI tweak. < 50 lines changed. |
| **M** | New endpoint, new component, moderate refactoring. 50-300 lines changed. |
| **L** | New subsystem, cross-cutting change, major feature. 300+ lines changed. |

### Depends on
Reference other task IDs that must complete first. This creates an execution order.

- `T5.1` — depends on task 1 of sprint 5
- `T5.1, T5.3` — depends on multiple tasks
- `None` — can start immediately

### DoD (Definition of Done)
Every checkbox must be **independently verifiable** by grepping the codebase or running a command. See `DEFINITION_OF_DONE.md` for detailed guidance.

| Quality | Example |
|---------|---------|
| Good | `[ ] GET /api/health returns 200 with { status: "ok" }` |
| Bad | `[ ] Health endpoint works` |
| Good | `[ ] Rate limiter returns 429 after 100 requests in 60s (test: rate-limit.test.ts)` |
| Bad | `[ ] Rate limiting implemented` |

**Always include these baseline items:**
- `[ ] Tests pass (npm test)`
- `[ ] Lint clean (npm run lint)`

### Technical Specs
Concrete implementation details. File paths, endpoints, schemas, environment variables, configuration changes.

| Quality | Example |
|---------|---------|
| Good | `New file: lib/rate-limiter.ts — sliding window counter using Redis INCR` |
| Bad | `Add rate limiting logic somewhere` |
| Good | `Env var: RATE_LIMIT_MAX (default: 100), RATE_LIMIT_WINDOW_MS (default: 60000)` |
| Bad | `Make it configurable` |

### Test Plan
What tests to write, what they verify, and where they live.

| Quality | Example |
|---------|---------|
| Good | `test/rate-limiter.test.ts — unit tests: counter increment, window reset, 429 response, header values` |
| Bad | `Write some tests` |

### Demo Data Impact
Does the demo data generator need updating for this task? New fields, new endpoints, new UI that depends on data shape?

| Quality | Example |
|---------|---------|
| Good | `Update gen-demo.ts to include rate_limit_tier field on user docs` |
| Good | `None — no new fields or endpoints` |
| Bad | _(field omitted)_ |

---

## Full Example

```markdown
### T5.2 — Add API rate limiting middleware
- **Goal:** Prevent API abuse by enforcing per-key rate limits (100 req/min) on all authenticated endpoints
- **Specialist:** devsecops-expert + api-designer
- **Complexity:** M
- **Depends on:** T5.1 (API key system must exist first)
- **DoD:**
  - [ ] Middleware applied to all `/api/*` routes
  - [ ] Returns 429 with `Retry-After` header when limit exceeded
  - [ ] Rate limit headers present on all responses: `X-RateLimit-Limit`, `X-RateLimit-Remaining`
  - [ ] Configurable via `RATE_LIMIT_MAX` and `RATE_LIMIT_WINDOW_MS` env vars
  - [ ] Tests pass (`npm test`)
  - [ ] Lint clean (`npm run lint`)
  - [ ] Deployed to staging and verified with curl
- **Technical Specs:**
  - New file: `lib/rate-limiter.ts` — sliding window counter (in-memory Map for local, Redis for production)
  - New middleware: `middleware/rate-limit.ts` — wraps route handlers
  - Env vars: `RATE_LIMIT_MAX` (default: 100), `RATE_LIMIT_WINDOW_MS` (default: 60000)
  - Response headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`
  - 429 body: `{ "error": "rate_limit_exceeded", "retryAfter": <seconds> }`
- **Test Plan:**
  - `test/rate-limiter.test.ts` — unit: counter increment, window expiry, limit enforcement
  - `test/middleware/rate-limit.test.ts` — integration: header presence, 429 response, reset behavior
- **Demo Data Impact:**
  - None — rate limiting is transparent to data shape
```
