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

### Smoke benchmark

A minimal latency probe to surface order-of-magnitude numbers
without waiting for S2's honest measurement.

- `npm run bench` — Playwright script in headless Chrome that:
  1. Loads the built `scanner.esm.js` + spawns the worker pool.
  2. Scans a synthetic ~1K-prompt batch from
     `tester/corpus/bench/` (short prose + interleaved credential
     shapes; no pathological ReDoS-inducing inputs).
  3. Reports mean / p50 / p99 / max per-scan latency, plus
     throughput and bundle parse time.
- Output: printed to stdout and written to
  `tester/corpus/bench/last_run.json` (gitignored).
- **Labeled order-of-magnitude only.** The synthetic corpus does
  not reflect real WildChat prompt shapes and ReDoS exposure; S2
  remains the source of honest P50/P95/P99 + the ReDoS audit.
- Catches 10× regressions at PR time without needing the full S2
  apparatus.

### Documented Stage-1 deltas (JS `RegExp` vs Python `re2`)

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
  - `bench` — smoke latency benchmark (see "Smoke benchmark" below).
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

## Python → JS sync

The "patterns are a shared asset, no fork" commitment covers the
JSON-encoded data assets. It does **not** cover logic drift. There
are three kinds of sync to keep honest:

### 1. Data sync (patterns, key-names, stopwords, placeholders)

Generator regenerates `src/generated/*.js` from the Python JSON on
every `npm run generate`. `src/generated/` is `.gitignore`d and the
pre-test hook always regenerates, so data drift is impossible at
test time. No further mechanism needed.

### 2. Scoring-parameter sync (thresholds, multipliers, weights)

Python thresholds live in `data_classifier/config/engine_defaults.yaml`
(e.g. `definitive_multiplier`, `strong_min_entropy_score`,
`relative_entropy_thresholds`, `diversity_threshold`,
`prose_alpha_threshold`).

Generator emits `src/generated/constants.js` from that YAML so the
JS engine reads the same values. A human changing a threshold in
Python and running `npm run generate` propagates it to JS with no
hand-edit. Covers numeric-parameter drift automatically.

### 3. Algorithm sync (entropy formula, charset detection, KV parsers, validators, tier composition)

This is the drift surface — ported code that can diverge silently
when the Python source evolves. Mechanism: **versioned differential
fixtures**.

Generator computes a SHA-256 over the concatenated contents of the
Python logic files:

- `data_classifier/engines/secret_scanner.py`
- `data_classifier/engines/regex_engine.py`
- `data_classifier/engines/validators.py`
- `data_classifier/engines/parsers.py`
- `data_classifier/engines/heuristic_engine.py`
- `data_classifier/config/engine_defaults.yaml`

…and emits it as `PYTHON_LOGIC_VERSION` in `constants.js`. In the
same run the generator invokes the Python library against the
`tester/corpus/` seed inputs and writes the expected findings to
`tester/corpus/fixtures.json`, stamped with the same
`PYTHON_LOGIC_VERSION`.

The differential test (`tests/e2e/differential.spec.js`) asserts
`fixtures.PYTHON_LOGIC_VERSION === constants.PYTHON_LOGIC_VERSION`
before comparing findings. When a Python logic file changes,
fixtures go stale; running `npm run generate` mints new fixtures
but the JS findings will now diverge until the port follows. Test
fails loudly with a message pointing at which Python file changed
and instructing the developer to update the corresponding JS
module.

**What this buys:** a Python-side fix that tightens a tier's
entropy floor, swaps a validator, or adjusts KV parsing can't ship
silently — the next PR touching the scaffold (or the nightly
differential run, when we add one) fails until the JS port is
aligned or the change is consciously deferred.

**What it doesn't buy:** a Python-side CI touch-guard that blocks
PRs mutating those files without a coordinated browser-side update
in the same PR. That's heavier (requires either a pre-commit hook
or a cross-package CI job), would slow down Python-only changes
that intentionally defer browser sync, and belongs in a follow-up
sprint item once real drift incidents justify it. Filed as
`backlog/` candidate after scaffold lands; not in v1.

### Responsibilities summary

| Change | Who does what |
|---|---|
| Add/edit pattern in `default_patterns.json` | `npm run generate` → commit |
| Tighten a threshold in `engine_defaults.yaml` | `npm run generate` → commit (constants auto-regen) |
| Change entropy formula / validator / KV parser in Python | `npm run generate` → differential tests fail → port the change to JS → re-run → commit both |
| Add a new Credential pattern whose validator isn't ported | Generator emits warning; pattern ships with stub validator; decision to port validator or accept stubbed behavior is tracked in the PR description |

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
- Drift incident: a Python-side logic change ships without the JS
  port following, and the divergence is caught by something other
  than the differential fixture test (e.g. a production report).
  Triggers the deferred CI touch-guard work.
