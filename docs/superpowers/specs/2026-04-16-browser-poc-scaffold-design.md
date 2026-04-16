# Design — `data_classifier/clients/browser/` PoC scaffold

**Date:** 2026-04-16
**Branch:** `sprint14/browser-poc-secret`
**Worktree:** `data_classifier-browser-poc`
**Status:** Approved (user, 2026-04-16)

---

## Goal

Deliver a client-side secret-detection engine (JavaScript, runs in browser, no
Python at runtime) that preserves byte-identical semantics with the Python
library for the Credential subset.

This document scopes the **scaffold only** — the file layout, module
boundaries, worker/pool architecture, build toolchain, and test skeleton.
It does not cover:

- S0 WildChat prevalence run (research-branch deliverable)
- S1 pattern gap audit, S3 pattern mine, S4 re2-wasm migration
- MV3 extension shell or Chrome Web Store packaging
- PII/Financial enablement at runtime (code path exists; default off)
- Plaintext-prose password detection (explicitly OUT per
  `queue.md` §"Secret detection track" → "Out of scope")

## Relationship to research-branch commitments

The architecture is pre-committed in
`docs/experiments/prompt_analysis/queue.md` §"Secret detection track"
(on `research/prompt-analysis`, synced 2026-04-16). This spec
instantiates those commitments into code; it does not re-open them.

Committed decisions inherited without discussion:

1. PoC location is `data_classifier/clients/browser/` on `main`; the
   Python wheel excludes that path.
2. Patterns are a shared asset on `main` (no fork); JS dict is
   generated from the Python JSON via a build script.
3. `secret_scanner` is built for structured content (KV pairs); for
   free-form prose only `regex_engine` patterns fire.
4. CREDENTIAL family is `{API_KEY, PRIVATE_KEY, PASSWORD_HASH,
   OPAQUE_SECRET}` — no plaintext `PASSWORD` subtype.
5. ReDoS defense is Web Worker `terminate`, not pattern-audit-as-gate.
6. Regex engine is JS-native for Stage 1; re2-wasm is the committed
   destination for Stage 2 behind the same interface.
7. Worker pool is size 2, lazy init, eager respawn, MV3-lifecycle-aware.
8. Fail-open default on scan timeout, configurable to fail-closed.
   Default budget 100ms pending S2 measurement.
9. Pattern source policy excludes trufflehog (AGPL-3.0); provenance is
   per-pattern and CI-enforced upstream.

## Directory layout

```
data_classifier/clients/browser/
├── README.md
├── package.json                  # name, scripts, esbuild + vitest + playwright
├── esbuild.config.mjs            # two bundles: scanner.esm.js + worker.esm.js
├── src/
│   ├── scanner.js                # public async API: scan(text, opts)
│   ├── pool.js                   # worker pool (size 2, lazy, respawn, MV3-aware)
│   ├── worker.js                 # worker shim: msg → scanner-core → postMessage
│   ├── scanner-core.js           # regex pass + secret-scanner pass
│   ├── regex-backend.js          # Stage-1 JS RegExp backend behind 1-fn iface
│   ├── validators.js             # Credential-touching validators only
│   ├── entropy.js                # shannon + charset-aware relative entropy
│   ├── kv-parsers.js             # JSON / env / code-assignment / quoted-KV
│   ├── decoder.js                # xor:/b64: decoder (mirror of _decoder.py)
│   └── generated/                # .gitignored; generator output
│       ├── patterns.js
│       ├── secret-key-names.js
│       ├── placeholder-values.js
│       └── stopwords.js
├── tester/
│   ├── index.html                # paste text → findings JSON
│   ├── tester.js
│   └── corpus/                   # small differential-test seed (xor-encoded)
├── tests/
│   ├── unit/                     # Vitest
│   └── e2e/                      # Playwright
└── .gitignore
```

Generator (Python side, at repo root):

```
scripts/generate_browser_patterns.py
```

Python wheel excludes `data_classifier/clients/browser/**` via
`pyproject.toml`.

## Runtime architecture

### Main thread — `scanner.js`

```
scan(text, { timeoutMs = 100, failMode = 'open' }) → Promise<Finding[]>
    ↓
pool.run({ text })            // Promise, raced against timeoutMs
    ↓
worker.js → scanner-core.scanText(text) → postMessage(findings)
```

On timeout:

- `pool.terminate(worker)` kills the worker (ReDoS defense).
- Pool respawns lazily on next request.
- Result is `[]` if `failMode === 'open'` (default), or a
  `{code: 'TIMEOUT'}` rejection if `'closed'`.

### Worker — `scanner-core.js`

Two passes per `scanText`:

1. **Regex pass** — iterate Credential-category patterns via
   `regex-backend.js` (Stage-1 `RegExp.exec`). Per match apply
   stopword → allowlist → validator → context adjustment. Mirrors
   `data_classifier/engines/regex_engine.py` minus the column-hint
   gate (structured-only concept that does not apply to prose).
2. **Secret-scanner pass** — `kv-parsers.js` extracts KV pairs;
   score each key against `secret-key-names`; tier-gate with entropy
   + char-class diversity; emit finding with `subtype` in
   `{API_KEY, PRIVATE_KEY, PASSWORD_HASH, OPAQUE_SECRET}`. Mirrors
   `data_classifier/engines/secret_scanner.py`.

Both passes produce `Finding`-shaped objects (mirror
`data_classifier/core/types.py::ClassificationFinding`, minus
`column_id` and `sample_analysis` since prompts have no columns or
sample sets).

### Finding shape

```js
{
  entity_type: string,     // e.g. "API_KEY", "OPAQUE_SECRET"
  category: "Credential",
  sensitivity: "CRITICAL",
  confidence: number,      // 0.0-1.0
  engine: "regex" | "secret_scanner",
  evidence: string,        // human-readable reason
  match: {                 // regex-pass only
    value: string,         // masked per entity_type
    start: number,
    end: number
  },
  kv: {                    // secret-scanner-pass only
    key: string,
    valueMasked: string,
    tier: "definitive" | "strong" | "contextual"
  }
}
```

## Narrow scope decisions (approved 2026-04-16)

| # | Decision | Chosen |
|---|---|---|
| 1 | Pattern scope in bundled `patterns.js` | All 77 patterns, Credential-filtered at runtime by default |
| 2 | Validators to port | Credential-touching only: `aws_secret_not_hex`, `not_placeholder_credential`, `random_password`. Patterns referencing any other validator (e.g. `luhn`, `bitcoin_address`) load with a **stub validator that always returns `true`**, and the generator emits a warning listing them so the gap is visible. No silent pattern drop. |
| 3 | KV parsers in v1 | JSON + env-style + code-assignment + quoted (mirror Python `parsers.py` exposed formats). Skip YAML. |
| 4 | `phone_number` validator | Skip entirely in v1 (PII, not in Credential scope) |
| 5 | MV3 extension shell | Out of v1 scope (tester page + Playwright cover S2 feasibility) |

## Testing strategy

### Vitest unit tests (TDD-driven, one per module)

- `entropy.test.js` — fixed vectors computed by the Python engine on
  a seed corpus; JS must match to 4 decimal places.
- `decoder.test.js` — xor/b64 round-trip; same fixtures as the
  Python decoder's tests.
- `validators.test.js` — table-driven per validator (accept / reject
  cases imported from the Python test corpus).
- `kv-parsers.test.js` — each format's positive + negative cases.
- `pool.test.js` — lazy init (first call spawns), timeout →
  `terminate` called, respawn on next call, size-2 concurrency.
  Uses `@vitest/web-worker` (official Vitest plugin that treats
  `new Worker(new URL(...))` as a module-in-process) so pool logic
  is testable without spinning up a real OS worker.
- `scanner-core.test.js` — end-to-end on 3-5 prose snippets with
  known expected findings.

### Playwright e2e

- Tester page loads, paste text, findings render.
- Worker timeout: pathological pattern input triggers `terminate`
  within the configured budget.

### Differential test skeleton

Parameterized over `tester/corpus/`. JS finding set ≡ Python finding
set within documented Stage-1 regex-semantics deltas. Scaffold ships
loader + 3-5 seed cases. Full corpus is S2's deliverable.

**Documented Stage-1 deltas** (JS `RegExp` vs Python `re2`):

- All patterns are authored against RE2 syntax, which is a syntactic
  subset of JS `RegExp` on the features used (character classes,
  anchors, quantifiers, non-capturing groups, Unicode properties).
  No pattern uses backreferences or lookaround, so JS compiles them
  without translation.
- JS regex has catastrophic-backtracking exposure that RE2 does not.
  The worker-terminate kill switch is the real defense; differential
  tests do not need to reproduce RE2's worst-case bound.
- Any other divergence discovered in S2 measurement gets documented
  here before the differential test's golden set is frozen.

## Build & CI

- `package.json` scripts:
  - `build` — esbuild production bundles.
  - `dev` — esbuild watch.
  - `generate` — invokes `python3 scripts/generate_browser_patterns.py`.
  - `test:unit` — Vitest.
  - `test:e2e` — Playwright.
  - `format` — Prettier (format-only; no ESLint in v1 to keep the
    toolchain minimal). ESLint adoption is a later decision.
- Pre-test hook runs `generate` so `src/generated/` is always fresh.
- `.gitignore` covers `src/generated/`, `dist/`, `node_modules/`.
- `pyproject.toml` excludes `data_classifier/clients/browser/**`
  from the wheel.
- Top-level CI (GitHub Actions) stays Python-only for now; a
  JS-CI job follows in a separate item once the scaffold lands.

## Module boundaries (isolation contract)

Each module has one responsibility and a small interface:

- `decoder.js` — `decodeEncodedStrings(values: string[]) → string[]`.
  No imports from `src/`.
- `entropy.js` — `shannon(s)`, `relativeEntropy(s)`, `detectCharset(s)`,
  `charClassDiversity(s)`. Pure functions, no imports.
- `validators.js` — object of validators keyed by name; signature
  `(value: string) → boolean`. Pure.
- `kv-parsers.js` — `parseKeyValues(text: string) → [key, value][]`.
  Pure.
- `regex-backend.js` — `createBackend() → { iterate(text, patterns, cb) }`.
  Swappable; Stage 2 reimplements `createBackend()` against re2-wasm.
- `scanner-core.js` — composes the above; exports
  `scanText(text, config) → Finding[]`. No DOM, no worker APIs.
- `worker.js` — worker-only shim; imports `scanner-core` and handles
  `postMessage`.
- `pool.js` — worker-lifecycle; no regex or pattern knowledge.
- `scanner.js` — public API; composes `pool` with timeout + fail mode.

Tests target each module independently; `scanner-core.test.js`
covers composition.

## Explicit non-goals

- Not shipping an MV3 extension.
- Not claiming measured bundle size yet (S2 feasibility spike measures).
- Not claiming measured scan latency (S2 measures).
- Not enabling PII/Financial detection by default; code path exists
  behind a category filter flag.
- Not porting Bitcoin, Ethereum, IBAN, SSN, VIN, DEA, EIN, NPI, ABA,
  phone validators in v1.

## Trigger to revisit

Revisit this spec when any of:

- S2 measures bundle > 200KB gzipped or P99 > worker kill budget
  (triggers Stage-2 re2-wasm item).
- S1 pattern gap audit lands (triggers S3 pattern expansion, which
  may bump pattern count past the ~250 Stage-2 threshold).
- First MV3 extension item is filed (triggers manifest + background
  service worker shell, likely reworks `pool.js` MV3 hooks).
