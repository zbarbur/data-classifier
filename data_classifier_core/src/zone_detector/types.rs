//! Core types for zone detection — mirrors Python types.py.

use serde::{Deserialize, Serialize};

/// The eight zone types recognized by the detector.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ZoneType {
    Code,
    Markup,
    Config,
    Query,
    CliShell,
    Data,
    ErrorOutput,
    NaturalLanguage,
}

/// A single detected zone block within a prompt.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ZoneBlock {
    pub start_line: usize,
    pub end_line: usize,
    pub zone_type: ZoneType,
    pub confidence: f64,
    pub method: String,
    #[serde(default)]
    pub language_hint: String,
    #[serde(default)]
    pub language_confidence: f64,
    #[serde(skip_serializing)]
    pub text: String,
}

/// Result of zone detection on a single prompt.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PromptZones {
    pub prompt_id: String,
    pub total_lines: usize,
    pub blocks: Vec<ZoneBlock>,
}
