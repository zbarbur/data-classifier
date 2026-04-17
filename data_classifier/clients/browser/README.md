# @data-classifier/browser

Client-side secret detection engine, ported from the Python
`data_classifier` library. Scans user-submitted text (e.g. a prompt
about to be sent to a chat AI) and returns findings + a redacted
version.

**12.5 KB gzipped.** No runtime dependencies. ES module.

> Scaffold — tracking `sprint14/browser-poc-secret`. Full pattern
> coverage arrives in subsequent sprint items.

## Quick start

```js
import { createScanner } from '@data-classifier/browser';

const scanner = createScanner();
const { findings, redactedText, scannedMs } = await scanner.scan(
  'export API_KEY=ghp_...'
);
```

## Chrome extension integration

The extension's bundler resolves the main entry. The worker file must
be copied as a separate static asset:

```js
// In your extension code (offscreen document or content script)
import { createScanner } from '@data-classifier/browser';

const scanner = createScanner({
  spawn: () => new Worker(
    chrome.runtime.getURL('worker.esm.js'),
    { type: 'module' }
  ),
});

const { findings, redactedText } = await scanner.scan(promptText);
```

**Webpack:** Use `copy-webpack-plugin` to copy `node_modules/@data-classifier/browser/dist/worker.esm.js` to your output directory.

**Vite:** Copy the worker file in a `buildEnd` plugin hook.

### MV3 lifecycle

```js
chrome.runtime.onSuspend.addListener(() => {
  scanner.onServiceWorkerSuspend();
});
```

## Scan options

```js
scanner.scan(text, {
  timeoutMs: 100,                       // worker kill budget (ms)
  failMode: 'open',                     // 'open' = empty on timeout
                                        // 'closed' = rejects with {code:'TIMEOUT'}
  redactStrategy: 'type-label',         // 'asterisk' | 'placeholder' | 'none'
  verbose: false,                       // attach details block per finding
  dangerouslyIncludeRawValues: false,   // see WARNING below
  categoryFilter: ['Credential'],       // v1 Credential-only
});
```

## Standalone testing

```
git clone <repo>
cd data_classifier/clients/browser
npm install
npm run serve
# open http://localhost:4173/tester/
```

The tester page includes 12 real-world examples from the WildChat
corpus. Select one from the dropdown to see the scanner in action.

## Development

```
npm install
npm run generate      # regenerate src/generated/ from Python library
npm run build         # esbuild -> dist/ (minified, no sourcemaps)
npm run build:dev     # esbuild -> dist/ (unminified, with sourcemaps)
npm run dist          # generate + build + size report
npm run serve         # generate + build + http-server on :4173
npm run test:unit     # Vitest (75 tests)
npm run test:e2e      # Playwright (smoke + timeout + differential)
npm run bench         # 1K-prompt latency benchmark
```

## Raw-value escape hatch

`scan(text, { dangerouslyIncludeRawValues: true })` populates
`match.valueRaw` with the unmasked matched value.

**Never enable in production.** Use only for local fixture authoring
and differential-test diagnostics.

## Python-JS sync

- **Data** (patterns, stopwords, placeholders, key names) — generated
  from Python source. Run `npm run generate`.
- **Scoring params** (`engine_defaults.yaml`) — also generated as
  `constants.js`. Run `npm run generate`.
- **Algorithm changes** — `PYTHON_LOGIC_VERSION` SHA stamps fixtures
  and constants. Differential test fails on drift.

### CI integration

```
./scripts/ci_browser_parity.sh                 # after pytest
./scripts/ci_browser_parity.sh --strict-validators  # also fail on stubs
```

## Documentation

- [Pattern reference](docs/patterns.md) — all 77 patterns with validators and descriptions
- [Secret detection logic](docs/secret-scanner.md) — how the scanner works
- [Real-world stories](docs/stories.md) — 12 annotated examples from WildChat

## Architecture

- `src/scanner.js` — public API
- `src/pool.js` — 2-worker pool, lazy init, respawn, MV3-aware
- `src/worker.js` — worker shim
- `src/scanner-core.js` — regex + secret-scanner orchestration
- `src/regex-backend.js` — Stage-1 JS RegExp backend
- `src/kv-parsers.js` — JSON / env / code-literal parsers
- `src/redaction.js` — four strategies, right-to-left replacement
- `src/validators.js` — three ported validators + stubs
- `src/entropy.js` — Shannon + relative entropy
- `src/decoder.js` — xor: / b64: prefix decoder
- `src/generated/` — regenerated from Python; gitignored

## Footprint

| Component | Raw | Gzipped | In extension? |
|-----------|-----|---------|---------------|
| scanner.esm.js | 1.5 KB | 0.8 KB | Yes |
| worker.esm.js | 77 KB | 11.7 KB | Yes |
| **Extension total** | **78.5 KB** | **12.5 KB** | |
| Tester + stories + docs | ~55 KB | ~10 KB | No |
| **npm package total** | ~135 KB | ~25 KB | |
