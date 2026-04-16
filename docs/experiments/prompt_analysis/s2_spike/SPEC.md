# S2 — Browser-port feasibility spike (SPEC)

**Stage**: S2 from `docs/experiments/prompt_analysis/queue.md` §"Secret detection track"
**Date**: 2026-04-16
**Branch**: `research/prompt-analysis`
**Status**: spec — pending implementation
**Effort**: ~1 day
**Driver**: First prompt-analysis client = Chrome extension over ChatGPT (sprint14/browser-poc-secret execution track). Before that track commits to a regex strategy, S2 produces the data needed to choose Path 1 (audited JS regex) vs Path 2 (re2-wasm).

---

## Goal

Produce a distribution of measurements that lets us pick between two implementation paths for the browser PoC's content-regex layer. **No pass/fail thresholds in the spike itself** — output the full latency distribution + ReDoS categorization + bundle size so the budget decision can be made post-hoc with real numbers in front of us.

The execution track (sprint14/browser-poc-secret) consumes this output to decide:
- **Path 1**: ship JS-native `RegExp` with a per-pattern audit gate
- **Path 2**: ship re2-wasm (linear-time guarantee, ~250KB extra bundle, slower per-call)

## Decision support, not decision

The spike does **not** lock a worker kill budget. It produces enough data that the budget can be set with evidence:

> "If you set a 100ms kill budget, X% of prompts will be killed. If you set 200ms, Y%. The worst pattern by P99 is `<name>`."

queue.md currently lists "default 100ms pending S2 measurement" — this spike retires the "pending" qualifier by replacing the default with measured curves.

---

## Scope

### In scope

- All **77 content regex patterns** in `data_classifier/patterns/default_patterns.json`
- WildChat-1M corpus (already cached locally from S0)
- Headless Chrome via Playwright
- `recheck` for ReDoS audit
- esbuild + gzip for bundle measurement
- Final memo output

### Out of scope (explicit)

- **`secret_scanner` port + perf** — separate algorithm shape (key=value parser + entropy + 178-entry dict lookup); filed as **S2.5** below
- **Validator port** — only a *projected size* number (LOC-based estimate); actual port is part of the execution track build
- **Mobile / cold-device perf** — desktop Chrome only; mobile is an execution-track concern
- **Memory profiling** — heap delta only (no allocation tracing, no leak hunt)
- **Worker lifecycle / MV3 service-worker behavior** — pure regex perf; worker integration is execution-track build
- **Cross-engine comparison** (Firefox / Safari) — V8 only; if Path 1 ships, execution track validates other engines

---

## Methodology

### Corpus (11K prompts, single streaming pass)

- **Stream 20K** user-turns from WildChat-1M `train` split, dedup by SHA-256 fingerprint
- **Split**: 10K random (first 10K by stream order) + 1K longest (top-1K by character length from the remaining 10K)
- Output: `corpus.jsonl` with `{turn_index, length, sha256, text_xor, bucket}` where `bucket ∈ {"random","long"}` (XOR-encoded per project rule)

Rationale: single-pass streaming avoids a costly 1M re-scan; the random 10K gives unbiased perf distribution; the long-prompt 1K explicitly stresses the tail because ReDoS-flavored worst cases live in long pasted code blocks, not random short prompts. Reported distributions are computed per-bucket AND combined, so we can see whether the tail is corpus-representative or a long-prompt artifact.

### Pattern extraction

- Read `default_patterns.json`, output `patterns.js` exporting an array of `{name, regex_source, flags}`.
- Patterns are RE2-compatible by project policy, which is a clean subset of JS RegExp — no syntax translation needed. Spot-check confirms zero patterns use named groups, `\A`/`\Z`, lookarounds, possessive quantifiers, or backreferences.
- Compile patterns to `RegExp` instances at module load (one-time cost reported separately as "bundle parse time").

### Measurement 1 — Perf benchmark

**What runs**: in headless Chrome via Playwright, for each prompt in the 11K corpus:

```js
const t0 = performance.now();
for (const p of patterns) {
  // exhaustive find — match all occurrences, not just first
  const re = new RegExp(p.regex_source, 'g');
  for (const m of text.matchAll(re)) { /* count */ }
}
const elapsed = performance.now() - t0;
```

**What's reported** (in `report/perf.json`):

- Per-prompt total scan latency (all 77 patterns sequentially): full distribution
  - P50, P75, P90, P95, P99, P99.9, max
  - Histogram (50 buckets, log-scale)
  - Latency vs prompt-length scatter (sampled 1K points)
- Per-pattern P99 latency: which patterns dominate the tail
- Throughput: prompts/sec
- Bundle parse time: time to construct 77 `RegExp` instances at module load
- Heap delta: `performance.memory.usedJSHeapSize` before vs after benchmark (Chrome-only API)

**Methodology guards**:

- Warm-up: 100 prompts before measurement starts (V8 JIT settle)
- Use `performance.now()` not `Date.now()` (sub-millisecond precision)
- One Playwright page per run; no contention from other browser activity
- Run 3 times. The "representative run" = the run whose P99 is the median of the three P99s. Distribution stats reported from that run; cross-run variance reported as `(min P99, median P99, max P99)` triplet

### Measurement 2 — ReDoS audit

**What runs**: `recheck` (`@makenowjust-labs/recheck` Node CLI) on each of the 77 pattern regex sources.

**What's reported** (in `report/redos.json`):

- Per-pattern verdict: `safe` / `vulnerable` (with complexity: polynomial / exponential)
- For each `vulnerable` pattern: attack string, complexity class, worst-case time estimate
- Tabulated counts: `safe`, `polynomial`, `exponential`

**No gate** — pure data. The cross-reference happens in the report:

> "Pattern `X` is `recheck`-flagged exponential AND its measured P99 = N ms in measurement (1)."

That intersection is what the execution track cares about.

### Measurement 3 — Bundle size

**What's bundled** (via esbuild, minified):

- `patterns.js` (regex sources + metadata: name, entity_type, category)
- `entropy.js` (Shannon entropy function, ~30 LOC port)

**What's reported** (in `report/bundle.json`):

- Raw bundle bytes
- Gzipped bytes
- **Projected total** including validators: `measured + (validators_python_LOC × 0.7 × 30 bytes)` ≈ measured + ~12KB conservative
  - The 0.7 is JS-vs-Python LOC ratio (rough), 30 bytes/min-LOC is empirical for minified JS with similar identifier density
  - Marked clearly as a projection, not a measurement
- Reference target from queue.md: <200KB total (gzipped)

---

## Components

```
docs/experiments/prompt_analysis/s2_spike/
├── SPEC.md                    # this file
├── package.json               # deps: playwright, @makenowjust-labs/recheck, esbuild
├── .gitignore                 # node_modules/, *.log
├── extract_patterns.mjs       # default_patterns.json → patterns.js
├── extract_corpus.py          # WildChat → corpus.jsonl (XOR-encoded)
├── benchmark.html             # bare HTML page, loaded by Playwright
├── benchmark.js               # in-page perf code
├── run_benchmark.mjs          # Playwright driver: opens page, collects timings
├── audit_redos.mjs            # iterates patterns, calls recheck CLI
├── measure_bundle.mjs         # esbuild bundle, gzip, report bytes
├── entropy.js                 # Shannon entropy (small util)
├── corpus.jsonl               # generated, gitignored (regenerable)
├── report/
│   ├── perf.json
│   ├── redos.json
│   ├── bundle.json
│   └── s2_browser_port_spike.md   # final memo
```

## Output: final memo

Structure (target ~150-250 lines):

1. **TL;DR** — one paragraph: what we measured, what the data says about Path 1 viability at three threshold options (50/100/200ms)
2. **Methodology** — corpus, harness, three measurements (links to scripts)
3. **Perf results** — distribution table, histogram description, top-5 worst patterns by P99
4. **ReDoS results** — count table, list of any `polynomial`/`exponential` patterns with attack strings
5. **Bundle results** — measured + projected
6. **Cross-reference** — patterns that appear in both perf-tail AND ReDoS-flagged (the actual risk set)
7. **Recommendation** — Path 1 vs Path 2, with the budget decision deferred to execution track but the data laid out
8. **Filed follow-ups** — S2.5 secret_scanner perf, any Sprint 13/14 backlog items surfaced

---

## Acceptance criteria

- [ ] `corpus.jsonl` exists with 11K records, XOR-encoded prompt text
- [ ] `report/perf.json` contains distribution + per-pattern P99 + bundle parse time + heap delta
- [ ] `report/redos.json` contains 77 verdicts, attack strings for non-safe patterns
- [ ] `report/bundle.json` contains raw + gzipped bytes + projected total
- [ ] Final memo committed at `report/s2_browser_port_spike.md` with all 8 sections
- [ ] queue.md S2 status updated to ✅ COMPLETE with headline numbers
- [ ] node_modules/ gitignored; corpus.jsonl gitignored (regenerable from `extract_corpus.py`)
- [ ] All scripts runnable via documented one-liners in spec

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Pattern translation bug (Python regex flavor → JS) | Spot-check confirmed RE2-compatible; add per-pattern smoke test that compiles each `RegExp` at extract time and reports any failures |
| WildChat HF cache stale or evicted | Cache is warm from S0 (run 8 min ago in dataset terms); fall back to streaming with limit |
| Playwright not installed / Chromium download blocked | Document install step explicitly; if blocked, fall back to `node --experimental-vm-modules` with V8 directly (lose page-context fidelity but get regex perf) |
| `recheck` CLI behavior changes between versions | Pin exact version in package.json |
| esbuild minification too aggressive (mangling regex strings) | Patterns are stored as JS strings, not RegExp literals at bundle level; minifier won't touch string contents |
| 11K corpus too small for stable P99.9 | Acceptable for go/no-go; if P99.9 is the load-bearing number we'd need 100K, but P99 is sufficient for path selection |

---

## Decisions made during brainstorm (2026-04-16)

| Decision | Choice | Rationale |
|---|---|---|
| Scope | 77 content regex patterns only | secret_scanner is a different algorithm shape; perf characteristics don't transfer |
| Corpus | 10K random + 1K longest = 11K | Random for unbiased distribution; long for explicit tail stress |
| Threshold | None — output distribution | "Don't anchor on a number, measure" (user direction) |
| ReDoS gate | None — categorize only | No gate; data drives execution-track decision |
| Validators in bundle | Projected, not measured | Out of S2 scope; measure once execution track ports them |
| Test env | Headless Chrome via Playwright | Per queue.md S2 specification |
| Output location | `docs/experiments/prompt_analysis/s2_spike/` | Co-located with research artifacts; node_modules gitignored |

## Filed follow-ups (post-spike)

### S2.5 — secret_scanner browser-port perf (file as backlog item)

When: after S2 completes. Triggers: even if Path 1 viable, execution track also needs to know secret_scanner's runtime cost to size the worker kill budget.

What: port `parse_key_values` + entropy scoring + 178-entry secret_key dict lookup to JS, run on same 11K corpus, report distribution. Same harness, separate measurement.

### Sprint-13/14 backlog items potentially surfaced by S2

- If a pattern shows pathological perf in measurement (1) AND is `recheck`-flagged exponential in (2), file as a Sprint 13 P1 pattern-rewrite item with the failing regex + perf evidence
- If bundle exceeds 200KB even before validators, file an architectural item to pre-decide Path 2 (re2-wasm)

---

## How to run (final memo will include this verbatim)

```bash
cd docs/experiments/prompt_analysis/s2_spike
npm install
node extract_patterns.mjs
DATA_CLASSIFIER_DISABLE_ML=1 .venv/bin/python extract_corpus.py --limit 10000 --long-from-s0 1000
node run_benchmark.mjs       # ~10-15 min
node audit_redos.mjs         # ~2-3 min
node measure_bundle.mjs      # ~5 sec
# Final memo writing is manual — review the three JSONs, write report/s2_browser_port_spike.md
```
