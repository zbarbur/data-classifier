# @data-classifier/browser

Client-side scanner for detecting secrets and classifying code zones in text.
Scans user-submitted text (e.g. a prompt about to be sent to a chat AI)
and returns secret findings, zone blocks (code/markup/config), and a redacted version.

Both detection engines run in Rust/WASM in a Web Worker pool:

- **Secret scanner** — Rust/WASM (`data_classifier_core`), 122 regex + 283 key-name patterns, 24 validators (zero stubs)
- **Zone detector** — Rust/WASM (`data_classifier_core`), lazy-loaded on first use

## Quick start

```js
import { createScanner } from '@data-classifier/browser';

const scanner = createScanner();

// Both engines run by default
const { findings, zones, redactedText } = await scanner.scan(text);

// Secrets only (WASM never loads)
const { findings } = await scanner.scan(text, { zones: false });

// Zones only (JS scanner skipped)
const { zones } = await scanner.scan(text, { secrets: false });
```

### Result shape

```js
{
  findings: [
    { entity_type: 'API_KEY', display_name: 'GitHub Token', confidence: 0.99,
      engine: 'regex', match: { valueMasked: 'g]****a', start: 42, end: 82 } }
  ],
  zones: {
    total_lines: 15,
    blocks: [
      { start_line: 3, end_line: 12, zone_type: 'code', confidence: 0.95,
        language_hint: 'python', language_confidence: 0.85 }
    ]
  },
  redactedText: '...export GITHUB_TOKEN=[REDACTED:API_KEY]...',
  scannedMs: 1.2
}
```

## Chrome extension integration

```js
import { createScanner } from '@data-classifier/browser';

const scanner = createScanner({
  spawn: () => new Worker(
    chrome.runtime.getURL('worker.esm.js'),
    { type: 'module' }
  ),
});

const { findings, zones, redactedText } = await scanner.scan(promptText);
```

**Static assets to copy:** `dist/worker.esm.js`, `dist/data_classifier_core_bg.wasm`, `dist/unified_patterns.json`

**Webpack:** Use `copy-webpack-plugin` to copy all three files to your output directory.

**Vite:** Copy the files in a `buildEnd` plugin hook.

### MV3 lifecycle

```js
chrome.runtime.onSuspend.addListener(() => {
  scanner.onServiceWorkerSuspend();
  // WASM state is discarded; next scan re-initializes (~15-25ms)
});
```

## Scan options

```js
scanner.scan(text, {
  secrets: true,                          // run secret detection (default: true)
  zones: true,                            // run zone detection (default: true)
  timeoutMs: 5000,                        // worker kill budget (ms). 5s when zones enabled, 100ms otherwise
  failMode: 'open',                       // 'open' = empty on timeout, 'closed' = reject
  redactStrategy: 'type-label',           // 'asterisk' | 'placeholder' | 'none'
  verbose: false,                         // attach details block per finding
  dangerouslyIncludeRawValues: false,     // see WARNING below
  categoryFilter: ['Credential'],         // Credential-only (default)
});
```

## Tester

Interactive tester page with real-world examples:

```bash
npm run serve
# open http://localhost:4173/tester/
```

The tester includes:
- **15 secret detection stories** from the WildChat corpus
- **13 real zone detection prompts** (code, config, markup, multi-block, pure prose)
- **8 synthetic zone showcase examples** (Python, JSON, HTML, SQL, bash, traceback, unfenced code)
- **Unified output view** with zone-colored line backgrounds and inline secret redaction

Select a category (Secrets / Zones real / Zones showcase) and pick an example.

## Raw-value escape hatch

`scan(text, { dangerouslyIncludeRawValues: true })` populates
`match.valueRaw` with the unmasked matched value.

**Never enable in production.** Use only for local fixture authoring
and diagnostics.

## Documentation

- [API reference](docs/api.md) — all methods, parameters, return types, zone types
- [Zone detection logic](docs/zone-detection.md) — 10-step pipeline, WASM runtime, quality metrics
- [Zone detection stories](docs/zone-stories.md) — annotated examples (real + synthetic)
- [Secret detection logic](docs/secret-scanner.md) — regex + secret-scanner passes
- [Secret detection stories](docs/stories.md) — 17 annotated examples from WildChat
- [Pattern reference](docs/patterns.md) — 158 credential patterns + 283 key-name entries

TypeScript declarations are at `scanner.d.ts`.

## Footprint

| Component | Raw | Gzipped | Notes |
|-----------|-----|---------|-------|
| scanner.esm.js | 1.5 KB | 0.7 KB | Public API entry point |
| worker.esm.js | ~2.2 KB | ~1 KB | WASM glue only (98% reduction from JS era) |
| data_classifier_core_bg.wasm | ~1.6 MB | ~500 KB | Zones + secrets (Rust/WASM); lazy-loaded on first use |
| unified_patterns.json | ~190 KB | ~30 KB | All detection patterns (secrets + zones), lazy-loaded |
| **Secrets only** | **~1.8 MB** | **~530 KB** | WASM includes both engines; patterns filtered at runtime |
| **Full (secrets + zones)** | **~1.8 MB** | **~530 KB** | Same binary — essentially unchanged from JS era gzipped |
