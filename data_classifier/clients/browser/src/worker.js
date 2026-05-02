// Worker shim — unified WASM detection.
// Receives {id, text, opts} and posts {id, result} or {id, error}.

import { initDetector, detect } from './detector.js';

let initialized = false;

self.addEventListener('message', async (event) => {
  const { id, text, opts = {} } = event.data || {};
  try {
    // Lazy-init WASM on first message
    if (!initialized) {
      initialized = await initDetector();
      if (!initialized) {
        self.postMessage({ id, error: { message: 'WASM detector init failed' } });
        return;
      }
    }

    const optsJson = JSON.stringify({
      secrets: opts.secrets !== false,
      zones: opts.zones !== false,
      redact_strategy: opts.redactStrategy || 'type-label',
      verbose: !!opts.verbose,
      include_raw: !!opts.dangerouslyIncludeRawValues,
    });

    const result = detect(text, optsJson);
    if (!result) {
      self.postMessage({ id, error: { message: 'detect returned null' } });
      return;
    }

    // Map WASM snake_case output to browser API camelCase shape
    self.postMessage({
      id,
      result: {
        findings: result.findings || [],
        zones: result.zones || null,
        redactedText: result.redacted_text || text,
        scannedMs: result.scanned_ms || 0,
      },
    });
  } catch (err) {
    self.postMessage({ id, error: { message: String((err && err.message) || 'scan failed') } });
  }
});
