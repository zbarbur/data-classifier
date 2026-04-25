// Worker shim. Receives {id, text, opts} and posts {id, result} or {id, error}.
// Zone detection: WASM is lazy-loaded on first zone-enabled scan.

import { scanText, initZones } from './scanner-core.js';

let zonesInitialized = false;

self.addEventListener('message', async (event) => {
  const { id, text, opts } = event.data || {};
  try {
    const runZones = (opts && opts.zones) !== false;

    // Lazy-init WASM on first zone-enabled scan.
    // initZones() deduplicates concurrent calls internally.
    if (runZones && !zonesInitialized) {
      zonesInitialized = await initZones();
    }

    const result = scanText(text, opts);
    self.postMessage({ id, result });
  } catch (err) {
    self.postMessage({ id, error: { message: String((err && err.message) || 'scan failed') } });
  }
});
