// Worker shim. Receives {id, text, opts} and posts {id, result} or {id, error}.
// Any exception inside scanText is caught and surfaced so the pool can react.

import { scanText } from './scanner-core.js';

self.addEventListener('message', (event) => {
  const { id, text, opts } = event.data || {};
  try {
    const result = scanText(text, opts);
    self.postMessage({ id, result });
  } catch (err) {
    self.postMessage({ id, error: { message: String((err && err.message) || 'scan failed') } });
  }
});
