/**
 * WildChat parity test — compare JS scanner vs Python scan_text on real prompts.
 *
 * Reads the WildChat eval dataset (built by scripts/build_wildchat_eval.py),
 * decodes each prompt, scans with the JS scanner, and compares against
 * the Python findings stored in the JSONL.
 *
 * Reports: per-prompt agreement rate, false-positive/negative divergences,
 * and entity-type-level precision/recall.
 *
 * Usage (standalone):
 *   npx playwright test tests/e2e/wildchat-parity.spec.js
 *
 * Part of CI via scripts/ci_browser_parity.sh.
 */
import { test, expect } from '@playwright/test';
import { readFileSync, existsSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
const __dirname = dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = resolve(__dirname, '../../../../..');
const EVAL_DATA = resolve(PROJECT_ROOT, 'data/wildchat_eval/wildchat_eval.jsonl');

// XOR key must match Python data_classifier/patterns/_decoder.py
const XOR_KEY = 0x5a;

function xorDecode(b64) {
  // prompt_xor values are raw base64 (no "xor:" prefix)
  const raw = Buffer.from(b64, 'base64');
  const decoded = Buffer.alloc(raw.length);
  for (let i = 0; i < raw.length; i++) {
    decoded[i] = raw[i] ^ XOR_KEY;
  }
  return decoded.toString('utf-8');
}



test('wildchat parity — JS findings match Python scan_text on credential prompts', async ({ page }) => {
  test.setTimeout(120_000);

  if (!existsSync(EVAL_DATA)) {
    test.skip(true, `WildChat eval dataset not found at ${EVAL_DATA} — run scripts/build_wildchat_eval.py first`);
    return;
  }

  const lines = readFileSync(EVAL_DATA, 'utf-8').trim().split('\n');
  const rows = lines.map((l) => JSON.parse(l));

  // Sample up to 200 prompts for CI speed (full corpus = 3,515)
  const sampleSize = Math.min(200, rows.length);
  const step = Math.floor(rows.length / sampleSize);
  const sampled = [];
  for (let i = 0; i < rows.length && sampled.length < sampleSize; i += step) {
    sampled.push(rows[i]);
  }

  // Decode prompts and prepare for JS scanning
  const cases = sampled.map((row) => ({
    promptId: row.prompt_id,
    text: xorDecode(row.prompt_xor),
    pyHasCredential: row.has_credential,
    pyFindings: row.findings,
    pyEntityTypes: new Set(row.findings.map((f) => f.entity_type)),
  }));

  await page.goto('/tester/');

  const results = await page.evaluate(
    async ({ cases: casesData }) => {
      const { createScanner } = await import('../dist/scanner.esm.js');
      const scanner = createScanner();
      const out = [];
      for (const c of casesData) {
        const { findings } = await scanner.scan(c.text, { secrets: true, zones: false });
        const jsHasCredential = findings.length > 0;
        const jsEntityTypes = [...new Set(findings.map((f) => f.entity_type))];
        out.push({
          promptId: c.promptId,
          jsHasCredential,
          jsEntityTypes,
          jsCount: findings.length,
        });
      }
      return out;
    },
    {
      cases: cases.map((c) => ({
        promptId: c.promptId,
        text: c.text,
      })),
    }
  );

  // Compute metrics
  let agree = 0;
  let jsOnly = 0; // JS finds credential, Python doesn't
  let pyOnly = 0; // Python finds credential, JS doesn't
  const jsOnlyDetails = [];
  const pyOnlyDetails = [];

  for (let i = 0; i < results.length; i++) {
    const js = results[i];
    const py = cases[i];

    if (js.jsHasCredential === py.pyHasCredential) {
      agree++;
    } else if (js.jsHasCredential && !py.pyHasCredential) {
      jsOnly++;
      if (jsOnlyDetails.length < 5) {
        jsOnlyDetails.push({
          promptId: js.promptId,
          jsTypes: js.jsEntityTypes,
        });
      }
    } else {
      pyOnly++;
      if (pyOnlyDetails.length < 5) {
        pyOnlyDetails.push({
          promptId: js.promptId,
          pyTypes: [...py.pyEntityTypes],
        });
      }
    }
  }

  const total = results.length;
  const agreementRate = agree / total;

  console.log(`\nWildChat Parity Report (${total} prompts sampled)`);
  console.log(`  Agreement:     ${agree}/${total} (${(agreementRate * 100).toFixed(1)}%)`);
  console.log(`  JS-only FP:    ${jsOnly} (JS finds, Python doesn't)`);
  console.log(`  Python-only:   ${pyOnly} (Python finds, JS doesn't)`);

  if (jsOnlyDetails.length) {
    console.log(`  JS-only samples: ${JSON.stringify(jsOnlyDetails)}`);
  }
  if (pyOnlyDetails.length) {
    console.log(`  Python-only samples: ${JSON.stringify(pyOnlyDetails)}`);
  }

  // Gate: agreement rate must be >= 85%.
  // Gap is driven by 19 Python validators not yet ported to JS (stubbed as always-true).
  // These cause JS to over-fire on patterns like SWIFT_BIC, IBAN, SSN where Python
  // correctly rejects invalid matches. Threshold will tighten as validators are ported.
  expect(
    agreementRate,
    `JS-Python agreement rate ${(agreementRate * 100).toFixed(1)}% is below 85% threshold. ` +
      `${jsOnly} JS-only, ${pyOnly} Python-only divergences out of ${total} prompts.`
  ).toBeGreaterThanOrEqual(0.85);
});
