// Public API. Example:
//   import { createScanner } from '@data-classifier/browser';
//   const scanner = createScanner();
//   const { findings, redactedText } = await scanner.scan(text);

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
    return pool.run({
      text,
      opts: scanOpts,
      timeoutMs: scanOpts.timeoutMs || 100,
      failMode: scanOpts.failMode || 'open',
    });
  }

  return { scan, onServiceWorkerSuspend: pool.onServiceWorkerSuspend };
}
