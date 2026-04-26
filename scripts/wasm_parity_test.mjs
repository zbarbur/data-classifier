/**
 * wasm_parity_test.mjs
 *
 * Loads the wasm-bindgen --target web WASM binary in Node.js using initSync,
 * then runs each fixture from wasm_parity_fixtures.json and validates that the
 * detected entity_type set matches expectations.
 *
 * Exit 0 = all pass.  Exit 1 = at least one failure.
 */

import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { resolve, dirname } from 'path';

const __dir = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dir, '..');

// ---------------------------------------------------------------------------
// Load WASM module
// ---------------------------------------------------------------------------

const pkgDir = resolve(root, 'data_classifier_core', 'pkg');
const wasmBytes = readFileSync(resolve(pkgDir, 'data_classifier_core_bg.wasm'));

const mod = await import(
  new URL('file://' + resolve(pkgDir, 'data_classifier_core.js')).href
);

// initSync bypasses fetch, which is not available in Node
mod.initSync({ module: wasmBytes });

// ---------------------------------------------------------------------------
// Load patterns and initialize unified detector
// ---------------------------------------------------------------------------

const patternsJson = readFileSync(
  resolve(root, 'data_classifier_core', 'patterns', 'unified_patterns.json'),
  'utf-8'
);

const initOk = mod.init(patternsJson);
if (!initOk) {
  console.error('FAIL: init() returned false — patterns failed to parse');
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Load fixtures
// ---------------------------------------------------------------------------

const fixtures = JSON.parse(
  readFileSync(
    resolve(root, 'data_classifier_core', 'tests', 'wasm_parity_fixtures.json'),
    'utf-8'
  )
);

// ---------------------------------------------------------------------------
// Run parity checks
// ---------------------------------------------------------------------------

const OPTS = JSON.stringify({
  secrets: true,
  zones: false,
  redact_strategy: 'type-label',
});

let passed = 0;
let failed = 0;

console.log('Running WASM parity fixtures...\n');

for (const fixture of fixtures) {
  let result;
  try {
    result = JSON.parse(mod.detect_unified(fixture.text, OPTS));
  } catch (err) {
    console.error(`  FAIL [${fixture.id}]: detect_unified threw: ${err.message}`);
    failed++;
    continue;
  }

  // Deduplicate entity types found (a span may repeat type across passes)
  const foundTypes = [...new Set(result.findings.map((f) => f.entity_type))].sort();
  const expectedTypes = [...fixture.expect_entity_types].sort();

  if (JSON.stringify(foundTypes) === JSON.stringify(expectedTypes)) {
    console.log(`  PASS [${fixture.id}]`);
    passed++;
  } else {
    console.error(
      `  FAIL [${fixture.id}]: expected ${JSON.stringify(expectedTypes)}, got ${JSON.stringify(foundTypes)}`
    );
    if (fixture.notes) {
      console.error(`       note: ${fixture.notes}`);
    }
    failed++;
  }
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------

console.log(`\n${passed} passed, ${failed} failed`);

if (failed > 0) {
  process.exit(1);
}
