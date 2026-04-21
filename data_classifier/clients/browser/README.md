# @data-classifier/browser

Client-side secret detection engine, ported from the Python
`data_classifier` library. Scans user-submitted text (e.g. a prompt
about to be sent to a chat AI) and returns findings + a redacted
version.

**20 KB gzipped.** No runtime dependencies. ES module.

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
  categoryFilter: ['Credential'],       // Credential-only (default)
});
```

## Tester

Serve the package directory with a static file server and open `/tester/`:

```bash
npx http-server . -p 4173
# open http://localhost:4173/tester/
```

Do NOT use `npx serve` — it runs in SPA mode and breaks module imports.

The tester includes 15 real-world credential stories from the
WildChat corpus. Select one from the dropdown and click **Scan** to see
findings with highlighted secrets, redacted output, and detection
metadata (including `detection_type` and human-friendly `display_name`).

## Raw-value escape hatch

`scan(text, { dangerouslyIncludeRawValues: true })` populates
`match.valueRaw` with the unmasked matched value.

**Never enable in production.** Use only for local fixture authoring
and diagnostics.

## Documentation

- [API reference](docs/api.md) — all methods, parameters, return types, error handling
- [Pattern reference](docs/patterns.md) — 158 credential patterns + 283 key-name entries
- [Secret detection logic](docs/secret-scanner.md) — how the scanner works
- [Real-world stories](docs/stories.md) — 17 annotated examples from WildChat

TypeScript declarations are at `scanner.d.ts`.

## Footprint

| Component | Raw | Gzipped | In extension? |
|-----------|-----|---------|---------------|
| scanner.esm.js | 1.5 KB | 0.7 KB | Yes |
| worker.esm.js | 140 KB | 20 KB | Yes |
| **Extension total** | **142 KB** | **21 KB** | |
