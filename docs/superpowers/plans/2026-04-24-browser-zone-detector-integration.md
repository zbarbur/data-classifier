# Browser Zone Detector Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add WASM-powered zone detection to the `@data-classifier/browser` library so `scan()` returns both secret findings and zone blocks in a single call.

**Architecture:** The existing JS secret scanner stays unchanged. A new `zone-detector.js` module lazy-loads the Rust/WASM binary (`data_classifier_core`) on first zone-enabled scan, calls `init_detector()` once per worker lifetime, then `detect()` per prompt. The worker dispatches both engines and merges results. The `scan()` API gains `{ secrets, zones }` per-call options.

**Tech Stack:** JavaScript (ESM), Rust/WASM (`data_classifier_core` crate via `wasm-pack`), Vitest (unit), Playwright (e2e), esbuild (bundler)

---

## File Structure

| File | Responsibility |
|------|---------------|
| `src/zone-detector.js` | WASM loader: lazy fetch, `init_detector()`, `detectZones(text, promptId)` wrapper |
| `src/scanner-core.js` | **Modified** — add zone detection pass, merge zones into result |
| `src/scanner.js` | **Modified** — accept `{ secrets, zones }` options, pass to worker |
| `src/worker.js` | **Modified** — import zone-detector, handle zone-enabled scans |
| `src/pool.js` | **Modified** — pass zones option through to worker, handle WASM timeout |
| `scanner.d.ts` | **Modified** — add `ZoneBlock`, `ZonesResult`, update `ScanOptions` and `ScanResult` |
| `assets/data_classifier_core_bg.wasm` | WASM binary (copied from `data_classifier_core/pkg/`) |
| `assets/zone_patterns.json` | Patterns config (copied from `v2/patterns/`) |
| `esbuild.config.mjs` | **Modified** — copy WASM + patterns assets to dist |
| `package.json` | **Modified** — add copy script, update exports |
| `tests/unit/zone-detector.test.js` | Unit tests: WASM lifecycle, options, error fallback |
| `tests/e2e/zone-stories.jsonl` | ~25 real WildChat zone detection stories with ground truth |
| `tests/e2e/zone-tester.spec.js` | Playwright tests for zone detection stories |
| `tests/e2e/bench.spec.js` | **Modified** — add three benchmark modes (secrets-only, zones-only, combined) |
| `tester/corpus/zone-showcase.jsonl` | ~8-10 synthetic showcase examples |
| `tester/index.html` | **Modified** — add zone results panel |
| `tester/tester.js` | **Modified** — render zone blocks, add zone stories |

---

### Task 1: Copy WASM Assets and Wire Build

**Files:**
- Create: `data_classifier/clients/browser/assets/data_classifier_core_bg.wasm`
- Create: `data_classifier/clients/browser/assets/zone_patterns.json`
- Modify: `data_classifier/clients/browser/esbuild.config.mjs`
- Modify: `data_classifier/clients/browser/package.json`

- [ ] **Step 1: Create assets directory and copy WASM binary**

```bash
cd data_classifier/clients/browser
mkdir -p assets
cp ../../../data_classifier_core/pkg/data_classifier_core_bg.wasm assets/
cp ../../../docs/experiments/prompt_analysis/s4_zone_detection/v2/patterns/zone_patterns.json assets/
```

Verify files exist:
```bash
ls -la assets/
# Expected: data_classifier_core_bg.wasm (~1.4MB), zone_patterns.json (~14KB)
```

- [ ] **Step 2: Add asset copy to esbuild config**

In `esbuild.config.mjs`, add an `fs.copyFileSync` step after the build to copy assets into `dist/`:

```javascript
import esbuild from 'esbuild';
import { copyFileSync, mkdirSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const watch = process.argv.includes('--watch');
const dev = process.argv.includes('--dev');

const shared = {
  bundle: true,
  format: 'esm',
  target: ['es2022'],
  minify: !watch && !dev,
  sourcemap: dev,
  logLevel: 'info',
};

const builds = [
  {
    ...shared,
    entryPoints: ['src/scanner.js'],
    outfile: 'dist/scanner.esm.js',
  },
  {
    ...shared,
    entryPoints: ['src/worker.js'],
    outfile: 'dist/worker.esm.js',
  },
];

function copyAssets() {
  mkdirSync(resolve(__dirname, 'dist'), { recursive: true });
  copyFileSync(
    resolve(__dirname, 'assets/data_classifier_core_bg.wasm'),
    resolve(__dirname, 'dist/data_classifier_core_bg.wasm'),
  );
  copyFileSync(
    resolve(__dirname, 'assets/zone_patterns.json'),
    resolve(__dirname, 'dist/zone_patterns.json'),
  );
}

if (watch) {
  const ctxs = await Promise.all(builds.map((b) => esbuild.context(b)));
  await Promise.all(ctxs.map((c) => c.watch()));
  copyAssets();
  console.log('esbuild: watching...');
} else {
  await Promise.all(builds.map((b) => esbuild.build(b)));
  copyAssets();
  console.log('esbuild: done');
}
```

- [ ] **Step 3: Update package.json exports and files**

In `package.json`, add the WASM and patterns to `files` and `exports`:

```json
{
  "files": [
    "dist/*.js",
    "dist/*.wasm",
    "dist/*.json",
    "scanner.d.ts",
    "tester/index.html",
    "tester/tester.js",
    "tester/corpus/stories.jsonl",
    "docs/*.md",
    "README.md"
  ],
  "exports": {
    ".": {
      "types": "./scanner.d.ts",
      "default": "./dist/scanner.esm.js"
    },
    "./worker": "./dist/worker.esm.js",
    "./wasm": "./dist/data_classifier_core_bg.wasm",
    "./zone-patterns": "./dist/zone_patterns.json",
    "./tester": "./tester/index.html"
  }
}
```

- [ ] **Step 4: Verify build copies assets**

```bash
cd data_classifier/clients/browser
npm run build
ls -la dist/
# Expected: scanner.esm.js, worker.esm.js, data_classifier_core_bg.wasm, zone_patterns.json
```

- [ ] **Step 5: Commit**

```bash
git add assets/ esbuild.config.mjs package.json
git commit -m "feat(browser): copy WASM + zone_patterns assets to dist"
```

---

### Task 2: Create zone-detector.js WASM Wrapper

**Files:**
- Create: `data_classifier/clients/browser/src/zone-detector.js`

This module is a thin loader. It lazy-loads the WASM binary and `zone_patterns.json`, initializes the detector once, then exposes a `detectZones(text, promptId)` function. It must work inside a Web Worker context (no DOM access).

- [ ] **Step 1: Write zone-detector.js**

```javascript
// Zone detector — WASM loader and wrapper.
// Lazy-loads data_classifier_core WASM + zone_patterns.json on first use.
// Init-once pattern: init_detector() compiles ~100 regex (~15-25ms),
// then detect() runs per-prompt (~0.5ms).

let wasmModule = null;
let detectorReady = false;
let initPromise = null;

/**
 * Lazy-initialize the WASM zone detector.
 * Fetches WASM binary + zone_patterns.json, compiles patterns once.
 * Resolves to true on success, false on failure.
 *
 * @param {string} [wasmUrl] - URL to WASM binary. Defaults to sibling path.
 * @param {string} [patternsUrl] - URL to zone_patterns.json. Defaults to sibling path.
 * @returns {Promise<boolean>}
 */
export function initZoneDetector(wasmUrl, patternsUrl) {
  if (detectorReady) return Promise.resolve(true);
  if (initPromise) return initPromise;

  initPromise = (async () => {
    try {
      // Resolve URLs relative to this module (works in worker context)
      const baseUrl = wasmUrl
        ? undefined
        : new URL('./', import.meta.url).href;
      const wUrl = wasmUrl || `${baseUrl}data_classifier_core_bg.wasm`;
      const pUrl = patternsUrl || `${baseUrl}zone_patterns.json`;

      // Fetch WASM module and patterns in parallel
      const [wasmResp, patternsResp] = await Promise.all([
        fetch(wUrl),
        fetch(pUrl),
      ]);

      if (!wasmResp.ok) throw new Error(`WASM fetch failed: ${wasmResp.status}`);
      if (!patternsResp.ok) throw new Error(`Patterns fetch failed: ${patternsResp.status}`);

      const patternsJson = await patternsResp.text();

      // Compile WASM
      const wasmBytes = await wasmResp.arrayBuffer();
      const imports = buildWasmImports();
      const { instance, module: mod } = await WebAssembly.instantiate(wasmBytes, imports);
      wasmModule = instance.exports;

      // Initialize externref table (required by wasm-bindgen)
      if (wasmModule.__wbindgen_start) {
        wasmModule.__wbindgen_start();
      }
      if (wasmModule.__wbindgen_externrefs) {
        const table = wasmModule.__wbindgen_externrefs;
        const offset = table.grow(4);
        table.set(0, undefined);
        table.set(offset + 0, undefined);
        table.set(offset + 1, null);
        table.set(offset + 2, true);
        table.set(offset + 3, false);
      }

      // Compile zone patterns (~100 regex, ~15-25ms)
      const ok = callInitDetector(patternsJson);
      if (!ok) throw new Error('init_detector returned false');

      detectorReady = true;
      return true;
    } catch (err) {
      console.warn('[zone-detector] init failed:', err.message || err);
      initPromise = null; // Allow retry
      return false;
    }
  })();

  return initPromise;
}

/**
 * Detect zones in text. Returns parsed zone result or null if detector not ready.
 *
 * @param {string} text
 * @param {string} promptId
 * @returns {{ total_lines: number, blocks: Array<{ start_line: number, end_line: number, zone_type: string, confidence: number, language_hint: string, language_confidence: number }> } | null}
 */
export function detectZones(text, promptId) {
  if (!detectorReady || !wasmModule) return null;

  try {
    const resultJson = callDetect(text, promptId);
    return JSON.parse(resultJson);
  } catch (err) {
    console.warn('[zone-detector] detect failed:', err.message || err);
    return null;
  }
}

/**
 * Reset detector state. Call on MV3 service worker suspend.
 * Next detectZones() call will re-initialize.
 */
export function resetZoneDetector() {
  wasmModule = null;
  detectorReady = false;
  initPromise = null;
}

/**
 * Whether the zone detector is initialized and ready.
 * @returns {boolean}
 */
export function isZoneDetectorReady() {
  return detectorReady;
}

// ── WASM FFI helpers (mirrors wasm-bindgen glue) ──────────────────

const textEncoder = new TextEncoder();
const textDecoder = new TextDecoder('utf-8', { ignoreBOM: true, fatal: true });

function getMemory() {
  return new Uint8Array(wasmModule.memory.buffer);
}

function passString(str) {
  const encoded = textEncoder.encode(str);
  const ptr = wasmModule.__wbindgen_malloc(encoded.length, 1) >>> 0;
  getMemory().set(encoded, ptr);
  return [ptr, encoded.length];
}

function getString(ptr, len) {
  return textDecoder.decode(getMemory().subarray(ptr >>> 0, (ptr + len) >>> 0));
}

function callInitDetector(patternsJson) {
  const [ptr, len] = passString(patternsJson);
  return wasmModule.init_detector(ptr, len) !== 0;
}

function callDetect(text, promptId) {
  const [ptr0, len0] = passString(text);
  const [ptr1, len1] = passString(promptId);
  const ret = wasmModule.detect(ptr0, len0, ptr1, len1);
  // wasm-bindgen returns [ptr, len] as a two-element array-like
  const rPtr = ret[0];
  const rLen = ret[1];
  try {
    return getString(rPtr, rLen);
  } finally {
    wasmModule.__wbindgen_free(rPtr, rLen, 1);
  }
}

function buildWasmImports() {
  return {
    __proto__: null,
    './data_classifier_core_bg.js': {
      __proto__: null,
      __wbindgen_init_externref_table: function () {
        // Handled after instantiation
      },
    },
  };
}
```

- [ ] **Step 2: Verify module syntax**

```bash
cd data_classifier/clients/browser
node -e "import('./src/zone-detector.js').then(m => console.log('exports:', Object.keys(m)))"
# Expected: exports: [ 'initZoneDetector', 'detectZones', 'resetZoneDetector', 'isZoneDetectorReady' ]
```

- [ ] **Step 3: Commit**

```bash
git add src/zone-detector.js
git commit -m "feat(browser): add zone-detector.js WASM wrapper"
```

---

### Task 3: Update TypeScript Definitions

**Files:**
- Modify: `data_classifier/clients/browser/scanner.d.ts`

- [ ] **Step 1: Add zone types and update ScanOptions/ScanResult**

Add these types after the existing `FindingDetails` interface (before `Finding`):

```typescript
/** A detected zone block (code, markup, config, etc.). */
export interface ZoneBlock {
  /** Start line (0-indexed, inclusive). */
  start_line: number;

  /** End line (0-indexed, exclusive). */
  end_line: number;

  /** Zone classification. */
  zone_type: 'code' | 'markup' | 'config' | 'query' | 'cli_shell' | 'data' | 'error_output' | 'natural_language';

  /** Detection confidence, 0–1. */
  confidence: number;

  /** Detected programming language (e.g., "python", "javascript"). Empty string if unknown. */
  language_hint: string;

  /** Language detection confidence, 0–1. */
  language_confidence: number;
}

/** Zone detection result. */
export interface ZonesResult {
  /** Total lines in the input text. */
  total_lines: number;

  /** Detected zone blocks. */
  blocks: ZoneBlock[];
}
```

Update the `ScanOptions` interface — add after `categoryFilter`:

```typescript
  /**
   * Run the secret detection engine (regex + secret_scanner + opaque_token).
   * @default true
   */
  secrets?: boolean;

  /**
   * Run the zone detection engine (code/markup/config identification via WASM).
   * When true, the WASM module is lazy-loaded on first use (~15-25ms init).
   * @default true
   */
  zones?: boolean;
```

Update the `ScanResult` interface — add after `allFindings`:

```typescript
  /**
   * Zone detection result. Contains detected code/markup/config blocks.
   * `null` when `zones: false` was passed to `scan()`.
   */
  zones: ZonesResult | null;
```

Update the `Scanner.scan()` return type doc to mention zones.

- [ ] **Step 2: Commit**

```bash
git add scanner.d.ts
git commit -m "feat(browser): add ZoneBlock/ZonesResult types to scanner.d.ts"
```

---

### Task 4: Wire Zone Detection into scanner-core.js

**Files:**
- Modify: `data_classifier/clients/browser/src/scanner-core.js`

- [ ] **Step 1: Import zone detector and add to scanText**

At the top of `scanner-core.js`, add the import:

```javascript
import { initZoneDetector, detectZones, isZoneDetectorReady } from './zone-detector.js';
```

Replace the `scanText` function with this updated version that handles the `secrets` and `zones` options:

```javascript
export async function initZones(wasmUrl, patternsUrl) {
  return initZoneDetector(wasmUrl, patternsUrl);
}

export function scanText(text, opts = {}) {
  const t0 = performanceNowSafe();
  const verbose = !!opts.verbose;
  const includeRaw = !!opts.dangerouslyIncludeRawValues;
  const categoryFilter = opts.categoryFilter || ['Credential'];
  const redactStrategy = opts.redactStrategy || 'type-label';
  const runSecrets = opts.secrets !== false;
  const runZones = opts.zones !== false;

  // Secret detection (existing JS passes)
  let findings = [];
  if (runSecrets) {
    const raw = [];
    raw.push(...regexPass(text, categoryFilter, verbose, includeRaw));
    raw.push(...secretScannerPass(text, verbose, includeRaw));
    raw.push(...opaqueTokenPass(text, verbose, includeRaw));
    findings = dedup(raw);
    if (verbose) {
      var allFindings = raw;
    }
  }

  const redactedText = runSecrets ? redact(text, findings, redactStrategy) : text;

  // Zone detection (WASM)
  let zones = null;
  if (runZones && isZoneDetectorReady()) {
    zones = detectZones(text, opts._promptId || '');
  }

  const result = { findings, redactedText, scannedMs: performanceNowSafe() - t0, zones };
  if (verbose && allFindings) result.allFindings = allFindings;
  return result;
}
```

Note: `scanText` remains synchronous. The WASM init is async and happens in the worker's message handler (Task 5). By the time `scanText` runs, the detector is either ready or not.

- [ ] **Step 2: Verify unit tests still pass**

```bash
cd data_classifier/clients/browser
npm run test:unit
# Expected: all existing tests pass. zones field will be null (detector not initialized in unit tests).
```

- [ ] **Step 3: Commit**

```bash
git add src/scanner-core.js
git commit -m "feat(browser): add zone detection pass to scanText"
```

---

### Task 5: Update worker.js for WASM Lifecycle

**Files:**
- Modify: `data_classifier/clients/browser/src/worker.js`

The worker must lazy-init the WASM detector on the first scan that has `zones !== false`. Subsequent scans reuse the initialized detector.

- [ ] **Step 1: Update worker.js**

```javascript
// Worker shim. Receives {id, text, opts} and posts {id, result} or {id, error}.
// Zone detection: WASM is lazy-loaded on first zone-enabled scan.

import { scanText, initZones } from './scanner-core.js';

let zonesInitialized = false;
let zonesInitializing = false;

self.addEventListener('message', async (event) => {
  const { id, text, opts } = event.data || {};
  try {
    const runZones = (opts && opts.zones) !== false;

    // Lazy-init WASM on first zone-enabled scan
    if (runZones && !zonesInitialized && !zonesInitializing) {
      zonesInitializing = true;
      zonesInitialized = await initZones();
      zonesInitializing = false;
    }

    const result = scanText(text, opts);
    self.postMessage({ id, result });
  } catch (err) {
    self.postMessage({ id, error: { message: String((err && err.message) || 'scan failed') } });
  }
});
```

- [ ] **Step 2: Commit**

```bash
git add src/worker.js
git commit -m "feat(browser): lazy-init WASM zone detector in worker"
```

---

### Task 6: Update scanner.js and pool.js for Options Passthrough

**Files:**
- Modify: `data_classifier/clients/browser/src/scanner.js`
- Modify: `data_classifier/clients/browser/src/pool.js`

- [ ] **Step 1: Update scanner.js**

The `scan()` function needs a higher default timeout when zones are enabled (WASM init can take 15-25ms on first call, and the detection itself ~0.5ms):

```javascript
// Public API. Example:
//   import { createScanner } from '@data-classifier/browser';
//   const scanner = createScanner();
//   const { findings, zones, redactedText } = await scanner.scan(text);

import { createPool } from './pool.js';

function defaultSpawn() {
  return new Worker(new URL('./worker.esm.js', import.meta.url), { type: 'module' });
}

export function createScanner(opts = {}) {
  const pool = createPool({
    size: opts.poolSize || 2,
    spawn: opts.spawn || defaultSpawn,
  });

  async function scan(text, scanOpts = {}) {
    // Higher timeout on first zone-enabled scan (WASM init ~20ms + detect ~0.5ms)
    const defaultTimeout = scanOpts.zones !== false ? 5000 : 100;
    return pool.run({
      text,
      opts: scanOpts,
      timeoutMs: scanOpts.timeoutMs || defaultTimeout,
      failMode: scanOpts.failMode || 'open',
    });
  }

  return { scan, onServiceWorkerSuspend: pool.onServiceWorkerSuspend };
}
```

- [ ] **Step 2: Update pool.js timeout fallback**

In `pool.js`, update the fail-open timeout response to include `zones: null`:

In the `dispatch` function, change the timeout resolution from:

```javascript
else resolve({ findings: [], redactedText: text, scannedMs: timeoutMs });
```

to:

```javascript
else resolve({ findings: [], redactedText: text, scannedMs: timeoutMs, zones: null });
```

- [ ] **Step 3: Commit**

```bash
git add src/scanner.js src/pool.js
git commit -m "feat(browser): pass secrets/zones options through scanner → pool → worker"
```

---

### Task 7: Unit Tests for zone-detector.js

**Files:**
- Create: `data_classifier/clients/browser/tests/unit/zone-detector.test.js`

These tests verify the module's behavior without actually loading WASM (mock the fetch/WASM APIs).

- [ ] **Step 1: Write unit tests**

```javascript
import { describe, it, expect, vi, beforeEach } from 'vitest';

// We test the module's export shape and option-gating logic.
// Full WASM integration is tested in e2e (Playwright).

describe('zone-detector exports', () => {
  it('exports the expected functions', async () => {
    const mod = await import('../../src/zone-detector.js');
    expect(typeof mod.initZoneDetector).toBe('function');
    expect(typeof mod.detectZones).toBe('function');
    expect(typeof mod.resetZoneDetector).toBe('function');
    expect(typeof mod.isZoneDetectorReady).toBe('function');
  });

  it('isZoneDetectorReady returns false before init', async () => {
    // Fresh import to get clean state
    const mod = await import('../../src/zone-detector.js');
    mod.resetZoneDetector();
    expect(mod.isZoneDetectorReady()).toBe(false);
  });

  it('detectZones returns null when not initialized', async () => {
    const mod = await import('../../src/zone-detector.js');
    mod.resetZoneDetector();
    const result = mod.detectZones('hello world', 'test-1');
    expect(result).toBeNull();
  });
});

describe('scanText zones option', () => {
  it('zones is null when zones option is false', async () => {
    const { scanText } = await import('../../src/scanner-core.js');
    const result = scanText('hello world', { zones: false });
    expect(result.zones).toBeNull();
  });

  it('zones is null when detector not initialized (default)', async () => {
    const { scanText } = await import('../../src/scanner-core.js');
    const result = scanText('hello world');
    // Zone detector not initialized in unit test environment → null
    expect(result.zones).toBeNull();
  });

  it('findings is empty array when secrets is false', async () => {
    const { scanText } = await import('../../src/scanner-core.js');
    const result = scanText('export API_KEY=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', { secrets: false });
    expect(result.findings).toEqual([]);
  });

  it('result always has zones key', async () => {
    const { scanText } = await import('../../src/scanner-core.js');
    const result = scanText('hello', {});
    expect('zones' in result).toBe(true);
  });
});
```

- [ ] **Step 2: Run unit tests**

```bash
cd data_classifier/clients/browser
npm run test:unit
# Expected: all tests pass (existing + new zone-detector tests)
```

- [ ] **Step 3: Commit**

```bash
git add tests/unit/zone-detector.test.js
git commit -m "test(browser): add unit tests for zone-detector options and lifecycle"
```

---

### Task 8: Curate Zone Detection Stories (Real Corpus)

**Files:**
- Create: `data_classifier/clients/browser/tests/e2e/zone-stories.jsonl`

Pull ~25 representative prompts from the 647-record labeled WildChat corpus. Each story has a human-readable description, the prompt text (XOR-encoded), and expected zone blocks with tolerance.

- [ ] **Step 1: Write story curation script**

Create a one-shot Python script that selects prompts from the labeled corpus, runs the Rust detector to get ground truth, and outputs JSONL. Run from repo root:

```bash
cd /Users/guyguzner/Projects/data_classifier-prompt-analysis
.venv/bin/python -c "
import json, base64, sys

LABELED = 'docs/experiments/prompt_analysis/s4_zone_detection/labeled_data/s4_labeled_corpus.jsonl'
CORPUS = 'data_classifier_core/bench/corpus_subset.json'
XOR_KEY = 0x5a

def xor_encode(text):
    raw = text.encode('utf-8')
    xored = bytes(b ^ XOR_KEY for b in raw)
    return 'xor:' + base64.b64encode(xored).decode('ascii')

# Load labeled corpus (has review.actual_blocks ground truth)
labeled = {}
with open(LABELED) as f:
    for line in f:
        d = json.loads(line)
        if d.get('review', {}).get('correct') is not None:
            labeled[d['prompt_id']] = d

# Load full corpus texts
corpus = {}
with open(CORPUS) as f:
    for item in json.load(f):
        corpus[item['prompt_id']] = item['text']

# Select prompts by category
selections = {
    'fenced_tagged': [],        # ```python, ```json, etc.
    'fenced_untagged': [],      # ``` with code interior
    'unfenced_code': [],        # code in prose without fences
    'config': [],               # JSON/YAML/ENV
    'markup': [],               # XML/HTML
    'error_output': [],         # stack traces, logs
    'pure_prose': [],           # no zones
    'edge_cases': [],           # tricky cases
}

for pid, entry in labeled.items():
    text = corpus.get(pid, '')
    if not text:
        continue
    review = entry.get('review', {})
    blocks = review.get('actual_blocks', [])
    hblocks = entry.get('heuristic_blocks', [])

    has_fence = any('fence' in str(hb.get('method', '')) for hb in hblocks)
    zone_types = set(b.get('zone_type', '') for b in blocks)

    if not blocks and review.get('correct') == True:
        if len(selections['pure_prose']) < 3:
            selections['pure_prose'].append(pid)
    elif has_fence and any(hb.get('language_hint', '') for hb in hblocks):
        if len(selections['fenced_tagged']) < 4:
            selections['fenced_tagged'].append(pid)
    elif has_fence:
        if len(selections['fenced_untagged']) < 2:
            selections['fenced_untagged'].append(pid)
    elif 'config' in zone_types:
        if len(selections['config']) < 3:
            selections['config'].append(pid)
    elif 'markup' in zone_types:
        if len(selections['markup']) < 2:
            selections['markup'].append(pid)
    elif 'error_output' in zone_types:
        if len(selections['error_output']) < 2:
            selections['error_output'].append(pid)
    elif 'code' in zone_types and not has_fence:
        if len(selections['unfenced_code']) < 4:
            selections['unfenced_code'].append(pid)
    elif len(selections['edge_cases']) < 5:
        selections['edge_cases'].append(pid)

# Flatten and output
all_ids = []
for category, ids in selections.items():
    all_ids.extend([(pid, category) for pid in ids])

stories = []
for pid, category in all_ids:
    text = corpus[pid]
    entry = labeled[pid]
    review = entry.get('review', {})
    blocks = review.get('actual_blocks', [])

    story = {
        'id': f'zone_{category}_{pid[:8]}',
        'prompt_id': pid,
        'category': category,
        'title': f'{category}: {pid[:8]}',
        'description': review.get('notes', f'{category} zone detection'),
        'text_xor': xor_encode(text),
        'expected_zones': blocks,
        'tolerance_lines': 2,
    }
    stories.append(story)

print(f'Selected {len(stories)} stories across {len(selections)} categories', file=sys.stderr)
for cat, ids in selections.items():
    print(f'  {cat}: {len(ids)}', file=sys.stderr)

for story in stories:
    print(json.dumps(story))
"  > data_classifier/clients/browser/tests/e2e/zone-stories.jsonl
```

- [ ] **Step 2: Verify story count and structure**

```bash
wc -l data_classifier/clients/browser/tests/e2e/zone-stories.jsonl
# Expected: ~25 lines

head -1 data_classifier/clients/browser/tests/e2e/zone-stories.jsonl | python3 -c "
import sys, json
d = json.loads(sys.stdin.readline())
print(f'Keys: {sorted(d.keys())}')
print(f'Category: {d[\"category\"]}')
print(f'Expected zones: {len(d[\"expected_zones\"])} blocks')
"
```

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/zone-stories.jsonl
git commit -m "test(browser): curate ~25 WildChat zone detection stories"
```

---

### Task 9: Create Synthetic Zone Showcase Examples

**Files:**
- Create: `data_classifier/clients/browser/tester/corpus/zone-showcase.jsonl`

Short, clean synthetic examples (10-30 lines each) that demonstrate each zone type clearly. Used for the tester page dropdown and documentation.

- [ ] **Step 1: Write zone-showcase.jsonl**

Each entry is XOR-encoded like the secret stories. Create 8 examples:

```bash
cd /Users/guyguzner/Projects/data_classifier-prompt-analysis
.venv/bin/python -c "
import json, base64

XOR_KEY = 0x5a

def xor_encode(text):
    raw = text.encode('utf-8')
    xored = bytes(b ^ XOR_KEY for b in raw)
    return 'xor:' + base64.b64encode(xored).decode('ascii')

examples = [
    {
        'id': 'zone_showcase_python_fenced',
        'title': 'Fenced Python code block',
        'text': '''Write a function that sorts a list of dictionaries by a given key.

\`\`\`python
def sort_by_key(items, key):
    return sorted(items, key=lambda x: x[key])

# Example usage
data = [{\"name\": \"Alice\", \"age\": 30}, {\"name\": \"Bob\", \"age\": 25}]
result = sort_by_key(data, \"age\")
print(result)
\`\`\`

Can you add error handling for missing keys?''',
        'expected_zones': [{'zone_type': 'code', 'start_line': 2, 'end_line': 11}],
        'annotation': 'Tagged fenced block (```python) — high confidence structural detection.',
    },
    {
        'id': 'zone_showcase_json_config',
        'title': 'JSON configuration block',
        'text': '''Here is my webpack config that is not working:

{
  \"mode\": \"production\",
  \"entry\": \"./src/index.js\",
  \"output\": {
    \"filename\": \"bundle.js\",
    \"path\": \"/dist\"
  },
  \"module\": {
    \"rules\": [
      { \"test\": \"\\\\.css$\", \"use\": [\"style-loader\", \"css-loader\"] }
    ]
  }
}

The CSS imports are not being processed. What am I missing?''',
        'expected_zones': [{'zone_type': 'config', 'start_line': 2, 'end_line': 15}],
        'annotation': 'Unfenced JSON — detected by format detector (brace matching + key:value structure).',
    },
    {
        'id': 'zone_showcase_html_markup',
        'title': 'HTML with embedded script',
        'text': '''Fix the alignment issue in this HTML page:

<html>
<head>
  <style>
    .container { display: flex; gap: 16px; }
    .sidebar { width: 200px; }
  </style>
</head>
<body>
  <div class=\"container\">
    <div class=\"sidebar\">Nav</div>
    <main>Content</main>
  </div>
  <script>
    document.querySelector(\".sidebar\").addEventListener(\"click\", () => {
      console.log(\"sidebar clicked\");
    });
  </script>
</body>
</html>

The sidebar should be fixed position.''',
        'expected_zones': [{'zone_type': 'markup', 'start_line': 2, 'end_line': 21}],
        'annotation': 'HTML with embedded <style> and <script> — structural delimiter detection.',
    },
    {
        'id': 'zone_showcase_sql_query',
        'title': 'SQL query in fenced block',
        'text': '''I need to optimize this query, it takes 30 seconds on 10M rows:

\`\`\`sql
SELECT u.name, COUNT(o.id) AS order_count, SUM(o.total) AS revenue
FROM users u
LEFT JOIN orders o ON u.id = o.user_id
WHERE o.created_at >= '2024-01-01'
GROUP BY u.name
HAVING COUNT(o.id) > 5
ORDER BY revenue DESC
LIMIT 100;
\`\`\`

Should I add an index on orders.created_at?''',
        'expected_zones': [{'zone_type': 'query', 'start_line': 2, 'end_line': 12}],
        'annotation': 'Tagged fenced block (```sql) — mapped to query zone type via lang_tag_map.',
    },
    {
        'id': 'zone_showcase_bash_cli',
        'title': 'Bash commands in fenced block',
        'text': '''How do I deploy this to production? Here are my current steps:

\`\`\`bash
docker build -t myapp:latest .
docker tag myapp:latest registry.example.com/myapp:v2.1
docker push registry.example.com/myapp:v2.1
kubectl set image deployment/myapp myapp=registry.example.com/myapp:v2.1
kubectl rollout status deployment/myapp
\`\`\`

Is there a way to do zero-downtime deployment?''',
        'expected_zones': [{'zone_type': 'cli_shell', 'start_line': 2, 'end_line': 9}],
        'annotation': 'Tagged fenced block (```bash) — mapped to cli_shell zone type.',
    },
    {
        'id': 'zone_showcase_error_output',
        'title': 'Python stack trace',
        'text': '''My app crashes with this error:

Traceback (most recent call last):
  File \"/app/main.py\", line 42, in handle_request
    result = process_data(payload)
  File \"/app/processor.py\", line 18, in process_data
    return transform(data[\"items\"])
  File \"/app/transform.py\", line 7, in transform
    return [parse_item(i) for i in items]
TypeError: string indices must be integers, not 'str'

How do I fix this?''',
        'expected_zones': [{'zone_type': 'error_output', 'start_line': 2, 'end_line': 10}],
        'annotation': 'Python traceback — detected by negative filter as error_output (not code).',
    },
    {
        'id': 'zone_showcase_unfenced_code',
        'title': 'Unfenced code mixed with prose',
        'text': '''I have a React component that re-renders too often. The component looks like:

function UserList({ users }) {
  const [filter, setFilter] = useState(\"\");
  const filtered = users.filter(u => u.name.includes(filter));
  return (
    <div>
      <input onChange={e => setFilter(e.target.value)} />
      {filtered.map(u => <UserCard key={u.id} user={u} />)}
    </div>
  );
}

The issue is that UserCard re-renders even when user data hasn't changed. Should I use React.memo?''',
        'expected_zones': [{'zone_type': 'code', 'start_line': 2, 'end_line': 12}],
        'annotation': 'Unfenced code block — detected by syntax scoring (keywords, brackets, JSX).',
    },
    {
        'id': 'zone_showcase_pure_prose',
        'title': 'Pure prose (no code zones)',
        'text': '''Can you explain the difference between microservices and monolithic architecture?
I am building a new project and I am not sure which approach to take. The team has
five developers, and we expect moderate traffic initially but want to scale later.
We are using AWS for hosting. What factors should I consider when making this decision?''',
        'expected_zones': [],
        'annotation': 'Pure natural language — no zones should be detected.',
    },
]

for ex in examples:
    story = {
        'id': ex['id'],
        'title': ex['title'],
        'prompt_xor': xor_encode(ex['text']),
        'annotation': ex['annotation'],
        'expected_zones': ex['expected_zones'],
    }
    print(json.dumps(story))
" > data_classifier/clients/browser/tester/corpus/zone-showcase.jsonl
```

- [ ] **Step 2: Verify**

```bash
wc -l data_classifier/clients/browser/tester/corpus/zone-showcase.jsonl
# Expected: 8 lines

head -1 data_classifier/clients/browser/tester/corpus/zone-showcase.jsonl | python3 -c "
import sys, json
d = json.loads(sys.stdin.readline())
print(f'ID: {d[\"id\"]}, Title: {d[\"title\"]}')
"
```

- [ ] **Step 3: Commit**

```bash
git add tester/corpus/zone-showcase.jsonl
git commit -m "test(browser): add 8 synthetic zone showcase examples"
```

---

### Task 10: Playwright E2E Tests for Zone Detection

**Files:**
- Create: `data_classifier/clients/browser/tests/e2e/zone-tester.spec.js`

These tests load the browser library with WASM, scan prompts from the curated stories, and verify zone blocks match expected ground truth within tolerance.

- [ ] **Step 1: Write zone-tester.spec.js**

```javascript
import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const STORIES_PATH = resolve(__dirname, 'zone-stories.jsonl');
const XOR_KEY = 0x5a;

function decodeXor(encoded) {
  if (encoded.startsWith('xor:')) encoded = encoded.slice(4);
  const raw = Buffer.from(encoded, 'base64');
  const decoded = Buffer.alloc(raw.length);
  for (let i = 0; i < raw.length; i++) decoded[i] = raw[i] ^ XOR_KEY;
  return decoded.toString('utf-8');
}

const stories = readFileSync(STORIES_PATH, 'utf-8')
  .split('\n')
  .filter(Boolean)
  .map((l) => JSON.parse(l));

test.describe('zone detection stories', () => {
  test.setTimeout(60_000);

  for (const story of stories) {
    test(`${story.category}: ${story.id}`, async ({ page }) => {
      await page.goto('/tester/');

      const text = decodeXor(story.text_xor);

      const result = await page.evaluate(async (text) => {
        const { createScanner } = await import('../dist/scanner.esm.js');
        const scanner = createScanner();
        return scanner.scan(text, { secrets: false, zones: true });
      }, text);

      expect(result.zones).not.toBeNull();

      const actualBlocks = result.zones.blocks;
      const expectedBlocks = story.expected_zones;
      const tolerance = story.tolerance_lines || 2;

      // Verify block count matches (with some flexibility for edge cases)
      if (expectedBlocks.length === 0) {
        expect(actualBlocks.length).toBe(0);
        return;
      }

      // Each expected block should have a matching actual block
      for (const expected of expectedBlocks) {
        const match = actualBlocks.find(
          (b) =>
            b.zone_type === expected.zone_type &&
            Math.abs(b.start_line - expected.start_line) <= tolerance &&
            Math.abs(b.end_line - expected.end_line) <= tolerance,
        );
        expect(match, `Expected ${expected.zone_type} block near lines ${expected.start_line}-${expected.end_line}`).toBeTruthy();
      }
    });
  }
});
```

- [ ] **Step 2: Build and run zone tests**

```bash
cd data_classifier/clients/browser
npm run build
npx playwright test tests/e2e/zone-tester.spec.js
# Expected: all stories pass
```

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/zone-tester.spec.js
git commit -m "test(browser): add Playwright e2e tests for zone detection stories"
```

---

### Task 11: Performance Benchmarks (Three Modes)

**Files:**
- Modify: `data_classifier/clients/browser/tests/e2e/bench.spec.js`

Add three benchmark modes: secrets-only, zones-only, and combined. Each reports P50/P95/P99 latency plus WASM init time.

- [ ] **Step 1: Rewrite bench.spec.js with three modes**

```javascript
import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const CORPUS = resolve(__dirname, '../../tester/corpus/bench/prompts.jsonl');
const TARGET_SCANS = 1000;

function reportStats(name, latencies) {
  latencies.sort((a, b) => a - b);
  const mean = latencies.reduce((s, x) => s + x, 0) / latencies.length;
  const p50 = latencies[Math.floor(latencies.length * 0.5)];
  const p95 = latencies[Math.floor(latencies.length * 0.95)];
  const p99 = latencies[Math.floor(latencies.length * 0.99)];
  const max = latencies[latencies.length - 1];
  const summary = { mode: name, count: latencies.length, mean, p50, p95, p99, max };
  console.log(`\n=== ${name.toUpperCase()} ===`);
  console.log(JSON.stringify(summary, null, 2));
  console.log('===\n');
  return { mean, p50, p95, p99, max };
}

const prompts = readFileSync(CORPUS, 'utf-8')
  .split('\n')
  .filter(Boolean)
  .map((l) => JSON.parse(l).text);

test('benchmark: secrets-only (baseline JS throughput)', async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto('/tester/');

  const latencies = await page.evaluate(
    async ({ prompts, targetScans }) => {
      const { createScanner } = await import('../dist/scanner.esm.js');
      const scanner = createScanner();
      const out = [];
      for (let i = 0; i < targetScans; i++) {
        const text = prompts[i % prompts.length];
        const t0 = performance.now();
        await scanner.scan(text, { secrets: true, zones: false });
        out.push(performance.now() - t0);
      }
      return out;
    },
    { prompts, targetScans: TARGET_SCANS },
  );

  const stats = reportStats('secrets-only', latencies);
  expect(stats.p50).toBeLessThan(500);
});

test('benchmark: zones-only (WASM throughput)', async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto('/tester/');

  const result = await page.evaluate(
    async ({ prompts, targetScans }) => {
      const { createScanner } = await import('../dist/scanner.esm.js');
      const scanner = createScanner();

      // First scan: measures WASM init time
      const t0init = performance.now();
      await scanner.scan(prompts[0], { secrets: false, zones: true });
      const initMs = performance.now() - t0init;

      // Warm scans
      const out = [];
      for (let i = 0; i < targetScans; i++) {
        const text = prompts[i % prompts.length];
        const t0 = performance.now();
        await scanner.scan(text, { secrets: false, zones: true });
        out.push(performance.now() - t0);
      }
      return { latencies: out, initMs };
    },
    { prompts, targetScans: TARGET_SCANS },
  );

  console.log(`\nWASM init time (first call): ${result.initMs.toFixed(1)} ms\n`);
  const stats = reportStats('zones-only', result.latencies);
  expect(stats.p50).toBeLessThan(500);
});

test('benchmark: combined (secrets + zones)', async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto('/tester/');

  const latencies = await page.evaluate(
    async ({ prompts, targetScans }) => {
      const { createScanner } = await import('../dist/scanner.esm.js');
      const scanner = createScanner();

      // Warm up WASM
      await scanner.scan(prompts[0], { secrets: true, zones: true });

      const out = [];
      for (let i = 0; i < targetScans; i++) {
        const text = prompts[i % prompts.length];
        const t0 = performance.now();
        await scanner.scan(text, { secrets: true, zones: true });
        out.push(performance.now() - t0);
      }
      return out;
    },
    { prompts, targetScans: TARGET_SCANS },
  );

  const stats = reportStats('combined', latencies);
  expect(stats.p50).toBeLessThan(500);
});
```

- [ ] **Step 2: Run benchmarks**

```bash
cd data_classifier/clients/browser
npm run build
npx playwright test tests/e2e/bench.spec.js
# Expected: 3 benchmark tests pass, console output shows P50/P95/P99 for each mode
```

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/bench.spec.js
git commit -m "test(browser): add three-mode benchmark (secrets-only, zones-only, combined)"
```

---

### Task 12: Update Tester Page for Zone Results

**Files:**
- Modify: `data_classifier/clients/browser/tester/index.html`
- Modify: `data_classifier/clients/browser/tester/tester.js`

Add a zones result panel to the tester page: render zone blocks with colored line ranges, add zone showcase stories to the dropdown.

- [ ] **Step 1: Add zone results section to tester/index.html**

After the `<div id="results" ...>` section's text-panels div, add a zone results panel. Find the closing `</div>` of the text-panels and add before the raw-toggle button:

```html
    <!-- Zone Detection Results -->
    <div id="zone-results" style="display:none; margin-top: 16px;">
      <h3 style="margin: 0 0 8px 0; font-size: 14px; color: #333;">Zone Detection</h3>
      <div id="zone-summary" style="font-size: 13px; color: #666; margin-bottom: 8px;"></div>
      <div id="zone-blocks" style="font-family: ui-monospace, 'SF Mono', Monaco, monospace; font-size: 13px;"></div>
    </div>
```

Add a checkbox for enabling/disabling zone detection in the controls row, after the strategy dropdown:

```html
    <label style="margin-left: 12px; font-size: 13px;">
      <input type="checkbox" id="zones-enabled" checked /> Zones
    </label>
```

Add zone showcase stories dropdown (a second select) after the existing stories select:

```html
      <select id="zone-stories" style="display:none; margin-left: 8px;">
        <option value="">-- zone examples --</option>
      </select>
```

- [ ] **Step 2: Add zone CSS**

Add to the existing `<style>` block:

```css
    .zone-block {
      display: flex;
      align-items: center;
      padding: 4px 8px;
      margin: 2px 0;
      border-radius: 3px;
      font-size: 12px;
    }
    .zone-block .zone-type { font-weight: 600; min-width: 120px; }
    .zone-block .zone-lines { color: #666; min-width: 100px; }
    .zone-block .zone-conf { color: #888; min-width: 60px; }
    .zone-block .zone-lang { color: #0066cc; }
    .zone-code { background: #f0f4ff; border-left: 3px solid #3b82f6; }
    .zone-config { background: #fef9ee; border-left: 3px solid #f59e0b; }
    .zone-markup { background: #fef2f2; border-left: 3px solid #ef4444; }
    .zone-query { background: #f0fdf4; border-left: 3px solid #22c55e; }
    .zone-cli_shell { background: #f5f3ff; border-left: 3px solid #8b5cf6; }
    .zone-error_output { background: #fff7ed; border-left: 3px solid #f97316; }
    .zone-data { background: #f0f9ff; border-left: 3px solid #06b6d4; }
    .zone-natural_language { background: #f9fafb; border-left: 3px solid #9ca3af; }
```

- [ ] **Step 3: Update tester.js — render zones and load zone stories**

Add at the top of `tester.js`, after existing element references:

```javascript
const zonesEnabledEl = document.getElementById('zones-enabled');
const zoneResultsEl = document.getElementById('zone-results');
const zoneSummaryEl = document.getElementById('zone-summary');
const zoneBlocksEl = document.getElementById('zone-blocks');
const zoneStoriesEl = document.getElementById('zone-stories');

let zoneStories = [];
```

Add a `loadZoneStories` function after `loadStories`:

```javascript
async function loadZoneStories() {
  try {
    const res = await fetch('./corpus/zone-showcase.jsonl');
    if (!res.ok) return;
    const text = await res.text();
    if (text.startsWith('<')) return;
    zoneStories = text.split('\n').filter(Boolean).map((l) => JSON.parse(l));
    for (const s of zoneStories) {
      const opt = document.createElement('option');
      opt.value = s.id;
      opt.textContent = s.title;
      zoneStoriesEl.appendChild(opt);
    }
    zoneStoriesEl.style.display = '';
  } catch { /* zone stories not available */ }
}
loadZoneStories();

zoneStoriesEl.addEventListener('change', () => {
  const story = zoneStories.find((s) => s.id === zoneStoriesEl.value);
  if (story) {
    inputEl.value = decodeXor(story.prompt_xor);
    annotationEl.textContent = story.annotation || '';
    annotationEl.style.display = 'block';
  }
});
```

Update the scan button handler to pass zones option and render zone results. In the `btnEl.addEventListener('click', ...)` callback, update the opts and result handling:

```javascript
    const opts = {
      verbose: verboseEl.checked,
      redactStrategy: strategyEl.value,
      dangerouslyIncludeRawValues: true,
      zones: zonesEnabledEl.checked,
    };
```

After `renderRedacted(redactedOut, redactedText);`, add:

```javascript
    renderZones(findings, zones);
```

And after `findingsJson.textContent = ...`:

```javascript
    findingsJson.textContent = JSON.stringify({ scannedMs, findings, zones }, null, 2);
```

Add the `renderZones` function:

```javascript
function renderZones(findings, zones) {
  if (!zones || !zones.blocks) {
    zoneResultsEl.style.display = 'none';
    return;
  }

  zoneResultsEl.style.display = '';
  zoneSummaryEl.textContent = `${zones.blocks.length} zone(s) detected in ${zones.total_lines} lines`;
  zoneBlocksEl.textContent = '';

  if (!zones.blocks.length) {
    const div = document.createElement('div');
    div.style.cssText = 'color: #888; font-style: italic; padding: 4px;';
    div.textContent = 'No structured zones detected (pure prose).';
    zoneBlocksEl.appendChild(div);
    return;
  }

  for (const block of zones.blocks) {
    const el = document.createElement('div');
    el.className = `zone-block zone-${block.zone_type}`;

    const typeSpan = document.createElement('span');
    typeSpan.className = 'zone-type';
    typeSpan.textContent = block.zone_type;
    el.appendChild(typeSpan);

    const linesSpan = document.createElement('span');
    linesSpan.className = 'zone-lines';
    linesSpan.textContent = `L${block.start_line}–L${block.end_line}`;
    el.appendChild(linesSpan);

    const confSpan = document.createElement('span');
    confSpan.className = 'zone-conf';
    confSpan.textContent = `${(block.confidence * 100).toFixed(0)}%`;
    el.appendChild(confSpan);

    if (block.language_hint) {
      const langSpan = document.createElement('span');
      langSpan.className = 'zone-lang';
      langSpan.textContent = block.language_hint;
      el.appendChild(langSpan);
    }

    zoneBlocksEl.appendChild(el);
  }
}
```

- [ ] **Step 4: Build and manually test the tester page**

```bash
cd data_classifier/clients/browser
npm run build
npx http-server . -p 4173 -c-1
# Open http://localhost:4173/tester/ in browser
# 1. Paste some code-in-prose text, click Scan — verify zones panel appears
# 2. Select a zone showcase story from dropdown — verify it loads and detects zones
# 3. Uncheck "Zones" checkbox — verify zones panel hidden
```

- [ ] **Step 5: Commit**

```bash
git add tester/index.html tester/tester.js
git commit -m "feat(browser): add zone detection results panel to tester page"
```

---

### Task 13: Verify Full Integration End-to-End

**Files:** (no new files — validation only)

- [ ] **Step 1: Run full build**

```bash
cd data_classifier/clients/browser
npm run dist
# Expected: build succeeds, size check passes
# Note: worker bundle will be larger now (WASM loader code added)
```

- [ ] **Step 2: Run all unit tests**

```bash
cd data_classifier/clients/browser
npm run test:unit
# Expected: all unit tests pass
```

- [ ] **Step 3: Run all e2e tests**

```bash
cd data_classifier/clients/browser
npm run test:e2e
# Expected: tester.spec.js, zone-tester.spec.js, bench.spec.js, differential.spec.js, timeout.spec.js all pass
```

- [ ] **Step 4: Run existing secret detection regression**

```bash
cd data_classifier/clients/browser
npx playwright test tests/e2e/tester.spec.js
# Expected: GitHub PAT detection still works — secret scanner unaffected
```

- [ ] **Step 5: Verify WASM never loads when zones disabled**

```bash
cd data_classifier/clients/browser
npx playwright test tests/e2e/timeout.spec.js
# Expected: pathological input test still passes within timeout
# (WASM not loaded for secrets-only scans)
```

- [ ] **Step 6: Commit (if any fixes were needed)**

```bash
git add -A
git commit -m "fix(browser): integration fixes from full e2e validation"
```

---

## Self-Review Checklist

### Spec Coverage

| Spec Requirement | Task |
|-----------------|------|
| WASM + patterns shipped as static assets | Task 1 |
| `zone-detector.js` WASM loader | Task 2 |
| `scan()` accepts `{ secrets, zones }` options | Tasks 4, 5, 6 |
| Result shape: `findings` + `zones` | Tasks 3, 4 |
| `zones: false` → WASM never loads | Tasks 4, 5, 7 |
| `secrets: false` → JS scanner skipped | Tasks 4, 7 |
| Lazy WASM loading on first use | Tasks 2, 5 |
| MV3 service worker suspend | Task 2 (`resetZoneDetector`) |
| Unit tests: WASM lifecycle, options | Task 7 |
| ~25 real WildChat stories | Task 8 |
| ~8-10 synthetic showcase | Task 9 |
| Playwright e2e story tests | Task 10 |
| Three benchmark modes with P50/P95/P99 | Task 11 |
| Tester page zone results panel | Task 12 |
| Build copies WASM + patterns to dist | Task 1 |
| TypeScript definitions updated | Task 3 |
| Full integration validation | Task 13 |

### Placeholder Scan
No TBDs, TODOs, or "fill in later" found.

### Type Consistency
- `initZoneDetector()` → used as `initZones()` re-export in `scanner-core.js` → called as `initZones()` in `worker.js` ✓
- `detectZones(text, promptId)` → called with `opts._promptId || ''` in `scanner-core.js` ✓
- `ZoneBlock`, `ZonesResult` types in `.d.ts` → match WASM output shape ✓
- `result.zones` field → present in `scanText()`, pool timeout fallback, and type definitions ✓
