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
