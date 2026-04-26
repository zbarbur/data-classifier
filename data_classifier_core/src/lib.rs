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
    use super::zone_detector::{ZoneConfig, ZoneOrchestrator};
    use std::cell::RefCell;
    use wasm_bindgen::prelude::*;

    thread_local! {
        static DETECTOR: RefCell<Option<ZoneOrchestrator>> = const { RefCell::new(None) };
    }

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
