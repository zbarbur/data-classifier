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
