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
