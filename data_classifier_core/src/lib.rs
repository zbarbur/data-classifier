//! data_classifier_core — Zone and secret detection engine.
//!
//! Single Rust implementation compiled to:
//! - WASM for browser extensions (feature = "wasm")
//! - Python native module (feature = "python", via pyo3)
//! - Native binary for benchmarks (always available)
//!
//! Both consumers read shared JSON pattern configs, ensuring
//! identical detection behavior with zero parity gaps.

pub mod zone_detector;
pub mod secret_detector;
pub mod text_model;

// =========================================================================
// WASM API (feature = "wasm")
// =========================================================================

#[cfg(feature = "wasm")]
mod wasm_api {
    use super::secret_detector::redaction;
    use super::secret_detector::SecretOrchestrator;
    use super::text_model::TextModel;
    use super::zone_detector::{ZoneConfig, ZoneOrchestrator};
    use std::cell::RefCell;
    use wasm_bindgen::prelude::*;

    thread_local! {
        // Existing zone-only detector (kept for backward compatibility)
        static DETECTOR: RefCell<Option<ZoneOrchestrator>> = const { RefCell::new(None) };
        // Unified detector: zones + secrets in a single call
        static UNIFIED: RefCell<Option<UnifiedState>> = const { RefCell::new(None) };
    }

    struct UnifiedState {
        zone_detector: ZoneOrchestrator,
        secret_detector: SecretOrchestrator,
    }

    // ── Zone-only API (backward compatible) ──────────────────────────

    /// Initialize the zone detector with a patterns JSON config.
    /// Must be called once before `detect()`.
    #[wasm_bindgen]
    pub fn init_detector(patterns_json: &str) -> bool {
        let patterns: serde_json::Value = match serde_json::from_str(patterns_json) {
            Ok(v) => v,
            Err(_) => return false,
        };
        let config = ZoneConfig::default();
        let detector = ZoneOrchestrator::from_patterns(&patterns, &config);
        DETECTOR.with(|d| {
            *d.borrow_mut() = Some(detector);
        });
        true
    }

    /// Detect zones using the pre-initialized detector. Returns JSON.
    #[wasm_bindgen]
    pub fn detect(text: &str, prompt_id: &str) -> String {
        DETECTOR.with(|d| {
            let borrow = d.borrow();
            match borrow.as_ref() {
                Some(detector) => {
                    let result = detector.detect_zones(text, prompt_id);
                    serde_json::to_string(&result).unwrap_or_else(|_| "{}".to_string())
                }
                None => "{}".to_string(),
            }
        })
    }

    /// One-shot: parse config + build detector + detect. For single use only.
    #[wasm_bindgen]
    pub fn detect_zones_with_patterns(
        text: &str,
        prompt_id: &str,
        patterns_json: &str,
    ) -> String {
        let patterns: serde_json::Value = match serde_json::from_str(patterns_json) {
            Ok(v) => v,
            Err(_) => return "{}".to_string(),
        };
        let config = ZoneConfig::default();
        let detector = ZoneOrchestrator::from_patterns(&patterns, &config);
        let result = detector.detect_zones(text, prompt_id);
        serde_json::to_string(&result).unwrap_or_else(|_| "{}".to_string())
    }

    // ── Unified API (zones + secrets) ────────────────────────────────

    /// Initialize the unified detector with a patterns JSON config.
    /// Loads both zone and secret detection config.
    /// Must be called once before `detect_unified()`.
    #[wasm_bindgen]
    pub fn init(patterns_json: &str) -> bool {
        let patterns: serde_json::Value = match serde_json::from_str(patterns_json) {
            Ok(v) => v,
            Err(_) => return false,
        };
        let zone_config = ZoneConfig::default();
        let zone_detector = ZoneOrchestrator::from_patterns(&patterns, &zone_config);
        let secret_detector = SecretOrchestrator::from_patterns(&patterns);

        UNIFIED.with(|u| {
            *u.borrow_mut() = Some(UnifiedState {
                zone_detector,
                secret_detector,
            });
        });
        true
    }

    /// Unified detection — returns zones + secrets + redacted text as JSON.
    ///
    /// `opts_json` format:
    /// ```json
    /// {
    ///   "secrets": true,
    ///   "zones": true,
    ///   "redact_strategy": "type-label",
    ///   "verbose": false,
    ///   "include_raw": false
    /// }
    /// ```
    ///
    /// Returns a JSON string with:
    /// - `zones`: zone detection result (null if zones disabled)
    /// - `findings`: secret detection findings array
    /// - `redacted_text`: text with secrets replaced per strategy
    /// - `scanned_ms`: timing placeholder (0.0)
    #[wasm_bindgen]
    pub fn detect_unified(text: &str, opts_json: &str) -> String {
        UNIFIED.with(|u| {
            let borrow = u.borrow();
            let state = match borrow.as_ref() {
                Some(s) => s,
                None => return "{}".to_string(),
            };

            // Parse options with safe defaults
            let opts: serde_json::Value =
                serde_json::from_str(opts_json).unwrap_or(serde_json::json!({}));
            let run_secrets = opts.get("secrets").and_then(|v| v.as_bool()).unwrap_or(true);
            let run_zones = opts.get("zones").and_then(|v| v.as_bool()).unwrap_or(true);
            let redact_strategy = opts
                .get("redact_strategy")
                .and_then(|v| v.as_str())
                .unwrap_or("type-label");
            let verbose = opts.get("verbose").and_then(|v| v.as_bool()).unwrap_or(false);
            let include_raw = opts
                .get("include_raw")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);

            // Zone detection (keep PromptZones in native form for TextModel annotation)
            let zones_result = if run_zones {
                Some(state.zone_detector.detect_zones(text, ""))
            } else {
                None
            };

            // Secret detection (zone-aware scoring when zones are available)
            let findings = if run_secrets {
                if let Some(ref zones) = zones_result {
                    let mut model = TextModel::from_text(text);
                    model.annotate_zones(zones);
                    state
                        .secret_detector
                        .detect_secrets_with_zones_full(&model, verbose, include_raw)
                } else {
                    state
                        .secret_detector
                        .detect_secrets_full(text, verbose, include_raw)
                }
            } else {
                Vec::new()
            };

            // Redaction
            let redacted_text = if run_secrets && !findings.is_empty() {
                redaction::redact(text, &findings, redact_strategy)
            } else {
                text.to_string()
            };

            // Serialize zones for output
            let zones_json = zones_result
                .map(|z| serde_json::to_value(&z).unwrap_or(serde_json::json!(null)));

            // Build result
            let result = serde_json::json!({
                "zones": zones_json,
                "findings": findings,
                "redacted_text": redacted_text,
                "scanned_ms": 0.0
            });

            serde_json::to_string(&result).unwrap_or_else(|_| "{}".to_string())
        })
    }
}

// =========================================================================
// Python API (feature = "python")
// =========================================================================

#[cfg(feature = "python")]
mod python_api {
    use super::zone_detector::{ZoneConfig, ZoneOrchestrator};
    use pyo3::prelude::*;

    /// A detected zone block within a prompt.
    #[pyclass(frozen)]
    #[derive(Clone)]
    pub struct ZoneBlock {
        #[pyo3(get)]
        pub start_line: usize,
        #[pyo3(get)]
        pub end_line: usize,
        #[pyo3(get)]
        pub zone_type: String,
        #[pyo3(get)]
        pub confidence: f64,
        #[pyo3(get)]
        pub method: String,
        #[pyo3(get)]
        pub language_hint: String,
        #[pyo3(get)]
        pub language_confidence: f64,
        #[pyo3(get)]
        pub text: String,
    }

    #[pymethods]
    impl ZoneBlock {
        fn __repr__(&self) -> String {
            format!(
                "ZoneBlock({}–{}, {}, conf={:.2})",
                self.start_line, self.end_line, self.zone_type, self.confidence
            )
        }
    }

    /// Result of zone detection on a single prompt.
    #[pyclass(frozen)]
    #[derive(Clone)]
    pub struct PromptZones {
        #[pyo3(get)]
        pub prompt_id: String,
        #[pyo3(get)]
        pub total_lines: usize,
        #[pyo3(get)]
        pub blocks: Vec<ZoneBlock>,
    }

    /// Zone detector — compiles patterns once, detects many prompts.
    #[pyclass]
    pub struct ZoneDetector {
        inner: ZoneOrchestrator,
    }

    #[pymethods]
    impl ZoneDetector {
        /// Create a new detector from zone_patterns.json content.
        #[new]
        fn new(patterns_json: &str) -> PyResult<Self> {
            let patterns: serde_json::Value = serde_json::from_str(patterns_json)
                .map_err(|e| {
                    pyo3::exceptions::PyValueError::new_err(format!(
                        "invalid patterns JSON: {}",
                        e
                    ))
                })?;
            let config = ZoneConfig::default();
            Ok(Self {
                inner: ZoneOrchestrator::from_patterns(&patterns, &config),
            })
        }

        /// Detect zones in a prompt. Returns PromptZones.
        fn detect_zones(&self, text: &str, prompt_id: &str) -> PromptZones {
            let result = self.inner.detect_zones(text, prompt_id);
            PromptZones {
                prompt_id: result.prompt_id,
                total_lines: result.total_lines,
                blocks: result
                    .blocks
                    .into_iter()
                    .map(|b| ZoneBlock {
                        start_line: b.start_line,
                        end_line: b.end_line,
                        zone_type: b.zone_type.as_str().to_string(),
                        confidence: b.confidence,
                        method: b.method,
                        language_hint: b.language_hint,
                        language_confidence: b.language_confidence,
                        text: b.text,
                    })
                    .collect(),
            }
        }
    }

    /// Python module definition.
    #[pymodule]
    fn data_classifier_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
        m.add_class::<ZoneDetector>()?;
        m.add_class::<ZoneBlock>()?;
        m.add_class::<PromptZones>()?;
        Ok(())
    }
}
