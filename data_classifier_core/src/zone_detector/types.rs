//! Core types for zone detection — mirrors Python types.py.

use serde::{Deserialize, Serialize};

/// The eight zone types recognized by the detector.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
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

impl ZoneType {
    pub fn from_str(s: &str) -> Option<Self> {
        match s {
            "code" => Some(Self::Code),
            "markup" => Some(Self::Markup),
            "config" => Some(Self::Config),
            "query" => Some(Self::Query),
            "cli_shell" => Some(Self::CliShell),
            "data" => Some(Self::Data),
            "error_output" => Some(Self::ErrorOutput),
            "natural_language" => Some(Self::NaturalLanguage),
            _ => None,
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Code => "code",
            Self::Markup => "markup",
            Self::Config => "config",
            Self::Query => "query",
            Self::CliShell => "cli_shell",
            Self::Data => "data",
            Self::ErrorOutput => "error_output",
            Self::NaturalLanguage => "natural_language",
        }
    }
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
