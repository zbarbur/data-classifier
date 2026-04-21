import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import http from "node:http";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CORPUS = path.join(__dirname, "corpus.jsonl");
const REPORT_DIR = path.join(__dirname, "report");
const SERVER_PORT = 18765;
const HARNESS = `http://localhost:${SERVER_PORT}/benchmark.html`;

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
  const eps = 0.001;
  const lmin = Math.log10(min + eps);
  const lmax = Math.log10(max + eps);
  const edges = [];
  for (let i = 0; i <= buckets; i++) {
    edges.push(Math.pow(10, lmin + (lmax - lmin) * (i / buckets)) - eps);
  }
  const counts = new Array(buckets).fill(0);
  for (const v of values) {
    let b = buckets - 1;
    for (let i = 1; i <= buckets; i++) {
      if (v <= edges[i]) { b = i - 1; break; }
    }
    counts[b]++;
  }
  return edges.slice(0, -1).map((edge, i) => ({
    lower_ms: +edge.toFixed(4),
    upper_ms: +edges[i + 1].toFixed(4),
    count: counts[i],
  }));
}

// Minimal static file server for the spike directory (avoids file:// CORS block on ES modules)
function startServer() {
  const MIME = {
    ".html": "text/html",
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".json": "application/json",
  };
  const server = http.createServer((req, res) => {
    const rel = req.url.split("?")[0];
    const file = path.join(__dirname, rel);
    // Safety: only serve files under __dirname
    if (!file.startsWith(__dirname)) {
      res.writeHead(403); res.end("Forbidden"); return;
    }
    fs.readFile(file, (err, data) => {
      if (err) { res.writeHead(404); res.end("Not found"); return; }
      const ext = path.extname(file);
      res.writeHead(200, { "Content-Type": MIME[ext] || "application/octet-stream" });
      res.end(data);
    });
  });
  return new Promise((resolve, reject) => {
    server.listen(SERVER_PORT, "127.0.0.1", () => {
      console.log(`static server listening on http://localhost:${SERVER_PORT}`);
      resolve(server);
    });
    server.on("error", reject);
  });
}

async function runOnce(corpus, runIdx) {
  console.log(`[run ${runIdx + 1}/3] launching chromium`);
  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  // Set generous timeout — 11K prompts × 77 patterns can take minutes
  page.setDefaultTimeout(600_000);

  // Capture console output from the page for debugging
  page.on("console", msg => {
    if (msg.type() === "error") console.error(`[page error] ${msg.text()}`);
  });
  page.on("pageerror", err => console.error(`[page exception] ${err.message}`));

  await page.goto(HARNESS, { timeout: 30_000 });

  // Wait for ES module to load and expose __runBenchmark
  await page.waitForFunction(() => typeof window.__runBenchmark === "function", { timeout: 30_000 });

  console.log(`[run ${runIdx + 1}/3] running benchmark on ${corpus.length} prompts...`);
  const t0 = Date.now();
  const result = await page.evaluate((c) => window.__runBenchmark(c), corpus);
  const wallSec = (Date.now() - t0) / 1000;
  console.log(`[run ${runIdx + 1}/3] done in ${wallSec.toFixed(1)}s`);
  await browser.close();
  return result;
}

async function main() {
  const corpus = loadCorpus();
  console.log(`corpus: ${corpus.length} prompts`);

  const server = await startServer();

  const runs = [];
  try {
    for (let i = 0; i < 3; i++) {
      runs.push(await runOnce(corpus, i));
    }
  } finally {
    server.close();
  }

  // Pick representative run = median-by-P99 (all patterns)
  const p99s = runs.map(r => quantile(r.perPrompt.map(p => p.ms), 0.99));
  const sortedP99 = [...p99s].sort((a, b) => a - b);
  const medianP99 = sortedP99[1];
  const repIdx = p99s.indexOf(medianP99);
  const rep = runs[repIdx];

  // All-patterns distributions
  const allMs = rep.perPrompt.map(p => p.ms);
  const randomMs = rep.perPrompt.filter(p => p.bucket === "random").map(p => p.ms);
  const longMs = rep.perPrompt.filter(p => p.bucket === "long").map(p => p.ms);

  // Secrets-only distributions
  const allSecretMs = rep.perPrompt.map(p => p.secret_ms);
  const randomSecretMs = rep.perPrompt.filter(p => p.bucket === "random").map(p => p.secret_ms);
  const longSecretMs = rep.perPrompt.filter(p => p.bucket === "long").map(p => p.secret_ms);

  // Scatter: 1K sampled points
  const sampleN = Math.min(1000, rep.perPrompt.length);
  const stride = Math.max(1, Math.floor(rep.perPrompt.length / sampleN));
  const scatter = [];
  for (let i = 0; i < rep.perPrompt.length && scatter.length < sampleN; i += stride) {
    const p = rep.perPrompt[i];
    scatter.push({ length: p.length, ms: p.ms, secret_ms: p.secret_ms, bucket: p.bucket });
  }

  const out = {
    spec: "S2",
    date: new Date().toISOString(),
    runs_count: runs.length,
    representative_run_idx: repIdx,
    cross_run_p99_ms: { min: sortedP99[0], median: medianP99, max: sortedP99[2] },
    compile_ms: rep.compileMs,
    pattern_count: rep.patternCount,
    credential_pattern_count: rep.credentialPatternCount,
    corpus_size: rep.corpusSize,
    heap_delta_bytes: rep.heapDeltaBytes,

    // All 77 patterns
    all_patterns: {
      distribution_combined_ms: distribution(allMs),
      distribution_random_ms: distribution(randomMs),
      distribution_long_ms: distribution(longMs),
      histogram_combined: histogram(allMs, 50),
    },

    // Credential patterns only (browser PoC scope)
    credential_only: {
      distribution_combined_ms: distribution(allSecretMs),
      distribution_random_ms: distribution(randomSecretMs),
      distribution_long_ms: distribution(longSecretMs),
      histogram_combined: histogram(allSecretMs, 50),
    },

    scatter_length_vs_ms: scatter,
    per_pattern_max_ms: rep.perPatternMax.sort((a, b) => b.max_ms - a.max_ms),
  };

  fs.mkdirSync(REPORT_DIR, { recursive: true });
  fs.writeFileSync(path.join(REPORT_DIR, "perf.json"), JSON.stringify(out, null, 2));
  console.log(`\nwrote report/perf.json`);
  console.log(`\n=== ALL PATTERNS (${out.pattern_count}) ===`);
  console.log(`combined p99 = ${out.all_patterns.distribution_combined_ms.p99.toFixed(2)} ms`);
  console.log(`combined max = ${out.all_patterns.distribution_combined_ms.max.toFixed(2)} ms`);
  console.log(`\n=== CREDENTIAL ONLY (${out.credential_pattern_count}) ===`);
  console.log(`combined p99 = ${out.credential_only.distribution_combined_ms.p99.toFixed(2)} ms`);
  console.log(`combined max = ${out.credential_only.distribution_combined_ms.max.toFixed(2)} ms`);
  console.log(`\ncompile_ms   = ${out.compile_ms.toFixed(2)} ms`);
  console.log(`\ntop-5 patterns by max latency:`);
  for (const p of out.per_pattern_max_ms.slice(0, 5)) {
    console.log(`  ${p.name} [${p.category}]: ${p.max_ms.toFixed(2)} ms`);
  }
}

main().catch(e => { console.error(e); process.exit(1); });
