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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_zone_type_from_str_roundtrip() {
        let cases = [
            ("code", ZoneType::Code),
            ("markup", ZoneType::Markup),
            ("config", ZoneType::Config),
            ("query", ZoneType::Query),
            ("cli_shell", ZoneType::CliShell),
            ("data", ZoneType::Data),
            ("error_output", ZoneType::ErrorOutput),
            ("natural_language", ZoneType::NaturalLanguage),
        ];
        for (s, expected) in &cases {
            let parsed = ZoneType::from_str(s);
            assert_eq!(parsed.as_ref(), Some(expected), "from_str({})", s);
            assert_eq!(parsed.unwrap().as_str(), *s, "as_str round-trip for {}", s);
        }
    }

    #[test]
    fn test_zone_type_from_str_invalid() {
        assert_eq!(ZoneType::from_str("unknown"), None);
        assert_eq!(ZoneType::from_str(""), None);
        assert_eq!(ZoneType::from_str("Code"), None); // case-sensitive
    }

    #[test]
    fn test_zone_block_serde_roundtrip() {
        let block = ZoneBlock {
            start_line: 5,
            end_line: 15,
            zone_type: ZoneType::Code,
            confidence: 0.85,
            method: "syntax_score".to_string(),
            language_hint: "python".to_string(),
            language_confidence: 0.9,
            text: "should be skipped".to_string(),
        };
        let json = serde_json::to_string(&block).unwrap();
        assert!(!json.contains("should be skipped"), "text must be skip_serializing");
        assert!(json.contains("\"zone_type\":\"code\""), "zone_type must be snake_case");
    }

    #[test]
    fn test_prompt_zones_default() {
        let pz = PromptZones {
            prompt_id: "test".to_string(),
            total_lines: 0,
            blocks: vec![],
        };
        assert!(pz.blocks.is_empty());
    }
}
