# Classification Library — Performance & Resource Management

## Two Budgets

Every deployment of the classification library is constrained by two independent budgets that interact but require separate management.

**Latency budget** — how much time a single classification request can take. Measured in milliseconds. Driven by the consumer's responsiveness requirements: a prompt gateway intercepting ChatGPT submissions needs answers in 50-150ms; a batch scanner classifying 10,000 BigQuery columns overnight has no time pressure.

**Resource budget** — how much compute, memory, and money a deployment can consume. Measured in CPU cores, GB of RAM, GPU availability, API call counts, and dollars per month. Driven by infrastructure constraints and cost targets: a scanner image running on a shared VM has 2 cores and 4GB RAM; an enterprise classification service has dedicated GPU nodes and a $500/month API budget.

These budgets are orthogonal. A deployment can have a tight latency budget but generous resources (prompt gateway on a GPU-equipped server), or relaxed latency but tight resources (batch scanner on a small VM). The library's profile and configuration system addresses both.

---

## Latency Budget

### Mechanism

The latency budget is per-request, opt-in, and adaptive.

```
classify_text(text, budget_ms=100)
classify_column(column, budget_ms=50)
```

When `budget_ms` is set, the orchestrator uses live p95 latency measurements from the `TierLatencyTracker` to decide which tiers fit in the remaining time after fast tiers complete. Eligible slow tiers race in parallel; ineligible tiers are skipped.

When `budget_ms` is `null` (default), tiers run sequentially with no time constraint — full cascade, maximum accuracy.

### Latency Profile of Each Tier

| Tier | Typical Latency | Variance | Dependencies | Parallelizable |
|------|----------------|----------|-------------|----------------|
| Column Name Semantics | <0.5ms | Very low | None | N/A (fast) |
| Regex | <1ms | Very low | None | N/A (fast) |
| Heuristic Statistics | <0.5ms | Very low | None | N/A (fast) |
| Dictionaries | <1ms | Low | Dictionary size | N/A (fast) |
| **Structural Content Classifier** | <1ms | Very low | ML model (<200KB) or heuristics | N/A (fast) |
| **Boundary Detector** | <2ms | Low (text length) | Structural classifier | N/A (fast) |
| **Structured Secret Scanner** | <5ms | Medium (parse complexity) | None | N/A (fast) |
| Financial Density Scorer | <1ms | Very low | None | N/A (fast) |
| Cloud DLP | 50-200ms | High (network) | GCP API | Yes |
| GLiNER2 | 10-50ms | Medium (text length) | Model loaded | Yes |
| Embeddings | 5-20ms | Low | Model loaded | Yes |
| SLM | 50-500ms | High (model size, quantization) | Model loaded | Yes |
| LLM | 200-2000ms | Very high (network, provider) | External API | Yes |

### Latency Scenarios

**Prompt interception (budget: 100ms)**
```
Fast tiers:           1.5ms  → always complete
GLiNER2 (p95: 42ms):   fits   → runs in parallel
Embeddings (p95: 18ms): fits → runs in parallel
Cloud DLP (p95: 140ms): skip → exceeds budget
SLM (p95: 180ms):     skip   → exceeds budget

Total: ~45ms, 55ms remaining unused
Tiers executed: 6 of 9
```

**Batch scanner (no budget)**
```
All tiers run sequentially
Each column: 50-400ms depending on which tier classifies it
10,000 columns: ~15-60 minutes total
Full accuracy, no compromises
```

**Real-time API consumer (budget: 30ms)**
```
Fast tiers:           1.5ms  → always complete
GLiNER2 (p95: 42ms):   skip   → exceeds budget
Embeddings (p95: 18ms): fits → runs
Cloud DLP (p95: 140ms): skip
SLM (p95: 180ms):     skip

Total: ~20ms
Tiers executed: 5 of 9 (fast tiers + embeddings only)
Lower accuracy but meets deadline
```

### Adaptive Latency Tracking

The `TierLatencyTracker` maintains a rolling window of actual execution times per tier. Budget decisions use p95 (conservative but not worst-case).

**Cold start:** When the library starts with no history, it is optimistic — all tiers run to collect baseline measurements. Within 10-20 requests, the tracker has enough data for informed decisions. This means the first few requests under budget may slightly exceed the target.

**Latency drift:** If a tier's latency changes (e.g., DLP API slows due to network conditions), the tracker adapts within its window size. A tier that previously fit in the budget may be dynamically excluded until its latency improves.

**Monitoring:** Live latency stats are exposed via `GET /stats` for operational visibility:

```json
{
  "latency_tracker": {
    "regex":     {"p50_ms": 0.5, "p95_ms": 1.2, "p99_ms": 2.1, "samples": 100},
    "gliner":    {"p50_ms": 28,  "p95_ms": 42,  "p99_ms": 55,  "samples": 100},
    "cloud_dlp": {"p50_ms": 85,  "p95_ms": 140, "p99_ms": 210, "samples": 87}
  }
}
```

---

## Resource Budget

### Memory

Memory is the primary constraint that determines which tiers can be active. Each ML model consumes a fixed amount of RAM when loaded.

| Component | Memory (float32) | Memory (4-bit quantized) | Load Behavior |
|-----------|-----------------|-------------------------|---------------|
| Library core + fast tiers | ~50 MB | ~50 MB | Always loaded |
| GLiNER2 (205M, unified) | ~800 MB | ~200 MB (ONNX uint8) | Lazy: loaded on first invocation |
| GLiNER PII base (500M, optional) | ~2 GB | ~500 MB (ONNX uint8) | Lazy: only if higher PII accuracy needed |
| EmbeddingGemma (308M) | ~1.2 GB | ~200 MB (quantized) | Lazy |
| NLI / BART-MNLI (400M) | ~1.6 GB | ~400 MB (quantized) | Lazy (prompt module) |
| Gemma 3 1B-IT | ~4 GB | ~500 MB | Lazy |
| Gemma 3 4B-IT | ~16 GB | ~2 GB | Lazy |
| Gemma 4 E4B MoE | ~10 GB | ~4 GB | Lazy |
| Gemma 4 31B | ~62 GB | ~20 GB | Lazy |
| Reference taxonomy embeddings | ~5 MB | ~5 MB | Loaded with embeddings tier |
| Regex patterns (compiled) | ~2 MB | ~2 MB | Always loaded |
| Structural Content Classifier (ML) | <0.2 MB | <0.2 MB | Always loaded (pure Python decision rules) |
| Structured Secret Scanner (dictionaries) | ~1 MB | ~1 MB | Always loaded |
| Column name dictionary | ~5 MB | ~5 MB | Always loaded |
| Customer dictionaries | Varies | Varies | Loaded at init |

**Lazy loading** is critical. Models are loaded into memory only when their tier is first invoked. A Free profile deployment uses ~60MB. A Standard profile adds GLiNER2 on first use (~500MB quantized). Models that are never invoked never consume memory.

**Memory profiles:**

| Profile | Models Loaded | Peak Memory | Minimum VM |
|---------|-------------|-------------|------------|
| Free | None | ~60 MB | 256 MB |
| Standard | GLiNER2 (quantized) | ~600 MB | 1 GB |
| Standard+ Embeddings | GLiNER2 + EmbeddingGemma (quantized) | ~800 MB | 1.5 GB |
| Advanced (1B SLM) | GLiNER2 + EmbeddingGemma + Gemma 1B (4-bit) | ~1.3 GB | 2 GB |
| Advanced (4B SLM) | GLiNER2 + EmbeddingGemma + Gemma 4B (4-bit) | ~2.8 GB | 4 GB |
| Advanced (E4B MoE) | GLiNER2 + EmbeddingGemma + Gemma E4B (4-bit) | ~4.8 GB | 8 GB |
| Maximum (31B SLM) | All models, Gemma 31B (4-bit) | ~21 GB | 32 GB (GPU recommended) |

### CPU

All tiers run on CPU. GPU is optional and only accelerates model inference (GLiNER2, Embeddings, SLM).

**CPU-bound tiers:** Regex (pattern compilation), Heuristics (statistical computation), Dictionary (hash lookups). These are negligible — a single core handles thousands of classifications per second.

**Model inference tiers:** GLiNER2, Embeddings, SLM. These are the CPU bottleneck. Performance depends on:

| Factor | Impact | Mitigation |
|--------|--------|-----------|
| Model size | Larger = slower inference | Use quantized models, select appropriate size |
| Quantization | 4-bit: ~3-4x faster than float32 | Always quantize for CPU deployment |
| Text length | Longer text = slower NER/embedding | Chunk text to 1-5KB |
| Batch size | Batching amortizes model overhead | Use `classify_table` for column batches |
| CPU architecture | AVX2/AVX-512 improves inference | Choose compute-optimized VM instances |
| Concurrency | Parallel requests compete for CPU | Limit concurrent model inference |

**Throughput estimates (single CPU core, quantized models):**

| Tier | Throughput (column mode) | Throughput (text mode, 1KB) |
|------|------------------------|---------------------------|
| Fast tiers only (Free) | ~5,000 columns/sec | ~5,000 texts/sec |
| + GLiNER2 | ~50 columns/sec | ~30 texts/sec |
| + Embeddings | ~100 columns/sec | ~80 texts/sec |
| + SLM (4B, 4-bit) | ~10 columns/sec | ~5 texts/sec |

For batch workloads (scanner), throughput is usually not the bottleneck — BigQuery sampling is slower than classification. For real-time workloads (prompt gateway), concurrent request handling requires careful sizing.

### GPU

GPU acceleration is not required but provides significant speedup for model inference tiers.

| Tier | CPU Inference | GPU Inference (T4) | GPU Inference (A100) |
|------|-------------|-------------------|---------------------|
| GLiNER2 | 30-50ms | 5-10ms | 2-5ms |
| EmbeddingGemma | 10-20ms | 2-5ms | <2ms |
| Gemma 3 4B (4-bit) | 200-500ms | 30-80ms | 10-30ms |
| Gemma 4 31B (4-bit) | Not practical | 200-500ms | 50-150ms |

**GPU sizing guidance:**

| Use Case | Recommendation |
|----------|---------------|
| Batch scanner, ≤Standard profile | CPU only — no GPU needed |
| Batch scanner, Advanced profile | Optional T4 for faster SLM inference |
| Prompt gateway, Standard profile | CPU only if budget ≥100ms; T4 if budget <50ms |
| Prompt gateway, Advanced profile | T4 recommended for SLM under budget |
| High-throughput API service | A100 or equivalent for multiple concurrent model inferences |

### API Cost

Two tiers incur per-call API costs: Cloud DLP and LLM.

**Cloud DLP (Google):**

| Volume | Approximate Cost | Notes |
|--------|-----------------|-------|
| 1,000 inspect calls | ~$1-3 | Per scan of ~1,000 columns |
| 10,000 inspect calls | ~$10-30 | Large warehouse scan |
| 100,000 inspect calls/month | ~$100-300 | Continuous scanning |

Cloud DLP cost scales with the number of columns that reach Tier 4 (after fast tiers classify the rest). With a strong regex + heuristic tier, 40-60% of columns are classified before DLP fires — reducing API calls by half.

**LLM API (Gemini Flash / Claude Haiku / GPT-4o-mini):**

| Volume | Approximate Cost | Notes |
|--------|-----------------|-------|
| 50 calls per scan | ~$0.01-0.05 | Typical: <5% of columns reach LLM |
| 500 calls per scan | ~$0.10-0.50 | Unusual: weak earlier tiers |
| 10,000 calls/month | ~$2-10 | Continuous scanning with LLM fallback |

LLM cost is negligible when the cascade is working well. If >10% of classifications reach the LLM tier, earlier tiers need tuning or fine-tuning.

**Cost controls in configuration:**

```json
{
  "cost_budget": {
    "max_dlp_calls_per_scan": 1000,
    "max_llm_calls_per_scan": 50,
    "max_llm_cost_per_month_usd": 50
  }
}
```

When a budget is exhausted, the respective tier is skipped for the remainder of the scan. Events log tier skips with `outcome: "budget_exceeded"` so consumers can track when budgets constrain accuracy.

### Storage

The library itself has minimal storage requirements. All storage is for models and shipped assets.

| Component | Size on Disk | Notes |
|-----------|-------------|-------|
| Library package (code + patterns) | ~10 MB | Always required |
| GLiNER2 (or PII base) (ONNX, quantized) | ~250 MB | Downloaded on first use or pre-baked into image |
| GLiNER2 PII edge (ONNX, quantized) | ~100 MB | Smaller alternative |
| EmbeddingGemma (quantized) | ~200 MB | Downloaded on first use |
| NLI / BART-MNLI (quantized) | ~400 MB | Downloaded on first use (prompt module) |
| Gemma 3 1B (4-bit GGUF) | ~500 MB | Downloaded on first use |
| Gemma 3 4B (4-bit GGUF) | ~2.5 GB | Downloaded on first use |
| Gemma 4 E4B MoE (4-bit) | ~4 GB | Downloaded on first use |
| Reference taxonomy (pre-computed) | ~5 MB | Ships with library |

**Model caching:** Models are downloaded from Hugging Face or a configured model registry on first use and cached locally. For containerized deployments (scanner images), models should be pre-baked into the container image to avoid download latency on cold start.

---

## Deployment Sizing Guide

### Small: Scanner on Shared VM

```
Resources:  2 CPU cores, 4 GB RAM, no GPU
Profile:    Standard (regex + heuristics + DLP + GLiNER2)
Models:     GLiNER2 (quantized (quantized, ~200 MB)
Budget:     No latency budget (batch)
Cost:       Cloud DLP API only (~$1-10/scan)
Throughput: ~30-50 columns/sec
Use case:   Periodic BigQuery scan, <10K columns
```

### Medium: Dedicated Scanner Instance

```
Resources:  4 CPU cores, 8 GB RAM, no GPU
Profile:    Advanced (all local tiers)
Models:     GLiNER2 + EmbeddingGemma + Gemma 3 4B (all quantized, ~3 GB total)
Budget:     No latency budget (batch)
Cost:       Cloud DLP API (~$10-30/scan)
Throughput: ~10-20 columns/sec (with SLM)
Use case:   Large warehouse scan, 10K-100K columns
```

### Real-Time: Prompt Gateway (with Prompt Analysis Module)

```
Resources:  4 CPU cores, 6 GB RAM, optional T4 GPU
Profile:    Standard
Modules:    Classification library + Prompt analysis module
Models:     GLiNER2 (quantized, ~200 MB) + EmbeddingGemma (~200 MB) + NLI/BART-MNLI (~400 MB)
Budget:     100ms per request
Cost:       No API cost (local only)
Throughput: ~20-30 prompts/sec (CPU), ~60-80 prompts/sec (GPU)
Use case:   Prompt interception with zone + intent + risk analysis, <100 concurrent users
Scaling:    Horizontal — multiple instances behind load balancer
Note:       NLI model only loads if GLiNER2 intent confidence < threshold (lazy)
```

### Enterprise: Shared Classification Service

```
Resources:  8 CPU cores, 16 GB RAM, A100 GPU
Profile:    Advanced (configurable per consumer)
Modules:    Classification library + Prompt analysis module
Models:     All loaded (~6 GB total: GLiNER2 + EmbeddingGemma + NLI + Gemma 4B + taxonomy)
Budget:     Per-consumer (scanner: none, prompt: 100ms, API: 50ms)
Cost:       Cloud DLP + LLM API (~$50-200/month)
Throughput: ~150 texts/sec, ~400 columns/sec, ~80 prompts/sec
Use case:   Multi-consumer service (scanner + prompt gateway + API clients)
Scaling:    Vertical (bigger GPU) or horizontal (multiple instances, model replicas)
```

---

## Optimization Strategies

### Reduce Memory

| Strategy | Impact | Trade-off |
|----------|--------|-----------|
| Use GLiNER edge instead of base | -300 MB | ~4% lower F1 |
| Use EmbeddingGemma at 128 dimensions (vs 768) | Negligible RAM difference (model same size) | Slightly lower semantic precision |
| Use Gemma 3 1B instead of 4B | -1.5 GB | Lower SLM reasoning quality |
| Disable SLM tier entirely | -2 GB | Lose context-aware synthesis |
| Pre-filter: skip ML tiers for columns already classified by fast tiers | No change in peak, but less concurrent model use | None — this is the cascade's natural behavior |

### Reduce Latency

| Strategy | Impact | Trade-off |
|----------|--------|-----------|
| Set `budget_ms` | Enforces deadline, skips slow tiers | May reduce accuracy for that request |
| Quantize all models (4-bit/8-bit) | 2-4x faster inference | Minimal accuracy loss (QAT models) |
| Add GPU | 5-10x faster for GLiNER, SLM | Hardware cost |
| Pre-load models at startup (disable lazy loading) | Eliminates first-request latency spike | Higher baseline memory even if tiers unused |
| Use GLiNER edge | ~2x faster than base | ~4% lower F1 |
| Reduce embedding dimensions (768→128) | ~2x faster cosine similarity | Minor precision loss |

### Reduce API Cost

| Strategy | Impact | Trade-off |
|----------|--------|-----------|
| Strengthen fast tiers (better regex, richer column name dictionary) | Fewer columns reach DLP/LLM | Maintenance effort |
| Fine-tune GLiNER / SLM | Earlier tiers catch more | Requires feedback data + training pipeline |
| Set `max_dlp_calls_per_scan` | Hard cap on DLP cost | Some columns skip DLP |
| Cache LLM responses for recurring patterns | Fewer unique LLM calls | Stale cache risk |
| Use Free profile for known-format columns, Standard for unknown | DLP only fires on hard cases | Requires pre-classification routing |

### Reduce CPU

| Strategy | Impact | Trade-off |
|----------|--------|-----------|
| Batch classify (classify_table vs per-column) | Model overhead amortized | Minor — always prefer batch |
| Limit concurrent model inference | Prevents CPU thrashing | Queuing latency under load |
| Use smaller models (1B vs 4B) | ~4x less compute per inference | Lower accuracy |
| Offload to GPU | Frees CPU for other work | Hardware cost |

---

## Concurrency & Throughput

### The GIL Challenge

Python's Global Interpreter Lock (GIL) allows only one thread to execute Python bytecode at a time. For CPU-bound work (feature extraction, decision rules), this means a single Python process can only utilize one CPU core regardless of thread count.

**What holds the GIL:**
- Feature extraction (character counting, string operations) — pure Python, CPU-bound
- Decision rule evaluation (if/else chains) — pure Python, CPU-bound
- Note: regex matching does NOT hold the GIL — RE2 runs in C++ (see D34)

**What releases the GIL:**
- RE2 regex matching — C++ backend, releases GIL during pattern matching
- ONNX Runtime inference — C++ backend, releases GIL during computation
- PyTorch inference — C++ backend, releases GIL
- Cloud DLP calls — network I/O, releases GIL while waiting
- numpy operations — C backend, releases GIL for array operations

Ironically, the "fast" engines (pure Python) are the GIL bottleneck. The "slow" engines (C/C++ backends) handle concurrency naturally.

### Single-Request GIL Time

```
Feature extraction:  0.5ms  (Python, holds GIL)
Decision rules:      0.06ms (Python, holds GIL)
Total GIL time:      ~0.56ms per classification request

Single-worker maximum: 1000ms / 0.56ms ≈ 1,785 requests/second
```

### Throughput by Deployment Type

| Deployment | Requests/sec | Workers | Bottleneck |
|-----------|-------------|---------|-----------|
| Scanner (batch, 10K columns) | N/A — single request | 1 | 5.6 seconds total |
| Prompt gateway (light) | ~100 | 1 | 5.6% of one core |
| Prompt gateway (medium) | ~500 | 1 | 28% of one core |
| Prompt gateway (heavy) | ~2,000 | 2 | Approaching worker limit |
| Enterprise API service | ~10,000+ | 8 | Needs optimization (Phase 2) |

### Phase 1: Multiple Workers (Ships Immediately)

The simplest and most effective scaling approach. Each worker is a separate Python process with its own GIL.

```bash
# FastAPI with uvicorn — 8 workers on 8 cores
uvicorn main:app --workers 8 --host 0.0.0.0 --port 8000

# Each worker: independent Python process, own GIL, own memory
# 8 workers × 1,785 req/s = ~14,000 requests/second
# No code changes needed.
```

The classification library is stateless — no shared state between requests. Workers scale linearly with CPU cores. ML models are loaded per-worker (memory cost = workers × model size).

For the scanner use case (batch, not concurrent), a single worker handles 10,000 columns in 5.6 seconds — well within overnight batch windows.

For the prompt gateway use case, 4-8 workers handle typical enterprise load (500-5,000 requests/second) on a standard VM.

### Phase 2: Vectorized Feature Extraction (If Batch Throughput Matters)

Rewrite feature extraction to use numpy array operations that release the GIL:

```python
# Before: Python loop (holds GIL)
def extract_features(text):
    semicolons = sum(1 for c in text if c == ';')
    ...

# After: numpy vectorized (releases GIL during array ops)
def extract_features_batch(texts):
    byte_arrays = [np.frombuffer(t.encode(), dtype=np.uint8) for t in texts]
    semicolons = np.array([np.sum(b == ord(';')) for b in byte_arrays])
    ...
```

Decision rules can also be vectorized — replace if/else chains with numpy boolean indexing:

```python
# Before: Python if/else (one sample at a time)
if features["semicolon_density"] > 0.031: ...

# After: numpy boolean (entire batch at once, releases GIL)
mask = features_array[:, SEMICOLON_IDX] > 0.031
```

**Impact:** 5-10x throughput improvement for batch endpoints (scanner classifying 100K columns).

### Phase 3: Compiled Feature Extraction (If High-Concurrency Gateway)

If enterprise prompt gateways require >10,000 concurrent requests/second, rewrite `extract_features()` as a compiled extension:

**Option A: Cython (recommended first step)**

Cython compiles Python-like code to C. Add type annotations, rename `.py` to `.pyx`, compile. The inner loops become C loops (50x faster), and `with nogil:` blocks enable true multi-threaded parallelism.

```cython
# features.pyx — almost identical to Python, but compiled to C
def extract_features(str text):
    cdef int chars = len(text)
    cdef int semicolons = 0
    cdef bytes b_text = text.encode()
    cdef char c
    for c in b_text:          # C loop: ~1ns per character (vs ~50ns in Python)
        if c == b';':
            semicolons += 1
    return {"semicolon_density": <float>semicolons / chars}
```

Build: `pip install cython && cythonize -i features.pyx`
Impact: 10-50x speedup on feature extraction, GIL released during C loops.
Code change: minimal — add type hints to one ~100-line function.

**Option B: Rust via PyO3 (if Cython isn't enough)**

Full Rust implementation of feature extraction with automatic Python bindings. 50-100x speedup, memory safety, automatic GIL release.

```rust
// src/lib.rs
use pyo3::prelude::*;

#[pyfunction]
fn extract_features(text: &str) -> PyResult<HashMap<String, f64>> {
    let chars = text.len() as f64;
    let semicolons = text.chars().filter(|&c| c == ';').count() as f64;
    let mut features = HashMap::new();
    features.insert("semicolon_density".into(), semicolons / chars);
    Ok(features)
}
```

Build: `pip install maturin && maturin develop --release`
Impact: 50-100x speedup, zero GIL contention.
Code change: significant — rewrite in Rust, maintain two-language codebase.

**Decision framework:**

```
< 500 req/s:     uvicorn --workers 4           (Phase 1, no code changes)
500-5,000 req/s:  uvicorn --workers 8           (Phase 1, add cores)
5,000-20,000:     numpy vectorization           (Phase 2, batch optimization)
> 20,000 req/s:   Cython extract_features()     (Phase 3, compile hot path)
> 50,000 req/s:   Rust via PyO3                 (Phase 3, full rewrite of hot path)
```

Most deployments never need Phase 2. Enterprise-scale prompt gateways may need Phase 3.

### Process Pool for Async Handlers

For FastAPI async endpoints handling mixed CPU-bound and I/O-bound work, offload CPU work to a process pool:

```python
from concurrent.futures import ProcessPoolExecutor

pool = ProcessPoolExecutor(max_workers=8)

async def classify_text(request):
    # CPU-bound work runs in process pool — doesn't block event loop
    features = await asyncio.get_event_loop().run_in_executor(
        pool, extract_features, request.text
    )
    result = await asyncio.get_event_loop().run_in_executor(
        pool, classify, features
    )
    return result
```

This keeps the async event loop responsive for handling network I/O (Cloud DLP responses, LLM API calls) while CPU-bound feature extraction runs in parallel processes.

---

## Monitoring and Alerting

### Key Metrics to Track

**Latency metrics (from events):**
- p95 latency per tier — detect degradation
- Budget exhaustion rate — % of requests where budget ran out
- Tier skip rate under budget — which tiers are most often excluded

**Resource metrics (from infrastructure):**
- Memory usage — detect model loading issues, memory leaks
- CPU utilization — detect inference bottlenecks
- GPU utilization (if present) — ensure GPU is being used effectively

**Cost metrics (from events):**
- DLP API calls per scan / per day / per month
- LLM API calls per scan / per day / per month
- Cost per classification (DLP + LLM cost / total classifications)
- Cost per detected entity (DLP + LLM cost / total hits)

**Accuracy-adjacent metrics (from events):**
- Tier hit rate — which tiers are contributing
- Sole contributor rate — which tiers are indispensable
- Cascade depth — how many tiers fire on average before classification
- Coverage — % of inputs classified vs. total

### Alert Thresholds

| Condition | Alert | Action |
|-----------|-------|--------|
| p95 latency for any tier > 2x baseline | Warning | Investigate network (DLP) or model loading issues |
| Budget exhaustion rate > 20% | Warning | Increase budget, upgrade profile, or add GPU |
| Memory usage > 90% of available | Critical | Scale up VM or reduce model sizes |
| DLP API calls approaching monthly budget | Warning | Review whether DLP tier is necessary for all columns |
| LLM hit rate > 10% of classifications | Warning | Earlier tiers need tuning — too much falling through |
| Coverage dropping over time | Warning | New data types not covered — update patterns/labels |

---

## Capacity Planning

### Estimation Formula

```
Peak memory = library_base (50 MB)
            + sum(model sizes for active profile, quantized)
            + customer_dictionaries_size
            + overhead (~20%)

Throughput (columns/sec) = 1000 / avg_cascade_latency_ms
  where avg_cascade_latency ≈ fast_tiers (2ms) + slowest_active_tier * hit_rate

API cost/month = (columns_per_scan * pct_reaching_dlp * dlp_cost_per_call * scans_per_month)
               + (columns_per_scan * pct_reaching_llm * llm_cost_per_call * scans_per_month)
```

### Example: Weekly BigQuery Scan

```
Warehouse: 5,000 columns across 200 tables
Profile: Standard (regex + heuristics + DLP + GLiNER2)
Scan frequency: weekly

Fast tiers classify: ~55% (2,750 columns) → 0 API cost
DLP processes: ~45% (2,250 columns) → ~$2-7/scan
GLiNER processes: ~30% (1,500 columns) → $0 (local)

Monthly API cost: ~$8-28 (4 scans × $2-7)
Memory: ~600 MB (library + GLiNER quantized)
Scan time: ~5 minutes (2,250 DLP calls at ~150ms each, parallelized)
VM: 2 cores, 2 GB RAM is sufficient
```

### Example: Prompt Gateway (100 users)

```
Prompts: ~500/hour peak, ~2,000/day
Profile: Standard with budget_ms=100
Models: GLiNER quantized (~500 MB)

Memory: ~600 MB steady state
CPU: 2 cores handles ~30 texts/sec = 1,800/min (well above 500/hour peak)
API cost: $0 (no DLP or LLM in standard prompt path)
Latency: p95 < 50ms (regex + GLiNER under budget)
```
