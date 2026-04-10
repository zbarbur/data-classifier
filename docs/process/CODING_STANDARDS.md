# Coding Standards — {{PROJECT_NAME}}

## Formatting & Linting

### Biome v2

This project uses [Biome v2](https://biomejs.dev/) for both linting and formatting.

| Setting | Value |
|---------|-------|
| Indentation | Tabs |
| Quotes | Double quotes |
| Trailing commas | Always |
| Semicolons | Always |
| Line width | 100 (default) |

**Commands:**
```bash
# Check formatting and lint
npm run lint

# Fix formatting and lint issues
npx biome check --write .

# Note: Biome v2 removed --apply — use --write instead
```

**Biome config (`biome.json`) notes:**
- Biome v2 removed the `ignore` key — use `includes` with `!` negation patterns instead
- Exclude generated files, CSS files, and UI component libraries from linting

---

## TypeScript

### Compiler Configuration

| Setting | Value | Rationale |
|---------|-------|-----------|
| `strict` | `true` | Catch type errors at compile time |
| `target` | `ESNext` | Use latest JS features |
| `module` | `NodeNext` | Node.js native ESM resolution |
| `moduleResolution` | `NodeNext` | Matches module setting |
| `noUncheckedIndexedAccess` | `true` | Arrays and objects may be undefined |
| `exactOptionalPropertyTypes` | `true` | Distinguish `undefined` from missing |

### Type Rules

1. **No `any`** — use `unknown` and narrow with type guards
2. **No type assertions** (`as`) unless absolutely necessary — prefer type guards
3. **Explicit return types** on exported functions
4. **Interface over type** for object shapes (unless unions/intersections are needed)
5. **Const assertions** (`as const`) for literal objects and arrays

```typescript
// Good
function parseConfig(raw: unknown): Config {
	if (!isValidConfig(raw)) {
		throw new Error("Invalid config");
	}
	return raw;
}

// Bad
function parseConfig(raw: any): Config {
	return raw as Config;
}
```

---

## Testing

### Test Runner

This project uses the **Node.js built-in test runner** (`node --test`), not vitest or jest.

```bash
# Run all tests
npm test

# Run a specific test file
node --test --import tsx test/specific.test.ts

# Full CI check (lint + typecheck + test)
npm run ci
```

### Test File Organization

```
test/
  unit/           # Pure unit tests (no I/O, no network)
  integration/    # Tests that touch real services (DB, API)
  live/           # Tests against running instances (env-var gated)
  fixtures/       # Shared test data
```

### Test Writing Guidelines

1. **Descriptive test names** — describe the behavior, not the implementation
2. **One assertion per test** (when practical) — easier to diagnose failures
3. **No test interdependence** — each test must work in isolation
4. **Use `describe` blocks** to group related tests
5. **Skip gracefully** — use env-var checks for tests that need external services

```typescript
import { describe, it } from "node:test";
import { strict as assert } from "node:assert";

describe("TokenAuth", () => {
	describe("generateToken", () => {
		it("returns a token with the correct prefix", () => {
			const token = generateToken();
			assert.ok(token.startsWith("proj_"));
		});

		it("generates unique tokens on each call", () => {
			const a = generateToken();
			const b = generateToken();
			assert.notEqual(a, b);
		});
	});
});
```

---

## Error Handling

### Classification

Errors fall into two categories:

| Type | Behavior | Example |
|------|----------|---------|
| **Required** | Must succeed or the operation fails. Throw/propagate. | Database write for a user action |
| **Best-effort** | Failure is acceptable. Log and continue. | Analytics tracking, cache warming |

### Rules

1. **Never swallow errors silently** — at minimum, log them
2. **Classify every try/catch** — is this required or best-effort?
3. **Required operations:** let the error propagate (or throw a descriptive error)
4. **Best-effort operations:** catch, log with context, continue
5. **Always include context** in error messages — what operation failed, with what inputs

```typescript
// Required — let it propagate
async function createUser(data: UserInput): Promise<User> {
	const user = await db.collection("users").add(data);
	return user; // If this fails, the caller needs to know
}

// Best-effort — log and continue
async function trackEvent(event: AnalyticsEvent): Promise<void> {
	try {
		await analytics.send(event);
	} catch (error) {
		console.warn(`[analytics] Failed to track ${event.type}:`, error);
		// Continue — analytics failure should not break user flow
	}
}
```

### API Error Responses

Return structured error responses, never raw stack traces:

```typescript
// Good
return Response.json(
	{ error: "not_found", message: "User not found" },
	{ status: 404 },
);

// Bad
return Response.json(
	{ error: err.stack },
	{ status: 500 },
);
```

Standard error response shape:
```json
{
	"error": "error_code",
	"message": "Human-readable description"
}
```

---

## Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Files | `kebab-case.ts` | `token-auth.ts`, `rate-limiter.ts` |
| Directories | `kebab-case` | `lib/cloud/`, `test/unit/` |
| Variables & functions | `camelCase` | `tokenHash`, `validateRequest` |
| Constants | `UPPER_SNAKE_CASE` | `MAX_RETRIES`, `DEFAULT_TIMEOUT` |
| Types & interfaces | `PascalCase` | `UserConfig`, `TokenPayload` |
| Enums | `PascalCase` (members too) | `Role.Admin`, `Status.Active` |
| Environment variables | `UPPER_SNAKE_CASE` with project prefix | `PROJ_AUTH_SECRET`, `PROJ_DB_URL` |
| Test files | `*.test.ts` | `token-auth.test.ts` |
| CSS classes | `kebab-case` | `nav-header`, `btn-primary` |

---

## File Organization

### General Structure
```
src/                  # or lib/ — core logic
  module-name.ts      # Module implementation
  module-name.test.ts # Co-located test (alternative to test/ dir)
dashboard/            # Frontend (Next.js App Router)
  app/                # Routes and pages
  components/         # Reusable UI components
  lib/                # Frontend-specific utilities
test/                 # Test files (if not co-located)
bin/                  # CLI scripts and tools
docs/                 # Documentation
  process/            # Process docs (this directory)
  sprints/            # Sprint handover documents
```

### Module Rules

1. **One module, one responsibility** — a file should do one thing well
2. **Keep files under 300 lines** — if larger, consider splitting
3. **Export only what is needed** — minimize the public API
4. **Index files only re-export** — no logic in `index.ts`

---

## Import Ordering

Organize imports in this order, separated by blank lines:

```typescript
// 1. Node.js built-ins
import { readFile } from "node:fs/promises";
import { join } from "node:path";

// 2. External packages
import { Firestore } from "@google-cloud/firestore";
import { z } from "zod";

// 3. Internal modules (absolute paths)
import { validateToken } from "@/lib/token-auth";
import { Config } from "@/types/config";

// 4. Relative imports
import { helper } from "./utils";
import type { LocalType } from "./types";
```

---

## Comments

### When to Comment

Comments should explain **why**, not **what**. If the code needs a comment to explain what it does, consider refactoring for clarity first.

**Comment when:**
- The reason for a decision is not obvious from the code
- A workaround exists for a known issue (include issue reference)
- A complex algorithm or business rule needs context
- A TODO or FIXME marks incomplete work

**Do not comment:**
- Obvious code (`// increment counter` above `counter++`)
- Function signatures that are self-documenting
- Every line or every block

### Comment Format

```typescript
// Single-line comment for brief context

/**
 * Multi-line JSDoc for exported functions.
 * Describe parameters, return value, and side effects.
 */
export function processData(input: RawData): ProcessedData {
	// Circuit breaker: skip external call after 3 consecutive failures
	// to avoid cascading timeouts. Resets after 60 seconds.
	if (circuitBreaker.isOpen()) {
		return fallbackResult(input);
	}

	// TODO(T7.3): Replace in-memory counter with Redis when scaling horizontally
	const count = localCounter.increment(input.key);
}
```

---

## Environment Variables

### Rules

1. **Prefix all project env vars** with a consistent prefix (e.g., `PROJ_`, `APP_`)
2. **Never hardcode secrets** — always use env vars or a secret manager
3. **Provide defaults** for non-secret configuration
4. **Validate at startup** — fail fast if required env vars are missing
5. **Document all env vars** in a `.env.example` file

```typescript
// Good — validate at startup
const secret = process.env.PROJ_AUTH_SECRET;
if (!secret) {
	throw new Error("PROJ_AUTH_SECRET is required");
}

// Good — default for non-secret config
const port = Number(process.env.PORT) || 3000;
const maxRetries = Number(process.env.PROJ_MAX_RETRIES) || 3;
```

---

## Git Commit Messages

### Format
```
{type}: {short description}

{Optional longer description if the change is not self-evident}
```

### Types
| Type | When |
|------|------|
| `feat` | New feature |
| `fix` | Bug fix |
| `refactor` | Code restructuring without behavior change |
| `test` | Adding or updating tests |
| `docs` | Documentation changes |
| `chore` | Build, config, tooling changes |
| `security` | Security-related changes |

### Rules
- Keep the first line under 72 characters
- Use imperative mood ("Add feature" not "Added feature")
- One logical change per commit
- Reference task ID when applicable: `feat: add rate limiting (T5.2)`
