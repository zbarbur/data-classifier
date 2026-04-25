# Unified WASM Detector — Design Spec

## Goal

Replace the dual JS+WASM detection architecture with a single Rust implementation compiled to WASM (browser) and PyO3 (Python). Both zone detection and secret detection run in Rust, sharing a `TextModel` that enables zone-aware secret scoring. The Rust implementation is the single source of truth — no JS secret detection code remains. No detection compromises: the Rust detector must be a superset of both the current Python and JS implementations.

## Architecture

**Approach C — Zones-First, Secrets-Second, Shared TextModel.** Zones run first and annotate each line with zone type and confidence. The secret detector reads these annotations and adjusts finding confidence based on zone context. A shared `TextModel` struct is the spine connecting both detectors. The two detectors remain independently testable modules that communicate through data, not coupling.

**Delivery target:** PR to main as Sprint 16 first item. Text path (`scan_text`) and browser only — `classify_columns` stays on Python `secret_scanner.py` (migrates in Sprint 17).

---

## 1. TextModel — Shared Representation

The `TextModel` is populated by the zone detector and consumed by the secret detector.

```rust
pub struct TextModel {
    pub text: String,
    pub lines: Vec<LineInfo>,
    pub structural_markers: Vec<StructuralMarker>,
}

pub struct LineInfo {
    pub offset_start: usize,         // byte offset in original text
    pub offset_end: usize,
    pub content: String,
    pub zone: Option<ZoneAnnotation>,
}

pub struct ZoneAnnotation {
    pub zone_type: ZoneType,
    pub confidence: f64,
    pub language_hint: String,
    pub block_index: usize,
    pub is_literal_context: bool,    // line contains string literals (quotes)
}
```

`is_literal_context` is the key field: it lets the secret detector distinguish "this value is a code expression" (suppress) from "this value is a string literal inside code" (keep/boost).

**Changes to existing zone detector:** Minimal. After `detect_zones()` produces `PromptZones`, a new step writes `ZoneAnnotation` to each `LineInfo`. The 10-step pipeline itself is unchanged.

---

## 2. Secret Detector Module

New `secret_detector/` module alongside existing `zone_detector/`:

```
data_classifier_core/src/
├── lib.rs                    # unified API
├── text_model.rs             # TextModel, LineInfo, ZoneAnnotation
├── zone_detector/            # existing, unchanged
└── secret_detector/          # NEW
    ├── mod.rs                # SecretOrchestrator
    ├── types.rs              # Finding, Match, KVContext, EntityType
    ├── config.rs             # SecretConfig (loaded from JSON)
    ├── regex_pass.rs         # 162 regex patterns
    ├── kv_pass.rs            # KV secret scanner (tiered scoring)
    ├── opaque_pass.rs        # opaque token detection
    ├── pem_pass.rs           # PEM block detection
    ├── parsers/
    │   ├── mod.rs
    │   ├── json.rs           # JSON flattening with offset tracking
    │   ├── env.rs            # ENV format
    │   ├── code_literals.rs  # assignment syntax
    │   ├── yaml.rs           # YAML parsing (Python-only today)
    │   ├── toml.rs           # TOML parsing (Python-only today)
    │   ├── connection_str.rs # connection strings (Python-only today)
    │   └── url_query.rs      # URL query strings (Python-only today)
    ├── validators/
    │   ├── mod.rs            # resolve_validator() dispatch
    │   ├── luhn.rs           # luhn, luhn_strip, sin_luhn, npi_luhn
    │   ├── checksum.rs       # aba, iban, dea, vin, ein_prefix
    │   ├── crypto.rs         # bitcoin (base58check+bech32), ethereum
    │   ├── identity.rs       # ssn_zeros, bulgarian_egn, czech, swiss_ahv, danish_cpr
    │   ├── network.rs        # ipv4_not_reserved, phone_number
    │   ├── credential.rs     # aws_secret_not_hex, openai_legacy, huggingface, swift_bic
    │   └── placeholder.rs    # not_placeholder_credential
    ├── entropy.rs            # shannon, relative, charset, diversity, evenness
    ├── fp_filters.rs         # valueIsObviouslyNotSecret (42+ rules)
    ├── key_scoring.rs        # key name matching, camelToSnake, tiered scoring
    ├── zone_scorer.rs        # zone-aware confidence adjustment
    └── redaction.rs          # type-label, asterisk, placeholder, none
```

**SecretOrchestrator** runs all passes in sequence:

```rust
impl SecretOrchestrator {
    pub fn detect_secrets(&self, model: &TextModel) -> Vec<Finding> {
        let pem = self.pem_pass.detect(&model.text);
        let regex = self.regex_pass.detect(&model.text, &self.config);
        let kv = self.kv_pass.detect(&model.text, &self.config);
        let opaque = self.opaque_pass.detect(&model.text, &pem.spans, &self.config);

        let mut all = Vec::new();
        all.extend(pem.findings);
        all.extend(regex);
        all.extend(kv);
        all.extend(opaque);

        let adjusted = self.zone_scorer.adjust(&model, all);
        dedup(adjusted)
    }
}
```

### Source of Truth for Porting

Port from Python as primary reference (all validators implemented, no stubs). Cross-check every FP filter from JS Sprint 15. The Rust implementation is the union — anything either side does, Rust must do.

### Parity Gaps Resolved

**16 stubbed JS validators → all fully implemented in Rust:**
luhn, luhn_strip, ssn_zeros, ipv4_not_reserved, npi_luhn, dea_checkdigit, vin_checkdigit, ein_prefix, aba_checksum, iban_checksum, sin_luhn, phone_number, bitcoin_address, ethereum_address, openai_legacy_key + 4 EU gov ID validators (bulgarian_egn, czech_rodne_cislo, swiss_ahv, danish_cpr).

**4 KV parsers JS lacks → implemented in Rust:**
YAML, TOML, connection strings, URL query strings.

**All 42+ FP filter rules** from both Python and JS, unified.

---

## 3. Zone-Aware Confidence Scoring

Zone context is a **confidence modifier**, not a blanket filter. The key distinction: is the matched value a **literal** (string, quoted value) vs a **reference** (variable name, code expression).

All parameters are in `unified_patterns.json` — no hardcoded thresholds.

### Config Structure

```json
{
  "zone_scoring": {
    "enabled": true,
    "suppression_threshold": 0.30,
    "max_confidence": 0.99,

    "rules": [
      {
        "name": "code_literal_boost",
        "zone_type": "code",
        "value_context": "literal",
        "delta": 0.05,
        "description": "String literal in code zone — real assignment"
      },
      {
        "name": "code_expression_suppress",
        "zone_type": "code",
        "value_context": "expression",
        "delta": -0.20,
        "description": "Code expression (dot chain, function call) in code zone"
      },
      {
        "name": "config_boost",
        "zone_type": "config",
        "value_context": "any",
        "delta": 0.05,
        "description": "Credential in config zone — high likelihood"
      },
      {
        "name": "error_output_reduce",
        "zone_type": "error_output",
        "value_context": "any",
        "delta": -0.15,
        "description": "Tokens in stack traces / error logs"
      },
      {
        "name": "cli_literal_keep",
        "zone_type": "cli_shell",
        "value_context": "literal",
        "delta": 0.0,
        "description": "Inline secret in shell command"
      },
      {
        "name": "cli_reference_suppress",
        "zone_type": "cli_shell",
        "value_context": "expression",
        "delta": -0.25,
        "description": "Variable reference ($VAR) in shell — not a value"
      },
      {
        "name": "markup_reduce",
        "zone_type": "markup",
        "value_context": "any",
        "delta": -0.10,
        "description": "HTML/XML attributes rarely contain real secrets"
      },
      {
        "name": "query_reduce",
        "zone_type": "query",
        "value_context": "any",
        "delta": -0.05,
        "description": "SQL/GraphQL — parameterized values, rarely hardcoded"
      },
      {
        "name": "natural_language_reduce",
        "zone_type": "natural_language",
        "value_context": "any",
        "delta": -0.10,
        "description": "Prose inside fenced blocks"
      }
    ],

    "value_context_detection": {
      "literal_patterns": [
        "=[\\s]*[\"']",
        ":[\\s]*[\"']",
        "\\([\"']",
        ">[\"']"
      ],
      "expression_patterns": [
        "^[a-zA-Z_]\\w*(?:\\.[a-zA-Z_]\\w*)+$",
        "^\\$[\\w{]",
        "^[a-zA-Z_]\\w*\\(",
        "^[a-zA-Z_]\\w*\\[",
        "^\\{\\{.*\\}\\}$"
      ]
    },

    "tier_overrides": {
      "definitive_min_confidence": 0.50,
      "strong_min_confidence": 0.35,
      "contextual_min_confidence": 0.30
    }
  }
}
```

### Implementation

```rust
pub struct ZoneScorer {
    rules: Vec<ScoringRule>,
    suppression_threshold: f64,
    max_confidence: f64,
}

impl ZoneScorer {
    pub fn adjust(&self, model: &TextModel, findings: Vec<Finding>) -> Vec<Finding> {
        findings.into_iter().filter_map(|mut f| {
            let line_idx = model.line_at_offset(f.match_span.start);
            let annotation = &model.lines[line_idx].zone;

            match annotation {
                Some(ann) => {
                    let delta = self.compute_delta(&f, ann);
                    f.confidence = (f.confidence + delta).clamp(0.0, self.max_confidence);
                    if f.confidence < self.suppression_threshold { None } else { Some(f) }
                }
                None => Some(f), // prose — no adjustment
            }
        }).collect()
    }
}
```

---

## 4. Unified Patterns File

One JSON file with all config for both detectors:

```
unified_patterns.json
├── version                    # schema version
├── zone_types[]               # existing
├── pre_screen {}              # existing zone config
├── structural {}
├── format {}
├── syntax {}
├── tokenizer {}
├── scope {}
├── negative {}
├── assembly {}
├── language {}
├── lang_tag_map {}
├── secret_scanner {}          # NEW: all thresholds
│   ├── min_value_length
│   ├── max_value_length
│   ├── definitive_multiplier
│   ├── strong_min_entropy_score
│   ├── relative_entropy_strong
│   ├── relative_entropy_contextual
│   ├── diversity_threshold
│   ├── evenness_weight
│   ├── diversity_bonus_weight
│   ├── prose_alpha_threshold
│   ├── opaque_token {}
│   ├── anti_indicators []
│   ├── placeholder_patterns []
│   ├── non_secret_suffixes []
│   └── non_secret_allowlist []
├── secret_patterns []         # NEW: 162 regex patterns
├── secret_key_names []        # NEW: 290+ key name entries
├── validators {}              # NEW: validator-specific config
├── fp_filters {}              # NEW: FP filter patterns/thresholds
├── zone_scoring {}            # NEW: cross-detector rules
└── redaction {}               # NEW: strategy config
```

Every threshold, delta, pattern, and gate is in this file. Hypothesis testing = edit JSON, re-run benchmarks.

---

## 5. Public API

### WASM

```rust
#[wasm_bindgen]
pub fn init(patterns_json: &str) -> bool

#[wasm_bindgen]
pub fn detect(text: &str, opts_json: &str) -> String
// opts: { "secrets": true, "zones": true, "redact_strategy": "type-label", "verbose": false }
// returns: { "zones": {...}, "findings": [...], "redacted_text": "...", "scanned_ms": 1.2 }

// Legacy (kept during migration)
#[wasm_bindgen]
pub fn init_detector(patterns_json: &str) -> bool

#[wasm_bindgen]
pub fn detect_zones(text: &str, prompt_id: &str) -> String
```

### PyO3

```rust
#[pyclass]
pub struct UnifiedDetector { ... }

#[pymethods]
impl UnifiedDetector {
    #[new]
    pub fn new(patterns_json: &str) -> Self
    pub fn detect(&self, text: &str, opts: Option<&PyDict>) -> PyResult<DetectionResult>
    pub fn detect_zones(&self, text: &str, prompt_id: &str) -> PyResult<PromptZones> // legacy
}
```

### Browser JS Changes

`scanner-core.js` and all generated data files are **deleted**. The worker calls WASM directly.

```
// Before:
worker.js → scanner-core.js (JS secret detection) + zone-detector.js (WASM zones)

// After:
worker.js → detector.js (WASM secrets + zones)
```

**Deleted:** scanner-core.js, entropy.js, kv-parsers.js, regex-backend.js, validators.js, finding.js, decoder.js, generated/ directory.

**Kept:** scanner.js (public API, unchanged interface), pool.js (worker pool), worker.js (simplified), detector.js (expanded from zone-detector.js).

**Redaction:** Moves to Rust (`redaction.rs`). The WASM `detect()` call returns `redacted_text` directly — no JS-side redaction needed. `redaction.js` is deleted.

The public API (`createScanner`, `scanner.scan()`) is unchanged for consumers.

---

## 6. Bundle & Performance Budget

### Size

| Component | Current | After | Notes |
|-----------|---------|-------|-------|
| scanner.esm.js | 1.5 KB | ~1.5 KB | unchanged |
| worker.esm.js | 142 KB | ~5 KB | JS detection removed |
| WASM binary | 1.4 MB | ~2.0-2.5 MB | adds secret detection |
| patterns JSON | 14 KB | ~80-100 KB | zone + secret + scoring config |
| **Total (gzipped)** | **525 KB** | **~800 KB** | +300 KB for full validator coverage |

Chrome Web Store limit: 2 GB. Our total: ~3 MB unpacked.

### Performance

| Metric | Current | Target |
|--------|---------|--------|
| WASM init (first call) | 15-25 ms | <= 40 ms |
| Secrets-only scan | ~1 ms (JS) | <= 2 ms (WASM) |
| Zones-only scan | ~0.5 ms | <= 0.5 ms |
| Combined scan | ~1.5 ms | <= 2.5 ms |

---

## 7. Regression & Quality Gates

### Zone Detection (must not regress)

| Metric | Current | Gate |
|--------|---------|------|
| Precision | 98.3% | >= 98.0% |
| Recall | 95.7% | >= 95.0% |
| F1 | 0.970 | >= 0.960 |
| Boundary recall | 99.5% | >= 99.0% |
| Fragmentation | 1.06x | <= 1.10x |
| WASM/native parity | 647/647 | 100% |

### Secret Detection (must not regress)

| Benchmark | Current (Python) | Gate |
|-----------|-----------------|------|
| Differential parity (seed fixtures) | 100% match | 100% (Rust vs Python) |
| WildChat prompt-level F1 | 96.1% | >= 96.0% |
| WildChat finding-level precision | 73.2% | >= 73.0% |
| SecretBench recall | baseline | no regression |
| Family benchmark cross_family_rate | 0.0044 | no regression |

### New Gates

| Gate | Description |
|------|-------------|
| Rust/WASM parity | Identical findings + zones across native and WASM on all test inputs |
| Rust/PyO3 parity | Identical findings + zones across native and Python module |
| JS elimination | No JS detection code remains; all vitest tests ported to Rust |
| Validator parity | Every validator matches Python accept/reject on golden fixtures |
| Zone-scorer A/B | WildChat: FP count decreases, TP count unchanged with zone scoring on vs off |

### Regression Infrastructure

1. **Rust unit tests** — per module, per validator, per parser, per FP filter
2. **Rust integration tests** — full pipeline golden fixtures
3. **WASM e2e tests** — Playwright, same tester page and stories
4. **Cross-runtime parity** — CI script: Rust native vs WASM (Node) vs PyO3, diff outputs, zero divergence
5. **Zone-scorer evaluation** — before/after WildChat comparison

---

## 8. Migration Phases

### Phase 1: Rust Secret Detector (no zone interaction)

Port all secret detection to Rust `secret_detector/` module. All 24 validators, 7 KV parsers, entropy, FP filters, 4 passes. Zone scoring disabled.

**Gate:** Rust native produces identical findings to Python on all benchmarks.

### Phase 2: TextModel + Zone Annotation

Introduce `TextModel`. Refactor zone detector to write annotations. Wire `SecretOrchestrator` to read from `TextModel`. No zone scoring — detectors run independently through shared model.

**Gate:** Zone metrics unchanged. Secret detection unchanged. Both outputs from one `detect()` call.

### Phase 3: Zone-Aware Scoring

Implement `ZoneScorer` with configurable rules. A/B evaluation on WildChat. Tune deltas in config.

**Gate:** FP count decreases. TP count holds. All parameters in config.

### Phase 4: WASM + PyO3 Bindings

Build unified WASM binary and PyO3 module. Cross-runtime parity test.

**Gate:** 100% parity across Rust native, WASM, PyO3.

### Phase 5: Browser Migration

Replace JS detection with WASM calls. Delete scanner-core.js and generated files. Port vitest tests to Rust. Playwright e2e tests exercise WASM.

**Gate:** All tests pass. Tester works. Bundle size measured.

### Phase 6: Python Text-Path Migration

Replace Python `scan_text.py` with PyO3 calls to unified detector. `classify_columns` stays on Python `secret_scanner.py` (Sprint 17 migration).

**Gate:** All pytest tests pass. Family benchmark unchanged.

---

## Scope Boundary

**In scope (Sprint 16):**
- Full secret detection in Rust (superset of Python + JS)
- Zone-aware confidence scoring
- WASM + PyO3 bindings
- Browser migration (delete JS detection)
- Python `scan_text` migration
- All regression gates

**Out of scope (Sprint 17+):**
- `classify_columns` migration to Rust
- Population-level analysis (Path 3) in Rust
- Intent classification
- Risk scoring
