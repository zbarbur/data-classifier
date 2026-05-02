# data_classifier_core

Zone detection engine for identifying code, markup, config, and other structured blocks within LLM prompts. Single Rust implementation that compiles to both **WASM** (browser extensions) and **native Python module** (server-side), guaranteeing identical detection behavior across all environments.

## Detection Pipeline

10-step cascade, processing ~300 prompts/sec:

1. **Pre-screen** -- fast-path rejection (97% of plain prose)
2. **Structural** -- fenced blocks (` ``` `), `<script>`, `<style>` delimiter pairs
3. **Format** -- JSON, XML, YAML, ENV detection on unfenced regions
4. **Syntax** -- 3-pass line scoring: raw features, context smoothing, comment bridging
5. **Scope** -- bracket continuation + indentation scope tracking
6. **Negative filter** -- FP suppression (error output, math, prose, dialog, ratios)
7. **Assembler** -- block grouping, gap bridging, repetitive structure detection
8. **Block validator** -- code construct counting, math indicator suppression
9. **Language** -- fragment-hit language detection + C-family disambiguation
10. **Merge** -- adjacent compatible blocks (code + error_output)

Configuration is loaded from `zone_patterns.json` -- all thresholds, keywords, fragment patterns, and weights are shared between all build targets.

## Quality Metrics

Evaluated on 647 human-reviewed WildChat prompts:

| Metric | Value | Target |
|--------|-------|--------|
| Precision | 98.3% | >90% |
| Recall | 95.7% | >95% |
| F1 | 0.970 | >0.92 |
| Boundary recall | 99.5% | >85% |
| Fragmentation | 1.06x | <1.3x |

**Parity**: 647/647 prompts produce identical results across Python, Rust native, and WASM (100.0%).

## Performance

| Runtime | Throughput |
|---------|-----------|
| Python (via pyo3) | 315 prompts/sec |
| Rust native | 320 prompts/sec |
| WASM (Chrome) | 266 prompts/sec |

## Build

### Prerequisites

- Rust toolchain (`rustup`)
- For WASM: `wasm-pack` (`cargo install wasm-pack`)
- For Python: `maturin` (`pip install maturin`)

### Run tests

```bash
cd data_classifier_core
cargo test --no-default-features
```

### Build for Python

```bash
cd data_classifier_core
maturin develop --release
```

This installs `data_classifier_core` into the active virtualenv. Python usage:

```python
import json
from data_classifier_core import ZoneDetector

with open("zone_patterns.json") as f:
    patterns = f.read()

detector = ZoneDetector(patterns)
result = detector.detect_zones(text, prompt_id)
# result.blocks, result.total_lines, result.prompt_id
```

### Build for WASM (browser)

```bash
cd data_classifier_core
wasm-pack build --target web --release
```

Output goes to `pkg/`. Browser usage:

```javascript
import init, { init_detector, detect } from './pkg/data_classifier_core.js';
await init();
init_detector(patternsJson);            // compile patterns once
const resultJson = detect(text, id);     // ~0.5ms per prompt
```

### Build native evaluate binary

```bash
cd data_classifier_core
cargo build --release --no-default-features --bin evaluate
./target/release/evaluate <patterns.json> <corpus.jsonl> [--output results.jsonl]
```

## Architecture

```
Cargo.toml
  features: wasm (default) | python

src/
  lib.rs                    -- feature-gated WASM + Python APIs
  bin/evaluate.rs           -- corpus evaluator binary
  zone_detector/
    mod.rs                  -- ZoneOrchestrator (10-step pipeline)
    types.rs                -- ZoneType, ZoneBlock, PromptZones
    config.rs               -- ZoneConfig defaults
    pre_screen.rs           -- fast-path rejection
    structural.rs           -- fenced blocks + delimiter pairs
    format_detector.rs      -- JSON/XML/YAML/ENV
    syntax.rs               -- 3-pass line scoring + fragments
    tokenizer.rs            -- token profile extraction
    scope.rs                -- bracket/indentation scope
    negative.rs             -- FP suppression
    assembler.rs            -- block grouping + validation
    block_validator.rs      -- code construct patterns
    language.rs             -- language detection

bench/
    benchmark.html          -- browser WASM benchmark
    compare_parity.py       -- Python vs Rust comparison
```
