// @vitest-environment jsdom
import '@vitest/web-worker';
import { describe, it, expect } from 'vitest';
import { createPool } from '../../src/pool.js';

function mockSpawner(scanResult) {
  let spawned = 0;
  const terminated = [];
  const spawn = () => {
    spawned++;
    const listeners = new Set();
    const worker = {
      id: spawned,
      postMessage(msg) {
        setTimeout(() => {
          for (const l of listeners) l({ data: { id: msg.id, result: scanResult } });
        }, 0);
      },
      terminate: () => terminated.push(worker.id),
      addEventListener: (name, fn) => {
        if (name === 'message') listeners.add(fn);
      },
    };
    return worker;
  };
  return { spawn, spawnedCount: () => spawned, terminated };
}

describe('createPool — lazy init', () => {
  it('does not spawn a worker until the first run()', () => {
    const s = mockSpawner({ findings: [], redactedText: '', scannedMs: 0 });
    const pool = createPool({ size: 2, spawn: s.spawn });
    expect(s.spawnedCount()).toBe(0);
    pool.run({ text: 'x', opts: {} });
    expect(s.spawnedCount()).toBe(1);
  });

  it('caps at size 2 concurrent workers', async () => {
    const s = mockSpawner({ findings: [], redactedText: '', scannedMs: 0 });
    const pool = createPool({ size: 2, spawn: s.spawn });
    await Promise.all([
      pool.run({ text: 'a', opts: {} }),
      pool.run({ text: 'b', opts: {} }),
      pool.run({ text: 'c', opts: {} }),
    ]);
    expect(s.spawnedCount()).toBe(2);
  });
});

describe('createPool — timeout', () => {
  it('terminates + respawns the worker when a scan exceeds timeoutMs', async () => {
    let spawned = 0;
    const terminated = [];
    const spawn = () => {
      spawned++;
      const id = spawned;
      return {
        id,
        postMessage() {},
        terminate() { terminated.push(id); },
        addEventListener() {},
      };
    };
    const pool = createPool({ size: 1, spawn });
    const result = await pool.run({ text: 'x', opts: {}, timeoutMs: 10, failMode: 'open' });
    expect(result.findings).toEqual([]);
    expect(terminated).toEqual([1]);
    await pool.run({ text: 'y', opts: {}, timeoutMs: 10, failMode: 'open' }).catch(() => {});
    expect(spawned).toBeGreaterThanOrEqual(2);
  });

  it('rejects with TIMEOUT when failMode=closed', async () => {
    const spawn = () => ({
      postMessage() {},
      terminate() {},
      addEventListener() {},
    });
    const pool = createPool({ size: 1, spawn });
    await expect(
      pool.run({ text: 'x', opts: {}, timeoutMs: 10, failMode: 'closed' })
    ).rejects.toMatchObject({ code: 'TIMEOUT' });
  });
});
