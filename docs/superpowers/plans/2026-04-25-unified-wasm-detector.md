# Unified WASM Detector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dual JS+WASM detection architecture with a single Rust `data_classifier_core` crate that handles both zone and secret detection, compiled to WASM (browser) and PyO3 (Python).

**Architecture:** Approach C — shared `TextModel` spine. Zones run first and annotate lines; the secret detector reads zone annotations for confidence adjustment. All thresholds in `unified_patterns.json`. Port from Python as primary reference, cross-check JS Sprint 15 FP filters. Rust is the superset of both.

**Tech Stack:** Rust 2021 edition, `fancy-regex` 0.14, `serde`/`serde_json`, `wasm-bindgen` 0.2, `pyo3` 0.22. Browser: esbuild, Playwright, vitest. Python: maturin.

**Spec:** `docs/superpowers/specs/2026-04-25-unified-wasm-detector-design.md`

**Source of truth for porting:**
- Python validators: `data_classifier/engines/validators.py`
- Python secret scanner: `data_classifier/engines/secret_scanner.py`
- Python scan_text: `data_classifier/scan_text.py`
- Python parsers: `data_classifier/engines/parsers.py`
- Python entropy: `data_classifier/engines/heuristic_engine.py`
- JS FP filters (Sprint 15): `data_classifier/clients/browser/src/scanner-core.js:237-328`
- JS entropy: `data_classifier/clients/browser/src/entropy.js`

---

## File Structure

### New Files (Rust crate: `data_classifier_core/src/`)

```
text_model.rs                          — TextModel, LineInfo, ZoneAnnotation structs
secret_detector/
├── mod.rs                             — SecretOrchestrator: runs all passes, dedup, zone scoring
├── types.rs                           — Finding, Match, KVContext, EntityType, RedactStrategy
├── config.rs                          — SecretConfig loaded from JSON
├── entropy.rs                         — shannon, relative, charset, diversity, evenness
├── fp_filters.rs                      — value_is_obviously_not_secret (42+ rules)
├── key_scoring.rs                     — camel_to_snake, score_key_name, tiered_score
├── regex_pass.rs                      — regex pattern matching with validators
├── kv_pass.rs                         — KV secret scanner (parse + score + filter)
├── opaque_pass.rs                     — opaque token detection
├── pem_pass.rs                        — PEM block detection
├── redaction.rs                       — type-label, asterisk, placeholder, none
├── zone_scorer.rs                     — zone-aware confidence adjustment
├── parsers/
│   ├── mod.rs                         — parse_key_values_with_spans dispatch
│   ├── json.rs                        — JSON flattening with offset tracking
│   ├── env.rs                         — ENV format (export KEY=value)
│   ├── code_literals.rs               — assignment syntax (key = "value")
│   ├── yaml.rs                        — YAML key-value extraction
│   ├── toml.rs                        — TOML key-value extraction
│   ├── connection_str.rs              — JDBC/ODBC/URI connection strings
│   └── url_query.rs                   — URL query string parsing
└── validators/
    ├── mod.rs                         — resolve_validator() dispatch
    ├── luhn.rs                        — luhn, luhn_strip, sin_luhn, npi_luhn
    ├── checksum.rs                    — aba, iban, dea, vin, ein_prefix
    ├── crypto.rs                      — bitcoin (base58check + bech32), ethereum
    ├── identity.rs                    — ssn_zeros, bulgarian_egn, czech_rodne_cislo, swiss_ahv, danish_cpr
    ├── network.rs                     — ipv4_not_reserved, phone_number
    ├── credential.rs                  — aws_secret_not_hex, openai_legacy, huggingface, swift_bic, random_password
    └── placeholder.rs                 — not_placeholder_credential, is_placeholder_pattern
```

### Modified Files (Rust crate)

```
lib.rs                                 — Add `pub mod secret_detector; pub mod text_model;`, add unified WASM/PyO3 API
Cargo.toml                             — Add `sha2` (bitcoin), `regex` (if needed beyond fancy-regex)
```

### New Files (Browser)

```
src/detector.js                        — Unified WASM loader (replaces zone-detector.js)
```

### Deleted Files (Browser — Phase 5)

```
src/scanner-core.js                    — Replaced by WASM
src/entropy.js                         — Moved to Rust
src/kv-parsers.js                      — Moved to Rust
src/regex-backend.js                   — Moved to Rust
src/validators.js                      — Moved to Rust
src/finding.js                         — Moved to Rust
src/decoder.js                         — No longer needed
src/redaction.js                       — Moved to Rust
src/zone-detector.js                   — Replaced by detector.js
src/generated/                         — Entire directory deleted
```

### Modified Files (Browser — Phase 5)

```
src/worker.js                          — Simplified to call WASM detect()
package.json                           — Remove generate script, update exports
esbuild.config.mjs                     — Single WASM + patterns asset copy
scanner.d.ts                           — Update types (unchanged public API)
scripts/package.js                     — Remove generated/ includes
tester/tester.js                       — Update to use new WASM output format
```

### New Files (Patterns)

```
data_classifier_core/patterns/unified_patterns.json  — Merged zone + secret + scoring config
scripts/build_unified_patterns.py                     — Generates unified_patterns.json from Python sources
```

---

## Phase 1: Rust Secret Detector

### Task 1: Module scaffold + types

**Files:**
- Create: `data_classifier_core/src/secret_detector/mod.rs`
- Create: `data_classifier_core/src/secret_detector/types.rs`
- Create: `data_classifier_core/src/secret_detector/config.rs`
- Modify: `data_classifier_core/src/lib.rs`

- [ ] **Step 1: Create types.rs with Finding, Match, and EntityType**

```rust
// data_classifier_core/src/secret_detector/types.rs

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum EntityType {
    ApiKey,
    OpaqueSecret,
    PrivateKey,
    PasswordHash,
    Ssn,
    CreditCard,
    Email,
    Phone,
    IpAddress,
    MacAddress,
    Iban,
    SwiftBic,
    AbaRouting,
    BitcoinAddress,
    EthereumAddress,
    Url,
    CanadianSin,
    NationalId,
    Health,
    DeaNumber,
    Ein,
    Mbi,
    Npi,
    Vin,
    Date,
}

impl EntityType {
    pub fn from_str(s: &str) -> Self {
        match s {
            "API_KEY" => Self::ApiKey,
            "OPAQUE_SECRET" => Self::OpaqueSecret,
            "PRIVATE_KEY" => Self::PrivateKey,
            "PASSWORD_HASH" => Self::PasswordHash,
            "SSN" => Self::Ssn,
            "CREDIT_CARD" => Self::CreditCard,
            "EMAIL" => Self::Email,
            "PHONE" => Self::Phone,
            "IP_ADDRESS" => Self::IpAddress,
            "MAC_ADDRESS" => Self::MacAddress,
            "IBAN" => Self::Iban,
            "SWIFT_BIC" => Self::SwiftBic,
            "ABA_ROUTING" => Self::AbaRouting,
            "BITCOIN_ADDRESS" => Self::BitcoinAddress,
            "ETHEREUM_ADDRESS" => Self::EthereumAddress,
            "URL" => Self::Url,
            "CANADIAN_SIN" => Self::CanadianSin,
            "NATIONAL_ID" => Self::NationalId,
            "HEALTH" => Self::Health,
            "DEA_NUMBER" => Self::DeaNumber,
            "EIN" => Self::Ein,
            "MBI" => Self::Mbi,
            "NPI" => Self::Npi,
            "VIN" => Self::Vin,
            "DATE" => Self::Date,
            _ => Self::OpaqueSecret,
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Self::ApiKey => "API_KEY",
            Self::OpaqueSecret => "OPAQUE_SECRET",
            Self::PrivateKey => "PRIVATE_KEY",
            Self::PasswordHash => "PASSWORD_HASH",
            Self::Ssn => "SSN",
            Self::CreditCard => "CREDIT_CARD",
            Self::Email => "EMAIL",
            Self::Phone => "PHONE",
            Self::IpAddress => "IP_ADDRESS",
            Self::MacAddress => "MAC_ADDRESS",
            Self::Iban => "IBAN",
            Self::SwiftBic => "SWIFT_BIC",
            Self::AbaRouting => "ABA_ROUTING",
            Self::BitcoinAddress => "BITCOIN_ADDRESS",
            Self::EthereumAddress => "ETHEREUM_ADDRESS",
            Self::Url => "URL",
            Self::CanadianSin => "CANADIAN_SIN",
            Self::NationalId => "NATIONAL_ID",
            Self::Health => "HEALTH",
            Self::DeaNumber => "DEA_NUMBER",
            Self::Ein => "EIN",
            Self::Mbi => "MBI",
            Self::Npi => "NPI",
            Self::Vin => "VIN",
            Self::Date => "DATE",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Match {
    pub value_masked: String,
    pub start: usize,
    pub end: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub value_raw: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KVContext {
    pub key: String,
    pub tier: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Finding {
    pub entity_type: String,
    pub category: String,
    pub sensitivity: String,
    pub confidence: f64,
    pub engine: String,
    pub evidence: String,
    #[serde(rename = "match")]
    pub match_span: Match,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub detection_type: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub display_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub kv: Option<KVContext>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DetectionResult {
    pub findings: Vec<Finding>,
    pub redacted_text: String,
    pub scanned_ms: f64,
    pub zones: Option<serde_json::Value>,
}

/// Mask a secret value: first char + asterisks + last char.
/// For short values (<=4), return all asterisks.
pub fn mask_value(value: &str, _entity_type: &str) -> String {
    let chars: Vec<char> = value.chars().collect();
    if chars.len() <= 4 {
        return "*".repeat(chars.len());
    }
    let first = chars[0];
    let last = chars[chars.len() - 1];
    format!("{}{}{}", first, "*".repeat(chars.len() - 2), last)
}
```

- [ ] **Step 2: Create config.rs with SecretConfig**

```rust
// data_classifier_core/src/secret_detector/config.rs

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OpaqueTokenConfig {
    pub min_length: usize,
    pub max_length: usize,
    pub entropy_threshold: f64,
    pub diversity_threshold: usize,
    pub base_confidence: f64,
    pub max_confidence: f64,
    pub high_entropy_bonus: f64,
    pub high_entropy_gate: f64,
    pub length_bonus: f64,
    pub length_gate: usize,
    pub diversity_bonus_weight: f64,
}

impl Default for OpaqueTokenConfig {
    fn default() -> Self {
        Self {
            min_length: 16,
            max_length: 512,
            entropy_threshold: 0.7,
            diversity_threshold: 3,
            base_confidence: 0.65,
            max_confidence: 0.85,
            high_entropy_bonus: 0.10,
            high_entropy_gate: 0.85,
            length_bonus: 0.05,
            length_gate: 24,
            diversity_bonus_weight: 0.05,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SecretConfig {
    pub min_value_length: usize,
    pub max_value_length: usize,
    pub definitive_multiplier: f64,
    pub strong_min_entropy_score: f64,
    pub relative_entropy_strong: f64,
    pub relative_entropy_contextual: f64,
    pub diversity_threshold: usize,
    pub evenness_weight: f64,
    pub diversity_bonus_weight: f64,
    pub prose_alpha_threshold: f64,
    pub opaque_token: OpaqueTokenConfig,
    #[serde(default)]
    pub anti_indicators: Vec<String>,
    #[serde(default)]
    pub non_secret_suffixes: Vec<String>,
    #[serde(default)]
    pub non_secret_allowlist: Vec<String>,
}

impl Default for SecretConfig {
    fn default() -> Self {
        Self {
            min_value_length: 8,
            max_value_length: 500,
            definitive_multiplier: 0.95,
            strong_min_entropy_score: 0.6,
            relative_entropy_strong: 0.5,
            relative_entropy_contextual: 0.7,
            diversity_threshold: 3,
            evenness_weight: 0.15,
            diversity_bonus_weight: 0.05,
            prose_alpha_threshold: 0.6,
            opaque_token: OpaqueTokenConfig::default(),
            anti_indicators: vec![
                "example".into(), "test".into(),
                "placeholder".into(), "changeme".into(),
            ],
            non_secret_suffixes: vec![
                "_address".into(), "_field".into(), "_id".into(), "_name".into(),
                "_input".into(), "_label".into(), "_placeholder".into(),
                "_url".into(), "_endpoint".into(), "_file".into(), "_path".into(),
                "_dir".into(), "_prefix".into(), "_suffix".into(), "_format".into(),
                "_type".into(), "_mode".into(), "_status".into(), "_count".into(),
                "_size".into(), "_length".into(),
            ],
            non_secret_allowlist: vec![
                "session_id".into(), "auth_id".into(), "client_id".into(),
            ],
        }
    }
}

impl SecretConfig {
    pub fn from_json(patterns: &serde_json::Value) -> Self {
        if let Some(sc) = patterns.get("secret_scanner") {
            serde_json::from_value(sc.clone()).unwrap_or_default()
        } else {
            Self::default()
        }
    }
}
```

- [ ] **Step 3: Create mod.rs scaffold with SecretOrchestrator stub**

```rust
// data_classifier_core/src/secret_detector/mod.rs

pub mod types;
pub mod config;
pub mod entropy;
pub mod fp_filters;
pub mod key_scoring;
pub mod regex_pass;
pub mod kv_pass;
pub mod opaque_pass;
pub mod pem_pass;
pub mod redaction;
pub mod zone_scorer;
pub mod parsers;
pub mod validators;

use config::SecretConfig;
use types::{Finding, DetectionResult};

pub struct SecretOrchestrator {
    config: SecretConfig,
    // passes will be added as they're implemented
}

impl SecretOrchestrator {
    pub fn from_patterns(patterns: &serde_json::Value) -> Self {
        Self {
            config: SecretConfig::from_json(patterns),
        }
    }

    /// Placeholder — will be filled in Task 18 after all passes exist.
    pub fn detect_secrets(&self, _text: &str) -> Vec<Finding> {
        Vec::new()
    }
}
```

- [ ] **Step 4: Add secret_detector module to lib.rs**

Add after `pub mod zone_detector;`:

```rust
pub mod secret_detector;
```

- [ ] **Step 5: Verify crate compiles**

Run: `cd data_classifier_core && cargo test --no-default-features 2>&1 | tail -5`
Expected: All existing 79 zone tests pass, no compilation errors from new module stubs.

- [ ] **Step 6: Commit**

```bash
git add data_classifier_core/src/secret_detector/ data_classifier_core/src/lib.rs
git commit -m "feat(rust): scaffold secret_detector module — types, config, orchestrator stub"
```

---

### Task 2: Entropy module

**Files:**
- Create: `data_classifier_core/src/secret_detector/entropy.rs`

Port from Python `data_classifier/engines/heuristic_engine.py:109-282` and JS `data_classifier/clients/browser/src/entropy.js`.

- [ ] **Step 1: Write entropy tests**

```rust
// At bottom of entropy.rs

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_shannon_entropy_uniform() {
        // 4 distinct chars, each appears once → log2(4) = 2.0
        let e = shannon_entropy("abcd");
        assert!((e - 2.0).abs() < 0.001);
    }

    #[test]
    fn test_shannon_entropy_single_char() {
        assert_eq!(shannon_entropy("aaaa"), 0.0);
    }

    #[test]
    fn test_detect_charset_hex() {
        assert_eq!(detect_charset("0123456789abcdef"), "hex");
    }

    #[test]
    fn test_detect_charset_base64() {
        assert_eq!(detect_charset("ABCDabcd0123+/="), "base64");
    }

    #[test]
    fn test_detect_charset_full() {
        assert_eq!(detect_charset("hello world!@#"), "full");
    }

    #[test]
    fn test_relative_entropy_range() {
        let r = relative_entropy("aB3!cD4@eF5#");
        assert!(r > 0.0 && r <= 1.0);
    }

    #[test]
    fn test_char_class_diversity() {
        assert_eq!(char_class_diversity("abc"), 1);        // lowercase only
        assert_eq!(char_class_diversity("aBc"), 2);        // lower + upper
        assert_eq!(char_class_diversity("aB1"), 3);        // lower + upper + digit
        assert_eq!(char_class_diversity("aB1!"), 4);       // all four
    }

    #[test]
    fn test_char_class_evenness_single_class() {
        // Single class → evenness = 0.0 (degenerate)
        assert_eq!(char_class_evenness("aaaa"), 0.0);
    }

    #[test]
    fn test_char_class_evenness_perfectly_even() {
        // Two classes, equal distribution
        let e = char_class_evenness("aaBB");
        assert!((e - 1.0).abs() < 0.001);
    }

    #[test]
    fn test_score_relative_entropy_below_gate() {
        assert_eq!(score_relative_entropy(0.3), 0.0);
    }

    #[test]
    fn test_score_relative_entropy_above_gate() {
        assert!((score_relative_entropy(0.7) - 0.7).abs() < 0.001);
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd data_classifier_core && cargo test --no-default-features secret_detector::entropy 2>&1 | tail -10`
Expected: FAIL — functions not yet defined.

- [ ] **Step 3: Implement entropy functions**

```rust
// data_classifier_core/src/secret_detector/entropy.rs

use std::collections::HashMap;

/// Shannon entropy: H = -Σ(p_i * log2(p_i))
/// Port of Python heuristic_engine.py:109-127
pub fn shannon_entropy(value: &str) -> f64 {
    if value.is_empty() {
        return 0.0;
    }
    let mut freq: HashMap<char, usize> = HashMap::new();
    let len = value.len() as f64;
    for c in value.chars() {
        *freq.entry(c).or_insert(0) += 1;
    }
    let mut entropy = 0.0;
    for &count in freq.values() {
        let p = count as f64 / len;
        if p > 0.0 {
            entropy -= p * p.log2();
        }
    }
    entropy
}

/// Detect character set: hex, base64, alphanumeric, or full.
/// Port of Python secret_scanner.py:54-69
pub fn detect_charset(value: &str) -> &'static str {
    if value.chars().all(|c| c.is_ascii_hexdigit()) {
        return "hex";
    }
    if value.chars().all(|c| c.is_ascii_alphanumeric() || c == '+' || c == '/' || c == '=') {
        return "base64";
    }
    if value.chars().all(|c| c.is_ascii_alphanumeric()) {
        return "alphanumeric";
    }
    "full"
}

const CHARSET_MAX_ENTROPY: &[(&str, f64)] = &[
    ("hex", 4.0),
    ("base64", 6.0),
    ("alphanumeric", 5.954196310386876), // log2(62)
    ("full", 6.569855608330948),          // log2(95)
];

fn max_entropy_for_charset(charset: &str) -> f64 {
    for &(name, max) in CHARSET_MAX_ENTROPY {
        if name == charset {
            return max;
        }
    }
    6.569855608330948 // full
}

/// Relative entropy: entropy / max_entropy_for_charset, clamped to [0, 1].
/// Port of Python secret_scanner.py:72-86
pub fn relative_entropy(value: &str) -> f64 {
    if value.is_empty() {
        return 0.0;
    }
    let entropy = shannon_entropy(value);
    let charset = detect_charset(value);
    let max = max_entropy_for_charset(charset);
    if max == 0.0 {
        return 0.0;
    }
    (entropy / max).min(1.0)
}

/// Count of character classes present: lowercase, uppercase, digits, symbols.
/// Returns 0-4.
/// Port of Python heuristic_engine.py:220-241
pub fn char_class_diversity(value: &str) -> usize {
    let mut has_lower = false;
    let mut has_upper = false;
    let mut has_digit = false;
    let mut has_symbol = false;
    for c in value.chars() {
        if c.is_ascii_lowercase() { has_lower = true; }
        else if c.is_ascii_uppercase() { has_upper = true; }
        else if c.is_ascii_digit() { has_digit = true; }
        else if !c.is_whitespace() { has_symbol = true; }
    }
    has_lower as usize + has_upper as usize + has_digit as usize + has_symbol as usize
}

/// Normalized Shannon entropy over the 4-class histogram.
/// Returns 0.0 (one class dominates) to 1.0 (perfectly even).
/// Port of Python heuristic_engine.py:244-282
pub fn char_class_evenness(value: &str) -> f64 {
    let mut counts = [0u32; 4]; // lower, upper, digit, symbol
    for c in value.chars() {
        if c.is_ascii_lowercase() { counts[0] += 1; }
        else if c.is_ascii_uppercase() { counts[1] += 1; }
        else if c.is_ascii_digit() { counts[2] += 1; }
        else if !c.is_whitespace() { counts[3] += 1; }
    }
    let present: Vec<f64> = counts.iter().filter(|&&c| c > 0).map(|&c| c as f64).collect();
    let n = present.len();
    if n <= 1 {
        return 0.0;
    }
    let total: f64 = present.iter().sum();
    let mut h = 0.0;
    for &count in &present {
        let p = count / total;
        if p > 0.0 {
            h -= p * p.log2();
        }
    }
    let h_max = (n as f64).log2();
    if h_max == 0.0 { 0.0 } else { h / h_max }
}

/// Gate function: below 0.5 → 0, otherwise passthrough.
/// Port of Python secret_scanner.py:89-102
pub fn score_relative_entropy(rel: f64) -> f64 {
    if rel < 0.5 { 0.0 } else { rel.min(1.0) }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd data_classifier_core && cargo test --no-default-features secret_detector::entropy 2>&1 | tail -15`
Expected: All 9 entropy tests PASS.

- [ ] **Step 5: Commit**

```bash
git add data_classifier_core/src/secret_detector/entropy.rs
git commit -m "feat(rust): entropy module — shannon, relative, charset, diversity, evenness"
```

---

### Task 3: Validators — Luhn group

**Files:**
- Create: `data_classifier_core/src/secret_detector/validators/mod.rs`
- Create: `data_classifier_core/src/secret_detector/validators/luhn.rs`

Port from Python `data_classifier/engines/validators.py:26-44` (luhn_check, luhn_strip_check) and lines 123-128 (npi_luhn_check), 241-253 (sin_luhn_check).

- [ ] **Step 1: Write luhn tests**

```rust
// At bottom of luhn.rs
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_luhn_valid_visa() {
        assert!(luhn_check("4111111111111111"));
    }

    #[test]
    fn test_luhn_invalid() {
        assert!(!luhn_check("4111111111111112"));
    }

    #[test]
    fn test_luhn_strip_dashes() {
        assert!(luhn_strip_check("4111-1111-1111-1111"));
    }

    #[test]
    fn test_luhn_strip_spaces() {
        assert!(luhn_strip_check("4111 1111 1111 1111"));
    }

    #[test]
    fn test_npi_valid() {
        // NPI 1234567893 → prepend 80840 → Luhn on 808401234567893
        assert!(npi_luhn_check("1234567893"));
    }

    #[test]
    fn test_npi_wrong_length() {
        assert!(!npi_luhn_check("12345"));
    }

    #[test]
    fn test_sin_valid() {
        // Canadian SIN 046 454 286
        assert!(sin_luhn_check("046454286"));
    }

    #[test]
    fn test_sin_wrong_length() {
        assert!(!sin_luhn_check("1234"));
    }
}
```

- [ ] **Step 2: Implement luhn validators**

```rust
// data_classifier_core/src/secret_detector/validators/luhn.rs

/// Luhn algorithm — validate credit card numbers, SINs, NPIs.
/// Port of Python validators.py:26-38
pub fn luhn_check(value: &str) -> bool {
    let digits: Vec<u32> = value.chars().filter_map(|c| c.to_digit(10)).collect();
    if digits.is_empty() {
        return false;
    }
    let mut sum = 0u32;
    for (i, &d) in digits.iter().rev().enumerate() {
        if i % 2 == 1 {
            let doubled = d * 2;
            sum += if doubled > 9 { doubled - 9 } else { doubled };
        } else {
            sum += d;
        }
    }
    sum % 10 == 0
}

/// Strip dashes and spaces, then Luhn check.
/// Port of Python validators.py:41-44
pub fn luhn_strip_check(value: &str) -> bool {
    let cleaned: String = value.chars().filter(|c| *c != '-' && *c != ' ').collect();
    luhn_check(&cleaned)
}

/// NPI Luhn: extract 10 digits, prepend "80840", Luhn check.
/// Port of Python validators.py:123-128
pub fn npi_luhn_check(value: &str) -> bool {
    let digits: String = value.chars().filter(|c| c.is_ascii_digit()).collect();
    if digits.len() != 10 {
        return false;
    }
    let prefixed = format!("80840{}", digits);
    luhn_check(&prefixed)
}

/// Canadian SIN Luhn: extract exactly 9 digits, standard Luhn.
/// Port of Python validators.py:241-253
pub fn sin_luhn_check(value: &str) -> bool {
    let digits: String = value.chars().filter(|c| c.is_ascii_digit()).collect();
    if digits.len() != 9 {
        return false;
    }
    luhn_check(&digits)
}
```

- [ ] **Step 3: Create validators/mod.rs with dispatch**

```rust
// data_classifier_core/src/secret_detector/validators/mod.rs

pub mod luhn;
pub mod checksum;
pub mod crypto;
pub mod identity;
pub mod network;
pub mod credential;
pub mod placeholder;

use std::collections::HashMap;

pub type ValidatorFn = fn(&str) -> bool;

/// Build a map of validator name → function.
/// All 24 validators registered — no stubs.
pub fn build_validator_registry() -> HashMap<&'static str, ValidatorFn> {
    let mut m: HashMap<&'static str, ValidatorFn> = HashMap::new();
    // Luhn group
    m.insert("luhn", luhn::luhn_check);
    m.insert("luhn_strip", luhn::luhn_strip_check);
    m.insert("npi_luhn", luhn::npi_luhn_check);
    m.insert("sin_luhn", luhn::sin_luhn_check);
    // Will be filled in subsequent tasks
    m
}

/// Resolve a validator by name. Returns None if name is empty/null.
pub fn resolve_validator(name: &str, registry: &HashMap<&str, ValidatorFn>) -> Option<ValidatorFn> {
    if name.is_empty() {
        return None;
    }
    registry.get(name).copied()
}
```

- [ ] **Step 4: Run tests**

Run: `cd data_classifier_core && cargo test --no-default-features secret_detector::validators::luhn 2>&1 | tail -15`
Expected: All 8 luhn tests PASS.

- [ ] **Step 5: Commit**

```bash
git add data_classifier_core/src/secret_detector/validators/
git commit -m "feat(rust): luhn validators — luhn, luhn_strip, npi_luhn, sin_luhn"
```

---

### Task 4: Validators — Checksum group (aba, iban, dea, vin, ein)

**Files:**
- Create: `data_classifier_core/src/secret_detector/validators/checksum.rs`
- Modify: `data_classifier_core/src/secret_detector/validators/mod.rs`

Port from Python `validators.py`: aba (214-220), iban (223-238), dea (131-143), vin (146-187), ein (190-211).

- [ ] **Step 1: Write checksum tests**

Tests should cover: ABA valid/invalid, IBAN valid/invalid (DE, GB), DEA valid/invalid, VIN valid (with X check digit)/invalid, EIN valid/invalid prefix.

Use known-good values:
- ABA: `011000015` (valid — Federal Reserve Bank of Boston)
- IBAN: `GB29NWBK60161331926819` (valid IBAN example)
- DEA: `AB1234563` (compute valid check digit)
- VIN: `11111111111111111` (check digit is 1)
- EIN: `12-3456789` (prefix 12 is valid)

- [ ] **Step 2: Implement all 5 checksum validators**

Port each algorithm exactly from the Python source lines listed above. Key algorithms:
- **ABA:** Weights [3,7,1] repeated 3x, sum mod 10 == 0
- **IBAN:** Rearrange, convert letters A=10..Z=35, mod 97 == 1
- **DEA:** Extract digits[2:], (d0+d2+d4) + 2*(d1+d3+d5), mod 10 == d6
- **VIN:** 17 chars, transliteration map, weights [8,7,6,5,4,3,2,10,0,9,8,7,6,5,4,3,2], check position 8
- **EIN:** First 2 digits in valid IRS campus ranges

- [ ] **Step 3: Register in validators/mod.rs**

Add to `build_validator_registry()`:
```rust
m.insert("aba_checksum", checksum::aba_checksum_check);
m.insert("iban_checksum", checksum::iban_checksum_check);
m.insert("dea_checkdigit", checksum::dea_checkdigit_check);
m.insert("vin_checkdigit", checksum::vin_checkdigit_check);
m.insert("ein_prefix", checksum::ein_prefix_check);
```

- [ ] **Step 4: Run tests and commit**

Run: `cd data_classifier_core && cargo test --no-default-features secret_detector::validators::checksum`
Expected: All tests PASS.

```bash
git add data_classifier_core/src/secret_detector/validators/
git commit -m "feat(rust): checksum validators — aba, iban, dea, vin, ein"
```

---

### Task 5: Validators — Crypto group (bitcoin, ethereum)

**Files:**
- Create: `data_classifier_core/src/secret_detector/validators/crypto.rs`
- Modify: `data_classifier_core/Cargo.toml` — add `sha2 = "0.10"` dependency
- Modify: `data_classifier_core/src/secret_detector/validators/mod.rs`

Port from Python `validators.py`: bitcoin (385-410, base58 306-335, bech32 361-382), ethereum (433-453).

- [ ] **Step 1: Add sha2 dependency**

In `Cargo.toml` under `[dependencies]`:
```toml
sha2 = "0.10"
```

- [ ] **Step 2: Write crypto tests**

Test known Bitcoin addresses:
- P2PKH: `1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa` (genesis block)
- Bech32: `bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4`
- Invalid: `1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb` (bad checksum)

Test Ethereum:
- Valid: `0x742d35Cc6634C0532925a3b844Bc9e7595f2bD28`
- Invalid (all zeros): `0x0000000000000000000000000000000000000000`
- Invalid (wrong length): `0x742d35Cc`

- [ ] **Step 3: Implement base58check + bech32 + ethereum**

Port base58 decode from Python validators.py:306-323. Use `sha2` crate for SHA256 double-hash verification in base58check (326-335). Port bech32 polymod verification (361-382) with `_BECH32_CONST = 1` and `_BECH32M_CONST = 0x2BC830A3`. Ethereum: check 0x prefix, 42 chars, reject known fakes.

- [ ] **Step 4: Register and test**

```bash
git add data_classifier_core/src/secret_detector/validators/crypto.rs data_classifier_core/Cargo.toml
git commit -m "feat(rust): crypto validators — bitcoin (base58check+bech32), ethereum"
```

---

### Task 6: Validators — Identity group (ssn, EU IDs)

**Files:**
- Create: `data_classifier_core/src/secret_detector/validators/identity.rs`

Port from Python `validators.py`: ssn_zeros (47-83), bulgarian_egn (897-910), czech_rodne_cislo (913-931), swiss_ahv (934-947), danish_cpr (950-968).

- [ ] **Step 1: Write identity tests**

SSN tests: valid `078-05-1120`, invalid area `000-12-3456`, invalid group `123-00-4567`, ITIN range `900-12-3456`, SSA advertising `078-05-1120`.
EU ID tests: use known valid/invalid examples for each country's format.

- [ ] **Step 2: Implement all 5 identity validators**

Port algorithms exactly from Python source lines. Key: SSN has area/group/serial rules + advertising list. Bulgarian EGN uses modular weights. Czech rodné číslo has gender offset + mod 11. Swiss AHV is EAN-13 with "756" prefix. Danish CPR is DDMMYY-NNNN with weighted checksum.

- [ ] **Step 3: Register and commit**

```bash
git commit -m "feat(rust): identity validators — ssn, bulgarian_egn, czech, swiss_ahv, danish_cpr"
```

---

### Task 7: Validators — Credential group (aws, openai, hf, swift, random_password)

**Files:**
- Create: `data_classifier_core/src/secret_detector/validators/credential.rs`

Port from Python `validators.py`: aws (277-291), openai_legacy (856-869), huggingface (875-894), swift_bic (828-853), random_password (537-562).

- [ ] **Step 1: Write credential tests and implement**

These are simpler character-class validators. Port each exactly:
- **aws_secret_not_hex:** Reject pure hex, require upper AND lower
- **openai_legacy:** Strip "sk-", require ≥2 of {upper, lower, digit}
- **huggingface:** Strip "hf_", reject camelCase+no-digit+long
- **swift_bic:** 8 or 11 chars, positions 4-6 ISO country code, reject all-alpha 8-char
- **random_password:** Length 4-64, require symbol, ≥3 of 4 classes

- [ ] **Step 2: Register and commit**

```bash
git commit -m "feat(rust): credential validators — aws, openai, hf, swift_bic, random_password"
```

---

### Task 8: Validators — Network group (ipv4, phone) + Placeholder

**Files:**
- Create: `data_classifier_core/src/secret_detector/validators/network.rs`
- Create: `data_classifier_core/src/secret_detector/validators/placeholder.rs`

Port from Python `validators.py`: ipv4_not_reserved (86-120), phone_number (256-274), not_placeholder_credential (507-534).

- [ ] **Step 1: Implement ipv4 validator**

Parse IPv4 octets, reject loopback (127.x), unspecified (0.0.0.0/8), multicast (224-239.x), reserved (240-255.x), link-local (169.254.x). KEEP private ranges (10.x, 172.16-31.x, 192.168.x).

- [ ] **Step 2: Implement phone_number validator**

Simplified port without the `phonenumbers` library (no equivalent Rust crate with matching coverage). Implement structural validation: strip extensions, require 7-15 digits, reject all-same-digit, reject sequential. This matches the behavior when the Python library isn't installed (graceful degradation to structural check).

- [ ] **Step 3: Implement placeholder validator**

Port `not_placeholder_credential`: check known placeholder set, 5+ X's, 8+ repeated chars, template patterns (YOUR_*, my_*, insert_*, etc.). Also implement `is_placeholder_pattern` (the 21-pattern regex list from Python secret_scanner.py:191-237).

- [ ] **Step 4: Register all and commit**

Complete the `build_validator_registry()` with all remaining validators. Verify all 24 are registered — no stubs.

```bash
git commit -m "feat(rust): network + placeholder validators — ipv4, phone, placeholder (24/24 complete)"
```

---

### Task 9: FP filters module

**Files:**
- Create: `data_classifier_core/src/secret_detector/fp_filters.rs`

Port the union of Python `secret_scanner.py:369-604` and JS `scanner-core.js:237-328`. All 42+ rules.

- [ ] **Step 1: Write FP filter tests**

Test each major category with known true-positive and false-positive examples:
```rust
#[test] fn test_url_rejected() { assert!(value_is_obviously_not_secret("https://example.com")); }
#[test] fn test_real_key_kept() { assert!(!value_is_obviously_not_secret("sk-proj-abc123def456")); }
#[test] fn test_dot_notation_rejected() { assert!(value_is_obviously_not_secret("form.password.data")); }
#[test] fn test_file_path_rejected() { assert!(value_is_obviously_not_secret("/home/user/.config")); }
#[test] fn test_shell_var_rejected() { assert!(value_is_obviously_not_secret("$SECRET_KEY")); }
#[test] fn test_crypt_hash_kept() { assert!(!value_is_obviously_not_secret("$2b$12$abcdefghij")); }
#[test] fn test_constant_name_rejected() { assert!(value_is_obviously_not_secret("API_KEY_BINANCE")); }
#[test] fn test_camelcase_rejected() { assert!(value_is_obviously_not_secret("FeatureGateManager")); }
#[test] fn test_ethereum_rejected() { assert!(value_is_obviously_not_secret("0x742d35Cc6634C0532925a3b844Bc9e75")); }
#[test] fn test_prose_rejected() { assert!(value_is_obviously_not_secret("the quick brown fox jumps")); }
#[test] fn test_cjk_rejected() { assert!(value_is_obviously_not_secret("密码是123")); }
```

- [ ] **Step 2: Implement value_is_obviously_not_secret**

Port all rules using `fancy_regex::Regex` (lazy-compiled with `std::sync::OnceLock`). The function checks each rule in order and returns `true` if the value is not a secret. Include all 42+ rules from the union of Python and JS.

Key regexes to compile once:
```rust
static URL_RE: OnceLock<Regex> = OnceLock::new();
static DATE_RE: OnceLock<Regex> = OnceLock::new();
static IP_RE: OnceLock<Regex> = OnceLock::new();
// ... etc
```

- [ ] **Step 3: Run tests and commit**

```bash
git commit -m "feat(rust): FP filters — value_is_obviously_not_secret (42+ rules, union of Python + JS)"
```

---

### Task 10: Key scoring module

**Files:**
- Create: `data_classifier_core/src/secret_detector/key_scoring.rs`

Port from Python `secret_scanner.py`: camel_to_snake, score_key_name (640-672), match_key_pattern (607-623), tiered_score (1025-1080), is_compound_non_secret (300-305).

- [ ] **Step 1: Write key scoring tests**

```rust
#[test] fn test_camel_to_snake() { assert_eq!(camel_to_snake("apiKey"), "api_key"); }
#[test] fn test_camel_to_snake_already_snake() { assert_eq!(camel_to_snake("api_key"), "api_key"); }
#[test] fn test_compound_non_secret() { assert!(is_compound_non_secret("token_address", &config)); }
#[test] fn test_compound_allowlist() { assert!(!is_compound_non_secret("session_id", &config)); }
#[test] fn test_tiered_definitive() {
    let score = tiered_score(0.95, "definitive", "real-secret-value!@#", &config);
    assert!(score > 0.85);
}
#[test] fn test_tiered_strong_low_entropy() {
    let score = tiered_score(0.80, "strong", "aaaaaa", &config);
    assert_eq!(score, 0.0); // low entropy → rejected
}
```

- [ ] **Step 2: Implement key scoring**

Key name entries loaded from `patterns["secret_key_names"]` at init. Pre-compile word_boundary and suffix regexes. `score_key_name` iterates entries, returns best match. `tiered_score` applies entropy gates per tier with evenness/diversity bonuses.

- [ ] **Step 3: Run tests and commit**

```bash
git commit -m "feat(rust): key scoring — camel_to_snake, score_key_name, tiered_score"
```

---

### Task 11: KV parsers — JSON, ENV, code literals

**Files:**
- Create: `data_classifier_core/src/secret_detector/parsers/mod.rs`
- Create: `data_classifier_core/src/secret_detector/parsers/json.rs`
- Create: `data_classifier_core/src/secret_detector/parsers/env.rs`
- Create: `data_classifier_core/src/secret_detector/parsers/code_literals.rs`

Port from Python `parsers.py:56-176` and JS `kv-parsers.js`.

- [ ] **Step 1: Define KVPair type and parse_key_values_with_spans**

```rust
// parsers/mod.rs
pub struct KVPair {
    pub key: String,
    pub value: String,
    pub value_start: usize,
    pub value_end: usize,
}

pub fn parse_key_values_with_spans(text: &str) -> Vec<KVPair> {
    let mut results = Vec::new();
    results.extend(env::parse_env_with_spans(text));
    results.extend(code_literals::parse_code_literals_with_spans(text));
    // Dedup by (key, value)
    dedup_pairs(&mut results);
    results
}
```

- [ ] **Step 2: Implement each parser with offset tracking**

**JSON:** `serde_json::from_str`, flatten dict recursively with dot notation, find value offsets by searching for JSON-encoded values in source text.
**ENV:** Regex `^(?:export\s+)?([A-Za-z_]\w*)\s*=\s*(?:"([^"]*)"|'([^']*)'|(\S+))` per line.
**Code literals:** Regex `([A-Za-z_]\w*)\s*(?::=|:|=)\s*(?:"([^"]{1,500})"|'([^']{1,500})')`.

All return `Vec<KVPair>` with exact byte offsets in the original text.

- [ ] **Step 3: Test and commit**

```bash
git commit -m "feat(rust): KV parsers — json, env, code_literals with offset tracking"
```

---

### Task 12: KV parsers — YAML, TOML, connection strings, URL query

**Files:**
- Create: `data_classifier_core/src/secret_detector/parsers/yaml.rs`
- Create: `data_classifier_core/src/secret_detector/parsers/toml.rs`
- Create: `data_classifier_core/src/secret_detector/parsers/connection_str.rs`
- Create: `data_classifier_core/src/secret_detector/parsers/url_query.rs`

Port from Python `parsers.py` (YAML 79-98, flatten) and `structural_parsers.py` (connection strings 414-541).

- [ ] **Step 1: Implement YAML parser**

Simple line-by-line `key: value` extraction (no full YAML parsing — match Python's `yaml.safe_load` behavior for flat/nested dicts). Use regex for `^\s*([a-zA-Z_][\w.-]*)\s*:\s*(.+)$`.

- [ ] **Step 2: Implement TOML parser**

Key-value extraction from `[section]` blocks with `key = "value"` syntax.

- [ ] **Step 3: Implement connection string parser**

Port Python `ConnectionStringParser` patterns:
- JDBC: `jdbc:TYPE://...?password=xxx` or `...;password=xxx`
- ODBC: `Pwd=xxx` or `Password=xxx` in semicolon-delimited
- URI userinfo: `scheme://user:password@host`
- Redis: `redis://:password@host`
- Generic: `password=xxx` in semicolon strings

- [ ] **Step 4: Implement URL query parser**

Split on `?`, then `&`, then `key=value`. URL-decode values.

- [ ] **Step 5: Register in parsers/mod.rs and commit**

```bash
git commit -m "feat(rust): KV parsers — yaml, toml, connection_str, url_query (7/7 complete)"
```

---

### Task 13: Regex pass

**Files:**
- Create: `data_classifier_core/src/secret_detector/regex_pass.rs`

Port from Python `scan_text.py:153-192` (regex_pass) and JS `scanner-core.js:97-131`.

- [ ] **Step 1: Implement regex pass**

Load patterns from `patterns["secret_patterns"]`. For each pattern:
1. Compile regex (skip patterns with `requires_column_hint: true`)
2. Find all matches in text
3. For each match: check stopwords, run validator, check `value_is_obviously_not_secret`, check `is_placeholder_pattern`
4. Build `Finding` with entity_type, confidence, engine="regex"

Pattern struct from JSON:
```rust
struct SecretPattern {
    name: String,
    regex: String,
    entity_type: String,
    category: String,
    sensitivity: String,
    confidence: f64,
    validator: String,
    stopwords: Vec<String>,
    allowlist_patterns: Vec<String>,
    display_name: String,
    requires_column_hint: bool,
}
```

- [ ] **Step 2: Test with known patterns (GitHub PAT, AWS key) and commit**

```bash
git commit -m "feat(rust): regex pass — pattern matching with validators and FP filters"
```

---

### Task 14: KV pass (secret scanner)

**Files:**
- Create: `data_classifier_core/src/secret_detector/kv_pass.rs`

Port from Python `scan_text.py:194-259` and JS `scanner-core.js:133-182`.

- [ ] **Step 1: Implement KV pass**

1. Call `parse_key_values_with_spans(text)` to get KV pairs
2. For each pair: length checks (min 8, max 500), anti-indicator check, placeholder check, compound non-secret check
3. Score key name → (score, tier, subtype)
4. Compute tiered score → composite confidence
5. Build `Finding` with engine="secret_scanner"

- [ ] **Step 2: Test with `password = "realSecret123!"` and `token_address = "0x123"` and commit**

```bash
git commit -m "feat(rust): KV pass — key-value secret scanner with tiered scoring"
```

---

### Task 15: Opaque token pass

**Files:**
- Create: `data_classifier_core/src/secret_detector/opaque_pass.rs`

Port from Python `scan_text.py:303-375` and JS `scanner-core.js:399-464`.

- [ ] **Step 1: Implement opaque token pass**

Split text by whitespace, strip quotes/punctuation, apply filters (length, UUID, placeholder, FP, entropy ≥ 0.7, diversity ≥ 3), compute confidence with bonuses. Suppress tokens inside PEM spans.

- [ ] **Step 2: Test and commit**

```bash
git commit -m "feat(rust): opaque token pass — high-entropy standalone token detection"
```

---

### Task 16: PEM pass

**Files:**
- Create: `data_classifier_core/src/secret_detector/pem_pass.rs`

Port from Python `scan_text.py:262-301`.

- [ ] **Step 1: Implement PEM detection**

Regex: `-----BEGIN\s+([\w\s]+?)-----[\s\S]*?-----END\s+\1-----`. Match private key labels only. Return spans (for opaque pass suppression) and findings (for PRIVATE_KEY entities).

- [ ] **Step 2: Test with RSA PRIVATE KEY block and commit**

```bash
git commit -m "feat(rust): PEM pass — private key block detection"
```

---

### Task 17: Redaction module

**Files:**
- Create: `data_classifier_core/src/secret_detector/redaction.rs`

Port from JS `redaction.js` and Python masking logic.

- [ ] **Step 1: Implement 4 redaction strategies**

```rust
pub fn redact(text: &str, findings: &[Finding], strategy: &str) -> String {
    // Sort findings right-to-left by start position
    // For each finding, replace match span with:
    //   "type-label" → [REDACTED:ENTITY_TYPE]
    //   "asterisk"   → N asterisks (length-preserving)
    //   "placeholder" → «secret»
    //   "none"       → no replacement
}
```

- [ ] **Step 2: Test and commit**

```bash
git commit -m "feat(rust): redaction — type-label, asterisk, placeholder, none strategies"
```

---

### Task 18: SecretOrchestrator — wire all passes + dedup

**Files:**
- Modify: `data_classifier_core/src/secret_detector/mod.rs`

- [ ] **Step 1: Wire all passes into SecretOrchestrator**

```rust
pub struct SecretOrchestrator {
    config: SecretConfig,
    regex_pass: RegexPass,
    key_scorer: KeyScorer,
    // ... all initialized from patterns JSON
}

impl SecretOrchestrator {
    pub fn from_patterns(patterns: &serde_json::Value) -> Self { ... }

    pub fn detect_secrets(&self, text: &str) -> Vec<Finding> {
        let pem = self.pem_pass.detect(text);
        let regex = self.regex_pass.detect(text);
        let kv = self.kv_pass.detect(text, &self.config);
        let opaque = self.opaque_pass.detect(text, &pem.spans, &self.config);

        let mut all = Vec::new();
        all.extend(pem.findings);
        all.extend(regex);
        all.extend(kv);
        all.extend(opaque);

        dedup(all)
    }
}
```

- [ ] **Step 2: Implement dedup**

Sort by confidence descending. Keep highest-confidence finding per overlapping span. Restore position order.

- [ ] **Step 3: Integration test — full pipeline on known text**

Test with text containing a GitHub PAT, a KV secret (`password = "abc123!@#"`), and an opaque token. Verify all three passes fire and dedup works.

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(rust): SecretOrchestrator — wire all passes, dedup, integration test"
```

---

### Task 19: Golden fixture parity test

**Files:**
- Create: `data_classifier_core/tests/secret_parity.rs` (integration test)

- [ ] **Step 1: Build parity test**

Load the seed fixtures from `data_classifier/clients/browser/src/generated/fixtures.json`. For each fixture, run `SecretOrchestrator::detect_secrets()` and compare entity_type, start, end, confidence against expected. This proves Rust matches Python/JS on the canonical test set.

- [ ] **Step 2: Run and fix any mismatches**

Run: `cd data_classifier_core && cargo test --no-default-features --test secret_parity`

- [ ] **Step 3: Commit**

```bash
git commit -m "test(rust): golden fixture parity — Rust matches Python/JS on seed corpus"
```

---

## Phase 2: TextModel + Zone Annotation

### Task 20: TextModel struct

**Files:**
- Create: `data_classifier_core/src/text_model.rs`
- Modify: `data_classifier_core/src/lib.rs`

- [ ] **Step 1: Define TextModel and ZoneAnnotation**

```rust
// data_classifier_core/src/text_model.rs

use crate::zone_detector::types::ZoneType;

#[derive(Debug, Clone)]
pub struct ZoneAnnotation {
    pub zone_type: ZoneType,
    pub confidence: f64,
    pub language_hint: String,
    pub block_index: usize,
    pub is_literal_context: bool,
}

#[derive(Debug, Clone)]
pub struct LineInfo {
    pub offset_start: usize,
    pub offset_end: usize,
    pub content: String,
    pub zone: Option<ZoneAnnotation>,
}

#[derive(Debug, Clone)]
pub struct TextModel {
    pub text: String,
    pub lines: Vec<LineInfo>,
}

impl TextModel {
    /// Build a TextModel from raw text. Zone annotations are None until populated.
    pub fn from_text(text: &str) -> Self {
        let mut lines = Vec::new();
        let mut offset = 0;
        for line_content in text.split('\n') {
            let end = offset + line_content.len();
            lines.push(LineInfo {
                offset_start: offset,
                offset_end: end,
                content: line_content.to_string(),
                zone: None,
            });
            offset = end + 1; // +1 for the \n
        }
        Self {
            text: text.to_string(),
            lines,
        }
    }

    /// Find the line index for a byte offset.
    pub fn line_at_offset(&self, offset: usize) -> usize {
        self.lines.iter()
            .position(|l| offset >= l.offset_start && offset <= l.offset_end)
            .unwrap_or(0)
    }
}
```

- [ ] **Step 2: Add `pub mod text_model;` to lib.rs, test, commit**

```bash
git commit -m "feat(rust): TextModel — shared representation with line-level zone annotations"
```

---

### Task 21: Zone annotation writer

**Files:**
- Modify: `data_classifier_core/src/text_model.rs`
- Modify: `data_classifier_core/src/zone_detector/mod.rs` (or add a new annotate function)

- [ ] **Step 1: Implement annotate_zones**

```rust
// In text_model.rs
impl TextModel {
    /// Populate zone annotations from PromptZones.
    pub fn annotate_zones(&mut self, zones: &crate::zone_detector::types::PromptZones) {
        for (block_idx, block) in zones.blocks.iter().enumerate() {
            for line_idx in block.start_line..block.end_line {
                if line_idx < self.lines.len() {
                    let is_literal = self.lines[line_idx].content.contains('"')
                        || self.lines[line_idx].content.contains('\'');
                    self.lines[line_idx].zone = Some(ZoneAnnotation {
                        zone_type: block.zone_type.clone(),
                        confidence: block.confidence,
                        language_hint: block.language_hint.clone(),
                        block_index: block_idx,
                        is_literal_context: is_literal,
                    });
                }
            }
        }
    }
}
```

- [ ] **Step 2: Test — build TextModel, run zone detection, annotate, verify lines have zones**

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(rust): zone annotation writer — populate TextModel from PromptZones"
```

---

## Phase 3: Zone-Aware Scoring

### Task 22: ZoneScorer with configurable rules

**Files:**
- Create: `data_classifier_core/src/secret_detector/zone_scorer.rs`

- [ ] **Step 1: Define ScoringRule and ZoneScorer**

```rust
use serde::{Deserialize, Serialize};
use crate::text_model::TextModel;
use super::types::Finding;

#[derive(Debug, Clone, Deserialize)]
pub struct ScoringRule {
    pub name: String,
    pub zone_type: String,
    pub value_context: String, // "literal", "expression", "any"
    pub delta: f64,
}

pub struct ZoneScorer {
    rules: Vec<ScoringRule>,
    suppression_threshold: f64,
    max_confidence: f64,
    literal_patterns: Vec<fancy_regex::Regex>,
    expression_patterns: Vec<fancy_regex::Regex>,
}

impl ZoneScorer {
    pub fn from_patterns(patterns: &serde_json::Value) -> Self { ... }

    pub fn adjust(&self, model: &TextModel, findings: Vec<Finding>) -> Vec<Finding> {
        findings.into_iter().filter_map(|mut f| {
            let line_idx = model.line_at_offset(f.match_span.start);
            let annotation = &model.lines[line_idx].zone;
            match annotation {
                Some(ann) => {
                    let value_ctx = self.detect_value_context(&model.lines[line_idx].content, &f);
                    let delta = self.find_delta(&ann.zone_type.as_str(), &value_ctx);
                    f.confidence = (f.confidence + delta).clamp(0.0, self.max_confidence);
                    if f.confidence < self.suppression_threshold { None } else { Some(f) }
                }
                None => Some(f),
            }
        }).collect()
    }
}
```

- [ ] **Step 2: Test zone scoring rules**

Test: code zone + expression → confidence reduced by 0.20. Code zone + literal → confidence boosted by 0.05. Config zone → boosted. Error output → reduced. No zone → unchanged.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(rust): ZoneScorer — configurable zone-aware confidence adjustment"
```

---

### Task 23: Wire ZoneScorer into SecretOrchestrator

**Files:**
- Modify: `data_classifier_core/src/secret_detector/mod.rs`

- [ ] **Step 1: Update SecretOrchestrator to accept TextModel and apply zone scoring**

```rust
pub fn detect_secrets_with_zones(&self, model: &TextModel) -> Vec<Finding> {
    let raw = self.detect_secrets(&model.text);
    self.zone_scorer.adjust(model, raw)
}
```

- [ ] **Step 2: Integration test — secret in code zone with literal value is kept, code expression is suppressed**

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(rust): wire ZoneScorer into SecretOrchestrator — zone-aware detection complete"
```

---

## Phase 4: WASM + PyO3 Bindings

### Task 24: Unified patterns JSON builder

**Files:**
- Create: `scripts/build_unified_patterns.py`
- Create: `data_classifier_core/patterns/unified_patterns.json`

- [ ] **Step 1: Write Python script that merges zone + secret config**

Reads:
- `zone_patterns.json` (zone config)
- `data_classifier/patterns/standard.yaml` (secret patterns)
- `data_classifier/config/engine_defaults.yaml` (secret scanner config)
- `data_classifier/engines/secret_scanner.py` (placeholder patterns, anti-indicators, etc.)
- `data_classifier/clients/browser/src/generated/secret-key-names.js` (key name entries)

Outputs: `unified_patterns.json` with all sections from the spec (Section 4).

- [ ] **Step 2: Generate and validate**

Run: `python3 scripts/build_unified_patterns.py`
Verify: JSON is valid, has all expected top-level keys.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(build): unified_patterns.json builder — merges zone + secret + scoring config"
```

---

### Task 25: Unified WASM API

**Files:**
- Modify: `data_classifier_core/src/lib.rs`

- [ ] **Step 1: Add unified init() and detect() to wasm_api**

```rust
// In wasm_api module, add alongside existing functions:

thread_local! {
    static UNIFIED: RefCell<Option<(ZoneOrchestrator, SecretOrchestrator, ZoneScorer)>> = const { RefCell::new(None) };
}

#[wasm_bindgen]
pub fn init(patterns_json: &str) -> bool {
    let patterns: serde_json::Value = match serde_json::from_str(patterns_json) {
        Ok(v) => v,
        Err(_) => return false,
    };
    let zone_config = ZoneConfig::default();
    let zone_detector = ZoneOrchestrator::from_patterns(&patterns, &zone_config);
    let secret_detector = SecretOrchestrator::from_patterns(&patterns);
    let zone_scorer = ZoneScorer::from_patterns(&patterns);
    UNIFIED.with(|u| {
        *u.borrow_mut() = Some((zone_detector, secret_detector, zone_scorer));
    });
    true
}

#[wasm_bindgen]
pub fn detect_unified(text: &str, opts_json: &str) -> String {
    // Parse opts: { secrets: bool, zones: bool, redact_strategy: str, verbose: bool }
    // Build TextModel
    // Run zones if enabled → annotate TextModel
    // Run secrets if enabled → apply zone scoring
    // Redact
    // Return JSON: { zones, findings, redacted_text, scanned_ms }
}
```

- [ ] **Step 2: Test WASM build**

Run: `cd data_classifier_core && wasm-pack build --target web --release`
Verify: pkg/ contains updated .wasm and .js files.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(wasm): unified init() + detect() API — zones + secrets in single call"
```

---

### Task 26: PyO3 API

**Files:**
- Modify: `data_classifier_core/src/lib.rs`

- [ ] **Step 1: Add UnifiedDetector to python_api**

```rust
#[pyclass]
pub struct UnifiedDetector {
    zone_detector: ZoneOrchestrator,
    secret_detector: SecretOrchestrator,
    zone_scorer: ZoneScorer,
}

#[pymethods]
impl UnifiedDetector {
    #[new]
    fn new(patterns_json: &str) -> PyResult<Self> { ... }
    fn detect(&self, text: &str, opts: Option<&Bound<'_, PyDict>>) -> PyResult<String> { ... }
    fn detect_zones(&self, text: &str, prompt_id: &str) -> PromptZones { ... } // legacy
}
```

Register in `data_classifier_core` module alongside existing classes.

- [ ] **Step 2: Test PyO3 build**

Run: `cd data_classifier_core && maturin develop --release --features python`

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(pyo3): UnifiedDetector class — zones + secrets via Python"
```

---

### Task 27: Cross-runtime parity test

**Files:**
- Create: `scripts/cross_runtime_parity.sh`

- [ ] **Step 1: Write parity test script**

1. Run Rust native on seed fixtures → save output
2. Run WASM (via Node) on same fixtures → save output
3. Run PyO3 (via Python) on same fixtures → save output
4. Diff all three → zero divergence

- [ ] **Step 2: Run and fix any mismatches**

- [ ] **Step 3: Commit**

```bash
git commit -m "test(ci): cross-runtime parity — Rust native vs WASM vs PyO3"
```

---

## Phase 5: Browser Migration

### Task 28: Unified detector.js (replaces zone-detector.js)

**Files:**
- Create: `data_classifier/clients/browser/src/detector.js`

- [ ] **Step 1: Write detector.js**

Expand `zone-detector.js` to call unified `init()` + `unified_detect()` instead of `init_detector()` + `detect()`. Load `unified_patterns.json` instead of `zone_patterns.json`.

```javascript
// detector.js — unified WASM loader
let wasmModule = null;
let initPromise = null;
let detectorReady = false;

export async function initDetector(wasmUrl, patternsUrl) {
    if (initPromise) return initPromise;
    initPromise = (async () => {
        const [wasmBytes, patternsJson] = await Promise.all([
            fetch(wasmUrl || new URL('data_classifier_core_bg.wasm', import.meta.url)).then(r => r.arrayBuffer()),
            fetch(patternsUrl || new URL('unified_patterns.json', import.meta.url)).then(r => r.text()),
        ]);
        wasmModule = await WebAssembly.instantiate(wasmBytes, buildWasmImports());
        wasmModule.instance.exports.__wbindgen_start();
        const ok = callInit(patternsJson);
        detectorReady = ok;
        return ok;
    })();
    return initPromise;
}

export function detect(text, optsJson) {
    if (!detectorReady) return null;
    return callDetectUnified(text, optsJson);
}

export function isDetectorReady() { return detectorReady; }
export function resetDetector() { detectorReady = false; initPromise = null; wasmModule = null; }
```

- [ ] **Step 2: Commit**

```bash
git commit -m "feat(browser): detector.js — unified WASM loader for zones + secrets"
```

---

### Task 29: Simplify worker.js + delete JS detection code

**Files:**
- Modify: `data_classifier/clients/browser/src/worker.js`
- Delete: `src/scanner-core.js`, `src/entropy.js`, `src/kv-parsers.js`, `src/regex-backend.js`, `src/validators.js`, `src/finding.js`, `src/decoder.js`, `src/redaction.js`, `src/zone-detector.js`
- Delete: `src/generated/` (entire directory)

- [ ] **Step 1: Rewrite worker.js**

```javascript
import { initDetector, detect, isDetectorReady } from './detector.js';

let initialized = false;

self.onmessage = async function (e) {
    const { id, text, opts } = e.data;
    try {
        if (!initialized) {
            initialized = await initDetector();
        }
        const optsJson = JSON.stringify({
            secrets: opts.secrets !== false,
            zones: opts.zones !== false,
            redact_strategy: opts.redactStrategy || 'type-label',
            verbose: !!opts.verbose,
            include_raw: !!opts.dangerouslyIncludeRawValues,
        });
        const resultJson = detect(text, optsJson);
        const result = JSON.parse(resultJson);
        self.postMessage({ id, result });
    } catch (err) {
        self.postMessage({ id, error: { message: err.message || String(err) } });
    }
};
```

- [ ] **Step 2: Delete all JS detection files**

```bash
rm src/scanner-core.js src/entropy.js src/kv-parsers.js src/regex-backend.js \
   src/validators.js src/finding.js src/decoder.js src/redaction.js src/zone-detector.js
rm -rf src/generated/
```

- [ ] **Step 3: Update esbuild.config.mjs**

Change asset copying: `unified_patterns.json` instead of `zone_patterns.json`.

- [ ] **Step 4: Update package.json**

Remove `generate` script (no more Python → JS generation). Update exports.

- [ ] **Step 5: Build and verify**

Run: `npm run build`
Verify: `dist/` contains `scanner.esm.js`, `worker.esm.js`, `data_classifier_core_bg.wasm`, `unified_patterns.json`.

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(browser): replace JS detection with unified WASM — delete scanner-core.js + generated/"
```

---

### Task 30: Port vitest tests to Rust + update e2e

**Files:**
- Modify: `tests/unit/` — remove obsolete test files, keep pool.test.js
- Create: `tests/unit/detector.test.js` — test new detector.js wrapper
- Modify: `tests/e2e/tester.spec.js` — update for unified output format
- Modify: `tests/e2e/differential.spec.js` — now compares WASM vs Python

- [ ] **Step 1: Delete obsolete vitest files**

Remove: `scanner-core.test.js`, `entropy.test.js`, `kv-parsers.test.js`, `regex-backend.test.js`, `validators.test.js`. These are now covered by Rust unit tests.

Keep: `pool.test.js`, `zone-detector.test.js` (rename to `detector.test.js`).

- [ ] **Step 2: Update e2e tests**

Update `tester.spec.js` and `differential.spec.js` to work with unified WASM output.

- [ ] **Step 3: Run full test suite**

```bash
npm run test:unit && npm run test:e2e
```

- [ ] **Step 4: Commit**

```bash
git commit -m "test(browser): port tests to Rust, update e2e for unified WASM"
```

---

### Task 31: Update tester page + docs

**Files:**
- Modify: `tester/tester.js`
- Modify: `scanner.d.ts`
- Modify: `docs/api.md`
- Modify: `README.md`
- Modify: `scripts/package.js`

- [ ] **Step 1: Update tester.js**

The unified WASM `detect()` returns `{ zones, findings, redacted_text, scanned_ms }` directly. Update tester to use this shape.

- [ ] **Step 2: Update scanner.d.ts**

Remove internal types (EntropyDetails, etc.) that are now Rust-internal. Keep public API types.

- [ ] **Step 3: Update docs and README**

Update architecture description: single Rust/WASM engine, no JS detection code. Update footprint table with new sizes.

- [ ] **Step 4: Update package.js**

Remove `generated/` from includes. Add `unified_patterns.json`.

- [ ] **Step 5: Smoke test tester page**

```bash
npm run serve
# Open http://localhost:4173/tester/ — verify secrets + zones work
```

- [ ] **Step 6: Commit**

```bash
git commit -m "docs(browser): update API, README, tester for unified WASM architecture"
```

---

## Phase 6: Python Text-Path Migration

### Task 32: Wire scan_text.py to Rust via PyO3

**Files:**
- Modify: `data_classifier/scan_text.py`

- [ ] **Step 1: Replace Python detection with Rust UnifiedDetector**

```python
# scan_text.py — thin wrapper around Rust UnifiedDetector

from data_classifier_core import UnifiedDetector
import json
from pathlib import Path

_DETECTOR = None
_PATTERNS_PATH = Path(__file__).parent.parent / "data_classifier_core" / "patterns" / "unified_patterns.json"

def _get_detector():
    global _DETECTOR
    if _DETECTOR is None:
        patterns = _PATTERNS_PATH.read_text()
        _DETECTOR = UnifiedDetector(patterns)
    return _DETECTOR

def scan_text(text: str, *, min_confidence: float = 0.3) -> TextScanResult:
    detector = _get_detector()
    result_json = detector.detect(text, {"secrets": True, "zones": False})
    result = json.loads(result_json)
    findings = [f for f in result["findings"] if f["confidence"] >= min_confidence]
    return TextScanResult(findings=findings, scanned_length=len(text))
```

- [ ] **Step 2: Run existing pytest tests**

Run: `.venv/bin/python -m pytest tests/ -v -k "scan_text or secret"`
Expected: All pass — same output from Rust as from Python.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(python): scan_text.py → Rust UnifiedDetector via PyO3"
```

---

### Task 33: Full regression suite

**Files:**
- Modify: `scripts/ci_browser_parity.sh` — replace with cross-runtime parity

- [ ] **Step 1: Run all quality gates**

```bash
# Rust unit tests
cd data_classifier_core && cargo test --no-default-features

# Browser unit tests
cd data_classifier/clients/browser && npx vitest run

# Browser e2e tests
npx playwright test

# Cross-runtime parity
bash scripts/cross_runtime_parity.sh

# Python tests
.venv/bin/python -m pytest tests/ -v

# Family benchmark (no regression)
DATA_CLASSIFIER_DISABLE_ML=1 python -m tests.benchmarks.family_accuracy_benchmark \
    --out /tmp/bench.predictions.jsonl --summary /tmp/bench.summary.json
```

- [ ] **Step 2: Verify all gates from spec Section 7**

Zone: precision ≥98%, recall ≥95%, F1 ≥0.960, parity 100%.
Secrets: differential 100%, WildChat F1 ≥96%, finding precision ≥73%.
New: Rust/WASM parity, JS elimination, validator parity, zone-scorer A/B.

- [ ] **Step 3: Final commit**

```bash
git commit -m "chore: full regression — all quality gates pass for unified WASM detector"
```

---

## Summary

| Phase | Tasks | What it delivers |
|-------|-------|-----------------|
| **Phase 1** | Tasks 1-19 | Complete Rust secret detector with all 24 validators, 7 parsers, 42+ FP filters |
| **Phase 2** | Tasks 20-21 | TextModel shared representation + zone annotations |
| **Phase 3** | Tasks 22-23 | Zone-aware confidence scoring with configurable rules |
| **Phase 4** | Tasks 24-27 | WASM + PyO3 bindings, unified patterns JSON, cross-runtime parity |
| **Phase 5** | Tasks 28-31 | Browser migration — delete JS detection, unified WASM |
| **Phase 6** | Tasks 32-33 | Python scan_text migration + full regression |
