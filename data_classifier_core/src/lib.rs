//! data_classifier_core — Zone and secret detection engine.
//!
//! Single Rust implementation compiled to:
//! - WASM for browser extensions (via wasm-bindgen)
//! - Native library for Python (via wasmtime or pyo3)
//!
//! Both consumers read shared JSON pattern configs, ensuring
//! identical detection behavior with zero parity gaps.

pub mod zone_detector;

use wasm_bindgen::prelude::*;
use std::cell::RefCell;

// Store the initialized orchestrator for reuse across calls.
// WASM is single-threaded, so thread_local + RefCell is safe.
thread_local! {
    static DETECTOR: RefCell<Option<zone_detector::ZoneOrchestrator>> = const { RefCell::new(None) };
}

/// Initialize the zone detector with a patterns JSON config.
///
/// Must be called once before `detect()`. Compiles all regex patterns
/// (~100 patterns across 8 modules). Typical init time: ~15-25ms.
#[wasm_bindgen]
pub fn init_detector(patterns_json: &str) -> bool {
    let patterns: serde_json::Value = match serde_json::from_str(patterns_json) {
        Ok(v) => v,
        Err(_) => return false,
    };
    let config = zone_detector::ZoneConfig::default();
    let detector = zone_detector::ZoneOrchestrator::from_patterns(&patterns, &config);
    DETECTOR.with(|d| {
        *d.borrow_mut() = Some(detector);
    });
    true
}

/// Detect zones in a prompt using the pre-initialized detector.
///
/// Call `init_detector()` first. Returns JSON string with detected blocks.
/// Typical detection time: ~0.3-1.5ms per prompt.
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

/// One-shot detect: parses config, builds detector, runs detection.
///
/// Convenience for single-use. For batch processing, use
/// `init_detector()` + `detect()` instead.
#[wasm_bindgen]
pub fn detect_zones_with_patterns(text: &str, prompt_id: &str, patterns_json: &str) -> String {
    let patterns: serde_json::Value = match serde_json::from_str(patterns_json) {
        Ok(v) => v,
        Err(_) => return "{}".to_string(),
    };
    let config = zone_detector::ZoneConfig::default();
    let detector = zone_detector::ZoneOrchestrator::from_patterns(&patterns, &config);
    let result = detector.detect_zones(text, prompt_id);
    serde_json::to_string(&result).unwrap_or_else(|_| "{}".to_string())
}
