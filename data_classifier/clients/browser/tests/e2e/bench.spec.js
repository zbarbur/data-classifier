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
