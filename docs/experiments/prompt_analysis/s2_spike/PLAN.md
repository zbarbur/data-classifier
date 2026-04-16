# S2 Browser-port Feasibility Spike — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce three measurement artifacts (`perf.json`, `redos.json`, `bundle.json`) plus a final memo that lets the browser-PoC execution track choose between Path 1 (audited JS regex) and Path 2 (re2-wasm) for the content-regex layer.

**Architecture:** Small JS workspace at `docs/experiments/prompt_analysis/s2_spike/` containing 1 Python corpus extractor + 5 Node scripts. Patterns are RE2-compatible by project policy → direct copy from Python JSON to JS module (no syntax translation). Perf benchmark runs in headless Chrome via Playwright, taking 3 runs and reporting the median-by-P99. ReDoS audit and bundle measurement are pure Node.

**Tech Stack:** Node 20+, Python 3.11+ (project venv), `playwright` (headless Chromium), `recheck` (ReDoS analyzer), `esbuild` (bundler), `datasets` (HuggingFace, already installed in project venv).

**Spec:** [`SPEC.md`](./SPEC.md) — read before starting.

---

## File Structure

All files relative to `docs/experiments/prompt_analysis/s2_spike/`:

| File | Purpose | Created in task |
|---|---|---|
| `package.json` | npm deps + scripts | 1 |
| `.gitignore` | exclude node_modules, corpus.jsonl | 1 |
| `extract_patterns.mjs` | Python `default_patterns.json` → `patterns.js` (77 patterns) | 2 |
| `patterns.js` | generated; ES module exporting `patterns` array | 2 (output) |
| `extract_corpus.py` | WildChat-1M streaming → `corpus.jsonl` (11K records, XOR-encoded) | 3 |
| `corpus.jsonl` | generated, gitignored; 11K prompts | 3 (output) |
| `entropy.js` | Shannon entropy util, used in bundle measurement | 4 |
| `benchmark.html` | bare HTML loaded by Playwright | 4 |
| `benchmark.js` | in-page perf code; exposes `window.__runBenchmark()` | 4 |
| `run_benchmark.mjs` | Playwright driver, runs 3×, picks median-by-P99 | 5 |
| `audit_redos.mjs` | runs `recheck` over 77 patterns | 6 |
| `browser_entry.js` | bundle entry: re-exports patterns + entropy | 7 |
| `measure_bundle.mjs` | esbuild + gzip + validator-size projection | 7 |
| `report/perf.json` | distribution + per-pattern max + heap delta | 5 (output) |
| `report/redos.json` | per-pattern verdicts + counts | 6 (output) |
| `report/bundle.json` | measured + projected bytes | 7 (output) |
| `report/s2_browser_port_spike.md` | final memo (manual writeup) | 8 |

**Boundaries:** each script is one responsibility. `extract_*` produces inputs; `run_benchmark`/`audit_redos`/`measure_bundle` each produce one report JSON. Final memo is the only step that synthesizes across reports.

---

## Task 1: Project setup (npm workspace + ignores)

**Files:**
- Create: `docs/experiments/prompt_analysis/s2_spike/package.json`
- Create: `docs/experiments/prompt_analysis/s2_spike/.gitignore`

- [ ] **Step 1: Create `package.json`**

```json
{
  "name": "s2-browser-port-spike",
  "version": "0.0.1",
  "private": true,
  "type": "module",
  "scripts": {
    "extract:patterns": "node extract_patterns.mjs",
    "extract:corpus": "../../../.venv/bin/python extract_corpus.py",
    "bench": "node run_benchmark.mjs",
    "audit:redos": "node audit_redos.mjs",
    "bundle": "node measure_bundle.mjs"
  },
  "devDependencies": {
    "playwright": "1.45.0",
    "recheck": "4.4.5",
    "esbuild": "0.21.5"
  }
}
```

- [ ] **Step 2: Create `.gitignore`**

```
node_modules/
corpus.jsonl
*.log
```

- [ ] **Step 3: Install deps + Chromium**

Run from `docs/experiments/prompt_analysis/s2_spike/`:

```bash
cd docs/experiments/prompt_analysis/s2_spike
npm install
npx playwright install chromium
```

Expected: `node_modules/` populated, `playwright` reports Chromium installed (~150MB download). If `npx playwright install chromium` fails (offline / proxy), check `~/.cache/ms-playwright/` — Chromium may already be cached from prior work.

- [ ] **Step 4: Verify `recheck` API surface**

Run:

```bash
node -e "import('recheck').then(m => console.log(Object.keys(m)))"
```

Expected output includes `check` (function used in Task 6). If the export name differs, fix `audit_redos.mjs` in Task 6 to match the actual API.

- [ ] **Step 5: Commit**

```bash
git add docs/experiments/prompt_analysis/s2_spike/package.json docs/experiments/prompt_analysis/s2_spike/.gitignore
git commit -m "spike(s2): project setup — package.json + gitignore"
```

---

## Task 2: Pattern extraction (Python JSON → JS module)

**Files:**
- Create: `docs/experiments/prompt_analysis/s2_spike/extract_patterns.mjs`
- Output: `docs/experiments/prompt_analysis/s2_spike/patterns.js` (generated, committed)

- [ ] **Step 1: Create `extract_patterns.mjs`**

```js
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = path.resolve(__dirname, "../../../../data_classifier/patterns/default_patterns.json");
const OUT = path.join(__dirname, "patterns.js");

const raw = JSON.parse(fs.readFileSync(SOURCE, "utf8"));
if (!Array.isArray(raw.patterns)) {
  console.error("expected object with `patterns` array, got:", typeof raw.patterns);
  process.exit(1);
}

const patterns = raw.patterns.map(p => ({
  name: p.name,
  regex_source: p.regex,
  flags: "g",
  entity_type: p.entity_type,
  category: p.category,
  requires_column_hint: p.requires_column_hint || false,
}));

// Smoke: every pattern must compile in JS RegExp
const failed = [];
for (const p of patterns) {
  try { new RegExp(p.regex_source, p.flags); }
  catch (e) { failed.push({ name: p.name, error: e.message }); }
}
if (failed.length) {
  console.error("FAILED to compile in JS RegExp:");
  for (const f of failed) console.error(`  ${f.name}: ${f.error}`);
  process.exit(1);
}

const body = `// Generated by extract_patterns.mjs — do not edit by hand.
// Source: data_classifier/patterns/default_patterns.json
// Pattern count: ${patterns.length}
export const patterns = ${JSON.stringify(patterns, null, 2)};
`;
fs.writeFileSync(OUT, body);
console.log(`extracted ${patterns.length} patterns; all compile in JS RegExp`);
console.log(`wrote ${OUT}`);
```

- [ ] **Step 2: Run and verify cardinality**

```bash
cd docs/experiments/prompt_analysis/s2_spike
node extract_patterns.mjs
```

Expected output:
```
extracted 77 patterns; all compile in JS RegExp
wrote .../patterns.js
```

If count != 77, the source JSON has changed since 2026-04-16 — verify with `jq '.patterns | length' ../../../../data_classifier/patterns/default_patterns.json` and update SPEC.md if intentional.

- [ ] **Step 3: Verify generated file shape**

```bash
node -e "import('./patterns.js').then(m => console.log('count:', m.patterns.length, 'first:', m.patterns[0].name))"
```

Expected: `count: 77 first: us_ssn_formatted` (or whatever pattern is first in the JSON — order matches source).

- [ ] **Step 4: Commit**

```bash
git add docs/experiments/prompt_analysis/s2_spike/extract_patterns.mjs docs/experiments/prompt_analysis/s2_spike/patterns.js
git commit -m "spike(s2): pattern extraction — 77 patterns, all compile in JS RegExp"
```

---

## Task 3: Corpus extraction (WildChat → 11K-prompt JSONL)

**Files:**
- Create: `docs/experiments/prompt_analysis/s2_spike/extract_corpus.py`
- Output: `docs/experiments/prompt_analysis/s2_spike/corpus.jsonl` (gitignored)

- [ ] **Step 1: Create `extract_corpus.py`**

```python
"""S2 spike: WildChat-1M → 11K-prompt corpus (10K random + 1K longest).

Streams 20K user-turns deduped by SHA-256, splits into a random sample
(first 10K by stream order) and a long-prompt sample (top-1K longest from
the remaining 10K). XOR-encodes prompt text per project rule.

Run: ../../../.venv/bin/python extract_corpus.py
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import random
from pathlib import Path

os.environ.setdefault("DATA_CLASSIFIER_DISABLE_ML", "1")

from data_classifier.patterns._decoder import _XOR_KEY  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("s2_corpus")


def xor_encode(s: str) -> str:
    raw = bytes(b ^ _XOR_KEY for b in s.encode("utf-8"))
    return "xor:" + base64.b64encode(raw).decode("ascii")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stream-size", type=int, default=20_000)
    ap.add_argument("--random-size", type=int, default=10_000)
    ap.add_argument("--long-size", type=int, default=1_000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=str(Path(__file__).parent / "corpus.jsonl"))
    args = ap.parse_args()

    if args.random_size + args.long_size > args.stream_size:
        raise SystemExit(
            f"stream-size ({args.stream_size}) must be >= random + long "
            f"({args.random_size + args.long_size})"
        )

    random.seed(args.seed)

    from datasets import load_dataset

    log.info("loading allenai/WildChat-1M (streaming=True)")
    ds = load_dataset("allenai/WildChat-1M", split="train", streaming=True)

    seen: set[str] = set()
    records: list[dict] = []
    for row in ds:
        if len(records) >= args.stream_size:
            break
        for msg in row.get("conversation", []):
            if msg.get("role") != "user":
                continue
            text = msg.get("content", "") or ""
            if not text.strip():
                continue
            fp = hashlib.sha256(text.encode()).hexdigest()[:16]
            if fp in seen:
                continue
            seen.add(fp)
            records.append({
                "turn_index": len(records),
                "length": len(text),
                "sha256": fp,
                "text_xor": xor_encode(text),
            })
            if len(records) >= args.stream_size:
                break
        if (len(records) % 5_000) == 0 and len(records) > 0:
            log.info("collected %d unique user-turns", len(records))

    log.info("collected %d unique user-turns total", len(records))

    # Stable shuffle for reproducibility, then split.
    random.shuffle(records)
    random_recs = records[:args.random_size]
    remaining = records[args.random_size:]
    remaining.sort(key=lambda r: r["length"], reverse=True)
    long_recs = remaining[:args.long_size]

    for r in random_recs:
        r["bucket"] = "random"
    for r in long_recs:
        r["bucket"] = "long"

    out_records = random_recs + long_recs
    with open(args.out, "w") as f:
        for r in out_records:
            f.write(json.dumps(r) + "\n")

    avg_random_len = sum(r["length"] for r in random_recs) / len(random_recs)
    avg_long_len = sum(r["length"] for r in long_recs) / len(long_recs)
    log.info(
        "wrote %d records: %d random (avg %.0f chars) + %d long (avg %.0f chars) → %s",
        len(out_records), len(random_recs), avg_random_len,
        len(long_recs), avg_long_len, args.out,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke run with tiny sample**

```bash
cd docs/experiments/prompt_analysis/s2_spike
../../../.venv/bin/python extract_corpus.py --stream-size 200 --random-size 100 --long-size 10 --out /tmp/s2_corpus_smoke.jsonl
```

Expected: `wrote 110 records: 100 random (avg ~ chars) + 10 long (avg ~ chars) → /tmp/s2_corpus_smoke.jsonl` (avg-long should be greater than avg-random).

Verify shape:
```bash
head -1 /tmp/s2_corpus_smoke.jsonl | jq '{turn_index, length, bucket, sha256, text_starts: (.text_xor[0:8])}'
```

Expected: `text_starts` = `"xor:"` followed by base64.

- [ ] **Step 3: Full run (20K → 11K)**

```bash
cd docs/experiments/prompt_analysis/s2_spike
../../../.venv/bin/python extract_corpus.py
```

Expected: takes ~30-60 seconds on warm HF cache. Output:
```
collected 20000 unique user-turns total
wrote 11000 records: 10000 random (avg N chars) + 1000 long (avg M chars) → .../corpus.jsonl
```
where M >> N.

Verify:
```bash
wc -l corpus.jsonl  # → 11000
jq -r '.bucket' corpus.jsonl | sort | uniq -c  # → 10000 random, 1000 long
```

- [ ] **Step 4: Commit (script only)**

```bash
git add docs/experiments/prompt_analysis/s2_spike/extract_corpus.py
git commit -m "spike(s2): corpus extractor — 20K WildChat stream → 11K (10K random + 1K longest)"
```

`corpus.jsonl` is gitignored (regenerable from script + seed=42).

---

## Task 4: In-page benchmark code (entropy + HTML + benchmark.js)

**Files:**
- Create: `docs/experiments/prompt_analysis/s2_spike/entropy.js`
- Create: `docs/experiments/prompt_analysis/s2_spike/benchmark.html`
- Create: `docs/experiments/prompt_analysis/s2_spike/benchmark.js`

- [ ] **Step 1: Create `entropy.js`**

```js
// Shannon entropy of a string, in bits per symbol.
// Mirrors data_classifier/engines/secret_scanner.py shannon_entropy().
export function shannonEntropy(s) {
  if (!s) return 0;
  const counts = new Map();
  for (const c of s) counts.set(c, (counts.get(c) || 0) + 1);
  const n = s.length;
  let h = 0;
  for (const c of counts.values()) {
    const p = c / n;
    h -= p * Math.log2(p);
  }
  return h;
}
```

- [ ] **Step 2: Create `benchmark.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>S2 perf benchmark</title>
</head>
<body>
  <script type="module" src="./benchmark.js"></script>
</body>
</html>
```

- [ ] **Step 3: Create `benchmark.js`**

```js
import { patterns } from "./patterns.js";

// XOR decode (key 0x5A) — mirror of data_classifier/patterns/_decoder.py
function decodeXor(s) {
  const b64 = s.startsWith("xor:") ? s.slice(4) : s;
  const raw = atob(b64);
  let out = "";
  for (let i = 0; i < raw.length; i++) {
    out += String.fromCharCode(raw.charCodeAt(i) ^ 0x5A);
  }
  return out;
}

// Compile all patterns once and report parse time separately.
const compileStart = performance.now();
const compiled = patterns.map(p => ({
  name: p.name,
  re: new RegExp(p.regex_source, p.flags || "g"),
}));
const compileMs = performance.now() - compileStart;

window.__runBenchmark = function (corpus) {
  // Warm-up (V8 JIT settle): scan first 100 prompts and discard timings.
  const warmupSize = Math.min(100, corpus.length);
  for (let i = 0; i < warmupSize; i++) {
    const text = decodeXor(corpus[i].text_xor);
    for (const c of compiled) {
      // Iterate matchAll to force engine to walk the entire string.
      for (const _m of text.matchAll(c.re)) { /* discard */ }
    }
  }

  const heapBefore = (performance.memory && performance.memory.usedJSHeapSize) || 0;
  const perPrompt = [];
  const perPatternMax = new Array(compiled.length).fill(0);

  for (const rec of corpus) {
    const text = decodeXor(rec.text_xor);
    const totalStart = performance.now();
    for (let i = 0; i < compiled.length; i++) {
      const patStart = performance.now();
      for (const _m of text.matchAll(compiled[i].re)) { /* discard */ }
      const dt = performance.now() - patStart;
      if (dt > perPatternMax[i]) perPatternMax[i] = dt;
    }
    perPrompt.push({
      idx: rec.turn_index,
      length: rec.length,
      bucket: rec.bucket,
      ms: performance.now() - totalStart,
    });
  }

  const heapAfter = (performance.memory && performance.memory.usedJSHeapSize) || 0;

  return {
    compileMs,
    patternCount: compiled.length,
    corpusSize: corpus.length,
    perPrompt,
    perPatternMax: perPatternMax.map((ms, i) => ({
      name: compiled[i].name,
      max_ms: ms,
    })),
    heapDeltaBytes: heapAfter - heapBefore,
  };
};
```

- [ ] **Step 4: Smoke check (decode round-trip)**

```bash
cd docs/experiments/prompt_analysis/s2_spike
node -e "
import('./entropy.js').then(m => {
  console.log('entropy(abcd):', m.shannonEntropy('abcd').toFixed(3));
  console.log('entropy(aaaa):', m.shannonEntropy('aaaa').toFixed(3));
});
"
```

Expected: `entropy(abcd): 2.000`, `entropy(aaaa): 0.000` (4 unique chars = 2 bits, 1 unique = 0 bits).

The XOR decode is exercised in Task 5 when the benchmark runs against real corpus data.

- [ ] **Step 5: Commit**

```bash
git add docs/experiments/prompt_analysis/s2_spike/entropy.js docs/experiments/prompt_analysis/s2_spike/benchmark.html docs/experiments/prompt_analysis/s2_spike/benchmark.js
git commit -m "spike(s2): in-page benchmark code — entropy util + harness page + measurement loop"
```

---

## Task 5: Benchmark runner (Playwright driver)

**Files:**
- Create: `docs/experiments/prompt_analysis/s2_spike/run_benchmark.mjs`
- Output: `docs/experiments/prompt_analysis/s2_spike/report/perf.json`

- [ ] **Step 1: Create `run_benchmark.mjs`**

```js
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CORPUS = path.join(__dirname, "corpus.jsonl");
const HARNESS = "file://" + path.join(__dirname, "benchmark.html");
const REPORT_DIR = path.join(__dirname, "report");

function loadCorpus() {
  if (!fs.existsSync(CORPUS)) {
    console.error(`corpus.jsonl missing at ${CORPUS}; run extract_corpus.py first`);
    process.exit(1);
  }
  return fs.readFileSync(CORPUS, "utf8")
    .trim().split("\n").map(l => JSON.parse(l));
}

function quantile(arr, q) {
  if (arr.length === 0) return 0;
  const sorted = [...arr].sort((a, b) => a - b);
  const idx = Math.min(sorted.length - 1, Math.floor(q * sorted.length));
  return sorted[idx];
}

function distribution(values) {
  if (values.length === 0) return { n: 0 };
  const sum = values.reduce((a, b) => a + b, 0);
  return {
    n: values.length,
    p50: quantile(values, 0.50),
    p75: quantile(values, 0.75),
    p90: quantile(values, 0.90),
    p95: quantile(values, 0.95),
    p99: quantile(values, 0.99),
    p99_9: quantile(values, 0.999),
    max: Math.max(...values),
    mean: sum / values.length,
  };
}

function histogram(values, buckets = 50) {
  if (values.length === 0) return [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  // Log-scale buckets across [min, max], shifted by epsilon to handle 0.
  const eps = 0.001;
  const lmin = Math.log10(min + eps);
  const lmax = Math.log10(max + eps);
  const edges = [];
  for (let i = 0; i <= buckets; i++) {
    edges.push(Math.pow(10, lmin + (lmax - lmin) * (i / buckets)) - eps);
  }
  const counts = new Array(buckets).fill(0);
  for (const v of values) {
    let b = 0;
    for (let i = 1; i <= buckets; i++) {
      if (v <= edges[i]) { b = i - 1; break; }
      b = buckets - 1;
    }
    counts[b]++;
  }
  return edges.slice(0, -1).map((edge, i) => ({
    lower_ms: edge,
    upper_ms: edges[i + 1],
    count: counts[i],
  }));
}

async function runOnce(corpus, runIdx) {
  console.log(`[run ${runIdx + 1}/3] launching chromium`);
  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.goto(HARNESS);
  await page.waitForFunction(() => typeof window.__runBenchmark === "function");
  console.log(`[run ${runIdx + 1}/3] running benchmark on ${corpus.length} prompts`);
  const t0 = Date.now();
  const result = await page.evaluate((c) => window.__runBenchmark(c), corpus);
  const wallSec = (Date.now() - t0) / 1000;
  console.log(`[run ${runIdx + 1}/3] benchmark wall time = ${wallSec.toFixed(1)}s`);
  await browser.close();
  return result;
}

const corpus = loadCorpus();
const runs = [];
for (let i = 0; i < 3; i++) {
  runs.push(await runOnce(corpus, i));
}

// Pick representative run = median-by-P99.
const p99s = runs.map(r => quantile(r.perPrompt.map(p => p.ms), 0.99));
const sortedP99 = [...p99s].sort((a, b) => a - b);
const medianP99 = sortedP99[1];
const repIdx = p99s.indexOf(medianP99);
const rep = runs[repIdx];

const allMs = rep.perPrompt.map(p => p.ms);
const randomMs = rep.perPrompt.filter(p => p.bucket === "random").map(p => p.ms);
const longMs = rep.perPrompt.filter(p => p.bucket === "long").map(p => p.ms);

// Sample 1K (idx, length, ms) tuples for the latency-vs-length scatter.
const sampleN = Math.min(1000, rep.perPrompt.length);
const stride = Math.max(1, Math.floor(rep.perPrompt.length / sampleN));
const scatter = [];
for (let i = 0; i < rep.perPrompt.length; i += stride) {
  if (scatter.length >= sampleN) break;
  const p = rep.perPrompt[i];
  scatter.push({ length: p.length, ms: p.ms, bucket: p.bucket });
}

const out = {
  spec: "S2",
  date: new Date().toISOString(),
  runs_count: runs.length,
  representative_run_idx: repIdx,
  cross_run_p99_ms: { min: sortedP99[0], median: medianP99, max: sortedP99[2] },
  compile_ms: rep.compileMs,
  pattern_count: rep.patternCount,
  corpus_size: rep.corpusSize,
  heap_delta_bytes: rep.heapDeltaBytes,
  distribution_combined_ms: distribution(allMs),
  distribution_random_ms: distribution(randomMs),
  distribution_long_ms: distribution(longMs),
  histogram_combined: histogram(allMs, 50),
  scatter_length_vs_ms: scatter,
  per_pattern_max_ms: rep.perPatternMax.sort((a, b) => b.max_ms - a.max_ms),
};

fs.mkdirSync(REPORT_DIR, { recursive: true });
fs.writeFileSync(path.join(REPORT_DIR, "perf.json"), JSON.stringify(out, null, 2));
console.log(`wrote report/perf.json`);
console.log(`combined p99 = ${out.distribution_combined_ms.p99.toFixed(2)} ms`);
console.log(`combined max = ${out.distribution_combined_ms.max.toFixed(2)} ms`);
console.log(`compile_ms   = ${out.compile_ms.toFixed(2)} ms`);
console.log(`top-3 patterns by max latency:`);
for (const p of out.per_pattern_max_ms.slice(0, 3)) {
  console.log(`  ${p.name}: ${p.max_ms.toFixed(2)} ms`);
}
```

- [ ] **Step 2: Smoke run with mini-corpus**

Generate a 110-prompt smoke corpus and substitute it temporarily:

```bash
cd docs/experiments/prompt_analysis/s2_spike
../../../.venv/bin/python extract_corpus.py --stream-size 200 --random-size 100 --long-size 10 --out corpus.jsonl
node run_benchmark.mjs
```

Expected: 3 runs complete in <30 sec total. `report/perf.json` exists.

Verify shape:
```bash
jq '{p99: .distribution_combined_ms.p99, max: .distribution_combined_ms.max, compile: .compile_ms, top: .per_pattern_max_ms[0]}' report/perf.json
```

Expected: 4 finite numbers, top entry has `name` and `max_ms`.

- [ ] **Step 3: Full run (regenerate full corpus first)**

```bash
cd docs/experiments/prompt_analysis/s2_spike
../../../.venv/bin/python extract_corpus.py
node run_benchmark.mjs
```

Expected: ~10-15 min total. Three Chromium launches. Cross-run P99 should be within 2× across runs (instability indicates a bug or contention).

If P99 cross-run spread > 5×, there's likely a measurement contamination — check that `corpus.jsonl` isn't being modified mid-run, and re-run.

- [ ] **Step 4: Commit (script + report)**

```bash
git add docs/experiments/prompt_analysis/s2_spike/run_benchmark.mjs docs/experiments/prompt_analysis/s2_spike/report/perf.json
git commit -m "spike(s2): perf benchmark runner + report — p99=N.NN ms (replace with real number from report)"
```

---

## Task 6: ReDoS audit (recheck over 77 patterns)

**Files:**
- Create: `docs/experiments/prompt_analysis/s2_spike/audit_redos.mjs`
- Output: `docs/experiments/prompt_analysis/s2_spike/report/redos.json`

- [ ] **Step 1: Confirm `recheck` API surface**

```bash
cd docs/experiments/prompt_analysis/s2_spike
node -e "import('recheck').then(m => { console.log(Object.keys(m)); console.log(m.check.toString().slice(0, 200)); })"
```

Note the export name (`check`) and the result schema. The script below assumes `check(source, flags) → { status, complexity?: { type }, attack?: { string } }`. If the API is different (e.g., requires options object, returns `vulnerable: true`), adapt the field accesses in Step 2.

- [ ] **Step 2: Create `audit_redos.mjs`**

```js
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { check } from "recheck";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPORT_DIR = path.join(__dirname, "report");

const { patterns } = await import("./patterns.js");

const results = [];
let i = 0;
for (const p of patterns) {
  i++;
  process.stdout.write(`\r[${i}/${patterns.length}] ${p.name.padEnd(40)}`);
  let res;
  try {
    res = await check(p.regex_source, p.flags || "g");
  } catch (e) {
    results.push({
      name: p.name,
      regex_source: p.regex_source,
      status: "error",
      error: String(e),
    });
    continue;
  }
  results.push({
    name: p.name,
    regex_source: p.regex_source,
    status: res.status,                          // "safe" | "vulnerable" | "unknown"
    complexity_type: res.complexity?.type ?? null, // "polynomial" | "exponential" | null
    attack_string: res.attack?.string ?? null,
    hotspot: res.hotspot ?? null,
  });
}
process.stdout.write("\n");

const counts = results.reduce((acc, r) => {
  let key;
  if (r.status === "vulnerable") {
    key = `vulnerable_${r.complexity_type || "unknown"}`;
  } else {
    key = r.status;
  }
  acc[key] = (acc[key] || 0) + 1;
  return acc;
}, {});

const out = {
  spec: "S2",
  date: new Date().toISOString(),
  pattern_count: patterns.length,
  counts,
  results,
};

fs.mkdirSync(REPORT_DIR, { recursive: true });
fs.writeFileSync(path.join(REPORT_DIR, "redos.json"), JSON.stringify(out, null, 2));
console.log(`wrote report/redos.json`);
console.log(`counts: ${JSON.stringify(counts)}`);

const vulnerable = results.filter(r => r.status === "vulnerable");
if (vulnerable.length > 0) {
  console.log(`\nvulnerable patterns:`);
  for (const v of vulnerable) {
    console.log(`  ${v.name}: ${v.complexity_type}`);
  }
}
```

- [ ] **Step 3: Run**

```bash
cd docs/experiments/prompt_analysis/s2_spike
node audit_redos.mjs
```

Expected: ~2-5 min wall time (recheck does symbolic analysis per pattern). Output ends with counts and vulnerable list.

Verify shape:
```bash
jq '{count: .pattern_count, counts: .counts, first_result: .results[0]}' report/redos.json
```

Expected: `count: 77`, counts object with `safe` + possibly `vulnerable_polynomial` / `vulnerable_exponential` / `unknown`.

- [ ] **Step 4: Commit**

```bash
git add docs/experiments/prompt_analysis/s2_spike/audit_redos.mjs docs/experiments/prompt_analysis/s2_spike/report/redos.json
git commit -m "spike(s2): ReDoS audit via recheck — N safe / M poly / K exp (replace with real counts)"
```

---

## Task 7: Bundle measurement (esbuild + gzip)

**Files:**
- Create: `docs/experiments/prompt_analysis/s2_spike/browser_entry.js`
- Create: `docs/experiments/prompt_analysis/s2_spike/measure_bundle.mjs`
- Output: `docs/experiments/prompt_analysis/s2_spike/report/bundle.json`

- [ ] **Step 1: Create `browser_entry.js`**

```js
// Entry point for bundle-size measurement.
// Mirrors what a v1 PoC would expose: patterns + entropy.
// Validators are excluded by S2 scope (projected, not measured).
export { patterns } from "./patterns.js";
export { shannonEntropy } from "./entropy.js";
```

- [ ] **Step 2: Create `measure_bundle.mjs`**

```js
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import { fileURLToPath } from "node:url";
import esbuild from "esbuild";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ENTRY = path.join(__dirname, "browser_entry.js");
const VALIDATORS = path.resolve(__dirname, "../../../../data_classifier/engines/validators.py");
const REPORT_DIR = path.join(__dirname, "report");

const result = await esbuild.build({
  entryPoints: [ENTRY],
  bundle: true,
  minify: true,
  format: "esm",
  write: false,
  target: ["chrome120"],
});

if (result.errors.length > 0) {
  console.error("esbuild errors:", result.errors);
  process.exit(1);
}

const bundled = result.outputFiles[0].text;
const minifiedBytes = Buffer.byteLength(bundled, "utf8");
const gzippedBytes = zlib.gzipSync(bundled, { level: 9 }).length;

// Validator size projection: validators_python_LOC × 0.7 (JS/Python LOC ratio) × 30 (bytes/min-LOC).
const validatorsLOC = fs.readFileSync(VALIDATORS, "utf8").split("\n").length;
const projectedValidatorBytes = Math.round(validatorsLOC * 0.7 * 30);

const out = {
  spec: "S2",
  date: new Date().toISOString(),
  bundler: "esbuild (minify, format=esm, target=chrome120, gzip level 9)",
  measured: {
    bundled_modules: ["patterns.js", "entropy.js"],
    minified_bytes: minifiedBytes,
    minified_kb: +(minifiedBytes / 1024).toFixed(2),
    gzipped_bytes: gzippedBytes,
    gzipped_kb: +(gzippedBytes / 1024).toFixed(2),
  },
  projection: {
    validators_python_loc: validatorsLOC,
    projected_validator_bytes: projectedValidatorBytes,
    projected_validator_kb: +(projectedValidatorBytes / 1024).toFixed(2),
    formula: "loc * 0.7 (js/py ratio) * 30 (bytes/min-loc)",
  },
  projected_total_gzipped_bytes: gzippedBytes + projectedValidatorBytes,
  projected_total_gzipped_kb: +((gzippedBytes + projectedValidatorBytes) / 1024).toFixed(2),
  target: { gzipped_kb: 200, source: "queue.md S2 architectural commitment" },
};

fs.mkdirSync(REPORT_DIR, { recursive: true });
fs.writeFileSync(path.join(REPORT_DIR, "bundle.json"), JSON.stringify(out, null, 2));
console.log(`wrote report/bundle.json`);
console.log(`measured gzipped:  ${out.measured.gzipped_kb} KB`);
console.log(`projected total:   ${out.projected_total_gzipped_kb} KB (target: ${out.target.gzipped_kb} KB)`);
```

- [ ] **Step 3: Run**

```bash
cd docs/experiments/prompt_analysis/s2_spike
node measure_bundle.mjs
```

Expected: <5 sec. Output prints measured + projected sizes.

Verify shape:
```bash
jq '{measured_gz_kb: .measured.gzipped_kb, projected_total_kb: .projected_total_gzipped_kb, target_kb: .target.gzipped_kb}' report/bundle.json
```

- [ ] **Step 4: Commit**

```bash
git add docs/experiments/prompt_analysis/s2_spike/browser_entry.js docs/experiments/prompt_analysis/s2_spike/measure_bundle.mjs docs/experiments/prompt_analysis/s2_spike/report/bundle.json
git commit -m "spike(s2): bundle measurement — N KB measured, M KB projected total (replace with real numbers)"
```

---

## Task 8: Final memo + queue.md update

**Files:**
- Create: `docs/experiments/prompt_analysis/s2_spike/report/s2_browser_port_spike.md`
- Modify: `docs/experiments/prompt_analysis/queue.md` (S2 status line + headline numbers)

- [ ] **Step 1: Write final memo at `report/s2_browser_port_spike.md`**

Use the structure below. Fill all `<…>` placeholders with real numbers from `report/perf.json`, `report/redos.json`, `report/bundle.json`. **Do not commit the memo with placeholders unfilled.**

```markdown
# S2 — Browser-port Feasibility Spike Findings

**Stage**: S2 from `docs/experiments/prompt_analysis/queue.md` §"Secret detection track"
**Date**: <YYYY-MM-DD>
**Branch**: `research/prompt-analysis`
**Spec**: [`../SPEC.md`](../SPEC.md)
**Driver**: Browser PoC execution track (`sprint14/browser-poc-secret`) needs a Path 1 vs Path 2 (re2-wasm) decision before committing to a regex implementation.

---

## TL;DR

We measured **77 content regex patterns** against an **11K-prompt WildChat corpus** (10K random + 1K longest) in headless Chrome via Playwright, ran ReDoS audit via `recheck`, and measured esbuild+gzip bundle size.

**Headline numbers**:
- Per-prompt scan latency P99 = **<X> ms** (combined), max = **<Y> ms**
- ReDoS: **<safe>/<poly>/<exp>** of 77 patterns (safe / polynomial / exponential)
- Bundle gzipped: **<measured> KB** measured + **<projected> KB** projected validators = **<total> KB** (target 200 KB)

**Recommendation**: <Path 1 / Path 2 / conditional> — see §"Path decision" below.

---

## Methodology

See [SPEC.md](../SPEC.md). Three reports drive this memo:
- [`perf.json`](./perf.json) — perf benchmark, full distribution + per-pattern max
- [`redos.json`](./redos.json) — recheck verdicts per pattern
- [`bundle.json`](./bundle.json) — esbuild + gzip + validator projection

---

## Perf results

**Full distribution** (combined 11K corpus, representative run = median-by-P99 of 3):

| Metric | Combined | Random (10K) | Long (1K) |
|---|---|---|---|
| P50 | <ms> | <ms> | <ms> |
| P75 | <ms> | <ms> | <ms> |
| P90 | <ms> | <ms> | <ms> |
| P95 | <ms> | <ms> | <ms> |
| P99 | <ms> | <ms> | <ms> |
| P99.9 | <ms> | <ms> | <ms> |
| max | <ms> | <ms> | <ms> |
| mean | <ms> | <ms> | <ms> |

**Cross-run stability** (3 runs): P99 = (min <X>, median <Y>, max <Z>) ms.

**Bundle parse time**: <X> ms to construct 77 RegExp instances (one-time cost at module load).

**Heap delta during benchmark**: <X> bytes.

**Top 5 patterns by max latency**:

| # | Pattern | Max ms |
|---|---|---|
| 1 | <name> | <ms> |
| ... | | |

[Description of any pattern that's a clear outlier — e.g., is it a long-prompt-only spike, or does it spike on random prompts too?]

---

## ReDoS results

| Verdict | Count |
|---|---|
| safe | <N> |
| vulnerable (polynomial) | <N> |
| vulnerable (exponential) | <N> |
| unknown | <N> |
| error | <N> |

[List any vulnerable patterns with attack strings and complexity. If empty, say so explicitly.]

---

## Bundle results

| Component | Bytes (gzipped) | KB |
|---|---|---|
| Measured (patterns + entropy) | <N> | <X> |
| Projected validators (LOC × 0.7 × 30) | <N> | <X> |
| **Projected total** | <N> | <X> |
| Target (queue.md) | 204800 | 200 |

[Verdict: under / over target.]

---

## Cross-reference: perf-tail × ReDoS

[List any pattern that appears in BOTH the top-N by P99 AND in the recheck `vulnerable` list. This is the actual risk set — patterns that the analyzer flags AND that empirically are slow on real corpus data.]

If the intersection is empty, say so — that's a strong positive signal for Path 1.

---

## Path decision support

Three threshold scenarios for the worker kill budget:

| Budget | Prompts killed at this budget | Verdict |
|---|---|---|
| 50 ms | <N> (<%> of 11K) | <Path 1 / Path 2> |
| 100 ms | <N> (<%>) | <Path 1 / Path 2> |
| 200 ms | <N> (<%>) | <Path 1 / Path 2> |

**Recommendation to execution track**: <one paragraph explaining which path the data supports, and on what threshold>.

---

## Filed follow-ups

- **S2.5** — `secret_scanner` browser-port perf measurement. Same harness, separate measurement. File as backlog item.
- [Any pathological pattern surfaced by perf+ReDoS intersection → Sprint 13/14 P1 backlog item]
- [Anything else discovered]

---

## Artifact inventory

- [`perf.json`](./perf.json)
- [`redos.json`](./redos.json)
- [`bundle.json`](./bundle.json)
- [`../corpus.jsonl`](../corpus.jsonl) — gitignored, regenerable from `extract_corpus.py --seed 42`
- [`../patterns.js`](../patterns.js) — committed, generated from `extract_patterns.mjs`
```

- [ ] **Step 2: Update `docs/experiments/prompt_analysis/queue.md` S2 section**

Find the section starting `### Stage S2 — Browser-port feasibility spike` and update its status line.

Change:
```
- **Status:** 🟡 unblocked — can start in parallel with S0
```

To:
```
- **Status:** ✅ COMPLETE <YYYY-MM-DD> — see `s2_spike/report/s2_browser_port_spike.md`
```

Add a `## Headline numbers` block immediately after that line:

```
**Headline numbers** (from `s2_spike/report/`):

- Per-prompt scan latency P99 = <X> ms, max = <Y> ms (11K WildChat corpus, 77 patterns)
- ReDoS: <safe>/<poly>/<exp> of 77 patterns
- Bundle gzipped: <X> KB measured + <Y> KB projected validators (target 200 KB)
- **Path decision**: <Path 1 / Path 2 / conditional>
```

- [ ] **Step 3: Verify queue.md edit**

```bash
grep -A 5 "Stage S2" docs/experiments/prompt_analysis/queue.md | head -10
```

Expected: status line shows ✅ COMPLETE with the date; headline block follows.

- [ ] **Step 4: Commit**

```bash
git add docs/experiments/prompt_analysis/s2_spike/report/s2_browser_port_spike.md docs/experiments/prompt_analysis/queue.md
git commit -m "$(cat <<'EOF'
research(prompt-analysis): S2 complete — browser-port feasibility memo

Three measurements of 77 content regex patterns over 11K WildChat prompts:
- Perf P99 = <X> ms (full distribution + per-pattern max)
- ReDoS: <counts>
- Bundle gzipped: <measured> + <projected validators> = <total> KB

Path decision: <Path 1 / Path 2>. Execution track (sprint14/browser-poc-secret)
can now commit to a regex strategy.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Push**

```bash
git push origin research/prompt-analysis
```

---

## Self-review checklist (run before declaring complete)

- [ ] All 3 report JSONs exist under `report/`
- [ ] `report/s2_browser_port_spike.md` has zero `<placeholder>` strings
- [ ] queue.md S2 status reflects COMPLETE with real headline numbers
- [ ] `corpus.jsonl` is gitignored (verify via `git status` — should not appear)
- [ ] `node_modules/` is gitignored (verify same way)
- [ ] All 8 task commits are on the branch (verify via `git log --oneline -10`)
- [ ] Final commit pushed to origin
