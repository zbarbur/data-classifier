import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const FIXTURES = resolve(__dirname, '../../src/generated/fixtures.json');
const CONSTANTS_PATH = resolve(__dirname, '../../src/generated/constants.js');

test('differential — JS findings match Python findings per seed case', async ({ page }) => {
  const fixtures = JSON.parse(readFileSync(FIXTURES, 'utf-8'));
  const constantsSrc = readFileSync(CONSTANTS_PATH, 'utf-8');
  const versionMatch = constantsSrc.match(/PYTHON_LOGIC_VERSION\s*=\s*"([^"]+)"/);
  const runtimeVersion = versionMatch ? versionMatch[1] : null;

  if (runtimeVersion && runtimeVersion !== fixtures.python_logic_version) {
    throw new Error(
      `PYTHON_LOGIC_VERSION mismatch — fixtures=${fixtures.python_logic_version} runtime=${runtimeVersion}. ` +
        'Run npm run generate to refresh fixtures, then update the JS port to match if needed.'
    );
  }

  await page.goto('/tester/');
  const results = await page.evaluate(
    async ({ cases }) => {
      const { createScanner } = await import('../dist/scanner.esm.js');
      const scanner = createScanner();
      const out = [];
      for (const c of cases) {
        const { findings } = await scanner.scan(c.text);
        const jsSet = new Set(findings.map((f) => `${f.entity_type}:${f.category}:${f.engine}`));
        const pySet = new Set(c.findings.map((f) => `${f.entity_type}:${f.category}:${f.engine}`));
        const onlyJs = [...jsSet].filter((x) => !pySet.has(x));
        const onlyPy = [...pySet].filter((x) => !jsSet.has(x));
        if (onlyJs.length || onlyPy.length) out.push({ id: c.id, onlyJs, onlyPy });
      }
      return out;
    },
    { cases: fixtures.cases }
  );

  expect(
    results,
    `Differential mismatch on ${results.length} case(s). ` +
      'If a Python logic file changed, run npm run generate; if JS diverges, port the change.'
  ).toEqual([]);
});
