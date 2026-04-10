# Engineering Gotchas — Lessons from 17+ Sprints

> Hard-won knowledge distilled into actionable rules. Check here before making architectural decisions.
>
> **How to use this document:** Scan the relevant category before starting a new feature, migration, or infrastructure change. Each item describes a pitfall, explains why it matters, and provides a concrete fix. The Quick Reference table at the bottom lists the 10 most costly mistakes.

---

## 1. Docker & Containers

**1.1 `.gcloudignore` is not `.dockerignore`**
CI needs test files for lint/test steps; Docker does not need them at runtime. Never exclude `test/` from `.gcloudignore` if your CI pipeline runs tests before the Docker build step. Maintain both files independently and review them whenever you add a new top-level directory.

**1.2 Docker context boundaries in multi-service monorepos**
Build tools like Kaniko resolve the Docker context strictly from the specified root. If you have `services/api/` and `services/web/` sharing `lib/`, the context must include the shared directory or you must copy it into each service directory before building. Never assume the builder can reach files outside its context.

**1.3 Import extension mismatches between services**
A bundler-based service (e.g., Next.js with `moduleResolution: "bundler"`) allows `import "./foo"` without extensions, while a Node.js service using `"NodeNext"` requires `import "./foo.js"`. When two services share code, the shared library must use the stricter convention (explicit extensions) or each service must re-export with its own resolution rules.

**1.4 Standalone output mode for framework Docker builds**
Next.js `output: "standalone"` produces a self-contained `server.js` with only the dependencies it needs, shrinking the final image from 1GB+ to under 200MB. Without it, you must copy the entire `node_modules/` into the runner stage. Always enable standalone mode for any framework that supports it.

**1.5 Multi-stage builds: deps, builder, runner**
Use three stages: (1) `deps` installs `node_modules`, (2) `builder` compiles/bundles using those deps, (3) `runner` copies only production artifacts. This keeps the final image small, speeds up layer caching, and prevents dev dependencies from shipping to production.

**1.6 No symlinks in Docker context**
Kaniko and some Docker build backends cannot follow symlinks. If your shared library is symlinked into a service directory, the build will fail silently or produce an image missing that code. Copy the actual files into the service directory instead.

**1.7 Build ARGs vs runtime ENV for framework variables**
Framework variables like `NEXT_PUBLIC_*` are inlined at build time by the bundler. Passing them as runtime environment variables has no effect — the compiled JavaScript already contains the old values. Declare them as `ARG` in the Dockerfile and pass them via `--build-arg` during the build step.

**1.8 Non-root user in production containers**
Always create and switch to a non-root user (`USER node` or `USER appuser`) in the runner stage. Running as root inside containers is a security risk — a container escape gives the attacker root on the host. Most base images provide a non-root user; use it.

**1.9 Alpine images and libc compatibility**
Alpine Linux uses musl instead of glibc. Some Node.js native modules (e.g., those depending on `sharp` or gRPC) require glibc. Install `libc6-compat` on Alpine or switch to a Debian-slim base image if native modules fail with `Error: not found` or segfault.

**1.10 `.dockerignore` must exclude secrets**
Any `.env`, credentials file, or private key present in the build context will be baked into a layer — even if no `COPY` references it. Always add `*.env`, `.env*`, `credentials.json`, and `*.pem` to `.dockerignore`. Audit this file whenever you add a new secret type to the project.

**1.11 Copy shared code into service directories**
Cross-context imports (e.g., `../../lib/shared`) break in Docker builds because the context is scoped to a single service directory. Before building, either copy shared code into the service, use a workspace-root Dockerfile, or use a monorepo tool that handles this. Never rely on relative paths that escape the Docker context.

**1.12 Container images accumulate without cleanup policies**
Every CI build pushes a new image to the registry. Without a retention policy (e.g., keep last 10 tagged images, delete untagged after 7 days), storage costs grow linearly. Set up lifecycle rules on your container registry from day one.

**1.13 Health check path must match the framework's actual route**
Container orchestrators send health probes to a specific path. If your framework handles routes differently than expected (e.g., trailing slash normalization, base path prefix), the probe returns 404 and the container is killed in a restart loop. Test the exact health check URL from inside the container with `curl`.

---

## 2. Cloud Run / Serverless

**2.1 Bind to `0.0.0.0`, not `localhost`**
Cloud Run injects a `PORT` environment variable and routes traffic to it. If your server binds to `localhost` or `127.0.0.1`, the platform health check fails and the instance never receives traffic. Always bind to `0.0.0.0:$PORT`.

**2.2 `--no-traffic` fails on first deploy**
The `--no-traffic` flag for canary/gradual rollout requires an existing service revision. If the service does not exist yet, the deploy fails. Detect whether the service exists first (`gcloud run services describe`) and omit the flag on the initial deployment.

**2.3 `--allow-unauthenticated` may need an explicit IAM binding**
In some organizations, the `--allow-unauthenticated` flag is blocked by an org policy. You must explicitly grant the `allUsers` principal the `roles/run.invoker` role via IAM. Without this, the service returns 403 to all unauthenticated requests even though the flag was set.

**2.4 Ephemeral filesystem — design for cloud storage from day one**
Serverless containers have a writable filesystem, but it resets on every cold start and is not shared across instances. Never store persistent data (uploads, reports, scan results) on disk. Use cloud object storage (GCS, S3) from the first commit, even in local development, by providing a local adapter.

**2.5 `request.nextUrl` resolves to the internal container origin**
Behind a load balancer, framework URL helpers return the container's internal address (e.g., `http://localhost:8080`), not the public domain. Use `X-Forwarded-Host`, `X-Forwarded-Proto`, and `X-Forwarded-For` headers to reconstruct the public URL. Cloud Run sets these automatically.

**2.6 SSL certificate propagation takes 5-15 minutes**
After mapping a custom domain, the managed SSL certificate is not instant. During propagation, browsers see certificate errors or insecure warnings. Do not panic-revert DNS changes — wait at least 15 minutes and check with `curl -v` to see the certificate status.

**2.7 Min instances = 0 means cold starts**
Setting minimum instances to zero saves cost but introduces cold-start latency (2-10 seconds for Node.js with large dependency trees). For user-facing APIs, set min instances to at least 1. For background processors, zero is acceptable.

**2.8 Stateless design required**
In-memory caches, singleton patterns, and connection pools do not survive instance restarts or scale-down events. Any state that must persist across requests needs an external store (Redis, Firestore, etc.). Design every endpoint as if the instance will be destroyed after the response.

**2.9 Secret Manager IAM must be pre-granted before deploy**
If a Cloud Run revision references a Secret Manager secret but the service account lacks `secretmanager.secretAccessor`, the revision fails to start. Grant IAM permissions before deploying, not after. Automate this in your deploy script.

**2.10 Memory and CPU limits affect build and runtime differently**
Cloud Build steps may need 4GB+ RAM for TypeScript compilation of large projects, but the runtime container only needs 512MB. Set generous limits for build steps and tight limits for runtime. Monitor actual usage after launch and right-size.

**2.11 Concurrent deployment of dependent services causes ordering issues**
If service A depends on service B's new API, deploying both simultaneously can route traffic to the new A before B is ready. Deploy dependencies first, verify health, then deploy dependents. Encode this ordering in your deploy script.

---

## 3. CI/CD Pipelines

**3.1 `$COMMIT_SHA` is empty in manual builds**
Cloud Build populates `$COMMIT_SHA` only for trigger-based builds. When you run `gcloud builds submit` manually, the variable is empty, breaking image tags and version labels. Use a custom substitution like `_TAG` and default it to `$(git rev-parse --short HEAD)` in your script.

**3.2 Shell variables need `$$` escaping in build configs**
In `cloudbuild.yaml`, `$VAR` is a Cloud Build substitution, not a shell variable. To use a shell variable inside a build step, escape it as `$$VAR`. Forgetting this causes silent empty strings that break commands without any error message.

**3.3 Unused volumes cause validation errors**
If you declare a volume in `cloudbuild.yaml` but no step mounts it, the build fails validation. Only declare volumes that are actually used. This also applies to declared secrets that no step references.

**3.4 `NEXT_PUBLIC_*` must be build-time ARGs**
Framework environment variables that are inlined by the bundler must be available at build time, not just runtime. In your CI config, pass them as `--build-arg` to Docker or set them as environment variables in the build step that runs the bundler.

**3.5 Pre-commit hooks validate every commit**
Linting and formatting via pre-commit hooks (e.g., Husky + lint-staged with Biome) catch issues before they reach CI. This shortens the feedback loop from minutes (CI round-trip) to seconds (local hook). Always set up pre-commit hooks in the first sprint.

**3.6 Split CI (auto) from CD (manual)**
Continuous integration (lint, test, build) should run on every push. Continuous deployment to production should require a manual trigger or approval gate. Combining both into one pipeline means a merged PR can accidentally deploy to production.

**3.7 Test in manual builds before setting up triggers**
Before configuring automated build triggers, run the entire pipeline manually with `gcloud builds submit` (or equivalent) at least three times. This surfaces configuration issues, missing secrets, and permission gaps without polluting your trigger history.

**3.8 Secret Manager access must be pre-configured**
Build steps that need secrets (API keys, signing keys) must have the Cloud Build service account granted access to Secret Manager before the first build. A missing permission causes a cryptic "secret not found" error, not a permissions error.

**3.9 `.gcloudignore` must not exclude test files if CI runs tests**
If your CI pipeline runs `npm test` inside a Cloud Build step, the test files must be uploaded. A `.gcloudignore` that excludes `test/` or `*.test.ts` will cause all tests to silently pass (zero files found, zero failures). Always verify test count in CI output.

**3.10 `npm audit` should be advisory until dependencies are clean**
Adding `npm audit --audit-level=high` to CI will block every build if any transitive dependency has a known vulnerability. Use `npm audit || true` initially and track audit failures as tech debt. Switch to strict mode once the dependency tree is clean.

**3.11 Deploy scripts encode the right flags**
Wrap deployment commands in project scripts (e.g., `bin/deploy-staging.sh`) that include the correct flags, region, service account, and environment variables. Never use raw cloud CLI commands for deployment — one wrong flag can deploy to the wrong region or with missing secrets.

**3.12 Downgrade build machine type once builds are stable**
Start with a high-CPU machine type to keep build times low during development. Once the pipeline is stable and build times are predictable, downgrade to save cost. Monitor build duration after downgrading to ensure it stays acceptable.

**3.13 Pin dependency versions in CI lock files**
A missing or outdated lock file means CI installs different dependency versions than local development. Always commit `package-lock.json` or `pnpm-lock.yaml` and use `npm ci` (not `npm install`) in CI to ensure reproducible builds.

---

## 4. TypeScript & Node.js

**4.1 Linter major version breaking changes**
Biome v2, ESLint v9, and other linters introduce breaking config changes. Biome v2 replaced `ignore` with `includes` using `!` negation and renamed `--apply` to `--write`. Pin your linter version, read the migration guide, and update config files atomically in a dedicated commit.

**4.2 Shell glob differences between sh and zsh**
The pattern `**/*.test.ts` behaves differently in `/bin/sh` (used by npm scripts) versus zsh (interactive shell). In sh, `**` may not recurse. List explicit patterns (e.g., `test/*.test.ts test/**/*.test.ts`) or use a glob library. Always verify that `npm test` actually finds all test files.

**4.3 Edge Runtime: Web Crypto API only**
Middleware and edge functions run in a restricted runtime that does not include Node.js built-in modules. `require("crypto")` fails — use `globalThis.crypto` (Web Crypto API) instead. This affects HMAC, hashing, and random value generation. Test edge code in an edge-like environment, not full Node.js.

**4.4 `moduleResolution: "bundler"` vs `"NodeNext"`**
Bundler resolution allows bare imports without extensions (`import "./utils"`). NodeNext requires explicit `.js` extensions even for `.ts` source files (`import "./utils.js"`). Shared libraries consumed by both environments must use the stricter convention or provide dual exports.

**4.5 `"type": "module"` in package.json for ESM resolution**
When using tsx or ts-node to run TypeScript files, Node.js checks the nearest `package.json` for `"type": "module"`. Without it, `.ts` files are treated as CommonJS, and named ESM exports become inaccessible. This does not affect bundler-based frameworks (Next.js, Vite) which handle resolution internally.

**4.6 Dynamic CSS class names get purged**
Tailwind and similar utility-CSS frameworks scan source files for class names at build time. Dynamically constructed classes like `bg-${color}-500` are never found by the scanner and get purged from the production CSS. Use static lookup maps: `const bgColor = { red: "bg-red-500", blue: "bg-blue-500" }`.

**4.7 URLSearchParams iteration compatibility**
Iterating over `URLSearchParams` with `for...of` requires `--downlevelIteration` in tsconfig when targeting older ES versions. If your tsconfig does not enable this, use `.toString().split("&")` and parse manually, or call `.get()` / `.getAll()` for known parameter names.

**4.8 Lazy imports for heavy SDKs**
Large cloud SDKs (e.g., Firestore, BigQuery, Storage) add 2000+ modules to the dependency tree. Import them lazily with `const { Storage } = await import("@google-cloud/storage")` so that code paths that do not need the SDK do not pay the import cost. This is critical for serverless cold starts.

**4.9 ESM/CJS interop pitfalls**
tsx and ts-node treat files as CJS unless the nearest `package.json` declares `"type": "module"`. Mixing ESM and CJS in the same project causes `ERR_REQUIRE_ESM` or `Cannot use import statement outside a module`. Pick one module system per package and enforce it consistently.

**4.10 `noDefaultExport` rule must be disabled for frameworks**
Linter rules that prohibit default exports conflict with frameworks like Next.js, Remix, and Astro, which require default exports for pages, layouts, and API routes. Disable this rule for framework-convention files via config overrides, not globally.

**4.11 Strict mode catches bugs early**
TypeScript `strict: true` enables `strictNullChecks`, `noImplicitAny`, and other checks that catch entire categories of bugs at compile time. The cost of enabling strict mode is a one-time migration. Always enable it in new projects; for existing projects, enable it incrementally with `// @ts-expect-error` annotations.

**4.12 `resolveJsonModule` for JSON imports**
Importing JSON files (`import data from "./config.json"`) requires `resolveJsonModule: true` in tsconfig. Without it, TypeScript cannot find the module. Combine with `esModuleInterop: true` for default-import syntax to work correctly.

**4.13 Monorepo tsconfig `paths` do not work at runtime**
TypeScript `paths` aliases (e.g., `@shared/*`) are resolved at compile time only. At runtime, Node.js does not know about them. Use `tsx` with `--tsconfig` or configure your bundler to resolve paths. For test files, use `--import tsx` to enable path resolution.

---

## 5. Testing

**5.1 Node.js built-in test runner**
Node.js 18+ includes a built-in test runner (`node --test`) that requires no external dependencies. It supports `describe`, `it`, `beforeEach`, mocking, and coverage. For projects that do not need advanced features (snapshot testing, browser integration), it eliminates the vitest/jest dependency entirely.

**5.2 npm test uses `/bin/sh` for glob expansion**
When your `npm test` script uses a glob pattern, npm executes it via `/bin/sh`, not your interactive shell. The `**` glob may not recurse in sh. List multiple explicit patterns or use a Node.js test config file to avoid missing test files silently.

**5.3 lint-staged and parallel tests can conflict**
If lint-staged runs tests as part of the pre-commit hook, and those tests are slow, developers will skip the hook. Use `--test-skip-pattern` to exclude slow integration tests from pre-commit. Run the full suite in CI only.

**5.4 Extract route logic into testable modules**
Framework route handlers (Next.js API routes, Express middleware) are difficult to unit test because they depend on request/response objects and framework internals. Extract the core logic into pure functions in a `lib/` directory. The route handler just calls the function and maps the result to an HTTP response.

**5.5 Live smoke tests with env-var skip pattern**
Keep integration tests that hit real APIs in a separate directory (e.g., `test/live/`). Gate them on environment variables (`OCLENS_TOKEN`, `API_BASE_URL`). When the variable is unset, the test skips gracefully. This keeps `npm test` fast while providing real-API coverage in staging.

**5.6 Test coverage as a dedicated sprint deliverable**
Feature tasks focus on shipping working code. Adding a dedicated "test coverage" task at the end of each sprint ensures all new code gets comprehensive tests. Without this, coverage erodes over time because testing feels like overhead during feature work.

**5.7 Verify npm test actually runs all test files**
After adding a new test file, run `npm test` and check the output for the file name. Misconfigured glob patterns, incorrect file extensions, or wrong directories can cause new test files to be silently excluded. CI should fail if the test count drops unexpectedly.

**5.8 Test against real data shapes**
Unit tests that use hand-crafted mock data often miss edge cases present in real data (null fields, unexpected types, extra properties). Use anonymized snapshots of real data or generate realistic test fixtures from your schema definitions.

**5.9 Pre-commit vs CI test separation**
Pre-commit hooks should run fast checks only: lint, format, type-check, and a few critical unit tests. The full test suite (integration, end-to-end, performance) runs in CI. This keeps the commit cycle fast (under 10 seconds) while still catching regressions before merge.

**5.10 Temp directories with cleanup for filesystem tests**
Tests that write to the filesystem should create a temporary directory, operate within it, and clean up in an `after` hook. Never write to the project directory. Use `fs.mkdtemp()` for unique temp directories that avoid collisions in parallel test runs.

**5.11 Infrastructure tests**
Write tests that verify dependency completeness (all imports resolve), config validity (JSON schemas pass), and environment setup (required env vars documented). These catch deployment failures before they happen.

**5.12 Dev mode is not representative of performance**
Framework dev modes compile routes on first hit (adding 5-20 seconds of latency), enable hot-reload watchers, and often double-render components (React Strict Mode). Never use dev mode for performance testing. Always use production builds.

**5.13 Never trust docs over code**
Sprint status docs, TODO checkboxes, and README descriptions can go stale. When verifying whether a feature is implemented or a bug is fixed, grep the codebase. Code is the only source of truth for what the system actually does.

**5.14 Flaky tests erode trust in the entire suite**
A single test that intermittently fails trains developers to ignore test failures. Quarantine flaky tests immediately (mark as skip with a tracking issue), fix the root cause (usually timing, ordering, or shared state), and unskip. Never leave flaky tests in the main suite.

---

## 6. Security

**6.1 Auth ON by default, explicit opt-out only**
Every endpoint should require authentication unless explicitly marked as public. A configuration toggle that disables auth entirely (e.g., `AUTH_ENABLED=false`) is a critical security risk — it will inevitably leak to production. Design your auth middleware to reject by default.

**6.2 Cookie-forging scripts are an anti-pattern**
Test scripts that forge session cookies by using the signing secret bypass the auth flow, create unauditable sessions, and require distributing the secret to every developer. Use API tokens (Bearer tokens) for programmatic access and keep cookie signing internal to the auth module.

**6.3 Rate limiting on auth endpoints**
Login and token-generation endpoints are the primary target for brute-force attacks. Implement a sliding window rate limit (e.g., 5 attempts per 15 minutes per IP). Return 429 with a `Retry-After` header. Apply rate limiting at the reverse proxy level for defense in depth.

**6.4 Security audits surface real issues**
Periodic security audits (even self-audits) consistently find critical issues: auth bypasses, unprotected legacy routes, and privilege escalation bugs. Schedule an audit before any hardening sprint. Document findings with severity ratings and fix deadlines.

**6.5 Timing-safe comparison for all secret operations**
String comparison with `===` leaks information about which character position differs (timing side-channel). Use `crypto.timingSafeEqual()` (or the Web Crypto equivalent) for comparing hashes, tokens, HMAC signatures, and any other secret material.

**6.6 bcrypt/scrypt for passwords, SHA-256 for API keys**
Passwords need slow, salted hashing (bcrypt or scrypt) to resist brute-force attacks. API keys are high-entropy random strings that do not need slow hashing — SHA-256 is sufficient and much faster for per-request validation. Never use MD5 or plain SHA-1 for either.

**6.7 Remove legacy auth code aggressively**
When a new auth system replaces an old one, delete the old code immediately. Legacy auth paths that remain "just in case" become unmonitored attack surfaces. If the new system works in staging and production, the old code is dead weight.

**6.8 Input validation at API boundaries**
Validate all incoming data at the API boundary: check content-type headers, enforce size limits, validate against JSON schemas, and reject unknown fields. Never trust client input, even from your own frontend. Validation prevents injection, overflow, and malformed-data bugs.

**6.9 Dual auth pattern: session cookies + Bearer tokens**
Web browsers use HTTP-only session cookies; CLI tools and service-to-service calls use Bearer tokens. Supporting both in the same middleware provides a clean UX for humans and machines. Validate cookies with HMAC, validate tokens with hash lookup.

**6.10 Token format: prefix + base64url with hash storage**
Design API tokens with a recognizable prefix (e.g., `myapp_`) followed by base64url-encoded random bytes. Store only the SHA-256 hash in the database, never the raw token. The prefix makes tokens easy to identify in logs and secret scanners; hash storage means a database breach does not compromise active tokens.

**6.11 RBAC must be centralized in one module**
Authorization checks scattered across route handlers drift out of sync. Create a single `authorization.ts` module that maps roles to capabilities. Every route calls this module — never inline permission checks. Changes to the permission model happen in one file.

---

## 7. Data Integrity

**7.1 Upsert does not clean up orphaned documents**
`upsert` updates documents that match by ID but does not remove documents that no longer exist in the source data. When regenerating or syncing data, always delete stale documents first (`delete where source = X`), then upsert the current set.

**7.2 Fleet-wide stats must use aggregations, never page slices**
Computing totals, averages, or distributions from a paginated page slice produces incorrect results. Use database aggregation queries (`COUNT`, `SUM`, facets) that operate on the full dataset. The dashboard summary must reflect reality, not the current page.

**7.3 Denormalized counters reduce query complexity**
Maintaining pre-computed counters (e.g., `endpointCount`, `totalScans` on a tenant document) eliminates expensive count queries on every dashboard load. Update counters atomically when the source data changes. Accept eventual consistency for non-critical stats.

**7.4 Search index schema drift requires auto-patching**
When you add a field to your data model, the search index schema must be updated too. Implement a bootstrap function that diffs the current schema against the desired schema and patches missing fields. Create-only initialization is not enough for evolving schemas.

**7.5 Circuit breaker masks failures without observability**
A circuit breaker that silently falls back to a secondary data source (e.g., database instead of search index) hides failures from operators. Users experience degraded search before any alert fires. Always log circuit breaker state changes and expose them via health endpoints.

**7.6 Cache TTL needed, not one-shot load**
Loading configuration or registry data once at startup and never refreshing it means changes require a restart. Use a TTL-based cache (e.g., refresh every 5 minutes) so that configuration changes propagate without redeployment.

**7.7 Collection prefix for environment isolation**
Use a prefix on all database collection names (`prd_`, `stg_`, `local_`) to prevent environment crosstalk when multiple environments share a database instance. Make the prefix mandatory (fail fast if unset) to prevent accidental writes to production data.

**7.8 Concurrent writes on shared resources need locking**
When multiple processes update the same document or counter simultaneously, last-write-wins causes data loss. Use optimistic concurrency (version fields), database transactions, or atomic increment operations. Design for concurrency from the start.

**7.9 Composite indexes must be deployed before queries**
Database queries that filter or sort on multiple fields require composite indexes. If the index does not exist, the query fails at runtime. Deploy index definitions as part of your CI/CD pipeline, not as a manual step. Test queries against a fresh database to catch missing indexes.

**7.10 Write verification after bulk operations**
After a bulk write (backfill, migration, data generation), verify the result: compare the expected count against the actual count, and spot-check a few documents for correctness. Silent partial failures in bulk operations are common and easy to miss.

**7.11 Client-side filtering of page slices is misleading**
Filtering a paginated response on the client produces incorrect results because the filter only sees the current page, not the full dataset. Push all filters to the server (database query or search index `filter_by`). Return the filtered total count alongside the page.

**7.12 Demo data timestamps drift**
Static timestamps in demo data (e.g., `lastSeen: "2025-01-15"`) become stale as time passes, causing hosts to appear "inactive" or "stale." Either use relative timestamps (e.g., "now minus 2 hours") or regenerate demo data on a schedule.

**7.13 Soft deletes complicate queries but enable audit trails**
Marking records as deleted (`deletedAt: timestamp`) instead of removing them preserves audit history but requires every query to add `WHERE deletedAt IS NULL`. Decide on hard vs soft delete per entity type at design time, and enforce the filter in a data-access layer, not in individual queries.

---

## 8. Performance

**8.1 Dev mode is not representative of production performance**
Framework dev modes compile routes on first request (adding 5-20 seconds), enable source maps, and run extra validation (React Strict Mode double-mounts components, tripling API calls). Always benchmark with a production build.

**8.2 Use production mode for performance testing**
Create a `start-prod` script that builds the project and runs it in production mode locally. This eliminates compilation overhead and framework dev-mode behaviors, giving you measurements that match real deployment performance.

**8.3 Bundler optimizations do not help with large dependency trees**
Turbopack, SWC, and esbuild speed up compilation but cannot reduce the number of modules that must be loaded at runtime. If cold-start latency is high because of a 2000-module SDK, the fix is lazy imports or tree-shaking, not a faster bundler.

**8.4 Search service provides sub-100ms queries**
A dedicated search index (Typesense, Elasticsearch, Meilisearch) returns results in under 100ms with facets and full-text search. Database full-scans with client-side filtering take 1-10 seconds at scale. Invest in a search service early if your dataset will exceed 1000 documents.

**8.5 Scoped client caching with TTL**
Re-creating database or search clients on every request wastes time on connection setup and authentication. Cache clients at module scope with a TTL (e.g., 5 minutes) so they are reused across requests within the same instance. Invalidate on auth token rotation.

**8.6 Database fallback cap prevents unbounded reads**
When a search service is down and you fall back to direct database queries, add a hard limit (e.g., max 500 documents). Without a cap, a single request can scan the entire collection, exhausting memory and database read quota.

**8.7 Visualization endpoints need lightweight responses**
Grid and treemap visualizations need all matching documents, not just one page. Create a dedicated endpoint (e.g., `?mode=viz`) that returns only the fields needed for rendering (`name`, `value`, `category`) and omits heavy fields like descriptions, logs, and metadata.

**8.8 Server-side facet filtering is crucial for large datasets**
Client-side facet counts computed from a page slice show incorrect numbers. Push facet computation to the search service or database aggregation pipeline. This ensures facet counts reflect the full filtered result set, not just the visible page.

---

## 9. Process & Workflow

**9.1 KANBAN is source of truth for backlog, TODO for active sprint only**
The KANBAN board holds all backlog, tech debt, and future work. The TODO/sprint document contains only tasks selected for the current sprint. Mixing backlog into the active sprint document creates noise and makes priorities unclear.

**9.2 Check off DoD items as each task completes**
Definition of Done checkboxes should be marked immediately when a task is finished, not deferred to sprint end. Batch check-offs at sprint close are inaccurate — you will forget what was actually verified and what was assumed.

**9.3 One commit per feature or task**
Each commit should represent a single logical change: one feature, one bug fix, or one refactor. Batching multiple unrelated changes into a single commit makes bisecting regressions difficult and code review painful.

**9.4 All work on feature branches, merged via PR**
Never commit directly to the main branch, even for solo projects. Feature branches with pull requests create a review trail, enable CI gating, and provide a clean history. Name branches with a pattern: `sprint{N}/{feature-slug}`.

**9.5 Never trust docs over code — grep to verify**
TODO checkboxes, README descriptions, and sprint handover documents can be stale. When reporting status or verifying whether a feature exists, search the codebase. If the code does not contain the feature, it is not done, regardless of what the docs say.

**9.6 Every task must consider demo data impact**
When adding a new field, endpoint, or UI component that depends on data, check whether the demo data generator needs updating. Shipping a feature without corresponding demo data means reviewers and stakeholders cannot see it in action.

**9.7 Staging-first deployment reduces risk**
Always deploy to staging before production. Staging validates the build, configuration, secrets, and database migrations in a production-like environment. A "quick fix" deployed directly to production will eventually cause an outage.

**9.8 Demo script should be the single source of truth for demo data**
If demo data is created by multiple scripts, notebooks, or manual steps, it will drift out of sync. Consolidate all demo data generation into a single idempotent script that can be re-run safely to reset the environment.

**9.9 Demo data needs realistic distribution patterns**
Uniform random data does not exercise edge cases: empty categories, skewed distributions, max-length strings, special characters, and null fields. Design your demo data generator to produce a realistic distribution that tests the full range of UI and API behavior.

**9.10 Static timestamps drift — need refresh mechanism**
Demo data with hardcoded timestamps (e.g., "last seen 2 hours ago") becomes stale when the data is not regenerated. Either compute timestamps relative to the current time or provide a refresh command that updates all timestamps without regenerating everything.

**9.11 Always follow sprint start and end checklists**
Sprint transitions involve updating KANBAN, TODO, handover docs, project context, and memory files. Without a checklist, steps get skipped — especially documentation updates. Create `SPRINT_START_CHECKLIST.md` and `SPRINT_END_CHECKLIST.md` and reference them every time.

**9.12 Full task specs with verifiable DoD required before work begins**
A task without a Definition of Done is a task that is never finished. Every sprint task needs: a goal statement, complexity estimate, concrete DoD checkboxes (testable, not vague), and technical specs (file paths, API shapes, schema changes, fallback behavior).

**9.13 Use project scripts, never raw CLI commands**
Deployment, tenant management, and local development commands should be wrapped in project scripts (`bin/deploy.sh`, `bin/manage.sh`, `bin/local-stack.sh`). Raw CLI commands (`gcloud run deploy`, `firebase deploy`) are easy to misconfigure. Scripts encode institutional knowledge.

**9.14 Login page convention: primary auth above, SSO below**
When a login page supports both email/password and SSO (Google, GitHub), place the email/password form at the top and SSO buttons below a divider. This matches user expectations from most SaaS products and reduces confusion.

**9.15 Health endpoints split by access level**
A public health endpoint (`/health`) should return minimal information: `{ "status": "ok" }`. An authenticated health endpoint (`/api/health`) can include version, uptime, dependency status, and feature flags. Never expose internal system details to unauthenticated callers.

**9.16 Design observability endpoints with access control from the start**
Metrics, debug, and status endpoints expose sensitive operational data. Add authentication and authorization to these endpoints from the first implementation, not as a follow-up. An unprotected `/debug` or `/metrics` endpoint is a common source of information leakage.

**9.17 Handover documents prevent knowledge loss between sprints**
At the end of every sprint, write a handover document summarizing what was done, what changed architecturally, what was deferred, and any known issues. Without this, the next sprint (or a new team member) starts with stale context and re-discovers decisions that were already made.

**9.18 Automate the boring parts of sprint ceremonies**
Sprint start and sprint end involve repetitive file updates (KANBAN, TODO, project context, memory). Create checklist templates and scripts that automate or prompt for each step. Manual processes get skipped under time pressure.

---

## 10. GKE Autopilot

**10.1 GKE has no `K_SERVICE` environment variable**
Cloud Run auto-sets `K_SERVICE` with the service name. GKE does not. If your code uses `K_SERVICE` to detect the cloud environment, it will think it is running locally. Set an explicit environment variable (`APP_ENV=gcp`) in your pod spec and add fallback detection logic: `const isCloud = !!process.env.K_SERVICE || process.env.APP_ENV === "gcp"`.

**10.2 Autopilot blocks `hostPort`**
GKE Autopilot does not allow `hostPort` on containers for security reasons. Use a ClusterIP Service to expose infrastructure services (OTel collectors, metrics endpoints) within the cluster. Application pods connect via the service DNS name (e.g., `otel-collector.monitoring.svc.cluster.local:4317`).

**10.3 ManagedCertificates: one per domain**
Multi-domain ManagedCertificates block provisioning if any single domain fails DNS validation. All domains in the certificate wait indefinitely. Always create separate ManagedCertificate resources, one per domain, so they provision independently.

**10.4 BackendConfig CRD required for custom health check paths**
The GCE L7 load balancer defaults to `GET /` for health checks. If your app redirects `/` (e.g., to a login page), the health check returns 302 and the load balancer marks the backend as unhealthy, causing a restart loop. Create a BackendConfig with the correct `requestPath` (e.g., `/api/health`).

**10.5 `kubectl apply` reverts `kubectl set image`**
If you deploy with `kubectl set image` but your manifest YAML still has the old image tag, the next `kubectl apply` reverts the image to the old version. Either keep manifests in sync with deployed versions or use `kubectl set image` exclusively without mixing in `kubectl apply`.

**10.6 `AUTH_URL` required for OAuth on GKE**
Frameworks like NextAuth use the request URL to construct OAuth callback URLs. Behind a GKE load balancer, the internal URL is `http://0.0.0.0:8080`, not your public domain. Set `AUTH_URL` (or equivalent) to your public URL in the pod env vars.

**10.7 `sed -i ''` on macOS can empty files**
When using `sed -i ''` (macOS in-place edit) and the search pattern does not match, some expressions can truncate the file to zero bytes. Always verify file contents after sed operations in scripts, or use `cat > file << 'EOF'` for full rewrites.

**10.8 `kubeconform` for offline manifest validation**
`kubectl apply --dry-run=client` needs API server connectivity even for schema validation. Use `kubeconform -strict -summary` instead for fully offline validation. This catches schema errors before `kubectl apply` without requiring a running cluster.

---

## 11. OpenTelemetry

**11.1 OTel instrumentation must be the very first import**
`import "./instrumentation"` must be the first import in your application entry point. OTel patches `http`, `https`, and other modules at import time. If other modules are imported first, OTel cannot intercept their HTTP calls and traces will be incomplete or missing.

**11.2 `getNodeAutoInstrumentations()` is too heavy**
The auto-instrumentations package pulls in 30+ instrumentation libraries for Express, MongoDB, MySQL, Redis, gRPC, and more. Most projects use 2-3 of these. The unused ones add 5+ seconds to startup and significant memory overhead. Import only the specific instrumentations you need (e.g., `HttpInstrumentation`, `GrpcInstrumentation`).

**11.3 LoggerProvider needs explicit Resource**
The NodeSDK sets resource on trace and metrics providers but NOT on standalone LoggerProviders. Without an explicit `resource` parameter, logs appear as `unknown_service` in your observability backend. Always pass `resource: resourceFromAttributes({ [ATTR_SERVICE_NAME]: "my-service" })` to the LoggerProvider constructor.

**11.4 `metricReaders` (plural) for multiple readers**
The NodeSDK accepts `metricReaders: IMetricReader[]` for configuring multiple metric readers (e.g., PrometheusExporter + PeriodicExportingMetricReader). The singular `metricReader` property is deprecated and only accepts one reader.

**11.5 Pino `hooks.logMethod` has dual signatures**
`logger.info("msg")` passes `["msg"]` to `logMethod`, while `logger.info({key:"v"}, "msg")` passes `[{key:"v"}, "msg"]`. Always check `typeof inputArgs[0]` to determine which signature was used before injecting trace context.

**11.6 OTLP protocol: gRPC vs HTTP**
Grafana Cloud OTLP endpoint uses `http/protobuf` (otlphttp), not gRPC. If you push directly to Grafana Cloud without an intermediate collector, use the HTTP exporter. Within a cluster (app to OTel Collector), gRPC is preferred for lower overhead.

**11.7 Google Cloud Monitoring data source, not Prometheus**
Grafana's Prometheus data source cannot authenticate to Google Managed Prometheus (GMP). Use the Google Cloud Monitoring plugin in Grafana, which has native service account key authentication.

---

## 12. Next.js + Standalone + OTel

**12.1 Dynamic `require()` is invisible to Next.js file tracing**
Next.js `output: "standalone"` uses a file tracing algorithm to determine which files to include. Dynamic `require()` calls (used to bypass webpack for OTel) are invisible to this algorithm. OTel packages get excluded from the standalone output, causing `MODULE_NOT_FOUND` errors at runtime.

**12.2 `outputFileTracingIncludes` must list ALL transitive deps**
The `@opentelemetry/**/`* glob in `outputFileTracingIncludes` only covers scoped packages. Non-scoped transitive dependencies like `require-in-the-middle`, `import-in-the-middle`, `module-details-from-path`, `yaml`, and `forwarded-parse` must be listed explicitly. Missing any one of these causes OTel to fail silently or crash at startup.

**12.3 Diagnosing OTel load failures in containers**
Dashboard startup goes from ~400ms to ~4s when OTel SDK loads successfully. If startup stays fast, OTel is not loading. Quick check: `kubectl exec POD -- node -e "require('@opentelemetry/sdk-node')"`. If it fails with `MODULE_NOT_FOUND`, the missing module name is in the error message.

**12.4 `serverComponentsExternalPackages` for OTel**
OTel packages must be listed in `experimental.serverComponentsExternalPackages` in `next.config.js` to prevent webpack from bundling them. Without this, webpack mangles the dynamic imports and OTel cannot patch modules correctly.

---

## 13. npm audit in CI

**13.1 `--production` flag is deprecated**
`npm audit --production` is deprecated. Use `npm audit --omit=dev` instead to audit only production dependencies.

**13.2 Use `--audit-level=moderate` for CI gates**
`npm audit --audit-level=high` misses moderate-severity vulnerabilities. Use `--audit-level=moderate` for a balanced CI gate that catches significant issues without being overwhelmed by low-severity findings.

**13.3 Start advisory, then enforce**
Adding strict `npm audit` to CI immediately blocks every build if any transitive dependency has a known vulnerability. Start with `npm audit || true` (advisory mode) and track findings as tech debt. Switch to strict mode (`npm audit --omit=dev --audit-level=moderate`) once the dependency tree is clean.

---

## Quick Reference — Top 10 Most Costly Mistakes


| #   | Gotcha                                              | Category    | Impact                         |
| --- | --------------------------------------------------- | ----------- | ------------------------------ |
| 1   | Auth toggle that can disable auth entirely          | Security    | Critical vulnerability         |
| 2   | `NEXT_PUBLIC_`* as runtime env instead of build ARG | CI/CD       | Broken frontend config         |
| 3   | Dev mode used for performance benchmarks            | Performance | 10-20x slower measurements     |
| 4   | Client-side filtering of paginated data             | Data        | Incorrect stats and counts     |
| 5   | Missing `.dockerignore` for secrets                 | Docker      | Credentials in image layers    |
| 6   | `$COMMIT_SHA` empty in manual builds                | CI/CD       | Untagged container images      |
| 7   | Binding to localhost in containers                  | Cloud Run   | Service never receives traffic |
| 8   | Symlinks in Docker build context                    | Docker      | Silent build failures          |
| 9   | Legacy auth code left "just in case"                | Security    | Unmonitored attack surface     |
| 10  | No search index schema migration                    | Data        | Silent field omission          |


