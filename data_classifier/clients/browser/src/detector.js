// detector.js — Unified WASM loader for zones + secrets.
// Lazy-loads data_classifier_core WASM + unified_patterns.json on first use.
// Init-once pattern: init() compiles zone patterns + secret patterns (~20-40ms),
// then detect() runs per-prompt (~1-2ms combined).

let wasmModule = null;
let detectorReady = false;
let initPromise = null;

const textEncoder = new TextEncoder();
const textDecoder = new TextDecoder('utf-8', { ignoreBOM: true, fatal: true });

/**
 * Lazy-initialize the unified detector (zones + secrets).
 * Fetches WASM binary + unified_patterns.json, compiles all patterns once.
 * Resolves to true on success, false on failure.
 *
 * @param {string} [wasmUrl] - URL to WASM binary. Defaults to sibling path.
 * @param {string} [patternsUrl] - URL to unified_patterns.json. Defaults to sibling path.
 * @returns {Promise<boolean>}
 */
export function initDetector(wasmUrl, patternsUrl) {
  if (detectorReady) return Promise.resolve(true);
  if (initPromise) return initPromise;

  initPromise = (async () => {
    try {
      // Resolve URLs relative to this module (works in worker context)
      const baseUrl = wasmUrl ? undefined : new URL('./', import.meta.url).href;
      const wUrl = wasmUrl || `${baseUrl}data_classifier_core_bg.wasm`;
      const pUrl = patternsUrl || `${baseUrl}unified_patterns.json`;

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
      const { instance } = await WebAssembly.instantiate(wasmBytes, imports);
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

      // Initialize both zone and secret detectors
      const ok = callInit(patternsJson);
      if (!ok) throw new Error('init() returned false');

      detectorReady = true;
      return true;
    } catch (err) {
      console.warn('[detector] init failed:', err.message || err);
      initPromise = null; // Allow retry
      return false;
    }
  })();

  return initPromise;
}

/**
 * Run unified detection. Returns parsed result or null if not ready.
 *
 * @param {string} text - Text to scan
 * @param {string} optsJson - JSON string: { secrets: bool, zones: bool, redact_strategy: str, verbose: bool, include_raw: bool }
 * @returns {{ zones: object|null, findings: Array, redacted_text: string, scanned_ms: number } | null}
 */
export function detect(text, optsJson) {
  if (!detectorReady || !wasmModule) return null;

  try {
    const resultJson = callDetectUnified(text, optsJson);
    return JSON.parse(resultJson);
  } catch (err) {
    console.warn('[detector] detect failed:', err.message || err);
    return null;
  }
}

/**
 * Reset detector state. Call on MV3 service worker suspend.
 * Next detect() call will re-initialize.
 */
export function resetDetector() {
  wasmModule = null;
  detectorReady = false;
  initPromise = null;
}

/**
 * Whether the detector is initialized and ready.
 * @returns {boolean}
 */
export function isDetectorReady() {
  return detectorReady;
}

// ── WASM FFI helpers (mirrors wasm-bindgen glue) ──────────────────

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

function callInit(patternsJson) {
  const [ptr, len] = passString(patternsJson);
  return wasmModule.init(ptr, len) !== 0;
}

function callDetectUnified(text, optsJson) {
  const [ptr0, len0] = passString(text);
  const [ptr1, len1] = passString(optsJson);
  const ret = wasmModule.detect_unified(ptr0, len0, ptr1, len1);
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
