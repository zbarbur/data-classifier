# data_classifier — browser client (PoC)

Client-side secret detection engine, ported from the Python
`data_classifier` library. Scans user-submitted text (e.g. a prompt
about to be sent to a chat AI) and returns findings + a redacted
version.

> **Scaffold — not yet published.** Tracks Sprint 14 item
> `sprint14/browser-poc-secret`. Honest performance + full pattern
> coverage arrive in subsequent sprint items. See
> `docs/superpowers/specs/2026-04-16-browser-poc-scaffold-design.md`.

## Usage

```js
import { createScanner } from '@data-classifier/browser';

const scanner = createScanner();
const { findings, redactedText, scannedMs } = await scanner.scan(
  'export API_KEY=ghp_...'
);
```

### Options

```js
scanner.scan(text, {
  timeoutMs: 100,                 // kill budget
  failMode: 'open',               // 'open' → empty findings on timeout
                                  // 'closed' → rejects with {code:'TIMEOUT'}
  redactStrategy: 'type-label',   // | 'asterisk' | 'placeholder' | 'none'
  verbose: false,                 // include a `details` block per finding
  dangerouslyIncludeRawValues: false,   // see WARNING below
  categoryFilter: ['Credential'],       // v1 Credential-only by default
});
```

## Development

```
npm install
npm run generate      # regenerates src/generated/ from the Python library
npm run build         # esbuild → dist/
npm run test:unit     # Vitest
npm run test:e2e      # Playwright (builds first)
npm run bench         # order-of-magnitude latency benchmark
```

`src/generated/` is gitignored. The `pretest` hook runs `generate`
every time, so generated assets are always fresh.

## ⚠️ Raw-value escape hatch

`scan(text, { dangerouslyIncludeRawValues: true })` populates
`match.valueRaw` with the unmasked matched value.

**Never enable in production.** Use only for local fixture authoring
and differential-test diagnostics. Any telemetry or log pipeline
that could receive a finding from this code path must strip
`valueRaw` before emit.

## Python ↔ JS sync

See the "Python → JS sync" section of the design spec. In short:

- **Data** (patterns, key names, stopwords, placeholders) — emitted
  by `scripts/generate_browser_patterns.py`. Run `npm run generate`.
- **Scoring parameters** (`engine_defaults.yaml`) — also emitted by
  the generator as `constants.js`. Run `npm run generate`.
- **Algorithm changes** — the generator SHAs the Python logic files
  into `PYTHON_LOGIC_VERSION` and stamps both fixtures and
  constants. If Python's logic changes, the differential test fails
  until the JS port follows.

### CI integration

After Python tests pass, run:

```
./scripts/ci_browser_parity.sh
```

With `--strict-validators`, the script also fails if any pattern
references a validator not yet ported to JS:

```
./scripts/ci_browser_parity.sh --strict-validators
```

## Architecture pointers

- `src/scanner.js` — public API.
- `src/pool.js` — 2-worker pool, lazy init, eager respawn, MV3-aware hook.
- `src/worker.js` — worker shim routing messages to scanner-core.
- `src/scanner-core.js` — orchestration of regex + secret-scanner passes.
- `src/regex-backend.js` — Stage-1 JS `RegExp` backend; Stage 2 swap target.
- `src/kv-parsers.js` — JSON / env / code-literal parsers with offsets.
- `src/redaction.js` — four strategies, right-to-left span replacement.
- `src/validators.js` — three ported validators; stubs for the rest.
- `src/entropy.js` — Shannon + charset-aware relative entropy.
- `src/decoder.js` — `xor:` / `b64:` prefix decoder.
- `src/generated/` — regen'd from Python; gitignored.
