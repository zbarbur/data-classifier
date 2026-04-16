# Browser PoC Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold a browser-side secret-detection engine in `data_classifier/clients/browser/` that ports `secret_scanner` + `regex_engine` from Python to JS, isolated behind a Web Worker pool, with a pattern-generator build script so Python remains the single source of truth.

**Architecture:** Two-pass scan (regex iteration + KV-based secret scanner) runs inside a Web Worker. A main-thread pool (size 2, lazy init, eager respawn) dispatches scans with a fail-open timeout that terminates runaway workers. Patterns, secret-key-names, stopwords, placeholder-values, and scoring constants are all emitted by a Python generator into `src/generated/` (gitignored). Public API returns `{findings, redactedText, scannedMs}`.

**Tech Stack:** Vanilla ES modules (Node 20 / modern browsers), esbuild for bundling, Vitest for unit tests (with `@vitest/web-worker`), Playwright for e2e + smoke benchmark, Prettier for formatting, Python 3.11 for the generator (uses the existing `data_classifier` package).

**Spec:** [`docs/superpowers/specs/2026-04-16-browser-poc-scaffold-design.md`](../specs/2026-04-16-browser-poc-scaffold-design.md)

**Note on regex iteration style:** Throughout this plan, JS regex iteration uses `String.prototype.matchAll` (modern, idiomatic, avoids `lastIndex` state). Match objects from `matchAll` carry `.index` and capture groups, same semantics as the stateful alternative.

---

## File Structure

### Created files (JS side)

| Path | Responsibility |
|---|---|
| `data_classifier/clients/browser/README.md` | Contributor guide, API usage, warnings |
| `data_classifier/clients/browser/package.json` | Deps, scripts, ESM config |
| `data_classifier/clients/browser/esbuild.config.mjs` | Two-bundle build (scanner + worker) |
| `data_classifier/clients/browser/.gitignore` | Ignore generated, dist, node_modules |
| `data_classifier/clients/browser/.prettierrc.json` | Format config |
| `data_classifier/clients/browser/vitest.config.js` | Vitest config with web-worker plugin |
| `data_classifier/clients/browser/playwright.config.js` | Playwright config |
| `data_classifier/clients/browser/src/scanner.js` | Public API: `scan(text, opts)` |
| `data_classifier/clients/browser/src/pool.js` | Worker pool (size 2, lazy, MV3-aware) |
| `data_classifier/clients/browser/src/worker.js` | Worker shim: msg → scanner-core |
| `data_classifier/clients/browser/src/scanner-core.js` | Regex pass + secret-scanner pass |
| `data_classifier/clients/browser/src/regex-backend.js` | Stage-1 JS `RegExp` backend |
| `data_classifier/clients/browser/src/validators.js` | Ported validators (3) + stub |
| `data_classifier/clients/browser/src/entropy.js` | Shannon, relative entropy, charset, diversity |
| `data_classifier/clients/browser/src/kv-parsers.js` | JSON / env / code-literal parsers with offsets |
| `data_classifier/clients/browser/src/redaction.js` | Four strategies, right-to-left replacement |
| `data_classifier/clients/browser/src/decoder.js` | `xor:` / `b64:` decoder (mirror of `_decoder.py`) |
| `data_classifier/clients/browser/src/finding.js` | Finding shape factory helpers |
| `data_classifier/clients/browser/tester/index.html` | Paste text → findings JSON |
| `data_classifier/clients/browser/tester/tester.js` | Tester page logic |
| `data_classifier/clients/browser/tester/corpus/seed.jsonl` | Differential seed cases |
| `data_classifier/clients/browser/tester/corpus/bench/prompts.jsonl` | Smoke-bench synthetic inputs |
| `data_classifier/clients/browser/tests/unit/decoder.test.js` | Decoder round-trip |
| `data_classifier/clients/browser/tests/unit/entropy.test.js` | Entropy fixed vectors |
| `data_classifier/clients/browser/tests/unit/validators.test.js` | Three validators, table-driven |
| `data_classifier/clients/browser/tests/unit/kv-parsers.test.js` | Each format + offset correctness |
| `data_classifier/clients/browser/tests/unit/redaction.test.js` | Four strategies + overlap stability |
| `data_classifier/clients/browser/tests/unit/regex-backend.test.js` | Iteration + validator integration |
| `data_classifier/clients/browser/tests/unit/scanner-core.test.js` | End-to-end on prose snippets |
| `data_classifier/clients/browser/tests/unit/pool.test.js` | Pool lifecycle, timeout, respawn |
| `data_classifier/clients/browser/tests/e2e/tester.spec.js` | Tester page smoke |
| `data_classifier/clients/browser/tests/e2e/timeout.spec.js` | Worker terminate under pathological input |
| `data_classifier/clients/browser/tests/e2e/differential.spec.js` | Version-gated differential fixtures |
| `data_classifier/clients/browser/tests/e2e/bench.spec.js` | Smoke latency benchmark |

### Created files (Python generator)

| Path | Responsibility |
|---|---|
| `scripts/generate_browser_patterns.py` | Emits `constants.js`, `patterns.js`, `secret-key-names.js`, `stopwords.js`, `placeholder-values.js`, `fixtures.json`, `PYTHON_LOGIC_VERSION` |

### Modified files

| Path | Change |
|---|---|
| `pyproject.toml` | Exclude `data_classifier/clients/browser/**` from wheel |

### Generated (gitignored) — created by the generator, never committed

| Path | Responsibility |
|---|---|
| `data_classifier/clients/browser/src/generated/constants.js` | Scoring thresholds + `PYTHON_LOGIC_VERSION` |
| `data_classifier/clients/browser/src/generated/patterns.js` | 77 patterns, examples stripped |
| `data_classifier/clients/browser/src/generated/secret-key-names.js` | 178 key-name entries |
| `data_classifier/clients/browser/src/generated/stopwords.js` | Decoded stopwords set |
| `data_classifier/clients/browser/src/generated/placeholder-values.js` | Placeholder set |
| `data_classifier/clients/browser/src/generated/fixtures.json` | Seed-corpus expected findings, version-stamped |

---

## Node / Python prerequisites

Before starting:

- Node 20+ (check with `node --version`).
- Python 3.11 with the `data_classifier` package installed editable: `pip install -e ".[dev]"` from the repo root.
- All work happens in the `data_classifier-browser-poc` worktree on branch `sprint14/browser-poc-secret`.

---

## Task 0: Project bootstrap

**Files:**
- Create: `data_classifier/clients/browser/package.json`
- Create: `data_classifier/clients/browser/.gitignore`
- Create: `data_classifier/clients/browser/.prettierrc.json`
- Create: `data_classifier/clients/browser/esbuild.config.mjs`
- Create: `data_classifier/clients/browser/vitest.config.js`
- Create: `data_classifier/clients/browser/playwright.config.js`
- Modify: `pyproject.toml` (add wheel exclusion)

- [ ] **Step 1: Create the `package.json`**

Write `data_classifier/clients/browser/package.json`:

```json
{
  "name": "@data-classifier/browser",
  "version": "0.0.0",
  "private": true,
  "type": "module",
  "description": "Client-side secret detection engine ported from data_classifier (Python). Scaffold — not yet published.",
  "engines": {
    "node": ">=20"
  },
  "scripts": {
    "build": "node esbuild.config.mjs",
    "dev": "node esbuild.config.mjs --watch",
    "generate": "cd ../../.. && python3 scripts/generate_browser_patterns.py",
    "pretest": "npm run generate",
    "test:unit": "vitest run",
    "test:unit:watch": "vitest",
    "pretest:e2e": "npm run build",
    "test:e2e": "playwright test",
    "bench": "playwright test tests/e2e/bench.spec.js",
    "format": "prettier --write 'src/**/*.js' 'tests/**/*.js' 'tester/**/*.js' 'tester/**/*.html'",
    "format:check": "prettier --check 'src/**/*.js' 'tests/**/*.js' 'tester/**/*.js' 'tester/**/*.html'"
  },
  "devDependencies": {
    "@playwright/test": "^1.45.0",
    "@vitest/web-worker": "^2.0.0",
    "esbuild": "^0.23.0",
    "prettier": "^3.3.0",
    "vitest": "^2.0.0"
  }
}
```

- [ ] **Step 2: Create the `.gitignore`**

Write `data_classifier/clients/browser/.gitignore`:

```
node_modules/
dist/
src/generated/
tester/corpus/**/last_run.json
.playwright/
playwright-report/
test-results/
```

- [ ] **Step 3: Create the Prettier config**

Write `data_classifier/clients/browser/.prettierrc.json`:

```json
{
  "semi": true,
  "singleQuote": true,
  "trailingComma": "es5",
  "printWidth": 100,
  "tabWidth": 2
}
```

- [ ] **Step 4: Create the esbuild config**

Write `data_classifier/clients/browser/esbuild.config.mjs`:

```js
import esbuild from 'esbuild';

const watch = process.argv.includes('--watch');

const shared = {
  bundle: true,
  format: 'esm',
  target: ['es2022'],
  minify: !watch,
  sourcemap: true,
  logLevel: 'info',
};

const builds = [
  {
    ...shared,
    entryPoints: ['src/scanner.js'],
    outfile: 'dist/scanner.esm.js',
  },
  {
    ...shared,
    entryPoints: ['src/worker.js'],
    outfile: 'dist/worker.esm.js',
  },
];

if (watch) {
  const ctxs = await Promise.all(builds.map((b) => esbuild.context(b)));
  await Promise.all(ctxs.map((c) => c.watch()));
  console.log('esbuild: watching…');
} else {
  await Promise.all(builds.map((b) => esbuild.build(b)));
  console.log('esbuild: done');
}
```

- [ ] **Step 5: Create the Vitest config**

Write `data_classifier/clients/browser/vitest.config.js`:

```js
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    include: ['tests/unit/**/*.test.js'],
    setupFiles: [],
    server: {
      deps: {
        inline: ['@vitest/web-worker'],
      },
    },
  },
});
```

- [ ] **Step 6: Create the Playwright config**

Write `data_classifier/clients/browser/playwright.config.js`:

```js
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'off',
  },
  webServer: {
    command: 'npx --yes http-server . -p 4173 -c-1',
    port: 4173,
    reuseExistingServer: !process.env.CI,
    timeout: 10_000,
  },
});
```

- [ ] **Step 7: Modify `pyproject.toml` to exclude the browser package from the wheel**

Edit `pyproject.toml` (around line 70) — replace:

```toml
[tool.setuptools.packages.find]
include = ["data_classifier*"]
```

with:

```toml
[tool.setuptools.packages.find]
include = ["data_classifier*"]
exclude = ["data_classifier.clients*"]
```

- [ ] **Step 8: Install dependencies**

Run:
```
cd data_classifier/clients/browser
npm install
```

Expected: success; creates `node_modules/` and `package-lock.json`.

- [ ] **Step 9: Verify wheel build excludes the browser package**

Run from repo root:
```
python3 -m build --wheel --outdir /tmp/wheel-check
unzip -l /tmp/wheel-check/*.whl | grep -c clients/browser
```

Expected: `0` (no files from `clients/browser` in the wheel).

- [ ] **Step 10: Commit**

```
git add data_classifier/clients/browser/package.json \
        data_classifier/clients/browser/.gitignore \
        data_classifier/clients/browser/.prettierrc.json \
        data_classifier/clients/browser/esbuild.config.mjs \
        data_classifier/clients/browser/vitest.config.js \
        data_classifier/clients/browser/playwright.config.js \
        data_classifier/clients/browser/package-lock.json \
        pyproject.toml
git commit -m "feat(sprint14): scaffold browser PoC bootstrap (Task 0)"
```

---

## Task 1: Decoder module — `xor:` and `b64:` prefix support

**Files:**
- Create: `data_classifier/clients/browser/src/decoder.js`
- Test: `data_classifier/clients/browser/tests/unit/decoder.test.js`

This mirrors `data_classifier/patterns/_decoder.py`. XOR key is `0x5A`.

- [ ] **Step 1: Write the failing test**

Write `data_classifier/clients/browser/tests/unit/decoder.test.js`:

```js
import { describe, it, expect } from 'vitest';
import { decodeEncodedStrings } from '../../src/decoder.js';

describe('decodeEncodedStrings', () => {
  it('passes through unprefixed values unchanged', () => {
    expect(decodeEncodedStrings(['hello', 'world'])).toEqual(['hello', 'world']);
  });

  it('decodes a xor: prefixed value with key 0x5A', () => {
    // 'AKIA' XOR 0x5A byte-wise = [0x1B, 0x11, 0x13, 0x1B] → base64 'GxETGw=='
    expect(decodeEncodedStrings(['xor:GxETGw=='])).toEqual(['AKIA']);
  });

  it('decodes a b64: prefixed value (no xor)', () => {
    // base64('hello') = 'aGVsbG8='
    expect(decodeEncodedStrings(['b64:aGVsbG8='])).toEqual(['hello']);
  });

  it('handles a mix of encoded and plain entries', () => {
    expect(decodeEncodedStrings(['plain', 'xor:GxETGw==', 'b64:aGVsbG8='])).toEqual([
      'plain',
      'AKIA',
      'hello',
    ]);
  });

  it('returns an empty array for an empty input', () => {
    expect(decodeEncodedStrings([])).toEqual([]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```
cd data_classifier/clients/browser
npx vitest run tests/unit/decoder.test.js
```

Expected: FAIL with `Cannot find module '../../src/decoder.js'`.

- [ ] **Step 3: Write the implementation**

Write `data_classifier/clients/browser/src/decoder.js`:

```js
// Mirror of data_classifier/patterns/_decoder.py — decodes xor:/b64: prefixes.

const XOR_KEY = 0x5a;

function base64ToBytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) {
    out[i] = bin.charCodeAt(i);
  }
  return out;
}

function bytesToUtf8(bytes) {
  return new TextDecoder('utf-8').decode(bytes);
}

export function decodeEncodedStrings(values) {
  const out = [];
  for (const v of values) {
    if (v.startsWith('xor:')) {
      const bytes = base64ToBytes(v.slice(4));
      for (let i = 0; i < bytes.length; i++) bytes[i] ^= XOR_KEY;
      out.push(bytesToUtf8(bytes));
    } else if (v.startsWith('b64:')) {
      out.push(bytesToUtf8(base64ToBytes(v.slice(4))));
    } else {
      out.push(v);
    }
  }
  return out;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```
npx vitest run tests/unit/decoder.test.js
```

Expected: PASS, 5 tests green.

- [ ] **Step 5: Commit**

```
git add data_classifier/clients/browser/src/decoder.js \
        data_classifier/clients/browser/tests/unit/decoder.test.js
git commit -m "feat(sprint14): port xor/b64 decoder to JS (Task 1)"
```

---

## Task 2: Entropy module

**Files:**
- Create: `data_classifier/clients/browser/src/entropy.js`
- Test: `data_classifier/clients/browser/tests/unit/entropy.test.js`

Mirrors `data_classifier/engines/secret_scanner.py` helpers plus `heuristic_engine.compute_shannon_entropy` / `compute_char_class_diversity`.

- [ ] **Step 1: Write the failing test**

Write `data_classifier/clients/browser/tests/unit/entropy.test.js`:

```js
import { describe, it, expect } from 'vitest';
import {
  shannonEntropy,
  detectCharset,
  relativeEntropy,
  charClassDiversity,
  scoreRelativeEntropy,
} from '../../src/entropy.js';

describe('shannonEntropy', () => {
  it('returns 0 for an empty string', () => {
    expect(shannonEntropy('')).toBe(0);
  });

  it('returns 0 for a constant string', () => {
    expect(shannonEntropy('aaaa')).toBe(0);
  });

  it('returns 1 bit per char for a balanced 2-symbol string', () => {
    expect(shannonEntropy('abab')).toBeCloseTo(1.0, 4);
  });

  it('returns log2(4) for a balanced 4-symbol string', () => {
    expect(shannonEntropy('abcd')).toBeCloseTo(2.0, 4);
  });
});

describe('detectCharset', () => {
  it('detects hex', () => {
    expect(detectCharset('deadbeef1234')).toBe('hex');
  });

  it('detects base64', () => {
    expect(detectCharset('SGVsbG8gV29ybGQ=')).toBe('base64');
  });

  it('detects alphanumeric (mixed-case, no symbols)', () => {
    expect(detectCharset('AbcDef123')).toBe('alphanumeric');
  });

  it('falls back to full for strings with symbols or spaces', () => {
    expect(detectCharset('hello world!')).toBe('full');
  });
});

describe('relativeEntropy', () => {
  it('returns 0 for an empty string', () => {
    expect(relativeEntropy('')).toBe(0);
  });

  it('returns > 0.6 for a high-entropy full-charset string', () => {
    const v = '9sK!2f#Aq@Lp$7tZ&rM*uX(jN)bH+cY^';
    expect(relativeEntropy(v)).toBeGreaterThan(0.6);
    expect(relativeEntropy(v)).toBeLessThanOrEqual(1.0);
  });
});

describe('charClassDiversity', () => {
  it('counts lowercase + uppercase + digit + symbol classes', () => {
    expect(charClassDiversity('Abc123!')).toBe(4);
  });

  it('counts only present classes', () => {
    expect(charClassDiversity('abc')).toBe(1);
    expect(charClassDiversity('abc123')).toBe(2);
    expect(charClassDiversity('Abc123')).toBe(3);
  });
});

describe('scoreRelativeEntropy', () => {
  it('returns 0 below the 0.5 floor', () => {
    expect(scoreRelativeEntropy(0.4)).toBe(0);
  });

  it('scales linearly above the floor, capped at 1.0', () => {
    expect(scoreRelativeEntropy(0.5)).toBeCloseTo(0.5, 4);
    expect(scoreRelativeEntropy(0.75)).toBeCloseTo(0.75, 4);
    expect(scoreRelativeEntropy(1.0)).toBe(1.0);
    expect(scoreRelativeEntropy(1.5)).toBe(1.0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```
npx vitest run tests/unit/entropy.test.js
```

Expected: FAIL with module-not-found.

- [ ] **Step 3: Write the implementation**

Write `data_classifier/clients/browser/src/entropy.js`:

```js
// Shannon entropy + charset-aware relative entropy + char-class diversity.
// Mirrors:
//   data_classifier/engines/heuristic_engine.py :: compute_shannon_entropy,
//                                                  compute_char_class_diversity
//   data_classifier/engines/secret_scanner.py  :: _detect_charset,
//                                                  _compute_relative_entropy,
//                                                  _score_relative_entropy

const LOG2 = Math.log(2);
const log2 = (x) => Math.log(x) / LOG2;

const CHARSET_MAX_ENTROPY = {
  hex: log2(16),
  base64: log2(64),
  alphanumeric: log2(62),
  full: log2(95),
};

const HEX_RE = /^[0-9a-fA-F]+$/;
const BASE64_RE = /^[A-Za-z0-9+/=]+$/;
const ALNUM_RE = /^[A-Za-z0-9]+$/;

export function shannonEntropy(value) {
  if (!value) return 0;
  const counts = new Map();
  for (const ch of value) counts.set(ch, (counts.get(ch) || 0) + 1);
  const n = value.length;
  let h = 0;
  for (const c of counts.values()) {
    const p = c / n;
    h -= p * log2(p);
  }
  return h;
}

export function detectCharset(value) {
  if (HEX_RE.test(value)) return 'hex';
  if (BASE64_RE.test(value)) return 'base64';
  if (ALNUM_RE.test(value)) return 'alphanumeric';
  return 'full';
}

export function relativeEntropy(value) {
  if (!value) return 0;
  const h = shannonEntropy(value);
  const charset = detectCharset(value);
  const max = CHARSET_MAX_ENTROPY[charset] || CHARSET_MAX_ENTROPY.full;
  if (max === 0) return 0;
  return Math.min(1.0, h / max);
}

export function charClassDiversity(value) {
  let hasLower = false;
  let hasUpper = false;
  let hasDigit = false;
  let hasSymbol = false;
  for (const ch of value) {
    if (ch >= 'a' && ch <= 'z') hasLower = true;
    else if (ch >= 'A' && ch <= 'Z') hasUpper = true;
    else if (ch >= '0' && ch <= '9') hasDigit = true;
    else if (!/\s/.test(ch)) hasSymbol = true;
  }
  return +hasLower + +hasUpper + +hasDigit + +hasSymbol;
}

export function scoreRelativeEntropy(rel) {
  if (rel < 0.5) return 0;
  return Math.min(1.0, rel);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```
npx vitest run tests/unit/entropy.test.js
```

Expected: PASS, all green.

- [ ] **Step 5: Commit**

```
git add data_classifier/clients/browser/src/entropy.js \
        data_classifier/clients/browser/tests/unit/entropy.test.js
git commit -m "feat(sprint14): port Shannon + relative entropy to JS (Task 2)"
```

---

## Task 3: Validators module

**Files:**
- Create: `data_classifier/clients/browser/src/validators.js`
- Test: `data_classifier/clients/browser/tests/unit/validators.test.js`

Ports `aws_secret_not_hex`, `not_placeholder_credential`, `random_password_check` from `data_classifier/engines/validators.py`. The `not_placeholder_credential` validator needs a placeholder-value set injected; the validator module accepts the set as a constructor dependency so tests can pass a fixture.

- [ ] **Step 1: Write the failing test**

Write `data_classifier/clients/browser/tests/unit/validators.test.js`:

```js
import { describe, it, expect } from 'vitest';
import {
  awsSecretNotHex,
  randomPassword,
  makeNotPlaceholderCredential,
  resolveValidator,
} from '../../src/validators.js';

describe('awsSecretNotHex', () => {
  it('rejects pure-hex strings (git SHAs)', () => {
    expect(awsSecretNotHex('a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0')).toBe(false);
  });

  it('accepts base64-shaped values with mixed case', () => {
    expect(awsSecretNotHex('wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY')).toBe(true);
  });

  it('rejects values that are only uppercase or only lowercase', () => {
    expect(awsSecretNotHex('ALLUPPERCASENOLOWER12345')).toBe(false);
    expect(awsSecretNotHex('alllowercasenoupper12345')).toBe(false);
  });
});

describe('randomPassword', () => {
  it('accepts a 3-class value with symbol', () => {
    expect(randomPassword('Abc123!x')).toBe(true);
  });

  it('rejects values without a symbol', () => {
    expect(randomPassword('Hello123')).toBe(false);
  });

  it('rejects values below minimum length', () => {
    expect(randomPassword('Ab1!')).toBe(true);
    expect(randomPassword('Ab1')).toBe(false);
  });

  it('rejects values above maximum length', () => {
    expect(randomPassword('A'.repeat(65) + '1!')).toBe(false);
  });

  it('rejects 2-class values even with symbols', () => {
    expect(randomPassword('hello!!!')).toBe(false);
  });
});

describe('makeNotPlaceholderCredential', () => {
  it('rejects values in the placeholder set (case-insensitive)', () => {
    const validator = makeNotPlaceholderCredential(new Set(['changeme', 'password123']));
    expect(validator('changeme')).toBe(false);
    expect(validator('CHANGEME')).toBe(false);
    expect(validator('password123')).toBe(false);
  });

  it('accepts values not in the placeholder set', () => {
    const validator = makeNotPlaceholderCredential(new Set(['changeme']));
    expect(validator('ghp_abc123xyz')).toBe(true);
  });

  it('trims whitespace before comparing', () => {
    const validator = makeNotPlaceholderCredential(new Set(['changeme']));
    expect(validator('  changeme  ')).toBe(false);
  });
});

describe('resolveValidator', () => {
  it('returns a function for a known validator name', () => {
    expect(typeof resolveValidator('aws_secret_not_hex')).toBe('function');
    expect(typeof resolveValidator('random_password')).toBe('function');
  });

  it('returns a stub (always true) for an unported validator name', () => {
    const r = resolveValidator('luhn');
    expect(typeof r).toBe('function');
    expect(r('anything')).toBe(true);
    expect(r.isStub).toBe(true);
  });

  it('returns a passthrough for unknown/empty names', () => {
    expect(resolveValidator('')('x')).toBe(true);
    expect(resolveValidator(null)('x')).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```
npx vitest run tests/unit/validators.test.js
```

Expected: FAIL with module-not-found.

- [ ] **Step 3: Write the implementation**

Write `data_classifier/clients/browser/src/validators.js`:

```js
// Credential-touching validators ported from data_classifier/engines/validators.py.
// v1 ports: aws_secret_not_hex, random_password, not_placeholder_credential.
// Other validators (luhn, bitcoin_address, …) load as stubs that always return true;
// the generator emits a warning enumerating the stubbed list so the gap is visible.

export function awsSecretNotHex(value) {
  const clean = value.trim();
  if (/^[0-9a-fA-F]+$/.test(clean)) return false;
  let hasUpper = false;
  let hasLower = false;
  for (const ch of clean) {
    if (ch >= 'A' && ch <= 'Z') hasUpper = true;
    else if (ch >= 'a' && ch <= 'z') hasLower = true;
  }
  return hasUpper && hasLower;
}

export function randomPassword(value) {
  if (value.length < 4 || value.length > 64) return false;
  let hasLower = false;
  let hasUpper = false;
  let hasDigit = false;
  let hasSymbol = false;
  for (const ch of value) {
    if (ch >= 'a' && ch <= 'z') hasLower = true;
    else if (ch >= 'A' && ch <= 'Z') hasUpper = true;
    else if (ch >= '0' && ch <= '9') hasDigit = true;
    else if (!/\s/.test(ch)) hasSymbol = true;
  }
  if (!hasSymbol) return false;
  const classes = +hasLower + +hasUpper + +hasDigit + +hasSymbol;
  return classes >= 3;
}

export function makeNotPlaceholderCredential(placeholderSet) {
  return function notPlaceholderCredential(value) {
    const clean = value.trim().toLowerCase();
    return !placeholderSet.has(clean);
  };
}

const PORTED = {
  aws_secret_not_hex: awsSecretNotHex,
  random_password: randomPassword,
};

function makeStub() {
  const fn = (_value) => true;
  fn.isStub = true;
  return fn;
}

export function resolveValidator(name, { notPlaceholderCredential } = {}) {
  if (!name) return (_v) => true;
  if (name === 'not_placeholder_credential') {
    return notPlaceholderCredential || makeStub();
  }
  const fn = PORTED[name];
  if (fn) return fn;
  return makeStub();
}
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```
npx vitest run tests/unit/validators.test.js
```

Expected: PASS, 13 tests green.

- [ ] **Step 5: Commit**

```
git add data_classifier/clients/browser/src/validators.js \
        data_classifier/clients/browser/tests/unit/validators.test.js
git commit -m "feat(sprint14): port Credential validators to JS (Task 3)"
```

---

## Task 4: KV parsers with offsets

**Files:**
- Create: `data_classifier/clients/browser/src/kv-parsers.js`
- Test: `data_classifier/clients/browser/tests/unit/kv-parsers.test.js`

Mirrors `data_classifier/engines/parsers.py` (JSON + env + code-literal; YAML skipped per decision #3). **Offsets are the one JS extension over the Python port** — each returned pair carries `valueStart` / `valueEnd` byte offsets into the original input so redaction can splice without re-searching. Uses `String.prototype.matchAll` to iterate regex matches.

- [ ] **Step 1: Write the failing test**

Write `data_classifier/clients/browser/tests/unit/kv-parsers.test.js`:

```js
import { describe, it, expect } from 'vitest';
import { parseKeyValues } from '../../src/kv-parsers.js';

function assertOffsets(text, pairs) {
  for (const p of pairs) {
    expect(text.slice(p.valueStart, p.valueEnd)).toBe(p.value);
  }
}

describe('parseKeyValues — JSON', () => {
  it('extracts flat string KV pairs', () => {
    const text = '{"api_key": "ghp_abc123", "port": 8080}';
    const out = parseKeyValues(text);
    expect(out.map((p) => [p.key, p.value])).toEqual([
      ['api_key', 'ghp_abc123'],
      ['port', '8080'],
    ]);
    assertOffsets(text, out.filter((p) => p.key === 'api_key'));
  });

  it('flattens nested dicts with dotted keys', () => {
    const text = '{"db": {"password": "s3cret"}}';
    const out = parseKeyValues(text);
    expect(out.map((p) => [p.key, p.value])).toEqual([['db.password', 's3cret']]);
    assertOffsets(text, out);
  });

  it('returns empty on non-object JSON', () => {
    expect(parseKeyValues('[1,2,3]')).toEqual([]);
    expect(parseKeyValues('"hello"')).toEqual([]);
  });
});

describe('parseKeyValues — env format', () => {
  it('parses bare KEY=VALUE', () => {
    const text = 'API_KEY=ghp_abc123';
    const out = parseKeyValues(text);
    expect(out.map((p) => [p.key, p.value])).toEqual([['API_KEY', 'ghp_abc123']]);
    assertOffsets(text, out);
  });

  it('parses export KEY=VALUE', () => {
    const text = 'export AUTH_TOKEN=xyz789';
    const out = parseKeyValues(text);
    expect(out.map((p) => [p.key, p.value])).toEqual([['AUTH_TOKEN', 'xyz789']]);
    assertOffsets(text, out);
  });

  it('parses quoted values and strips quotes', () => {
    const text = 'PASS="my secret"';
    const out = parseKeyValues(text);
    expect(out.map((p) => [p.key, p.value])).toEqual([['PASS', 'my secret']]);
    assertOffsets(text, out);
  });

  it('parses multiple lines', () => {
    const text = 'KEY_A=aaa\nKEY_B=bbb';
    const out = parseKeyValues(text);
    expect(out.map((p) => [p.key, p.value])).toEqual([
      ['KEY_A', 'aaa'],
      ['KEY_B', 'bbb'],
    ]);
    assertOffsets(text, out);
  });
});

describe('parseKeyValues — code literals', () => {
  it('parses identifier = "value"', () => {
    const text = 'password = "hunter2"';
    const out = parseKeyValues(text);
    expect(out.map((p) => [p.key, p.value])).toEqual([['password', 'hunter2']]);
    assertOffsets(text, out);
  });

  it("parses identifier = 'value'", () => {
    const text = "api_key = 'abc-def'";
    const out = parseKeyValues(text);
    expect(out.map((p) => [p.key, p.value])).toEqual([['api_key', 'abc-def']]);
    assertOffsets(text, out);
  });

  it('parses identifier := "value"', () => {
    const text = 'pw := "golang-style"';
    const out = parseKeyValues(text);
    expect(out.map((p) => [p.key, p.value])).toEqual([['pw', 'golang-style']]);
    assertOffsets(text, out);
  });
});

describe('parseKeyValues — empty / whitespace', () => {
  it('returns empty on empty input', () => {
    expect(parseKeyValues('')).toEqual([]);
    expect(parseKeyValues('   \n  ')).toEqual([]);
  });

  it('returns empty on prose with no KV structure', () => {
    expect(parseKeyValues('just some prose with no structure')).toEqual([]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```
npx vitest run tests/unit/kv-parsers.test.js
```

Expected: FAIL with module-not-found.

- [ ] **Step 3: Write the implementation**

Write `data_classifier/clients/browser/src/kv-parsers.js`:

```js
// KV parsers — JSON, env, code-literal.
// Mirrors data_classifier/engines/parsers.py. Each returned pair carries
// { key, value, valueStart, valueEnd } offsets into the original text, used
// by redaction.js to splice without re-searching.

const ENV_RE =
  /^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|(\S+))\s*$/gm;

const CODE_RE =
  /([A-Za-z_][A-Za-z0-9_]*)\s*(?::=|:|=)\s*(?:"([^"]{1,500})"|'([^']{1,500})')/g;

export function parseKeyValues(text) {
  if (!text || !text.trim()) return [];

  const jsonPairs = parseJson(text);
  if (jsonPairs.length > 0) return jsonPairs;

  const results = [];
  results.push(...parseEnv(text));
  results.push(...parseCodeLiterals(text));
  return results;
}

function parseJson(text) {
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    return [];
  }
  if (data === null || typeof data !== 'object' || Array.isArray(data)) return [];
  return flattenDict(data, '', text, { cursor: 0 });
}

function flattenDict(obj, prefix, text, state) {
  const out = [];
  for (const [key, value] of Object.entries(obj)) {
    const fullKey = prefix ? `${prefix}.${key}` : key;
    if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
      out.push(...flattenDict(value, fullKey, text, state));
    } else if (Array.isArray(value)) {
      for (let i = 0; i < value.length; i++) {
        const item = value[i];
        if (item !== null && typeof item === 'object') {
          out.push(...flattenDict(item, `${fullKey}[${i}]`, text, state));
        } else if (item !== null && item !== undefined) {
          pushJsonPair(out, fullKey, String(item), text, state);
        }
      }
    } else if (value !== null && value !== undefined) {
      pushJsonPair(out, fullKey, String(value), text, state);
    }
  }
  return out;
}

function pushJsonPair(out, key, value, text, state) {
  const offsets = findValueOffset(text, value, state.cursor);
  if (offsets) {
    state.cursor = offsets.valueEnd;
    out.push({ key, value, valueStart: offsets.valueStart, valueEnd: offsets.valueEnd });
  } else {
    out.push({ key, value, valueStart: -1, valueEnd: -1 });
  }
}

function findValueOffset(text, value, from) {
  const quoted = `"${value}"`;
  const qIdx = text.indexOf(quoted, from);
  if (qIdx >= 0) {
    return { valueStart: qIdx + 1, valueEnd: qIdx + 1 + value.length };
  }
  const bare = text.indexOf(value, from);
  if (bare >= 0) {
    return { valueStart: bare, valueEnd: bare + value.length };
  }
  return null;
}

function parseEnv(text) {
  const out = [];
  for (const m of text.matchAll(ENV_RE)) {
    const key = m[1];
    let value = '';
    let valueStart = -1;
    let valueEnd = -1;
    if (m[2] !== undefined) {
      value = m[2];
      const quoteOpen = m.index + m[0].indexOf('"');
      valueStart = quoteOpen + 1;
      valueEnd = valueStart + value.length;
    } else if (m[3] !== undefined) {
      value = m[3];
      const quoteOpen = m.index + m[0].indexOf("'");
      valueStart = quoteOpen + 1;
      valueEnd = valueStart + value.length;
    } else if (m[4] !== undefined) {
      value = m[4];
      valueStart = m.index + m[0].indexOf(value, m[0].indexOf('='));
      valueEnd = valueStart + value.length;
    }
    if (value) out.push({ key, value, valueStart, valueEnd });
  }
  return out;
}

function parseCodeLiterals(text) {
  const out = [];
  for (const m of text.matchAll(CODE_RE)) {
    const key = m[1];
    const value = m[2] !== undefined ? m[2] : m[3] !== undefined ? m[3] : '';
    if (!value) continue;
    const quoteChar = m[2] !== undefined ? '"' : "'";
    const quoteOpen = m.index + m[0].lastIndexOf(quoteChar, m[0].length - value.length - 1);
    const valueStart = quoteOpen + 1;
    const valueEnd = valueStart + value.length;
    out.push({ key, value, valueStart, valueEnd });
  }
  return out;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```
npx vitest run tests/unit/kv-parsers.test.js
```

Expected: PASS, all green.

- [ ] **Step 5: Commit**

```
git add data_classifier/clients/browser/src/kv-parsers.js \
        data_classifier/clients/browser/tests/unit/kv-parsers.test.js
git commit -m "feat(sprint14): port KV parsers with offsets to JS (Task 4)"
```

---

## Task 5: Python generator script

**Files:**
- Create: `scripts/generate_browser_patterns.py`
- Create: `data_classifier/clients/browser/tester/corpus/seed.jsonl`

Generates six artifacts into `data_classifier/clients/browser/src/generated/`:

1. `constants.js` — scoring thresholds from `engine_defaults.yaml` + `PYTHON_LOGIC_VERSION` SHA.
2. `patterns.js` — 77 patterns as a JSON string constant, examples stripped.
3. `secret-key-names.js` — 178 entries, match-type + tier + subtype preserved.
4. `stopwords.js` — decoded stopwords set.
5. `placeholder-values.js` — placeholder set.
6. `fixtures.json` — runs the Python library over `tester/corpus/seed.jsonl` and writes expected findings, stamped with `PYTHON_LOGIC_VERSION`.

- [ ] **Step 1: Create the seed corpus**

Write `data_classifier/clients/browser/tester/corpus/seed.jsonl`:

```
{"id": "seed_01_plain_prose", "text": "please help me write a cover letter"}
{"id": "seed_02_env_github_pat", "text": "export GITHUB_TOKEN=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
{"id": "seed_03_json_aws_secret", "text": "{\"aws_secret_access_key\": \"wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\"}"}
{"id": "seed_04_code_literal_password", "text": "db_password = \"S3cureP@ss!xyz\""}
{"id": "seed_05_placeholder_only", "text": "export API_KEY=YOUR_API_KEY_HERE"}
```

- [ ] **Step 2: Write the generator**

Write `scripts/generate_browser_patterns.py`:

```python
"""Generate JS assets for data_classifier/clients/browser from the Python source.

Emits six files into data_classifier/clients/browser/src/generated/:

  * constants.js           - scoring thresholds + PYTHON_LOGIC_VERSION SHA
  * patterns.js            - 77 patterns, examples stripped
  * secret-key-names.js    - 178 key-name entries
  * stopwords.js           - decoded stopwords set
  * placeholder-values.js  - placeholder-value set
  * fixtures.json          - seed-corpus expected findings, version-stamped

PYTHON_LOGIC_VERSION is the SHA-256 of the concatenated contents of the Python
logic files that matter for JS parity. A change in any of them invalidates the
JS fixtures and forces the port to follow.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
BROWSER_DIR = REPO_ROOT / "data_classifier" / "clients" / "browser"
GENERATED_DIR = BROWSER_DIR / "src" / "generated"
SEED_PATH = BROWSER_DIR / "tester" / "corpus" / "seed.jsonl"

LOGIC_FILES = [
    REPO_ROOT / "data_classifier" / "engines" / "secret_scanner.py",
    REPO_ROOT / "data_classifier" / "engines" / "regex_engine.py",
    REPO_ROOT / "data_classifier" / "engines" / "validators.py",
    REPO_ROOT / "data_classifier" / "engines" / "parsers.py",
    REPO_ROOT / "data_classifier" / "engines" / "heuristic_engine.py",
    REPO_ROOT / "data_classifier" / "config" / "engine_defaults.yaml",
]

PORTED_VALIDATORS = {"aws_secret_not_hex", "random_password", "not_placeholder_credential", ""}

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("generate_browser_patterns")


def python_logic_version() -> str:
    h = hashlib.sha256()
    for p in sorted(LOGIC_FILES):
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def load_secret_scanner_config() -> dict:
    yaml_path = REPO_ROOT / "data_classifier" / "config" / "engine_defaults.yaml"
    data = yaml.safe_load(yaml_path.read_text())
    return data.get("secret_scanner", {})


def emit_constants(version: str) -> None:
    cfg = load_secret_scanner_config()
    scoring = cfg.get("scoring", {})
    rel = scoring.get("relative_entropy_thresholds", {})
    tiers = scoring.get("tier_boundaries", {})
    js = f"""// GENERATED - do not edit. Run: npm run generate
export const PYTHON_LOGIC_VERSION = {json.dumps(version)};

export const SECRET_SCANNER = {{
  minValueLength: {cfg.get("min_value_length", 8)},
  antiIndicators: {json.dumps(cfg.get("anti_indicators", []))},
  definitiveMultiplier: {scoring.get("definitive_multiplier", 0.95)},
  strongMinEntropyScore: {scoring.get("strong_min_entropy_score", 0.6)},
  relativeEntropyStrong: {rel.get("strong", 0.5)},
  relativeEntropyContextual: {rel.get("contextual", 0.7)},
  diversityThreshold: {scoring.get("diversity_threshold", 3)},
  proseAlphaThreshold: {scoring.get("prose_alpha_threshold", 0.6)},
  tierBoundaryDefinitive: {tiers.get("definitive", 0.9)},
  tierBoundaryStrong: {tiers.get("strong", 0.7)},
}};
"""
    (GENERATED_DIR / "constants.js").write_text(js)
    log.info("wrote constants.js (PYTHON_LOGIC_VERSION=%s)", version)


def emit_patterns() -> None:
    from data_classifier.patterns import load_default_patterns

    patterns = load_default_patterns()
    stub_report: set[str] = set()
    out = []
    for p in patterns:
        if p.validator and p.validator not in PORTED_VALIDATORS:
            stub_report.add(p.validator)
        out.append(
            {
                "name": p.name,
                "regex": p.regex,
                "entity_type": p.entity_type,
                "category": p.category,
                "sensitivity": p.sensitivity,
                "confidence": p.confidence,
                "validator": p.validator,
                "description": p.description,
                "context_words_boost": list(p.context_words_boost),
                "context_words_suppress": list(p.context_words_suppress),
                "stopwords": list(p.stopwords),
                "allowlist_patterns": list(p.allowlist_patterns),
                "requires_column_hint": p.requires_column_hint,
                "column_hint_keywords": list(p.column_hint_keywords),
            }
        )
    if stub_report:
        log.warning(
            "%d pattern(s) reference validators not ported to JS; "
            "they will load with stub validators that always return true: %s",
            len(stub_report),
            sorted(stub_report),
        )
    js = (
        "// GENERATED - do not edit. Run: npm run generate\n"
        "const RAW = " + json.dumps(json.dumps(out)) + ";\n"
        "export const PATTERNS = JSON.parse(RAW);\n"
    )
    (GENERATED_DIR / "patterns.js").write_text(js)
    log.info("wrote patterns.js (%d patterns)", len(out))


def emit_secret_key_names() -> None:
    src = REPO_ROOT / "data_classifier" / "patterns" / "secret_key_names.json"
    data = json.loads(src.read_text())
    entries = data["key_names"]
    js = (
        "// GENERATED - do not edit. Run: npm run generate\n"
        "const RAW = " + json.dumps(json.dumps(entries)) + ";\n"
        "export const SECRET_KEY_NAMES = JSON.parse(RAW);\n"
    )
    (GENERATED_DIR / "secret-key-names.js").write_text(js)
    log.info("wrote secret-key-names.js (%d entries)", len(entries))


def emit_stopwords() -> None:
    from data_classifier.patterns._decoder import decode_encoded_strings

    src = REPO_ROOT / "data_classifier" / "patterns" / "stopwords.json"
    raw = json.loads(src.read_text()).get("stopwords", [])
    decoded = decode_encoded_strings(raw)
    lower = sorted({s.lower() for s in decoded})
    js = (
        "// GENERATED - do not edit. Run: npm run generate\n"
        f"export const STOPWORDS = new Set({json.dumps(lower)});\n"
    )
    (GENERATED_DIR / "stopwords.js").write_text(js)
    log.info("wrote stopwords.js (%d entries)", len(lower))


def emit_placeholder_values() -> None:
    src = REPO_ROOT / "data_classifier" / "patterns" / "known_placeholder_values.json"
    raw = json.loads(src.read_text()).get("placeholder_values", [])
    lower = sorted({s.lower() for s in raw})
    js = (
        "// GENERATED - do not edit. Run: npm run generate\n"
        f"export const PLACEHOLDER_VALUES = new Set({json.dumps(lower)});\n"
    )
    (GENERATED_DIR / "placeholder-values.js").write_text(js)
    log.info("wrote placeholder-values.js (%d entries)", len(lower))


def emit_fixtures(version: str) -> None:
    from data_classifier.core.types import ColumnInput
    from data_classifier.engines.regex_engine import RegexEngine
    from data_classifier.engines.secret_scanner import SecretScannerEngine
    from data_classifier.profiles import load_profile

    profile = load_profile()
    regex_engine = RegexEngine()
    regex_engine.startup()
    scanner_engine = SecretScannerEngine()
    scanner_engine.startup()

    fixtures = {"python_logic_version": version, "cases": []}
    if not SEED_PATH.exists():
        log.warning("seed corpus missing: %s", SEED_PATH)
    else:
        for line in SEED_PATH.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            case = json.loads(line)
            col = ColumnInput(column_id=case["id"], column_name="prompt", sample_values=[case["text"]])
            findings = []
            for f in regex_engine.classify_column(col, profile=profile, min_confidence=0.3):
                if f.category == "Credential":
                    findings.append(
                        {"entity_type": f.entity_type, "category": f.category, "engine": "regex"}
                    )
            for f in scanner_engine.classify_column(col, profile=profile, min_confidence=0.3):
                findings.append(
                    {"entity_type": f.entity_type, "category": f.category, "engine": "secret_scanner"}
                )
            fixtures["cases"].append({"id": case["id"], "text": case["text"], "findings": findings})

    (GENERATED_DIR / "fixtures.json").write_text(json.dumps(fixtures, indent=2))
    log.info("wrote fixtures.json (%d cases)", len(fixtures["cases"]))


def main() -> int:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    version = python_logic_version()
    emit_constants(version)
    emit_patterns()
    emit_secret_key_names()
    emit_stopwords()
    emit_placeholder_values()
    emit_fixtures(version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run the generator**

Run from the repo root:
```
python3 scripts/generate_browser_patterns.py
```

Expected INFO lines (plus a WARNING listing stubbed validators):
```
INFO wrote constants.js (PYTHON_LOGIC_VERSION=<hex16>)
INFO wrote patterns.js (77 patterns)
INFO wrote secret-key-names.js (178 entries)
INFO wrote stopwords.js (42 entries)
INFO wrote placeholder-values.js (34 entries)
INFO wrote fixtures.json (5 cases)
```

- [ ] **Step 4: Verify generated assets exist and parse**

Run:
```
cd data_classifier/clients/browser
node --input-type=module -e "const m = await import('./src/generated/constants.js'); const p = await import('./src/generated/patterns.js'); console.log('version:', m.PYTHON_LOGIC_VERSION); console.log('patterns:', p.PATTERNS.length);"
```

Expected: non-empty version hash, patterns count of 77.

- [ ] **Step 5: Commit**

```
cd /Users/guyguzner/Projects/data_classifier-browser-poc
git add scripts/generate_browser_patterns.py \
        data_classifier/clients/browser/tester/corpus/seed.jsonl
git commit -m "feat(sprint14): Python→JS pattern generator with fixture versioning (Task 5)"
```

---

## Task 6: Regex backend (Stage-1 JS RegExp iteration)

**Files:**
- Create: `data_classifier/clients/browser/src/regex-backend.js`
- Create: `data_classifier/clients/browser/src/finding.js`
- Test: `data_classifier/clients/browser/tests/unit/regex-backend.test.js`

The backend compiles all patterns once per worker init, iterates every pattern against input (Stage-1 fallback for the Python RE2 Set), and emits raw match objects. Stopwords and allowlist checks are applied inside the backend; validator + context adjustment happen in scanner-core. Uses `String.prototype.matchAll` to iterate regex matches.

- [ ] **Step 1: Write the finding factory**

Write `data_classifier/clients/browser/src/finding.js`:

```js
// Shared helpers for building Finding objects that match the shape in the
// design doc. Keeping this in its own module lets unit tests avoid
// hand-building findings (which is brittle and drifts from the spec).

export function maskValue(value, entityType) {
  if (value.length <= 4) return '*'.repeat(value.length);
  if (entityType === 'EMAIL') {
    const at = value.indexOf('@');
    if (at > 1) return value[0] + '*'.repeat(at - 1) + value.slice(at);
  }
  return value[0] + '*'.repeat(value.length - 2) + value[value.length - 1];
}

export function makeFinding({
  entityType,
  category,
  sensitivity,
  confidence,
  engine,
  evidence,
  match,
  kv,
  details,
}) {
  const f = { entity_type: entityType, category, sensitivity, confidence, engine, evidence, match };
  if (kv) f.kv = kv;
  if (details) f.details = details;
  return f;
}
```

- [ ] **Step 2: Write the failing test**

Write `data_classifier/clients/browser/tests/unit/regex-backend.test.js`:

```js
import { describe, it, expect } from 'vitest';
import { createBackend } from '../../src/regex-backend.js';

const SAMPLE_PATTERNS = [
  {
    name: 'github_pat_like',
    regex: 'ghp_[A-Za-z0-9]{20,}',
    entity_type: 'API_KEY',
    category: 'Credential',
    sensitivity: 'CRITICAL',
    confidence: 0.95,
    validator: '',
    description: 'Test github-style PAT',
    context_words_boost: [],
    context_words_suppress: [],
    stopwords: [],
    allowlist_patterns: [],
    requires_column_hint: false,
    column_hint_keywords: [],
  },
  {
    name: 'password_gate',
    regex: '[A-Za-z0-9!@#$%^&*]{8,}',
    entity_type: 'PASSWORD',
    category: 'Credential',
    sensitivity: 'CRITICAL',
    confidence: 0.5,
    validator: 'random_password',
    description: 'Needs a validator',
    context_words_boost: [],
    context_words_suppress: [],
    stopwords: [],
    allowlist_patterns: [],
    requires_column_hint: false,
    column_hint_keywords: [],
  },
];

describe('createBackend', () => {
  it('iterates patterns and yields matches with start/end offsets', () => {
    const backend = createBackend(SAMPLE_PATTERNS, new Set(), new Set());
    const text = 'token=ghp_aaaaaaaaaaaaaaaaaaaaBBBB remaining prose';
    const matches = backend.iterate(text);
    const pat = matches.find((m) => m.pattern.name === 'github_pat_like');
    expect(pat).toBeDefined();
    expect(pat.value.startsWith('ghp_')).toBe(true);
    expect(pat.start).toBeGreaterThan(0);
    expect(pat.end).toBe(pat.start + pat.value.length);
    expect(text.slice(pat.start, pat.end)).toBe(pat.value);
  });

  it('skips stopwords (case-insensitive)', () => {
    const stop = new Set(['ghp_placeholder_dont_match_me_12345']);
    const backend = createBackend(SAMPLE_PATTERNS, stop, new Set());
    const matches = backend.iterate('token=ghp_placeholder_dont_match_me_12345 rest');
    expect(matches.find((m) => m.pattern.name === 'github_pat_like')).toBeUndefined();
  });

  it('resolves the validator by name', () => {
    const backend = createBackend(SAMPLE_PATTERNS, new Set(), new Set());
    const matches = backend.iterate('pw=Abc123!xyz done');
    const pwMatch = matches.find((m) => m.pattern.name === 'password_gate');
    expect(pwMatch).toBeDefined();
    expect(pwMatch.validator(pwMatch.value)).toBe(true);
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run:
```
npx vitest run tests/unit/regex-backend.test.js
```

Expected: FAIL with module-not-found.

- [ ] **Step 4: Write the implementation**

Write `data_classifier/clients/browser/src/regex-backend.js`:

```js
// Stage-1 regex backend: JS RegExp iteration over all patterns.
// Stage 2 (re2-wasm) reimplements this module against the same interface.

import { resolveValidator } from './validators.js';

export function createBackend(patterns, stopwordsSet, placeholderSet) {
  const compiled = patterns.map((p) => ({
    pattern: p,
    re: safeCompile(p.regex),
    validator: resolveValidator(p.validator, {
      notPlaceholderCredential: makeNotPlaceholder(placeholderSet),
    }),
  }));

  function iterate(text) {
    const out = [];
    for (const { pattern, re, validator } of compiled) {
      if (!re) continue;
      for (const m of text.matchAll(re)) {
        const value = m[0];
        if (valueIsStopword(value, pattern, stopwordsSet)) continue;
        if (matchesAllowlist(value, pattern)) continue;
        out.push({
          pattern,
          value,
          start: m.index,
          end: m.index + value.length,
          validator,
        });
      }
    }
    return out;
  }

  return { iterate };
}

function safeCompile(regex) {
  try {
    return new RegExp(regex, 'g');
  } catch {
    return null;
  }
}

function valueIsStopword(value, pattern, globalStopwords) {
  const lower = value.toLowerCase().trim();
  for (const s of pattern.stopwords || []) {
    if (s.toLowerCase() === lower) return true;
  }
  return globalStopwords.has(lower);
}

function matchesAllowlist(value, pattern) {
  for (const allow of pattern.allowlist_patterns || []) {
    try {
      if (new RegExp(allow).test(value)) return true;
    } catch {
      // invalid allowlist regex — ignore
    }
  }
  return false;
}

function makeNotPlaceholder(placeholderSet) {
  return function notPlaceholderCredential(value) {
    return !placeholderSet.has(value.trim().toLowerCase());
  };
}
```

- [ ] **Step 5: Run test to verify it passes**

Run:
```
npx vitest run tests/unit/regex-backend.test.js
```

Expected: PASS, 3 tests green.

- [ ] **Step 6: Commit**

```
git add data_classifier/clients/browser/src/regex-backend.js \
        data_classifier/clients/browser/src/finding.js \
        data_classifier/clients/browser/tests/unit/regex-backend.test.js
git commit -m "feat(sprint14): Stage-1 JS RegExp backend + finding helpers (Task 6)"
```

---

## Task 7: Redaction module

**Files:**
- Create: `data_classifier/clients/browser/src/redaction.js`
- Test: `data_classifier/clients/browser/tests/unit/redaction.test.js`

Four strategies: `type-label` (default), `asterisk`, `placeholder`, `none`. Right-to-left replacement so earlier offsets remain valid.

- [ ] **Step 1: Write the failing test**

Write `data_classifier/clients/browser/tests/unit/redaction.test.js`:

```js
import { describe, it, expect } from 'vitest';
import { redact } from '../../src/redaction.js';

describe('redact', () => {
  const text = 'Hello API_KEY=ghp_abc123 and AUTH=xyz';
  const findings = [
    {
      entity_type: 'API_KEY',
      match: { valueMasked: 'gh***23', start: 14, end: 24 },
    },
    {
      entity_type: 'OPAQUE_SECRET',
      match: { valueMasked: 'x**z', start: 34, end: 37 },
      kv: { key: 'AUTH', tier: 'definitive' },
    },
  ];

  it('type-label (default) replaces each span with [REDACTED:<TYPE>]', () => {
    expect(redact(text, findings, 'type-label')).toBe(
      'Hello API_KEY=[REDACTED:API_KEY] and AUTH=[REDACTED:OPAQUE_SECRET]'
    );
  });

  it('asterisk preserves length', () => {
    const redacted = redact(text, findings, 'asterisk');
    expect(redacted.length).toBe(text.length);
    expect(redacted).toBe('Hello API_KEY=********** and AUTH=***');
  });

  it('placeholder uses a fixed token', () => {
    expect(redact(text, findings, 'placeholder')).toBe(
      'Hello API_KEY=«secret» and AUTH=«secret»'
    );
  });

  it('none returns the text unchanged', () => {
    expect(redact(text, findings, 'none')).toBe(text);
  });

  it('handles multiple non-overlapping findings via right-to-left replacement', () => {
    const t = '0123456789';
    const fs = [
      { entity_type: 'A', match: { start: 0, end: 4 } },
      { entity_type: 'B', match: { start: 6, end: 9 } },
    ];
    expect(redact(t, fs, 'type-label')).toBe('[REDACTED:A]45[REDACTED:B]9');
  });

  it('throws on unknown strategy', () => {
    expect(() => redact(text, findings, 'unknown')).toThrow();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```
npx vitest run tests/unit/redaction.test.js
```

Expected: FAIL with module-not-found.

- [ ] **Step 3: Write the implementation**

Write `data_classifier/clients/browser/src/redaction.js`:

```js
// Redaction strategies. Right-to-left replacement so earlier offsets
// remain valid as the text mutates. For KV findings the match span is
// already the value only (parsers emit valueStart/valueEnd inside the
// quotes), so the key stays visible naturally.

const STRATEGIES = new Set(['type-label', 'asterisk', 'placeholder', 'none']);

export function redact(text, findings, strategy = 'type-label') {
  if (!STRATEGIES.has(strategy)) {
    throw new Error(`redact: unknown strategy "${strategy}"`);
  }
  if (strategy === 'none' || !findings.length) return text;

  const sorted = [...findings].sort((a, b) => b.match.start - a.match.start);
  let out = text;
  for (const f of sorted) {
    const replacement = replacementFor(f, strategy);
    out = out.slice(0, f.match.start) + replacement + out.slice(f.match.end);
  }
  return out;
}

function replacementFor(finding, strategy) {
  const length = finding.match.end - finding.match.start;
  switch (strategy) {
    case 'type-label':
      return `[REDACTED:${finding.entity_type}]`;
    case 'asterisk':
      return '*'.repeat(length);
    case 'placeholder':
      return '«secret»';
    default:
      throw new Error(`redact: unknown strategy "${strategy}"`);
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```
npx vitest run tests/unit/redaction.test.js
```

Expected: PASS, 6 tests green.

- [ ] **Step 5: Commit**

```
git add data_classifier/clients/browser/src/redaction.js \
        data_classifier/clients/browser/tests/unit/redaction.test.js
git commit -m "feat(sprint14): redaction module with four strategies (Task 7)"
```

---

## Task 8: Scanner-core — regex pass + secret-scanner pass

**Files:**
- Create: `data_classifier/clients/browser/src/scanner-core.js`
- Test: `data_classifier/clients/browser/tests/unit/scanner-core.test.js`

Orchestrates the two passes and produces `{findings, redactedText, scannedMs}`. Reads patterns, key names, stopwords, placeholders, and constants from `src/generated/`.

- [ ] **Step 1: Write the failing test**

Write `data_classifier/clients/browser/tests/unit/scanner-core.test.js`:

```js
import { describe, it, expect } from 'vitest';
import { scanText } from '../../src/scanner-core.js';

describe('scanText — regex pass', () => {
  it('detects a GitHub PAT in env-file text and returns a redacted output', () => {
    const text = 'please set export GITHUB_TOKEN=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa thanks';
    const { findings, redactedText, scannedMs } = scanText(text, {});
    expect(findings.length).toBeGreaterThan(0);
    const f = findings.find((x) => x.category === 'Credential');
    expect(f).toBeDefined();
    expect(redactedText.includes('ghp_aaaaaaaaaa')).toBe(false);
    expect(scannedMs).toBeGreaterThanOrEqual(0);
  });
});

describe('scanText — secret-scanner pass', () => {
  it('fires on a KV pair whose key is "api_key" and value has high entropy', () => {
    const text = 'api_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"';
    const { findings } = scanText(text, {});
    const f = findings.find((x) => x.engine === 'secret_scanner');
    expect(f).toBeDefined();
    expect(['API_KEY', 'OPAQUE_SECRET', 'PRIVATE_KEY']).toContain(f.entity_type);
  });

  it('does not fire on a placeholder value', () => {
    const text = 'api_key = "changeme"';
    const { findings } = scanText(text, {});
    expect(findings.find((x) => x.engine === 'secret_scanner')).toBeUndefined();
  });
});

describe('scanText — verbose mode', () => {
  it('attaches details only when verbose=true', () => {
    const text = 'export TOKEN=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
    const plain = scanText(text, { verbose: false }).findings[0];
    const verbose = scanText(text, { verbose: true }).findings[0];
    expect(plain.details).toBeUndefined();
    expect(verbose.details).toBeDefined();
    expect(typeof verbose.details.pattern).toBe('string');
  });
});

describe('scanText — raw values', () => {
  it('omits valueRaw by default', () => {
    const text = 'export TOKEN=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
    const f = scanText(text, {}).findings[0];
    expect(f.match.valueRaw).toBeUndefined();
  });

  it('includes valueRaw when dangerouslyIncludeRawValues=true', () => {
    const text = 'export TOKEN=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
    const f = scanText(text, { dangerouslyIncludeRawValues: true }).findings[0];
    expect(f.match.valueRaw).toBeTypeOf('string');
    expect(f.match.valueRaw.startsWith('ghp_')).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```
npx vitest run tests/unit/scanner-core.test.js
```

Expected: FAIL (module-not-found until step 3 lands; `pretest` hook ensures `src/generated/` is populated).

- [ ] **Step 3: Write the implementation**

Write `data_classifier/clients/browser/src/scanner-core.js`:

```js
// Scanner-core: orchestrates the regex pass + secret-scanner pass.
// Returns { findings, redactedText, scannedMs }.

import { PATTERNS } from './generated/patterns.js';
import { SECRET_KEY_NAMES } from './generated/secret-key-names.js';
import { STOPWORDS } from './generated/stopwords.js';
import { PLACEHOLDER_VALUES } from './generated/placeholder-values.js';
import { SECRET_SCANNER } from './generated/constants.js';

import { createBackend } from './regex-backend.js';
import { parseKeyValues } from './kv-parsers.js';
import { maskValue, makeFinding } from './finding.js';
import { redact } from './redaction.js';
import {
  shannonEntropy,
  relativeEntropy,
  detectCharset,
  charClassDiversity,
  scoreRelativeEntropy,
} from './entropy.js';

let backendCache = null;

function getBackend(categoryFilter) {
  const key = categoryFilter.join('|');
  if (backendCache && backendCache.key === key) return backendCache.backend;
  const filtered = PATTERNS.filter((p) => categoryFilter.includes(p.category));
  const backend = createBackend(filtered, STOPWORDS, PLACEHOLDER_VALUES);
  backendCache = { key, backend };
  return backend;
}

export function scanText(text, opts = {}) {
  const t0 = performanceNowSafe();
  const verbose = !!opts.verbose;
  const includeRaw = !!opts.dangerouslyIncludeRawValues;
  const categoryFilter = opts.categoryFilter || ['Credential'];
  const redactStrategy = opts.redactStrategy || 'type-label';

  const findings = [];
  findings.push(...regexPass(text, categoryFilter, verbose, includeRaw));
  findings.push(...secretScannerPass(text, verbose, includeRaw));

  const redactedText = redact(text, findings, redactStrategy);
  return { findings, redactedText, scannedMs: performanceNowSafe() - t0 };
}

function regexPass(text, categoryFilter, verbose, includeRaw) {
  const backend = getBackend(categoryFilter);
  const matches = backend.iterate(text);
  const out = [];
  for (const m of matches) {
    const validated = m.validator(m.value);
    if (!validated) continue;
    const p = m.pattern;
    const match = { valueMasked: maskValue(m.value, p.entity_type), start: m.start, end: m.end };
    if (includeRaw) match.valueRaw = m.value;
    out.push(
      makeFinding({
        entityType: p.entity_type,
        category: p.category,
        sensitivity: p.sensitivity,
        confidence: p.confidence,
        engine: 'regex',
        evidence: `Regex: ${p.entity_type} pattern "${p.name}" matched`,
        match,
        details: verbose
          ? {
              pattern: p.name,
              validator: m.validator.isStub ? 'stubbed' : p.validator ? 'passed' : 'none',
            }
          : undefined,
      })
    );
  }
  return out;
}

function secretScannerPass(text, verbose, includeRaw) {
  const pairs = parseKeyValues(text);
  const out = [];
  for (const { key, value, valueStart, valueEnd } of pairs) {
    if (value.length < SECRET_SCANNER.minValueLength) continue;
    if (hasAntiIndicator(key, value)) continue;
    if (PLACEHOLDER_VALUES.has(value.toLowerCase())) continue;
    const { score, tier, subtype } = scoreKeyName(key);
    if (score <= 0) continue;
    const composite = tieredScore(score, tier, value);
    if (composite <= 0) continue;
    const entityType = subtype || 'OPAQUE_SECRET';
    const rel = relativeEntropy(value);
    const charset = detectCharset(value);
    const match = { valueMasked: maskValue(value, entityType), start: valueStart, end: valueEnd };
    if (includeRaw) match.valueRaw = value;
    out.push(
      makeFinding({
        entityType,
        category: 'Credential',
        sensitivity: 'CRITICAL',
        confidence: Math.round(composite * 10000) / 10000,
        engine: 'secret_scanner',
        evidence:
          `secret_scanner: key "${key}" score=${score.toFixed(2)} tier=${tier} ` +
          `charset=${charset} relative_entropy=${rel.toFixed(2)} composite=${composite.toFixed(2)}`,
        match,
        kv: { key, tier },
        details: verbose
          ? {
              pattern: 'secret_scanner',
              validator: 'none',
              entropy: {
                shannon: shannonEntropy(value),
                relative: rel,
                charset,
                score: scoreRelativeEntropy(rel),
              },
              tier,
            }
          : undefined,
      })
    );
  }
  return out;
}

function scoreKeyName(key) {
  const lower = key.toLowerCase();
  let best = { score: 0, tier: '', subtype: 'OPAQUE_SECRET' };
  for (const entry of SECRET_KEY_NAMES) {
    if (!matchKey(lower, entry.pattern, entry.match_type)) continue;
    if (entry.score > best.score) {
      best = { score: entry.score, tier: entry.tier, subtype: entry.subtype };
    }
  }
  return best;
}

function matchKey(keyLower, pattern, matchType) {
  if (matchType === 'word_boundary') {
    const re = new RegExp(`(^|[_\\-\\s.])${escapeRegex(pattern)}($|[_\\-\\s.])`);
    return re.test(keyLower);
  }
  if (matchType === 'suffix') {
    const re = new RegExp(`[_\\-\\s.]${escapeRegex(pattern)}$`);
    return re.test(keyLower);
  }
  return keyLower.includes(pattern);
}

function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function tieredScore(keyScore, tier, value) {
  if (tier === 'definitive') {
    if (valueIsObviouslyNotSecret(value)) return 0;
    return keyScore * SECRET_SCANNER.definitiveMultiplier;
  }
  const rel = relativeEntropy(value);
  const div = charClassDiversity(value);
  if (tier === 'strong') {
    if (rel >= SECRET_SCANNER.relativeEntropyStrong || div >= SECRET_SCANNER.diversityThreshold) {
      return keyScore * Math.max(SECRET_SCANNER.strongMinEntropyScore, scoreRelativeEntropy(rel));
    }
    return 0;
  }
  if (rel >= SECRET_SCANNER.relativeEntropyContextual && div >= SECRET_SCANNER.diversityThreshold) {
    return keyScore * scoreRelativeEntropy(rel);
  }
  return 0;
}

function valueIsObviouslyNotSecret(value) {
  const v = value.toLowerCase().trim();
  if (['true', 'false', 'yes', 'no', 'none', 'null'].includes(v)) return true;
  if (/^https?:\/\//i.test(value)) return true;
  if (/^\d{4}[-/]\d{2}[-/]\d{2}/.test(value)) return true;
  if (value.includes(' ')) {
    let alpha = 0;
    for (const c of value) if (/[A-Za-z]/.test(c)) alpha++;
    if (alpha / value.length > SECRET_SCANNER.proseAlphaThreshold) return true;
  }
  return false;
}

function hasAntiIndicator(key, value) {
  const kl = key.toLowerCase();
  const vl = value.toLowerCase();
  for (const ai of SECRET_SCANNER.antiIndicators) {
    const a = ai.toLowerCase();
    if (kl.includes(a) || vl.includes(a)) return true;
  }
  return false;
}

function performanceNowSafe() {
  if (typeof performance !== 'undefined' && performance.now) return performance.now();
  const [s, ns] = process.hrtime();
  return s * 1000 + ns / 1e6;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```
npx vitest run tests/unit/scanner-core.test.js
```

Expected: PASS.

- [ ] **Step 5: Commit**

```
git add data_classifier/clients/browser/src/scanner-core.js \
        data_classifier/clients/browser/tests/unit/scanner-core.test.js
git commit -m "feat(sprint14): scanner-core composes regex + secret-scanner passes (Task 8)"
```

---

## Task 9: Worker shim

**Files:**
- Create: `data_classifier/clients/browser/src/worker.js`

No unit test for the shim alone — it is covered by pool tests and e2e. Purpose: receive `{id, text, opts}` via `postMessage`, run `scanText`, post back `{id, result}` or `{id, error}`.

- [ ] **Step 1: Write the shim**

Write `data_classifier/clients/browser/src/worker.js`:

```js
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
```

- [ ] **Step 2: Verify it builds**

Run:
```
cd data_classifier/clients/browser
npm run build
```

Expected: esbuild emits `dist/scanner.esm.js` and `dist/worker.esm.js` with no errors.

- [ ] **Step 3: Commit**

```
git add data_classifier/clients/browser/src/worker.js
git commit -m "feat(sprint14): worker shim routing messages to scanner-core (Task 9)"
```

---

## Task 10: Worker pool — size 2, lazy, respawn, MV3-aware

**Files:**
- Create: `data_classifier/clients/browser/src/pool.js`
- Test: `data_classifier/clients/browser/tests/unit/pool.test.js`

Size 2 workers; lazy init (first `run()` spawns); on `run()` timeout, terminate and respawn lazily; queue requests if both workers are busy. The `onServiceWorkerSuspend()` hook terminates all workers; the extension wires it up, the scaffold just defines it.

- [ ] **Step 1: Write the failing test**

Write `data_classifier/clients/browser/tests/unit/pool.test.js`:

```js
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
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```
npx vitest run tests/unit/pool.test.js
```

Expected: FAIL with module-not-found.

- [ ] **Step 3: Write the implementation**

Write `data_classifier/clients/browser/src/pool.js`:

```js
// Worker pool — size 2, lazy init, eager respawn on timeout, MV3-aware.
// The spawn function is injected so tests can mock it; in production, callers
// pass () => new Worker(new URL('./worker.js', import.meta.url), {type:'module'}).

export function createPool({ size = 2, spawn }) {
  const workers = []; // { worker, busy, listeners }
  const queue = [];
  let nextId = 0;

  function getFreeWorker() {
    for (const slot of workers) if (!slot.busy) return slot;
    if (workers.length < size) {
      const slot = { worker: spawn(), busy: false, listeners: new Map() };
      slot.worker.addEventListener('message', (event) => {
        const { id, result, error } = event.data || {};
        const resolver = slot.listeners.get(id);
        if (!resolver) return;
        slot.listeners.delete(id);
        slot.busy = false;
        if (error) resolver.reject(error);
        else resolver.resolve(result);
        pumpQueue();
      });
      workers.push(slot);
      return slot;
    }
    return null;
  }

  function pumpQueue() {
    while (queue.length) {
      const slot = getFreeWorker();
      if (!slot) return;
      const req = queue.shift();
      dispatch(slot, req);
    }
  }

  function dispatch(slot, req) {
    slot.busy = true;
    const id = ++nextId;
    const { text, opts, timeoutMs = 100, failMode = 'open', resolve, reject } = req;
    let timer;
    const cleanup = () => {
      clearTimeout(timer);
      slot.listeners.delete(id);
    };
    slot.listeners.set(id, {
      resolve: (result) => { cleanup(); resolve(result); },
      reject: (error) => { cleanup(); reject(error); },
    });
    timer = setTimeout(() => {
      cleanup();
      slot.worker.terminate();
      const idx = workers.indexOf(slot);
      if (idx >= 0) workers.splice(idx, 1);
      if (failMode === 'closed') reject({ code: 'TIMEOUT' });
      else resolve({ findings: [], redactedText: text, scannedMs: timeoutMs });
      pumpQueue();
    }, timeoutMs);
    slot.worker.postMessage({ id, text, opts });
  }

  function run({ text, opts = {}, timeoutMs = 100, failMode = 'open' }) {
    return new Promise((resolve, reject) => {
      const req = { text, opts, timeoutMs, failMode, resolve, reject };
      const slot = getFreeWorker();
      if (slot) dispatch(slot, req);
      else queue.push(req);
    });
  }

  function onServiceWorkerSuspend() {
    for (const slot of workers) slot.worker.terminate();
    workers.length = 0;
  }

  return { run, onServiceWorkerSuspend };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```
npx vitest run tests/unit/pool.test.js
```

Expected: PASS, 4 tests green.

- [ ] **Step 5: Commit**

```
git add data_classifier/clients/browser/src/pool.js \
        data_classifier/clients/browser/tests/unit/pool.test.js
git commit -m "feat(sprint14): worker pool size-2 lazy/respawn/MV3-aware (Task 10)"
```

---

## Task 11: Public scanner API

**Files:**
- Create: `data_classifier/clients/browser/src/scanner.js`

The public entry point. Wires the pool to a default spawner that creates real workers from `./worker.js`. Callers can inject their own spawner.

- [ ] **Step 1: Write the implementation**

Write `data_classifier/clients/browser/src/scanner.js`:

```js
// Public API. Example:
//   import { createScanner } from '@data-classifier/browser';
//   const scanner = createScanner();
//   const { findings, redactedText } = await scanner.scan(text);

import { createPool } from './pool.js';

function defaultSpawn() {
  return new Worker(new URL('./worker.js', import.meta.url), { type: 'module' });
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
```

- [ ] **Step 2: Verify the bundle builds**

Run:
```
cd data_classifier/clients/browser
npm run build
```

Expected: `dist/scanner.esm.js` and `dist/worker.esm.js` both present.

- [ ] **Step 3: Commit**

```
git add data_classifier/clients/browser/src/scanner.js
git commit -m "feat(sprint14): public scanner API wiring pool + worker (Task 11)"
```

---

## Task 12: Tester page

**Files:**
- Create: `data_classifier/clients/browser/tester/index.html`
- Create: `data_classifier/clients/browser/tester/tester.js`

Minimal page: textarea for input, button to scan, findings rendered as JSON.

- [ ] **Step 1: Write the HTML**

Write `data_classifier/clients/browser/tester/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>data_classifier browser tester</title>
    <style>
      body { font: 14px/1.4 system-ui, sans-serif; margin: 2em; max-width: 900px; }
      textarea { width: 100%; height: 180px; font-family: ui-monospace, monospace; }
      pre { background: #f5f5f5; padding: 1em; overflow: auto; max-height: 400px; }
      .row { margin-bottom: 1em; }
      button { padding: 0.5em 1em; }
      label { display: block; margin-bottom: 0.25em; font-weight: 600; }
    </style>
  </head>
  <body>
    <h1>data_classifier — browser secret detector (tester)</h1>
    <p>
      Paste text below and click Scan. This page imports the built scanner from
      <code>../dist/scanner.esm.js</code>. Run <code>npm run build</code> first if the page errors.
    </p>

    <div class="row">
      <label for="input">Input text</label>
      <textarea id="input" placeholder="export API_KEY=ghp_..."></textarea>
    </div>

    <div class="row">
      <label><input type="checkbox" id="verbose" /> verbose (include details)</label>
      <label>
        Redact strategy:
        <select id="strategy">
          <option value="type-label">type-label (default)</option>
          <option value="asterisk">asterisk</option>
          <option value="placeholder">placeholder</option>
          <option value="none">none</option>
        </select>
      </label>
      <button id="scan-btn">Scan</button>
    </div>

    <div class="row">
      <label>Redacted text</label>
      <pre id="redacted-out"></pre>
    </div>

    <div class="row">
      <label>Findings</label>
      <pre id="findings-out"></pre>
    </div>

    <script type="module" src="./tester.js"></script>
  </body>
</html>
```

- [ ] **Step 2: Write the tester script**

Write `data_classifier/clients/browser/tester/tester.js`:

```js
import { createScanner } from '../dist/scanner.esm.js';

const scanner = createScanner();
const inputEl = document.getElementById('input');
const verboseEl = document.getElementById('verbose');
const strategyEl = document.getElementById('strategy');
const btnEl = document.getElementById('scan-btn');
const redactedOut = document.getElementById('redacted-out');
const findingsOut = document.getElementById('findings-out');

btnEl.addEventListener('click', async () => {
  const text = inputEl.value;
  const opts = {
    verbose: verboseEl.checked,
    redactStrategy: strategyEl.value,
  };
  try {
    const { findings, redactedText, scannedMs } = await scanner.scan(text, opts);
    redactedOut.textContent = redactedText;
    findingsOut.textContent = JSON.stringify({ scannedMs, findings }, null, 2);
  } catch (err) {
    findingsOut.textContent = 'error: ' + ((err && err.message) || err);
  }
});
```

- [ ] **Step 3: Verify the tester page loads**

Run:
```
cd data_classifier/clients/browser
npm run build
npx --yes http-server . -p 4173 -c-1 >/tmp/hs.log 2>&1 &
SERVER_PID=$!
sleep 1
curl -sI http://127.0.0.1:4173/tester/ | head -1
kill $SERVER_PID
```

Expected: `HTTP/1.1 200 OK`.

- [ ] **Step 4: Commit**

```
git add data_classifier/clients/browser/tester/index.html \
        data_classifier/clients/browser/tester/tester.js
git commit -m "feat(sprint14): tester page for manual scanner exercise (Task 12)"
```

---

## Task 13: Playwright e2e — tester smoke + timeout

**Files:**
- Create: `data_classifier/clients/browser/tests/e2e/tester.spec.js`
- Create: `data_classifier/clients/browser/tests/e2e/timeout.spec.js`

Uses the Playwright `webServer` config from Task 0.

- [ ] **Step 1: Write the tester smoke spec**

Write `data_classifier/clients/browser/tests/e2e/tester.spec.js`:

```js
import { test, expect } from '@playwright/test';

test('tester page detects a GitHub PAT', async ({ page }) => {
  await page.goto('/tester/');
  await page.fill(
    '#input',
    'please set export GITHUB_TOKEN=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa done'
  );
  await page.click('#scan-btn');
  const findings = await page.locator('#findings-out').textContent();
  expect(findings).toMatch(/"category":\s*"Credential"/);

  const redacted = await page.locator('#redacted-out').textContent();
  expect(redacted).not.toContain('ghp_aaaaaaaaaaaaaaaa');
});
```

- [ ] **Step 2: Write the timeout spec**

Write `data_classifier/clients/browser/tests/e2e/timeout.spec.js`:

```js
import { test, expect } from '@playwright/test';

// Pathological input designed to be slow under backtracking regex.
// Worker kill budget should terminate and fail-open.
test('worker terminate on pathological input under fail-open', async ({ page }) => {
  await page.goto('/tester/');
  const pathological = 'a'.repeat(50_000) + '!';
  await page.fill('#input', pathological);
  await page.click('#scan-btn');

  await page.waitForSelector('#findings-out:not(:empty)', { timeout: 10_000 });
  const findings = await page.locator('#findings-out').textContent();
  expect(findings).toContain('scannedMs');
});
```

- [ ] **Step 3: Install Playwright browsers and run e2e**

Run:
```
cd data_classifier/clients/browser
npx playwright install chromium
npm run test:e2e
```

Expected: both tests pass.

- [ ] **Step 4: Commit**

```
git add data_classifier/clients/browser/tests/e2e/tester.spec.js \
        data_classifier/clients/browser/tests/e2e/timeout.spec.js
git commit -m "feat(sprint14): e2e smoke + timeout specs via Playwright (Task 13)"
```

---

## Task 14: Smoke benchmark

**Files:**
- Create: `data_classifier/clients/browser/tester/corpus/bench/prompts.jsonl`
- Create: `data_classifier/clients/browser/tests/e2e/bench.spec.js`

Synthetic 1K-prompt batch scanned in headless Chrome. Labeled as order-of-magnitude; S2 remains the honest measurement.

- [ ] **Step 1: Create the synthetic corpus**

Write `data_classifier/clients/browser/tester/corpus/bench/prompts.jsonl`:

```
{"text": "please help me write a short thank-you note for my colleague"}
{"text": "what are common causes of high CPU usage on Linux servers?"}
{"text": "export API_KEY=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
{"text": "here's a JSON: {\"db_password\": \"S3cureP@ss!xyz\"}"}
{"text": "the AUTH_TOKEN=abcdef1234567890 will expire tomorrow"}
{"text": "I need a recipe for a quick vegetarian dinner"}
{"text": "could you debug this code snippet for me:\nfunction foo(x){return x+1}"}
{"text": "aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"}
{"text": "what's the capital of Portugal?"}
{"text": "my password_here should be changeme please suggest a strong one"}
```

- [ ] **Step 2: Write the bench spec**

Write `data_classifier/clients/browser/tests/e2e/bench.spec.js`:

```js
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
    { prompts, targetScans: TARGET_SCANS }
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
```

- [ ] **Step 3: Run the benchmark**

Run:
```
cd data_classifier/clients/browser
npm run bench
```

Expected: test passes; stdout shows the summary block.

- [ ] **Step 4: Commit**

```
git add data_classifier/clients/browser/tester/corpus/bench/prompts.jsonl \
        data_classifier/clients/browser/tests/e2e/bench.spec.js
git commit -m "feat(sprint14): smoke latency benchmark (Task 14)"
```

---

## Task 15: Differential test skeleton

**Files:**
- Create: `data_classifier/clients/browser/tests/e2e/differential.spec.js`

Loads `src/generated/fixtures.json` (produced by the Python generator), asserts `PYTHON_LOGIC_VERSION` matches, and runs the JS scanner over each seed case comparing `findings` (entity_type + engine + category — offsets are metadata, excluded from parity).

- [ ] **Step 1: Write the spec**

Write `data_classifier/clients/browser/tests/e2e/differential.spec.js`:

```js
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
```

- [ ] **Step 2: Run the differential**

Run:
```
cd data_classifier/clients/browser
npm run test:e2e -- tests/e2e/differential.spec.js
```

Expected: PASS.

- [ ] **Step 3: Commit**

```
git add data_classifier/clients/browser/tests/e2e/differential.spec.js
git commit -m "feat(sprint14): differential test skeleton gated by PYTHON_LOGIC_VERSION (Task 15)"
```

---

## Task 16: README

**Files:**
- Create: `data_classifier/clients/browser/README.md`

- [ ] **Step 1: Write the README**

Write `data_classifier/clients/browser/README.md`:

```markdown
# data_classifier — browser client (PoC)

Client-side secret detection engine, ported from the Python
`data_classifier` library. Scans user-submitted text (e.g. a prompt
about to be sent to a chat AI) and returns findings + a redacted
version.

> **Scaffold — not yet published.** Tracks Sprint 14 item
> `sprint14/browser-poc-secret`. Honest performance + full pattern
> coverage arrive in subsequent sprint items. See
> `docs/superpowers/specs/2026-04-16-browser-poc-scaffold-design.md`.

## Usage

\`\`\`js
import { createScanner } from '@data-classifier/browser';

const scanner = createScanner();
const { findings, redactedText, scannedMs } = await scanner.scan(
  'export API_KEY=ghp_...'
);
\`\`\`

### Options

\`\`\`js
scanner.scan(text, {
  timeoutMs: 100,                 // kill budget
  failMode: 'open',               // 'open' → empty findings on timeout
                                  // 'closed' → rejects with {code:'TIMEOUT'}
  redactStrategy: 'type-label',   // | 'asterisk' | 'placeholder' | 'none'
  verbose: false,                 // include a `details` block per finding
  dangerouslyIncludeRawValues: false,   // see WARNING below
  categoryFilter: ['Credential'],       // v1 Credential-only by default
});
\`\`\`

## Development

\`\`\`
npm install
npm run generate      # regenerates src/generated/ from the Python library
npm run build         # esbuild → dist/
npm run test:unit     # Vitest
npm run test:e2e      # Playwright (builds first)
npm run bench         # order-of-magnitude latency benchmark
\`\`\`

`src/generated/` is gitignored. The `pretest` hook runs `generate`
every time, so generated assets are always fresh.

## ⚠️ Raw-value escape hatch

`scan(text, { dangerouslyIncludeRawValues: true })` populates
`match.valueRaw` with the unmasked matched value.

**Never enable in production.** Use only for local fixture authoring
and differential-test diagnostics. Any telemetry or log pipeline
that could receive a finding from this code path must strip
`valueRaw` before emit.

## Python ↔ JS sync

See the "Python → JS sync" section of the design spec. In short:

- **Data** (patterns, key names, stopwords, placeholders) — emitted
  by `scripts/generate_browser_patterns.py`. Run `npm run generate`.
- **Scoring parameters** (`engine_defaults.yaml`) — also emitted by
  the generator as `constants.js`. Run `npm run generate`.
- **Algorithm changes** — the generator SHAs the Python logic files
  into `PYTHON_LOGIC_VERSION` and stamps both fixtures and
  constants. If Python's logic changes, the differential test fails
  until the JS port follows.

## Architecture pointers

- `src/scanner.js` — public API.
- `src/pool.js` — 2-worker pool, lazy init, eager respawn, MV3-aware hook.
- `src/worker.js` — worker shim routing messages to scanner-core.
- `src/scanner-core.js` — orchestration of regex + secret-scanner passes.
- `src/regex-backend.js` — Stage-1 JS `RegExp` backend; Stage 2 swap target.
- `src/kv-parsers.js` — JSON / env / code-literal parsers with offsets.
- `src/redaction.js` — four strategies, right-to-left span replacement.
- `src/validators.js` — three ported validators; stubs for the rest.
- `src/entropy.js` — Shannon + charset-aware relative entropy.
- `src/decoder.js` — `xor:` / `b64:` prefix decoder.
- `src/generated/` — regen'd from Python; gitignored.
```

- [ ] **Step 2: Commit**

```
git add data_classifier/clients/browser/README.md
git commit -m "docs(sprint14): browser scaffold README (Task 16)"
```

---

## Post-plan verification

Run every test suite end-to-end:

```
cd data_classifier/clients/browser
npm run format:check
npm run test:unit
npm run test:e2e
npm run bench
```

Expected:
- `format:check` — no diffs (run `npm run format` first if there are).
- `test:unit` — all Vitest suites green.
- `test:e2e` — tester smoke + timeout + differential all pass.
- `bench` — summary printed; p50 well under 500ms.

Run Python-side sanity:

```
cd /Users/guyguzner/Projects/data_classifier-browser-poc
ruff check .
ruff format --check .
pytest tests/ -v
```

Expected: all green (the scaffold does not touch Python test surface).

Verify the wheel still excludes the browser package:

```
python3 -m build --wheel --outdir /tmp/wheel-check-final
unzip -l /tmp/wheel-check-final/*.whl | grep -c clients/browser
```

Expected: `0`.

---

## Execution Handoff

Plan complete and saved to
`docs/superpowers/plans/2026-04-16-browser-poc-scaffold.md`.

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best for a scaffold of this size where each task is independently verifiable.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for your review.

Which approach?
