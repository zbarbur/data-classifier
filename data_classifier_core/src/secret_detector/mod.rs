pub mod config;
pub mod entropy;
pub mod parsers;
pub mod redaction;
pub mod types;
pub mod validators;
pub mod fp_filters;
pub mod key_scoring;
pub mod kv_pass;
pub mod opaque_pass;
pub mod pem_pass;
pub mod regex_pass;
pub mod zone_scorer;
// pub mod pattern_matcher;

use config::SecretConfig;
use kv_pass::KVPass;
use opaque_pass::OpaquePass;
use regex_pass::RegexPass;
use types::Finding;
use zone_scorer::ZoneScorer;

use crate::text_model::TextModel;

/// Top-level orchestrator for secret/credential detection.
///
/// Wires PEM -> regex -> KV -> opaque passes together with deduplication.
/// Compiles configuration once, then detects across many inputs.
pub struct SecretOrchestrator {
    config: SecretConfig,
    regex_pass: RegexPass,
    kv_pass: KVPass,
    opaque_pass: OpaquePass,
    zone_scorer: ZoneScorer,
}

impl SecretOrchestrator {
    /// Build from the top-level patterns JSON.
    pub fn from_patterns(patterns: &serde_json::Value) -> Self {
        Self {
            config: SecretConfig::from_json(patterns),
            regex_pass: RegexPass::from_patterns(patterns),
            kv_pass: KVPass::from_patterns(patterns),
            opaque_pass: OpaquePass::from_patterns(patterns),
            zone_scorer: ZoneScorer::from_patterns(patterns),
        }
    }

    /// Detect secrets in the given text using all passes with default options.
    pub fn detect_secrets(&self, text: &str) -> Vec<Finding> {
        self.detect_secrets_full(text, false, false)
    }

    /// Detect secrets with full control over verbose logging and raw-value inclusion.
    ///
    /// Pass order: PEM (provides spans for opaque suppression) -> regex -> KV -> opaque.
    /// Results are deduplicated by overlapping span, keeping the highest-confidence finding.
    pub fn detect_secrets_full(&self, text: &str, verbose: bool, include_raw: bool) -> Vec<Finding> {
        // 1. PEM detection first (provides spans for opaque suppression)
        let pem_result = pem_pass::detect_pem_blocks(text);

        // 2. All four passes
        let mut all = Vec::new();
        all.extend(pem_result.findings);
        all.extend(self.regex_pass.detect(text, verbose, include_raw));
        all.extend(self.kv_pass.detect(text, &self.config, verbose, include_raw));
        all.extend(
            self.opaque_pass
                .detect(text, &pem_result.spans, &self.config, verbose, include_raw),
        );

        // 3. Dedup: keep highest confidence per overlapping span
        dedup(all)
    }

    /// Run secret detection with zone-aware confidence adjustment.
    /// Zones should already be annotated on the TextModel before calling this.
    pub fn detect_secrets_with_zones(&self, model: &TextModel) -> Vec<Finding> {
        let raw = self.detect_secrets_full(&model.text, false, false);
        self.zone_scorer.adjust(model, raw)
    }

    /// Full version with verbose/include_raw options + zone scoring.
    pub fn detect_secrets_with_zones_full(
        &self,
        model: &TextModel,
        verbose: bool,
        include_raw: bool,
    ) -> Vec<Finding> {
        let raw = self.detect_secrets_full(&model.text, verbose, include_raw);
        self.zone_scorer.adjust(model, raw)
    }

    /// Access the loaded configuration (useful for tests).
    pub fn config(&self) -> &SecretConfig {
        &self.config
    }
}

/// Dedup findings: sort by confidence descending, keep highest-confidence
/// finding per overlapping span.  Restore position order (ascending by start).
fn dedup(mut findings: Vec<Finding>) -> Vec<Finding> {
    // Sort by confidence descending
    findings.sort_by(|a, b| {
        b.confidence
            .partial_cmp(&a.confidence)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    let mut kept: Vec<Finding> = Vec::new();
    for f in findings {
        let overlaps = kept
            .iter()
            .any(|k| f.match_span.start < k.match_span.end && f.match_span.end > k.match_span.start);
        if !overlaps {
            kept.push(f);
        }
    }

    // Restore position order
    kept.sort_by_key(|f| f.match_span.start);
    kept
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_orchestrator_from_empty_patterns() {
        let patterns = serde_json::json!({});
        let orch = SecretOrchestrator::from_patterns(&patterns);
        assert_eq!(orch.config().min_value_length, 8);
    }

    #[test]
    fn test_orchestrator_empty_text() {
        let orch = SecretOrchestrator::from_patterns(&make_test_patterns());
        let findings = orch.detect_secrets("");
        assert!(findings.is_empty());
    }

    #[test]
    fn test_orchestrator_no_secrets() {
        let orch = SecretOrchestrator::from_patterns(&make_test_patterns());
        let text = "This is a normal sentence with no secrets at all.";
        let findings = orch.detect_secrets(text);
        assert!(findings.is_empty());
    }

    #[test]
    fn test_orchestrator_regex_finding() {
        let orch = SecretOrchestrator::from_patterns(&make_test_patterns());
        let text = "token = ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789";
        let findings = orch.detect_secrets(text);
        assert!(
            findings.iter().any(|f| f.entity_type == "API_KEY" && f.engine == "regex"),
            "expected a regex API_KEY finding, got: {:?}",
            findings
        );
    }

    #[test]
    fn test_orchestrator_kv_finding() {
        let orch = SecretOrchestrator::from_patterns(&make_test_patterns());
        let text = "password = \"realSecret!@#123\"";
        let findings = orch.detect_secrets(text);
        assert!(
            findings.iter().any(|f| f.engine == "secret_scanner"),
            "expected a secret_scanner finding, got: {:?}",
            findings
        );
    }

    #[test]
    fn test_orchestrator_pem_finding() {
        let orch = SecretOrchestrator::from_patterns(&make_test_patterns());
        let text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQ...\n-----END RSA PRIVATE KEY-----";
        let findings = orch.detect_secrets(text);
        assert!(
            findings.iter().any(|f| f.entity_type == "PRIVATE_KEY"),
            "expected a PRIVATE_KEY finding, got: {:?}",
            findings
        );
    }

    #[test]
    fn test_orchestrator_position_order() {
        let orch = SecretOrchestrator::from_patterns(&make_test_patterns());
        let text = "password = \"secret1!@#abc\" and api_key = \"secret2!@#xyz\"";
        let findings = orch.detect_secrets(text);
        // Findings should be sorted by start position (ascending)
        for i in 1..findings.len() {
            assert!(
                findings[i].match_span.start >= findings[i - 1].match_span.start,
                "findings not in position order: [{i}].start={} < [{}].start={}",
                findings[i].match_span.start,
                i - 1,
                findings[i - 1].match_span.start,
            );
        }
    }

    #[test]
    fn test_dedup_keeps_highest_confidence() {
        let f1 = types::Finding {
            entity_type: "API_KEY".to_string(),
            category: "Credential".to_string(),
            sensitivity: "CRITICAL".to_string(),
            confidence: 0.99,
            engine: "regex".to_string(),
            evidence: "test".to_string(),
            match_span: types::Match {
                value_masked: "***".to_string(),
                start: 10,
                end: 50,
                value_raw: None,
            },
            detection_type: None,
            display_name: None,
            kv: None,
        };
        let f2 = types::Finding {
            entity_type: "OPAQUE_SECRET".to_string(),
            category: "Credential".to_string(),
            sensitivity: "CRITICAL".to_string(),
            confidence: 0.70,
            engine: "secret_scanner".to_string(),
            evidence: "test".to_string(),
            match_span: types::Match {
                value_masked: "***".to_string(),
                start: 10,
                end: 50,
                value_raw: None,
            },
            detection_type: None,
            display_name: None,
            kv: None,
        };
        let result = dedup(vec![f2, f1]);
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].confidence, 0.99); // highest confidence kept
        assert_eq!(result[0].entity_type, "API_KEY");
    }

    #[test]
    fn test_dedup_non_overlapping_kept() {
        let f1 = types::Finding {
            entity_type: "API_KEY".to_string(),
            category: "Credential".to_string(),
            sensitivity: "CRITICAL".to_string(),
            confidence: 0.99,
            engine: "regex".to_string(),
            evidence: "test".to_string(),
            match_span: types::Match {
                value_masked: "***".to_string(),
                start: 0,
                end: 20,
                value_raw: None,
            },
            detection_type: None,
            display_name: None,
            kv: None,
        };
        let f2 = types::Finding {
            entity_type: "OPAQUE_SECRET".to_string(),
            category: "Credential".to_string(),
            sensitivity: "CRITICAL".to_string(),
            confidence: 0.70,
            engine: "secret_scanner".to_string(),
            evidence: "test".to_string(),
            match_span: types::Match {
                value_masked: "***".to_string(),
                start: 30,
                end: 60,
                value_raw: None,
            },
            detection_type: None,
            display_name: None,
            kv: None,
        };
        let result = dedup(vec![f2, f1]);
        assert_eq!(result.len(), 2);
        // Position order restored
        assert_eq!(result[0].match_span.start, 0);
        assert_eq!(result[1].match_span.start, 30);
    }

    #[test]
    fn test_dedup_empty() {
        let result = dedup(vec![]);
        assert!(result.is_empty());
    }

    fn make_test_patterns() -> serde_json::Value {
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
                {
                    "pattern": "password",
                    "score": 0.95,
                    "match_type": "word_boundary",
                    "tier": "definitive",
                    "subtype": "OPAQUE_SECRET"
                },
                {
                    "pattern": "api_key",
                    "score": 0.90,
                    "match_type": "word_boundary",
                    "tier": "definitive",
                    "subtype": "API_KEY"
                }
            ],
            "stopwords": [],
            "placeholder_values": ["changeme"]
        })
    }
}
