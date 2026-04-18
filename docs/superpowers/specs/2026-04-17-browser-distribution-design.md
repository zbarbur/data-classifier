# Browser Scanner — Distribution & Integration Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the browser scanner consumable by an existing Chrome extension via npm, ship reference documentation and curated real-world examples, and provide a standalone tester for evaluation — all within a tight footprint budget.

**Assumes:** The browser scanner scaffold (Tasks 0-16) is complete on `sprint14/browser-poc-secret`. The S2 spike on `research/prompt-analysis` has validated the approach (P99 0.70ms, 13.45 KB gzip projected, no re2-wasm needed).

---

## 1. Package shape

The npm package `@data-classifier/browser` ships these files:

```
dist/
  scanner.esm.js          (1.5 KB, 0.8 KB gz)   — main entry
  worker.esm.js           (77 KB, 11.7 KB gz)    — self-contained worker bundle
tester/
  index.html              (1.7 KB)                — interactive demo page
  tester.js               (0.9 KB)                — tester script
  corpus/
    stories.jsonl          (~30 KB)               — 12 curated real-world examples (XOR-encoded)
docs/
  patterns.md              — human-readable pattern reference
  secret-scanner.md        — how the secret detection logic works
  stories.md               — annotated walkthrough of the 12 stories
README.md                  — integration guide + API reference
```

**Projected total package size:** ~25-30 KB gzipped.

### 1.1 package.json fields

```json
{
  "name": "@data-classifier/browser",
  "version": "0.1.0",
  "private": false,
  "type": "module",
  "exports": {
    ".": "./dist/scanner.esm.js",
    "./worker": "./dist/worker.esm.js",
    "./tester": "./tester/index.html"
  },
  "files": [
    "dist/*.js",
    "tester/index.html",
    "tester/tester.js",
    "tester/corpus/stories.jsonl",
    "docs/*.md",
    "README.md"
  ]
}
```

- `exports["."]` — resolves `import { createScanner } from '@data-classifier/browser'`
- `exports["./worker"]` — explicit worker reference for bundler copy-plugin configs
- `exports["./tester"]` — consumer-facing demo page
- `files` — whitelist. Tests, generated source, seed corpus, bench corpus, sourcemaps are all excluded from the published tarball.
- Sourcemaps are NOT shipped. The extension can generate its own via bundler config if needed.

### 1.2 What's excluded from the npm package

- `src/` (source modules — consumers use the bundles)
- `src/generated/` (intermediate generated assets)
- `tests/` (unit + e2e tests)
- `tester/corpus/seed.jsonl` (differential test fixtures — dev-only)
- `tester/corpus/bench/` (benchmark corpus — dev-only)
- `scripts/` (generator, CI script)
- `*.map` (sourcemaps)
- `node_modules/`, `dist/*.map`, `.playwright/`

---

## 2. Extension integration

The consuming extension bundles its own JS (webpack/vite/rollup). Integration is two steps:

### 2.1 Install

```
npm install @data-classifier/browser
```

### 2.2 Extension bundler config

The extension's bundler resolves the main entry via `exports["."]`. The worker file must be copied as a separate static asset because bundlers cannot inline Web Workers.

**Webpack example:**
```js
// webpack.config.js
const CopyPlugin = require('copy-webpack-plugin');
module.exports = {
  plugins: [
    new CopyPlugin({
      patterns: [{
        from: 'node_modules/@data-classifier/browser/dist/worker.esm.js',
        to: 'worker.esm.js',
      }],
    }),
  ],
};
```

**Vite example:**
```js
// vite.config.js
import { copyFileSync } from 'fs';
export default {
  plugins: [{
    name: 'copy-scanner-worker',
    buildEnd() {
      copyFileSync(
        'node_modules/@data-classifier/browser/dist/worker.esm.js',
        'dist/worker.esm.js'
      );
    },
  }],
};
```

### 2.3 Extension code

The extension passes a custom `spawn` that creates the worker from the extension's copied file URL:

```js
// In the extension's offscreen document or content script
import { createScanner } from '@data-classifier/browser';

const scanner = createScanner({
  spawn: () => new Worker(
    chrome.runtime.getURL('worker.esm.js'),
    { type: 'module' }
  ),
});

// Scan a prompt before submission
const { findings, redactedText, scannedMs } = await scanner.scan(promptText);

if (findings.length > 0) {
  // Show warning UI, offer redacted version, etc.
}
```

The `spawn` injection decouples the scanner from any specific extension architecture (content script, offscreen document, service worker). The scanner doesn't know or care where the worker file lives.

### 2.4 MV3 lifecycle

When the extension's MV3 service worker is about to suspend:

```js
chrome.runtime.onSuspend.addListener(() => {
  scanner.onServiceWorkerSuspend();
});
```

This terminates all pool workers cleanly. Next `scan()` call lazily re-spawns them.

---

## 3. Standalone testing (no extension)

For consumers evaluating the library without integrating it into an extension:

### 3.1 Clone and serve

```
git clone <repo>
cd data_classifier/clients/browser
npm install
npm run serve    # generate + build + http-server on :4173
# open http://localhost:4173/tester/
```

### 3.2 npm package consumer

```
npm install @data-classifier/browser
npx serve node_modules/@data-classifier/browser
# open http://localhost:3000/tester/
```

### 3.3 Tester page features

The tester page provides:
- **Textarea** — paste any text
- **Scan button** — runs the scanner, shows findings JSON + redacted text
- **Strategy dropdown** — type-label / asterisk / placeholder / none
- **Verbose checkbox** — shows details block per finding
- **Stories dropdown** — 12 pre-loaded real-world examples from `corpus/stories.jsonl`. Consumer selects an example, textarea fills with the decoded prompt, clicks Scan to see the scanner in action.

Stories are XOR-encoded in the JSONL file (same `0x5A` key as the rest of the project). The tester page decodes them client-side before displaying. This prevents raw credentials from appearing in the source.

---

## 4. Build pipeline

### 4.1 Scripts

| Script | What it does |
|---|---|
| `npm run build` | esbuild: minified, no sourcemaps (distribution default) |
| `npm run build:dev` | esbuild: unminified, with sourcemaps (debugging) |
| `npm run serve` | generate + build + http-server on :4173 |
| `npm run dist` | generate + build + size report |

### 4.2 Size reporting

`npm run dist` prints a size table after building:

```
  dist/scanner.esm.js    1.5 KB  (0.8 KB gz)
  dist/worker.esm.js   77.0 KB (11.7 KB gz)
  ─────────────────────────────────────────
  total                78.5 KB (12.5 KB gz)
```

This is a **soft warning** — no hard fail on budget. The report is informational so developers notice when bundle size grows. Current target: keep worker under 20 KB gzipped.

### 4.3 Sourcemap control

- `build` (default): `minify: true`, `sourcemap: false` — what ships
- `build:dev`: `minify: false`, `sourcemap: true` — for debugging

Implementation: `esbuild.config.mjs` checks `process.argv.includes('--dev')`. The `build:dev` script passes `--dev`. Default build omits sourcemaps. Current config always emits sourcemaps (135 KB of maps) — the refactored config defaults to off.

---

## 5. Reference documentation

Three documentation files shipped with the package:

### 5.1 `docs/patterns.md` — Pattern reference

Human-readable catalog of all 77 patterns. For each pattern:
- Name, entity type, category, sensitivity
- What it detects (one-line description)
- Confidence level
- Validator (if any) and what it checks
- Whether it requires column context (excluded from browser)

Organized by category (Credential, PII, Financial, etc.) with Credential patterns first (since that's v1 scope).

### 5.2 `docs/secret-scanner.md` — Secret detection logic

How the secret-scanner pass works, written for a technical audience evaluating the library:
- KV parsing (JSON, env, code literals) with offset tracking
- Key-name scoring: 178 key patterns, three match types (substring, word_boundary, suffix), three tiers (definitive, strong, contextual)
- Tiered entropy gating: what each tier requires (definitive = key score only; strong = entropy OR diversity; contextual = entropy AND diversity)
- Placeholder suppression: the 21 regex patterns that filter template values
- Anti-indicator suppression: keywords like "example", "test" that kill findings
- Confidence calculation: `key_score * multiplier` or `key_score * entropy_score`
- How it differs from the Python column-level classifier (text-level vs column-level, no column hints)

### 5.3 `docs/stories.md` — Annotated real-world examples

Walkthrough of the 12 curated stories from the WildChat corpus (S2 spike). For each story:
- What the user was trying to do (one paragraph context)
- What the scanner found (entity type, engine, confidence, key name)
- Why it triggered (which tier, what entropy/diversity scores)
- The redacted output
- Why this matters (what would happen if this prompt was sent to an LLM)

The 12 stories:

| # | ID | Entity | Key | Context |
|---|---|---|---|---|
| 1 | `747c7ba7` | API_KEY | `client_secret` | Azure Computer Vision SDK — Python script with Azure credential |
| 2 | `5911e6c0` | API_KEY | `access_token` | Instagram Graph API — Japanese prompt with embedded token |
| 3 | `1b711217` | OPAQUE_SECRET | `password` | C# homework — database connection string with password |
| 4 | `818ab6da` | OPAQUE_SECRET | `bot_token` | Telegram bot — Russian prompt with hardcoded bot token |
| 5 | `9466e01f` | OPAQUE_SECRET | `password` | Instagram scraper — plaintext login password in Python |
| 6 | `3fcbabd0` | API_KEY | `session_key` | Crypto homework — RSA session key discussion (low confidence) |
| 7 | `dcc0cad8` | OPAQUE_SECRET | `token` | Instagram API — long-lived Facebook access token in Python |
| 8 | `35a2aa0b` | OPAQUE_SECRET | `Password` | C# appliance rental — capitalized Password in .NET code |
| 9 | `38500e17` | OPAQUE_SECRET | `password_field` | Selenium automation — Russian, login with captcha solver |
| 10 | `80214d31` | OPAQUE_SECRET | `token_address` | Solana airdrop — SPL token transfer script (low confidence) |
| 11 | `41dad1b2` | API_KEY | regex | Shopify PHP config — `shpat_` access token matched by regex |
| 12 | `024eb7f3` | OPAQUE_SECRET | `bot_token` | Telegram bot — raw token string `5828712341:AAG5HJ...` |

Prompts in `stories.md` are shown redacted (the scanner's own output). The raw XOR-encoded versions live in `stories.jsonl` for the tester page to decode interactively.

---

## 6. Stories corpus format

`tester/corpus/stories.jsonl` — one line per story:

```json
{
  "id": "story_01_azure_client_secret",
  "fingerprint": "747c7ba7865681e6",
  "title": "Azure Computer Vision SDK with hardcoded client_secret",
  "prompt_xor": "xor:<base64-encoded prompt>",
  "expected_findings": [
    {"entity_type": "API_KEY", "engine": "secret_scanner", "confidence": 0.9025}
  ],
  "annotation": "User pasted a full Python script that imports Azure SDK and initializes it with a real client_secret. The secret_scanner fires on the client_secret KV pair (definitive tier, 0.95 key score)."
}
```

The tester page decodes `prompt_xor` using the existing `decoder.js` (same XOR key `0x5A`), populates the textarea, and runs the scan. The `annotation` field is displayed alongside the findings.

---

## 7. Tester page enhancements

The current tester page (Task 12) has: textarea, scan button, strategy dropdown, verbose checkbox, findings JSON output, redacted text output.

### 7.1 Add stories dropdown

Add a `<select id="stories">` dropdown above the textarea. Options:
- `(paste your own text)` — default, textarea is empty
- 12 story entries loaded from `corpus/stories.jsonl`

When a story is selected:
1. Fetch and decode the XOR-encoded prompt
2. Fill the textarea
3. Show the annotation in a `<p>` below the dropdown
4. Auto-scan (or let the user click Scan)

### 7.2 Loading stories.jsonl

The tester page fetches `./corpus/stories.jsonl` on load. Since it's served via http-server (or the extension's web_accessible_resources), a simple `fetch()` works. If the file is missing (npm package consumer who didn't install the corpus), the dropdown is hidden and the page works normally with manual paste.

---

## 8. Future extensibility (non-scope, documented)

These are NOT part of this implementation but are architecturally supported:

- **New categories** (PII, Financial): flip `categoryFilter`, port validators incrementally
- **ML engine in-browser**: download ONNX model to IndexedDB on first use, load via `ort-web` in the worker. Scanner's pool + worker architecture handles the cold start.
- **re2-wasm backend**: swap `regex-backend.js` for an re2-wasm implementation behind the same `createBackend` interface. S2 confirmed this is unnecessary (140x headroom), but the seam exists.

---

## 9. Footprint summary

| Component | Raw | Gzipped | Shipped in npm? | In extension? |
|---|---|---|---|---|
| `scanner.esm.js` | 1.5 KB | 0.8 KB | Yes | Yes |
| `worker.esm.js` | 77 KB | 11.7 KB | Yes | Yes |
| Tester page | 2.6 KB | ~1 KB | Yes | No |
| Stories corpus | ~30 KB | ~5 KB | Yes | No |
| Documentation (3 .md) | ~20 KB | ~5 KB | Yes | No |
| README | 3.5 KB | ~1 KB | Yes | No |
| **npm package total** | **~135 KB** | **~25 KB** | | |
| **Extension footprint** | **78.5 KB** | **12.5 KB** | | |

The extension only bundles the two dist files. Everything else (tester, stories, docs) is for evaluation and reference.
