// data_classifier_core/tests/zone_scoring_integration.rs
//
// Integration tests verifying that ZoneScorer is wired into SecretOrchestrator
// and that detect_secrets_with_zones produces zone-adjusted findings.

use data_classifier_core::secret_detector::SecretOrchestrator;
use data_classifier_core::text_model::TextModel;
use data_classifier_core::zone_detector::{PromptZones, ZoneBlock, ZoneType};

fn make_patterns() -> serde_json::Value {
    serde_json::json!({
        "secret_patterns": [
            {
                "name": "github_pat",
                "regex": "ghp_[A-Za-z0-9]{36}",
                "entity_type": "API_KEY",
                "category": "Credential",
                "sensitivity": "CRITICAL",
                "confidence": 0.99,
                "validator": "",
                "display_name": "GitHub Token",
                "stopwords": [],
                "allowlist_patterns": [],
                "requires_column_hint": false
            }
        ],
        "secret_key_names": [
            {"pattern": "password", "score": 0.95, "match_type": "word_boundary", "tier": "definitive", "subtype": "OPAQUE_SECRET"},
            {"pattern": "api_key", "score": 0.90, "match_type": "word_boundary", "tier": "definitive", "subtype": "API_KEY"}
        ],
        "stopwords": [],
        "placeholder_values": [],
        "zone_scoring": {
            "suppression_threshold": 0.30,
            "max_confidence": 0.99,
            "rules": [
                {"name": "code_literal_boost", "zone_type": "code", "value_context": "literal", "delta": 0.05},
                {"name": "code_expression_suppress", "zone_type": "code", "value_context": "expression", "delta": -0.20},
                {"name": "config_boost", "zone_type": "config", "value_context": "any", "delta": 0.05},
                {"name": "error_output_reduce", "zone_type": "error_output", "value_context": "any", "delta": -0.15}
            ],
            "value_context_detection": {
                "literal_patterns": ["=[\\s]*[\"']", ":[\\s]*[\"']"],
                "expression_patterns": ["^[a-zA-Z_]\\w*(?:\\.[a-zA-Z_]\\w*)+$", "^\\$[\\w{]"]
            }
        }
    })
}

#[test]
fn test_code_zone_literal_kept() {
    // Secret in a code zone inside a string literal — should be kept (boosted)
    let orch = SecretOrchestrator::from_patterns(&make_patterns());
    let text = "password = \"S3cureP@ss!xyz\"";
    let mut model = TextModel::from_text(text);

    // Annotate entire text as code zone
    let zones = PromptZones {
        prompt_id: "test".to_string(),
        total_lines: 1,
        blocks: vec![ZoneBlock {
            start_line: 0,
            end_line: 1,
            zone_type: ZoneType::Code,
            confidence: 0.95,
            method: "test".to_string(),
            language_hint: "python".to_string(),
            language_confidence: 0.9,
            text: String::new(),
        }],
    };
    model.annotate_zones(&zones);

    let findings = orch.detect_secrets_with_zones(&model);
    assert!(!findings.is_empty(), "literal secret in code zone should be kept");
}

#[test]
fn test_config_zone_boosted() {
    let orch = SecretOrchestrator::from_patterns(&make_patterns());
    let text = "password = \"S3cureP@ss!xyz\"";
    let mut model = TextModel::from_text(text);

    let zones = PromptZones {
        prompt_id: "test".to_string(),
        total_lines: 1,
        blocks: vec![ZoneBlock {
            start_line: 0,
            end_line: 1,
            zone_type: ZoneType::Config,
            confidence: 0.90,
            method: "test".to_string(),
            language_hint: "yaml".to_string(),
            language_confidence: 0.8,
            text: String::new(),
        }],
    };
    model.annotate_zones(&zones);

    let findings = orch.detect_secrets_with_zones(&model);
    assert!(!findings.is_empty(), "config zone should boost, not suppress");

    // Config boost = +0.05
    let without_zones = orch.detect_secrets(text);
    if !findings.is_empty() && !without_zones.is_empty() {
        assert!(
            findings[0].confidence >= without_zones[0].confidence,
            "config zone finding should have equal or higher confidence: with_zones={}, without_zones={}",
            findings[0].confidence,
            without_zones[0].confidence
        );
    }
}

#[test]
fn test_no_zone_no_change() {
    let orch = SecretOrchestrator::from_patterns(&make_patterns());
    let text = "password = \"S3cureP@ss!xyz\"";
    let model = TextModel::from_text(text); // no zones annotated

    let with_zones = orch.detect_secrets_with_zones(&model);
    let without_zones = orch.detect_secrets(text);

    assert_eq!(with_zones.len(), without_zones.len(), "no zones = same findings");
    if !with_zones.is_empty() {
        assert_eq!(
            with_zones[0].confidence,
            without_zones[0].confidence,
            "no zones = same confidence"
        );
    }
}

#[test]
fn test_error_output_reduced() {
    let orch = SecretOrchestrator::from_patterns(&make_patterns());
    let text = "password = \"S3cureP@ss!xyz\"";
    let mut model = TextModel::from_text(text);

    let zones = PromptZones {
        prompt_id: "test".to_string(),
        total_lines: 1,
        blocks: vec![ZoneBlock {
            start_line: 0,
            end_line: 1,
            zone_type: ZoneType::ErrorOutput,
            confidence: 0.90,
            method: "test".to_string(),
            language_hint: String::new(),
            language_confidence: 0.0,
            text: String::new(),
        }],
    };
    model.annotate_zones(&zones);

    let without_zones = orch.detect_secrets(text);
    let with_zones = orch.detect_secrets_with_zones(&model);

    // Error output reduces confidence by 0.15
    if !with_zones.is_empty() && !without_zones.is_empty() {
        assert!(
            with_zones[0].confidence < without_zones[0].confidence,
            "error_output zone should reduce confidence: with_zones={}, without_zones={}",
            with_zones[0].confidence,
            without_zones[0].confidence
        );
    }
}

#[test]
fn test_detect_secrets_with_zones_full_verbose() {
    // Verify detect_secrets_with_zones_full compiles and returns findings correctly
    let orch = SecretOrchestrator::from_patterns(&make_patterns());
    let text = "password = \"S3cureP@ss!xyz\"";
    let model = TextModel::from_text(text);

    let findings_default = orch.detect_secrets_with_zones(&model);
    let findings_full = orch.detect_secrets_with_zones_full(&model, false, false);

    assert_eq!(
        findings_default.len(),
        findings_full.len(),
        "default and full (verbose=false, include_raw=false) must produce same count"
    );
}
