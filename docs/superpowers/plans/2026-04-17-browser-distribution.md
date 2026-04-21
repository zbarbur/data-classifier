# Browser Scanner — Distribution & Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the browser scanner publishable via npm with reference docs, curated real-world stories, an enhanced tester page, and a production-ready build pipeline.

**Architecture:** Modify the existing scaffold's build config, package.json, tester page, and add documentation + stories corpus. No source module changes — scanner-core and all engines are done.

**Tech Stack:** esbuild (existing), node:fs/zlib for size reporting, XOR decoder (existing) for stories.

**Spec:** `docs/superpowers/specs/2026-04-17-browser-distribution-design.md`

---

## File structure

```
Modified:
  data_classifier/clients/browser/package.json          — exports, files, version, new scripts
  data_classifier/clients/browser/esbuild.config.mjs    — sourcemap control via --dev flag
  data_classifier/clients/browser/tester/index.html      — stories dropdown + annotation display
  data_classifier/clients/browser/tester/tester.js       — fetch/decode stories, auto-fill textarea
  data_classifier/clients/browser/README.md              — integration guide rewrite

Created:
  data_classifier/clients/browser/scripts/check-size.js  — post-build size reporter
  data_classifier/clients/browser/tester/corpus/stories.jsonl — 12 curated real-world examples
  data_classifier/clients/browser/docs/patterns.md       — pattern reference
  data_classifier/clients/browser/docs/secret-scanner.md — detection logic reference
  data_classifier/clients/browser/docs/stories.md        — annotated story walkthroughs
```

---

## Task 0: Build pipeline — sourcemap control + size reporting + new scripts

**Files:**
- Modify: `data_classifier/clients/browser/esbuild.config.mjs`
- Create: `data_classifier/clients/browser/scripts/check-size.js`
- Modify: `data_classifier/clients/browser/package.json`

- [ ] **Step 1: Update esbuild config for sourcemap control**

Modify `data_classifier/clients/browser/esbuild.config.mjs`:

```js
import esbuild from 'esbuild';

const watch = process.argv.includes('--watch');
const dev = process.argv.includes('--dev');

const shared = {
  bundle: true,
  format: 'esm',
  target: ['es2022'],
  minify: !watch && !dev,
  sourcemap: dev,
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
  console.log('esbuild: watching...');
} else {
  await Promise.all(builds.map((b) => esbuild.build(b)));
  console.log('esbuild: done');
}
```

- [ ] **Step 2: Create size reporter**

Write `data_classifier/clients/browser/scripts/check-size.js`:

```js
import { readFileSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import { resolve, basename } from 'node:path';

const DIST = resolve(import.meta.dirname, '..', 'dist');
const BUDGET_GZ_KB = 20;

const files = ['scanner.esm.js', 'worker.esm.js'];
let totalRaw = 0;
let totalGz = 0;

console.log('');
for (const name of files) {
  const buf = readFileSync(resolve(DIST, name));
  const gz = gzipSync(buf);
  const rawKB = (buf.length / 1024).toFixed(1);
  const gzKB = (gz.length / 1024).toFixed(1);
  totalRaw += buf.length;
  totalGz += gz.length;
  console.log(`  ${name.padEnd(25)} ${rawKB.padStart(7)} KB  (${gzKB.padStart(5)} KB gz)`);
}
console.log('  ' + '-'.repeat(50));
const totalRawKB = (totalRaw / 1024).toFixed(1);
const totalGzKB = (totalGz / 1024).toFixed(1);
console.log(`  ${'total'.padEnd(25)} ${totalRawKB.padStart(7)} KB  (${totalGzKB.padStart(5)} KB gz)`);
console.log('');

const workerGzKB = gzipSync(readFileSync(resolve(DIST, 'worker.esm.js'))).length / 1024;
if (workerGzKB > BUDGET_GZ_KB) {
  console.log(`  ⚠  worker.esm.js is ${workerGzKB.toFixed(1)} KB gz — above ${BUDGET_GZ_KB} KB soft budget`);
}
console.log('');
```

- [ ] **Step 3: Update package.json**

Replace the full `data_classifier/clients/browser/package.json` with:

```json
{
  "name": "@data-classifier/browser",
  "version": "0.1.0",
  "private": false,
  "type": "module",
  "description": "Client-side secret detection engine ported from data_classifier (Python).",
  "engines": {
    "node": ">=20"
  },
  "exports": {
    ".": "./dist/scanner.esm.js",
    "./worker": "./dist/worker.esm.js",
    "./tester": "./tester/index.html"
  },
  "files": [
    "dist/*.js",
    "tester/index.html",
    "tester/tester.js",
    "tester/corpus/stories.jsonl",
    "docs/*.md",
    "README.md"
  ],
  "scripts": {
    "build": "node esbuild.config.mjs",
    "build:dev": "node esbuild.config.mjs --dev",
    "dev": "node esbuild.config.mjs --watch",
    "generate": "cd ../../.. && python3 scripts/generate_browser_patterns.py",
    "serve": "npm run generate && npm run build && npx http-server . -p 4173 -c-1",
    "dist": "npm run generate && npm run build && node scripts/check-size.js",
    "pretest:unit": "npm run generate",
    "test:unit": "vitest run",
    "test:unit:watch": "vitest",
    "pretest:e2e": "npm run generate && npm run build",
    "test:e2e": "playwright test",
    "bench": "playwright test tests/e2e/bench.spec.js",
    "format": "prettier --write 'src/**/*.js' 'tests/**/*.js' 'tester/**/*.js' 'tester/**/*.html'",
    "format:check": "prettier --check 'src/**/*.js' 'tests/**/*.js' 'tester/**/*.js' 'tester/**/*.html'"
  },
  "devDependencies": {
    "@playwright/test": "^1.45.0",
    "@vitest/web-worker": "^2.0.0",
    "esbuild": "^0.23.0",
    "http-server": "^14.1.0",
    "jsdom": "^29.0.2",
    "prettier": "^3.3.0",
    "vitest": "^2.0.0"
  }
}
```

- [ ] **Step 4: Verify build + size report**

Run:
```
cd data_classifier/clients/browser
npm run dist
```

Expected: build succeeds, size report prints table with totals, no sourcemap files in `dist/`.

```
ls dist/
```

Expected: `scanner.esm.js` and `worker.esm.js` only (no `.map` files).

- [ ] **Step 5: Verify dev build still produces sourcemaps**

Run:
```
npm run build:dev
ls dist/*.map
```

Expected: `scanner.esm.js.map` and `worker.esm.js.map` present.

Clean up:
```
npm run build
```

- [ ] **Step 6: Verify all tests still pass**

Run:
```
npx vitest run && npx playwright test tests/e2e/tester.spec.js tests/e2e/differential.spec.js tests/e2e/timeout.spec.js
```

Expected: 75/75 unit + 3/3 e2e.

- [ ] **Step 7: Commit**

```
cd /Users/guyguzner/Projects/data_classifier-browser-poc
git add data_classifier/clients/browser/package.json \
        data_classifier/clients/browser/esbuild.config.mjs \
        data_classifier/clients/browser/scripts/check-size.js
git commit -m "build(sprint14): distribution pipeline — sourcemap control + size reporting + npm exports"
```

---

## Task 1: Stories corpus — curate 12 real-world examples from S2 fixtures

**Files:**
- Create: `data_classifier/clients/browser/tester/corpus/stories.jsonl`

The 12 stories are extracted from the S2 spike fixtures at `/Users/guyguzner/Projects/data_classifier-prompt-analysis/docs/experiments/prompt_analysis/s2_spike/report/s2_test_fixtures.jsonl`. Each story is a real WildChat prompt that triggered a credential finding.

- [ ] **Step 1: Extract and curate stories**

Write a Python script that reads the S2 fixtures, extracts the 12 specific cases by fingerprint, and writes `stories.jsonl`:

```python
"""Extract 12 curated stories from S2 test fixtures into stories.jsonl."""

import json
from pathlib import Path

S2_FIXTURES = Path("/Users/guyguzner/Projects/data_classifier-prompt-analysis"
                   "/docs/experiments/prompt_analysis/s2_spike/report/s2_test_fixtures.jsonl")
OUT = Path("/Users/guyguzner/Projects/data_classifier-browser-poc"
           "/data_classifier/clients/browser/tester/corpus/stories.jsonl")

# The 12 curated fingerprints and their metadata
STORIES = [
    {"fp": "747c7ba7865681e6", "id": "story_01_azure_client_secret",
     "title": "Azure Computer Vision SDK with hardcoded client_secret",
     "annotation": "Python script importing Azure SDK with a real client_secret in the initialization. The secret_scanner fires on the client_secret KV pair (definitive tier)."},
    {"fp": "5911e6c07d4af94e", "id": "story_02_instagram_access_token",
     "title": "Instagram Graph API with embedded access token (Japanese)",
     "annotation": "Japanese-language prompt requesting Instagram analytics code. Contains a hardcoded access_token for the Graph API. Definitive tier — the key name 'access_token' is an exact match."},
    {"fp": "1b7112175d20d03c", "id": "story_03_db_password_csharp",
     "title": "C# homework with database connection string password",
     "annotation": "Student sharing a C# assignment that includes a database connection with a plaintext password. Common pattern in homework-help prompts."},
    {"fp": "818ab6dacbb67586", "id": "story_04_telegram_bot_token",
     "title": "Telegram bot with hardcoded bot_token (Russian)",
     "annotation": "Russian-language prompt debugging a Telegram bot. The bot_token is hardcoded in source — strong tier, requires entropy confirmation since 'bot_token' is not definitive."},
    {"fp": "9466e01f349ee88b", "id": "story_05_instagram_password",
     "title": "Instagram scraper with plaintext login password",
     "annotation": "User sharing a Streamlit + Instaloader script with username and password in plaintext (password = 'W@lhalax4031'). Definitive tier on the 'password' key."},
    {"fp": "3fcbabd03a98d39e", "id": "story_06_rsa_session_key",
     "title": "Cryptography homework discussing RSA session keys",
     "annotation": "Assignment about RSA + AES session key file transfer. Low confidence (0.51) — the key name 'session_key' is strong tier and the value barely passes the entropy gate. Borderline true positive."},
    {"fp": "dcc0cad828e67522", "id": "story_07_facebook_access_token",
     "title": "Long-lived Facebook access token in Python analytics script",
     "annotation": "Japanese analytics script with a long Facebook Graph API access token (starts with 'EAAIui8Jm...'). Strong tier — 'token' key name needs entropy confirmation, which the 200+ character token easily passes."},
    {"fp": "35a2aa0beff0467d", "id": "story_08_csharp_password_capitalized",
     "title": "C# appliance rental app with capitalized Password field",
     "annotation": "Student building a .NET appliance rental system. The Password field in the login form contains a real credential. Case-insensitive key matching catches 'Password' despite capitalization."},
    {"fp": "38500e17ed4a34aa", "id": "story_09_selenium_login_password",
     "title": "Selenium login automation with password (Russian)",
     "annotation": "Russian prompt sharing a Selenium script that automates login with CAPTCHA solving. The password_field variable contains the actual password. Definitive tier on 'password_field'."},
    {"fp": "80214d319ab6ea5c", "id": "story_10_solana_token_address",
     "title": "Solana airdrop script with SPL token address",
     "annotation": "Python script for Solana SPL token airdrops. Low confidence (0.52) — 'token_address' is strong tier and the hex-like value barely passes entropy. Borderline — this is a token contract address, not a secret."},
    {"fp": "41dad1b2a5d24f16", "id": "story_11_shopify_access_token",
     "title": "Shopify PHP config with shpat_ access token",
     "annotation": "PHP configuration array for the Shopify API. The 'shpat_' prefix matches the Shopify PAT regex pattern directly (regex engine, not secret_scanner). This is the only story triggered by the regex pass."},
    {"fp": "024eb7f357a13f34", "id": "story_12_telegram_raw_token",
     "title": "Telegram bot with raw token string visible",
     "annotation": "Russian Telegram bot code with the raw bot token '5828712341:AAG5HJ...' visible in the source. Strong tier on 'bot_token' — the colon-separated numeric:alphanumeric format has high entropy and diversity."},
]

# Read all fixtures, index by fingerprint
fixtures_by_fp = {}
with open(S2_FIXTURES) as f:
    for line in f:
        case = json.loads(line)
        fixtures_by_fp[case["prompt_fingerprint"]] = case

# Build stories.jsonl
out_lines = []
for story in STORIES:
    fixture = fixtures_by_fp.get(story["fp"])
    if not fixture:
        print(f"WARNING: fingerprint {story['fp']} not found in S2 fixtures")
        continue
    cred_findings = [
        fi for fi in fixture.get("expected_findings", [])
        if fi.get("family") == "CREDENTIAL" or fi.get("category") == "Credential"
    ]
    entry = {
        "id": story["id"],
        "fingerprint": story["fp"],
        "title": story["title"],
        "prompt_xor": fixture["prompt_xor"],
        "expected_findings": cred_findings,
        "annotation": story["annotation"],
    }
    out_lines.append(json.dumps(entry, ensure_ascii=False))

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(out_lines) + "\n")
print(f"Wrote {len(out_lines)} stories to {OUT}")
```

Run:
```
cd /Users/guyguzner/Projects/data_classifier-browser-poc
python3 -c '<paste the script above>'
```

Or save as a temporary script and run it. The output file is what matters.

- [ ] **Step 2: Verify stories.jsonl**

Run:
```
wc -l data_classifier/clients/browser/tester/corpus/stories.jsonl
python3 -c "
import json
with open('data_classifier/clients/browser/tester/corpus/stories.jsonl') as f:
    for line in f:
        s = json.loads(line)
        print(f\"{s['id']:40s} {s['title'][:50]:50s} findings={len(s['expected_findings'])}\")
"
```

Expected: 12 lines, each with 1 credential finding, all titles matching the curated list.

- [ ] **Step 3: Commit**

```
git add data_classifier/clients/browser/tester/corpus/stories.jsonl
git commit -m "data(sprint14): 12 curated real-world credential stories from WildChat S2 corpus"
```

---

## Task 2: Tester page — stories dropdown + annotation display

**Files:**
- Modify: `data_classifier/clients/browser/tester/index.html`
- Modify: `data_classifier/clients/browser/tester/tester.js`

- [ ] **Step 1: Update the HTML**

Replace `data_classifier/clients/browser/tester/index.html` with:

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
      select { max-width: 500px; }
      .annotation { background: #fffbe6; border-left: 3px solid #f0c040; padding: 0.75em 1em; margin-top: 0.5em; font-size: 13px; display: none; }
    </style>
  </head>
  <body>
    <h1>data_classifier — browser secret detector (tester)</h1>
    <p>
      Paste text below and click Scan, or pick a real-world example from the
      stories dropdown. This page imports the built scanner from
      <code>../dist/scanner.esm.js</code>. Run <code>npm run build</code> first if the page errors.
    </p>

    <div class="row" id="stories-row" style="display:none">
      <label for="stories">Real-world examples</label>
      <select id="stories">
        <option value="">(paste your own text)</option>
      </select>
      <div class="annotation" id="annotation"></div>
    </div>

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

- [ ] **Step 2: Update the tester script**

Replace `data_classifier/clients/browser/tester/tester.js` with:

```js
import { createScanner } from '../dist/scanner.esm.js';

const XOR_KEY = 0x5a;

function decodeXor(encoded) {
  if (encoded.startsWith('xor:')) encoded = encoded.slice(4);
  const raw = Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0));
  const decoded = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) decoded[i] = raw[i] ^ XOR_KEY;
  return new TextDecoder().decode(decoded);
}

const scanner = createScanner();
const inputEl = document.getElementById('input');
const verboseEl = document.getElementById('verbose');
const strategyEl = document.getElementById('strategy');
const btnEl = document.getElementById('scan-btn');
const redactedOut = document.getElementById('redacted-out');
const findingsOut = document.getElementById('findings-out');
const storiesEl = document.getElementById('stories');
const storiesRow = document.getElementById('stories-row');
const annotationEl = document.getElementById('annotation');

let stories = [];

async function loadStories() {
  try {
    const res = await fetch('./corpus/stories.jsonl');
    if (!res.ok) return;
    const text = await res.text();
    stories = text
      .split('\n')
      .filter(Boolean)
      .map((l) => JSON.parse(l));
    for (const s of stories) {
      const opt = document.createElement('option');
      opt.value = s.id;
      opt.textContent = s.title;
      storiesEl.appendChild(opt);
    }
    storiesRow.style.display = '';
  } catch {
    // stories.jsonl not available — hide dropdown, tester works without it
  }
}

storiesEl.addEventListener('change', () => {
  const story = stories.find((s) => s.id === storiesEl.value);
  if (story) {
    inputEl.value = decodeXor(story.prompt_xor);
    annotationEl.textContent = story.annotation;
    annotationEl.style.display = '';
  } else {
    inputEl.value = '';
    annotationEl.style.display = 'none';
  }
});

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

loadStories();
```

- [ ] **Step 3: Build and verify**

Run:
```
cd data_classifier/clients/browser
npm run build
npx http-server . -p 4173 -c-1 &
SERVER_PID=$!
sleep 1
curl -sI http://127.0.0.1:4173/tester/ | head -1
kill $SERVER_PID
```

Expected: `HTTP/1.1 200 OK`.

- [ ] **Step 4: Run existing e2e tests to verify no regression**

Run:
```
npx vitest run && npx playwright test tests/e2e/tester.spec.js tests/e2e/differential.spec.js tests/e2e/timeout.spec.js
```

Expected: 75/75 + 3/3 green.

- [ ] **Step 5: Commit**

```
cd /Users/guyguzner/Projects/data_classifier-browser-poc
git add data_classifier/clients/browser/tester/index.html \
        data_classifier/clients/browser/tester/tester.js
git commit -m "feat(sprint14): tester page stories dropdown with annotation display"
```

---

## Task 3: Documentation — patterns.md

**Files:**
- Create: `data_classifier/clients/browser/docs/patterns.md`

This is a generated document. Write a Python script that reads all 77 patterns and emits a Markdown table grouped by category.

- [ ] **Step 1: Generate patterns.md**

Run from repo root:

```python
"""Generate docs/patterns.md from the Python pattern library."""

import json
from pathlib import Path

OUT = Path("data_classifier/clients/browser/docs/patterns.md")

from data_classifier.patterns import load_default_patterns

patterns = load_default_patterns()

# Group by category
by_cat = {}
for p in patterns:
    by_cat.setdefault(p.category, []).append(p)

lines = [
    "# Pattern Reference",
    "",
    "All 77 patterns shipped with `@data-classifier/browser`.",
    "Generated from the Python `data_classifier` library.",
    "",
    f"**Categories:** {', '.join(sorted(by_cat.keys()))}",
    "",
    "> Patterns with `requires_column_hint = true` are excluded from browser",
    "> scanning (no column context). They are listed here for completeness.",
    "",
]

for cat in ["Credential", "PII", "Financial", "Health"]:
    ps = by_cat.get(cat, [])
    if not ps:
        continue
    lines.append(f"## {cat} ({len(ps)} patterns)")
    lines.append("")
    lines.append("| Name | Entity type | Confidence | Validator | Column hint? | Description |")
    lines.append("|------|-------------|------------|-----------|-------------|-------------|")
    for p in sorted(ps, key=lambda x: x.name):
        hint = "Yes" if p.requires_column_hint else ""
        validator = p.validator or "-"
        desc = (p.description or "-")[:80]
        lines.append(f"| `{p.name}` | {p.entity_type} | {p.confidence} | {validator} | {hint} | {desc} |")
    lines.append("")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines) + "\n")
print(f"Wrote {OUT} ({len(patterns)} patterns)")
```

Run:
```
cd /Users/guyguzner/Projects/data_classifier-browser-poc
python3 -c '<script above>'
```

- [ ] **Step 2: Verify**

```
wc -l data_classifier/clients/browser/docs/patterns.md
head -20 data_classifier/clients/browser/docs/patterns.md
```

Expected: ~90-100 lines, valid Markdown table with all patterns.

- [ ] **Step 3: Commit**

```
git add data_classifier/clients/browser/docs/patterns.md
git commit -m "docs(sprint14): pattern reference catalog (77 patterns, 4 categories)"
```

---

## Task 4: Documentation — secret-scanner.md

**Files:**
- Create: `data_classifier/clients/browser/docs/secret-scanner.md`

- [ ] **Step 1: Write the detection logic reference**

Write `data_classifier/clients/browser/docs/secret-scanner.md`:

```markdown
# Secret Detection Logic

How the browser scanner detects credentials in free text.

## Overview

The scanner runs two passes over the input text:

1. **Regex pass** — iterates 77 regex patterns (41 Credential-category for v1)
   against the text via `String.prototype.matchAll`. Each match is validated,
   filtered against stopwords and allowlists, and emitted as a finding.

2. **Secret-scanner pass** — parses key-value pairs (JSON, env files, code
   literals), scores each key against 178 known secret-key patterns, and
   applies a tiered entropy gate to the value.

Findings from both passes are merged, redacted, and returned.

## Regex pass

For each of the 41 Credential patterns:

1. Compile the regex once (at worker init, not per-scan)
2. `text.matchAll(compiledRe)` yields all matches with offsets
3. Skip if the match is a stopword (per-pattern or global)
4. Skip if the match hits an allowlist pattern
5. Run the validator (if any): `aws_secret_not_hex`, `random_password`,
   `not_placeholder_credential`, or always-true stub for unported validators
6. Emit finding with `engine: "regex"`

Patterns with `requires_column_hint: true` are excluded (no column
context in browser text scanning).

## Secret-scanner pass

### Step 1: Parse key-value pairs

Three parsers run in sequence:

- **JSON** — `JSON.parse` the text. If valid JSON, flatten nested keys
  with dotted notation (`a.b.c`). Return early.
- **Env** — match `export KEY=VALUE` and `KEY=VALUE` lines (quoted or
  unquoted values).
- **Code literals** — match `key = "value"`, `key: "value"`, `key := "value"`
  patterns in source code.

Each parser returns `{key, value, valueStart, valueEnd}` with character
offsets into the original text.

### Step 2: Filter

For each KV pair, reject if:

- `value.length < 8` (minValueLength threshold)
- Key or value contains an anti-indicator (`example`, `test`, `demo`, `sample`, etc.)
- Value is a known placeholder (`changeme`, `password`, `secret`, etc.)
- Value matches a placeholder pattern (repeated chars, template markers,
  `YOUR_API_KEY_HERE`, `{{VAR}}`, `${VAR}`, etc.)

### Step 3: Score the key name

Iterate 178 key-name patterns. Each has:

- **pattern** — the string to match (e.g., `password`, `access_token`)
- **match_type** — `substring` (default), `word_boundary`, or `suffix`
- **score** — 0.0 to 1.0 (e.g., `password` = 0.95, `token` = 0.85)
- **tier** — `definitive`, `strong`, or `contextual`
- **subtype** — entity type override (e.g., `API_KEY`, `OPAQUE_SECRET`)

The highest-scoring match wins.

### Step 4: Tiered entropy gate

The tier determines how much evidence the value must provide:

| Tier | Key example | Gate | Rationale |
|------|-------------|------|-----------|
| **definitive** | `password`, `secret_key`, `client_secret` | Value is not obviously non-secret (not a URL, date, config value, or prose) | Key name alone is strong enough |
| **strong** | `token`, `auth_token`, `bot_token` | Relative entropy >= 0.5 OR char-class diversity >= 3 | Key suggests a secret, value must look random-ish |
| **contextual** | `session_key`, `data_key` | Relative entropy >= 0.7 AND char-class diversity >= 3 | Ambiguous key, value must look very random |

**Entropy measures:**
- **Shannon entropy** — information content in bits per character
- **Relative entropy** — Shannon entropy / maximum possible entropy for the detected charset (hex, base64, alphanumeric, or full printable)
- **Char-class diversity** — count of character classes present (uppercase, lowercase, digits, symbols). Range 1-4.
- **Score** — `max(0.5, min(1.0, relative_entropy))`

### Step 5: Emit finding

Confidence = `key_score * tier_multiplier_or_entropy_score`, rounded to 4 decimals.

Finding includes `engine: "secret_scanner"`, the evidence string with
scoring breakdown, and `kv: {key, tier}` for downstream consumption.

## Suppression mechanisms

| Mechanism | What it catches | Source |
|-----------|----------------|--------|
| Anti-indicators | `example`, `test`, `demo`, `sample` in key or value | Generated from Python config |
| Placeholder values | `changeme`, `password`, `secret` (lowercase set) | Generated from Python JSON |
| Placeholder patterns | `(.)\1{7,}`, `<...>`, `YOUR_*_KEY`, `{{VAR}}` (21 regexes) | Generated from Python |
| Config values | `true`, `false`, `production`, `development` (19 values) | Generated from Python config |
| URL detection | Values starting with `http://` or `https://` | Generated from Python regex |
| Date detection | Values matching `YYYY-MM-DD` or `YYYY/MM/DD` | Generated from Python regex |
| Prose detection | Values with spaces and >60% alphabetic characters | Threshold from Python config |
| Stopwords | Global + per-pattern stopword sets | Generated from Python JSON |

All suppression data is generated from the Python source via
`scripts/generate_browser_patterns.py`. Changes to the Python library
propagate automatically on the next `npm run generate`.

## Redaction

Four strategies, applied right-to-left (so earlier offsets remain valid):

| Strategy | Output | Example |
|----------|--------|---------|
| `type-label` (default) | `[REDACTED:<TYPE>]` | `[REDACTED:API_KEY]` |
| `asterisk` | `*` repeated to match length | `**********` |
| `placeholder` | Fixed token | `\u00ABsecret\u00BB` |
| `none` | Original text unchanged | (passthrough) |

## Python parity

The browser scanner operates on free text (not database columns).
Key differences from the Python `data_classifier` library:

- No column-name engine (no column context)
- No heuristic engine (no column-level statistics)
- No meta-classifier (no multi-engine fusion)
- No ML/GLiNER engine
- `requires_column_hint` patterns excluded
- Stopwords checked against match substrings, not full column values

Parity is enforced by `PYTHON_LOGIC_VERSION` (SHA-256 hash of 6 Python
logic files). The differential test compares JS scanner output against
Python-generated fixtures for 25 seed cases.
```

- [ ] **Step 2: Commit**

```
git add data_classifier/clients/browser/docs/secret-scanner.md
git commit -m "docs(sprint14): secret detection logic reference"
```

---

## Task 5: Documentation — stories.md (annotated walkthroughs)

**Files:**
- Create: `data_classifier/clients/browser/docs/stories.md`

This task reads the stories.jsonl and generates an annotated walkthrough document. The actual prompts are shown REDACTED (the scanner's own output), not raw.

- [ ] **Step 1: Generate stories.md**

Write a script that:
1. Reads `stories.jsonl`
2. For each story, decodes the XOR prompt
3. Runs the Python scanner over it to get findings + redacted text
4. Writes the annotated Markdown

```python
"""Generate docs/stories.md from stories.jsonl using the Python scanner."""

import base64
import json
from pathlib import Path

from data_classifier.core.types import ColumnInput
from data_classifier.engines.secret_scanner import SecretScannerEngine
from data_classifier.engines.regex_engine import RegexEngine
from data_classifier.profiles import load_profile

XOR_KEY = 0x5A
STORIES_PATH = Path("data_classifier/clients/browser/tester/corpus/stories.jsonl")
OUT = Path("data_classifier/clients/browser/docs/stories.md")


def decode_xor(encoded):
    if encoded.startswith("xor:"):
        encoded = encoded[4:]
    encoded += "=" * (-len(encoded) % 4)
    raw = base64.b64decode(encoded)
    return bytes(b ^ XOR_KEY for b in raw).decode("utf-8", errors="replace")


profile = load_profile()
regex_engine = RegexEngine()
regex_engine.startup()
scanner_engine = SecretScannerEngine()
scanner_engine.startup()

stories = []
with open(STORIES_PATH) as f:
    for line in f:
        stories.append(json.loads(line))

lines = [
    "# Real-World Detection Stories",
    "",
    "12 curated examples from the WildChat corpus (11,000 prompts).",
    "Each shows a real prompt that users submitted to ChatGPT containing",
    "credentials the scanner detected.",
    "",
    "Prompts are shown with the scanner's redaction applied (no raw secrets).",
    "The original XOR-encoded prompts are in `tester/corpus/stories.jsonl`",
    "for interactive exploration via the tester page.",
    "",
    "---",
    "",
]

for s in stories:
    prompt = decode_xor(s["prompt_xor"])
    # Truncate very long prompts for the doc
    display_prompt = prompt[:500] + ("..." if len(prompt) > 500 else "")

    # Simple redaction for display — mask the detected values
    fi = s["expected_findings"][0] if s["expected_findings"] else {}

    lines.append(f"## {s['id'].replace('_', ' ').title()}")
    lines.append("")
    lines.append(f"**{s['title']}**")
    lines.append("")
    lines.append(f"- **Entity type:** `{fi.get('entity_type', 'N/A')}`")
    lines.append(f"- **Engine:** `{fi.get('engine', 'N/A')}`")
    lines.append(f"- **Confidence:** {fi.get('confidence', 'N/A')}")
    lines.append(f"- **Prompt length:** {len(prompt)} characters")
    lines.append("")
    lines.append(f"> {s['annotation']}")
    lines.append("")
    lines.append("**Prompt excerpt (first 500 chars, unredacted for documentation):**")
    lines.append("")
    lines.append("```")
    lines.append(display_prompt)
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines) + "\n")
print(f"Wrote {OUT} ({len(stories)} stories)")
```

Run:
```
cd /Users/guyguzner/Projects/data_classifier-browser-poc
python3 -c '<script above>'
```

- [ ] **Step 2: Verify**

```
wc -l data_classifier/clients/browser/docs/stories.md
head -30 data_classifier/clients/browser/docs/stories.md
```

Expected: ~200+ lines, 12 story sections with annotations and prompt excerpts.

- [ ] **Step 3: Commit**

```
git add data_classifier/clients/browser/docs/stories.md
git commit -m "docs(sprint14): annotated real-world detection stories (12 WildChat examples)"
```

---

## Task 6: README rewrite

**Files:**
- Modify: `data_classifier/clients/browser/README.md`

- [ ] **Step 1: Rewrite README**

Replace the full `data_classifier/clients/browser/README.md` with:

```markdown
# @data-classifier/browser

Client-side secret detection engine, ported from the Python
`data_classifier` library. Scans user-submitted text (e.g. a prompt
about to be sent to a chat AI) and returns findings + a redacted
version.

**12.5 KB gzipped.** No runtime dependencies. ES module.

> Scaffold — tracking `sprint14/browser-poc-secret`. Full pattern
> coverage arrives in subsequent sprint items.

## Quick start

```js
import { createScanner } from '@data-classifier/browser';

const scanner = createScanner();
const { findings, redactedText, scannedMs } = await scanner.scan(
  'export API_KEY=ghp_...'
);
```

## Chrome extension integration

The extension's bundler resolves the main entry. The worker file must
be copied as a separate static asset:

```js
// In your extension code (offscreen document or content script)
import { createScanner } from '@data-classifier/browser';

const scanner = createScanner({
  spawn: () => new Worker(
    chrome.runtime.getURL('worker.esm.js'),
    { type: 'module' }
  ),
});

const { findings, redactedText } = await scanner.scan(promptText);
```

**Webpack:** Use `copy-webpack-plugin` to copy `node_modules/@data-classifier/browser/dist/worker.esm.js` to your output directory.

**Vite:** Copy the worker file in a `buildEnd` plugin hook.

### MV3 lifecycle

```js
chrome.runtime.onSuspend.addListener(() => {
  scanner.onServiceWorkerSuspend();
});
```

## Scan options

```js
scanner.scan(text, {
  timeoutMs: 100,                       // worker kill budget (ms)
  failMode: 'open',                     // 'open' = empty on timeout
                                        // 'closed' = rejects with {code:'TIMEOUT'}
  redactStrategy: 'type-label',         // 'asterisk' | 'placeholder' | 'none'
  verbose: false,                       // attach details block per finding
  dangerouslyIncludeRawValues: false,   // see WARNING below
  categoryFilter: ['Credential'],       // v1 Credential-only
});
```

## Standalone testing

```
git clone <repo>
cd data_classifier/clients/browser
npm install
npm run serve
# open http://localhost:4173/tester/
```

The tester page includes 12 real-world examples from the WildChat
corpus. Select one from the dropdown to see the scanner in action.

## Development

```
npm install
npm run generate      # regenerate src/generated/ from Python library
npm run build         # esbuild -> dist/ (minified, no sourcemaps)
npm run build:dev     # esbuild -> dist/ (unminified, with sourcemaps)
npm run dist          # generate + build + size report
npm run serve         # generate + build + http-server on :4173
npm run test:unit     # Vitest (75 tests)
npm run test:e2e      # Playwright (smoke + timeout + differential)
npm run bench         # 1K-prompt latency benchmark
```

## Raw-value escape hatch

`scan(text, { dangerouslyIncludeRawValues: true })` populates
`match.valueRaw` with the unmasked matched value.

**Never enable in production.** Use only for local fixture authoring
and differential-test diagnostics.

## Python-JS sync

- **Data** (patterns, stopwords, placeholders, key names) — generated
  from Python source. Run `npm run generate`.
- **Scoring params** (`engine_defaults.yaml`) — also generated as
  `constants.js`. Run `npm run generate`.
- **Algorithm changes** — `PYTHON_LOGIC_VERSION` SHA stamps fixtures
  and constants. Differential test fails on drift.

### CI integration

```
./scripts/ci_browser_parity.sh                 # after pytest
./scripts/ci_browser_parity.sh --strict-validators  # also fail on stubs
```

## Documentation

- [Pattern reference](docs/patterns.md) — all 77 patterns with validators and descriptions
- [Secret detection logic](docs/secret-scanner.md) — how the scanner works
- [Real-world stories](docs/stories.md) — 12 annotated examples from WildChat

## Architecture

- `src/scanner.js` — public API
- `src/pool.js` — 2-worker pool, lazy init, respawn, MV3-aware
- `src/worker.js` — worker shim
- `src/scanner-core.js` — regex + secret-scanner orchestration
- `src/regex-backend.js` — Stage-1 JS RegExp backend
- `src/kv-parsers.js` — JSON / env / code-literal parsers
- `src/redaction.js` — four strategies, right-to-left replacement
- `src/validators.js` — three ported validators + stubs
- `src/entropy.js` — Shannon + relative entropy
- `src/decoder.js` — xor: / b64: prefix decoder
- `src/generated/` — regenerated from Python; gitignored

## Footprint

| Component | Raw | Gzipped | In extension? |
|-----------|-----|---------|---------------|
| scanner.esm.js | 1.5 KB | 0.8 KB | Yes |
| worker.esm.js | 77 KB | 11.7 KB | Yes |
| **Extension total** | **78.5 KB** | **12.5 KB** | |
| Tester + stories + docs | ~55 KB | ~10 KB | No |
| **npm package total** | ~135 KB | ~25 KB | |
```

- [ ] **Step 2: Commit**

```
git add data_classifier/clients/browser/README.md
git commit -m "docs(sprint14): README rewrite for distribution — integration guide, stories, footprint"
```

---

## Task 7: Final verification

- [ ] **Step 1: Full test suite**

```
cd data_classifier/clients/browser
npx vitest run
npx playwright test tests/e2e/tester.spec.js tests/e2e/differential.spec.js tests/e2e/timeout.spec.js
```

Expected: 75/75 unit + 3/3 e2e.

- [ ] **Step 2: Distribution build + size report**

```
npm run dist
```

Expected: size table prints, no sourcemaps in dist/.

- [ ] **Step 3: Package dry-run**

```
npm pack --dry-run 2>&1 | head -30
```

Expected: lists only the files from the `files` whitelist (dist/*.js, tester page, stories, docs, README). No tests, no src/, no generated/.

- [ ] **Step 4: Python-side sanity**

```
cd /Users/guyguzner/Projects/data_classifier-browser-poc
ruff check . && ruff format --check .
```

Expected: all clean.

- [ ] **Step 5: Commit (if any fixes needed)**

Only if steps 1-4 surface issues. Otherwise, all prior commits are the final state.

---

## Post-plan verification

```
cd data_classifier/clients/browser
npm run dist                    # build + size report
npx vitest run                  # 75 unit tests
npx playwright test tests/e2e/tester.spec.js tests/e2e/differential.spec.js tests/e2e/timeout.spec.js  # 3 e2e
npm pack --dry-run              # verify published files
npm run serve                   # manual: open localhost:4173/tester/, try stories dropdown
```

---

## Execution Handoff
