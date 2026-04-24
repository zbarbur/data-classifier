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

/// WASM entry point: detect zones in a prompt string.
///
/// Returns JSON string with detected blocks.
#[wasm_bindgen]
pub fn detect_zones(text: &str, prompt_id: &str) -> String {
    let config = zone_detector::ZoneConfig::default();
    let detector = zone_detector::ZoneOrchestrator::new(&config);
    let result = detector.detect_zones(text, prompt_id);
    serde_json::to_string(&result).unwrap_or_else(|_| "{}".to_string())
}

/// WASM entry point: detect zones with custom patterns JSON.
///
/// `patterns_json` should be the full zone_patterns.json content.
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
