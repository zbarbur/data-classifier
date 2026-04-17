import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const CORPUS = resolve(__dirname, '../../tester/corpus/bench/prompts.jsonl');
const TARGET_SCANS = 1000;

test('smoke benchmark — mean/p50/p99 over ~1K synthetic prompts', async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto('/tester/');

  const prompts = readFileSync(CORPUS, 'utf-8')
    .split('\n')
    .filter(Boolean)
    .map((l) => JSON.parse(l).text);

  const latencies = await page.evaluate(
    async ({ prompts, targetScans }) => {
      const { createScanner } = await import('../dist/scanner.esm.js');
      const scanner = createScanner();
      const out = [];
      for (let i = 0; i < targetScans; i++) {
        const text = prompts[i % prompts.length];
        const t0 = performance.now();
        await scanner.scan(text);
        out.push(performance.now() - t0);
      }
      return out;
    },
    { prompts, targetScans: TARGET_SCANS },
  );

  latencies.sort((a, b) => a - b);
  const mean = latencies.reduce((s, x) => s + x, 0) / latencies.length;
  const p50 = latencies[Math.floor(latencies.length * 0.5)];
  const p99 = latencies[Math.floor(latencies.length * 0.99)];
  const max = latencies[latencies.length - 1];

  const summary = { count: latencies.length, mean, p50, p99, max };
  console.log('\n=== SMOKE BENCH (order-of-magnitude only) ===');
  console.log(JSON.stringify(summary, null, 2));
  console.log('==============================================\n');

  expect(p50).toBeLessThan(500);
});
