//! Zone-aware confidence adjustment for secret findings.
//!
//! All rules and thresholds are loaded from JSON config, not hardcoded.
//! The ZoneScorer adjusts finding confidence based on the zone context
//! (code, config, error_output, etc.) and whether the matched value appears
//! in a literal assignment or a code expression.

use serde::Deserialize;

use crate::secret_detector::types::Finding;
use crate::text_model::TextModel;

/// A single scoring rule: maps (zone_type, value_context) to a confidence delta.
#[derive(Debug, Clone, Deserialize)]
pub struct ScoringRule {
    pub name: String,
    pub zone_type: String,
    pub value_context: String, // "literal", "expression", "any"
    pub delta: f64,            // confidence adjustment (-0.25 to +0.10)
}

/// Zone-aware confidence scorer.
///
/// Applies configurable rules to adjust finding confidence based on the zone
/// annotation of the line where the finding occurs, and whether the value
/// appears in a literal or expression context.
pub struct ZoneScorer {
    rules: Vec<ScoringRule>,
    suppression_threshold: f64, // default 0.30 — below this, finding is dropped
    max_confidence: f64,        // default 0.99
    literal_patterns: Vec<regex::Regex>,
    expression_patterns: Vec<regex::Regex>,
}

impl ZoneScorer {
    /// Build from the top-level patterns JSON.
    ///
    /// Expects an optional `zone_scoring` key with `rules`, `suppression_threshold`,
    /// `max_confidence`, and `value_context_detection` sub-keys.
    pub fn from_patterns(patterns: &serde_json::Value) -> Self {
        let zone_scoring = patterns.get("zone_scoring");

        let rules: Vec<ScoringRule> = zone_scoring
            .and_then(|zs| zs.get("rules"))
            .and_then(|r| serde_json::from_value(r.clone()).ok())
            .unwrap_or_default();

        let suppression_threshold = zone_scoring
            .and_then(|zs| zs.get("suppression_threshold"))
            .and_then(|v| v.as_f64())
            .unwrap_or(0.30);

        let max_confidence = zone_scoring
            .and_then(|zs| zs.get("max_confidence"))
            .and_then(|v| v.as_f64())
            .unwrap_or(0.99);

        let literal_patterns = compile_patterns(zone_scoring, "value_context_detection", "literal_patterns");
        let expression_patterns = compile_patterns(zone_scoring, "value_context_detection", "expression_patterns");

        Self {
            rules,
            suppression_threshold,
            max_confidence,
            literal_patterns,
            expression_patterns,
        }
    }

    /// Adjust confidence of findings based on zone context.
    ///
    /// For each finding, looks up the zone annotation on its line, detects value
    /// context (literal vs expression), finds a matching rule, and applies the
    /// delta. Findings whose adjusted confidence falls below `suppression_threshold`
    /// are dropped.
    pub fn adjust(&self, model: &TextModel, findings: Vec<Finding>) -> Vec<Finding> {
        if self.rules.is_empty() {
            return findings; // no rules = no adjustment
        }

        findings
            .into_iter()
            .filter_map(|mut f| {
                let line_idx = model.line_at_offset(f.match_span.start);
                if line_idx >= model.lines.len() {
                    return Some(f);
                }
                let line_info = &model.lines[line_idx];

                match &line_info.zone {
                    Some(ann) => {
                        let value_ctx = self.detect_value_context(&line_info.content, &f);
                        let delta = self.find_matching_delta(ann.zone_type.as_str(), &value_ctx);
                        f.confidence = (f.confidence + delta).clamp(0.0, self.max_confidence);
                        if f.confidence < self.suppression_threshold {
                            None // suppressed
                        } else {
                            Some(f)
                        }
                    }
                    None => Some(f), // no zone annotation = no adjustment
                }
            })
            .collect()
    }

    /// Find the delta from the first matching rule for the given zone_type and value_context.
    fn find_matching_delta(&self, zone_type: &str, value_context: &str) -> f64 {
        for rule in &self.rules {
            if rule.zone_type == zone_type
                && (rule.value_context == "any" || rule.value_context == value_context)
            {
                return rule.delta;
            }
        }
        0.0 // no matching rule = no adjustment
    }

    /// Detect whether a finding's line represents a literal assignment or a code expression.
    ///
    /// Checks literal patterns first (e.g. `= "..."`, `: "..."`), then expression
    /// patterns (e.g. `$VAR`, `foo.bar.baz`). Returns "unknown" if neither matches.
    fn detect_value_context(&self, line: &str, _finding: &Finding) -> String {
        // Check literal patterns first (assignment of quoted value)
        for re in &self.literal_patterns {
            if re.is_match(line) {
                return "literal".to_string();
            }
        }

        // Check expression patterns (code reference)
        for re in &self.expression_patterns {
            if re.is_match(line) {
                return "expression".to_string();
            }
        }

        "unknown".to_string()
    }
}

/// Compile regex patterns from a nested JSON path: zone_scoring[section][key].
fn compile_patterns(
    zone_scoring: Option<&serde_json::Value>,
    section: &str,
    key: &str,
) -> Vec<regex::Regex> {
    zone_scoring
        .and_then(|zs| zs.get(section))
        .and_then(|s| s.get(key))
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str())
                .filter_map(|s| regex::Regex::new(s).ok())
                .collect()
        })
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::secret_detector::types::{Finding, Match};
    use crate::text_model::{TextModel, ZoneAnnotation};
    use crate::zone_detector::ZoneType;

    fn make_finding(confidence: f64, start: usize, end: usize) -> Finding {
        Finding {
            entity_type: "API_KEY".to_string(),
            category: "Credential".to_string(),
            sensitivity: "CRITICAL".to_string(),
            confidence,
            engine: "regex".to_string(),
            evidence: "test".to_string(),
            match_span: Match {
                value_masked: "***".to_string(),
                start,
                end,
                value_raw: None,
            },
            detection_type: None,
            display_name: None,
            kv: None,
        }
    }

    fn make_scorer() -> ZoneScorer {
        ZoneScorer::from_patterns(&serde_json::json!({
            "zone_scoring": {
                "suppression_threshold": 0.30,
                "max_confidence": 0.99,
                "rules": [
                    {"name": "code_expression_suppress", "zone_type": "code", "value_context": "expression", "delta": -0.20},
                    {"name": "code_literal_boost", "zone_type": "code", "value_context": "literal", "delta": 0.05},
                    {"name": "config_boost", "zone_type": "config", "value_context": "any", "delta": 0.05},
                    {"name": "error_output_reduce", "zone_type": "error_output", "value_context": "any", "delta": -0.15}
                ],
                "value_context_detection": {
                    "literal_patterns": ["=[\\s]*[\"']", ":[\\s]*[\"']"],
                    "expression_patterns": ["^[a-zA-Z_]\\w*(?:\\.[a-zA-Z_]\\w*)+$", "^\\$[\\w{]"]
                }
            }
        }))
    }

    fn make_model_with_zone(text: &str, zone_type: ZoneType) -> TextModel {
        let mut model = TextModel::from_text(text);
        for line in &mut model.lines {
            line.zone = Some(ZoneAnnotation {
                zone_type: zone_type.clone(),
                confidence: 0.95,
                language_hint: String::new(),
                block_index: 0,
                is_literal_context: line.content.contains('"') || line.content.contains('\''),
            });
        }
        model
    }

    #[test]
    fn test_no_zone_no_change() {
        let scorer = make_scorer();
        let model = TextModel::from_text("password = \"secret\"");
        let findings = vec![make_finding(0.90, 0, 20)];
        let adjusted = scorer.adjust(&model, findings);
        assert_eq!(adjusted.len(), 1);
        assert_eq!(adjusted[0].confidence, 0.90); // unchanged
    }

    #[test]
    fn test_config_zone_boost() {
        let scorer = make_scorer();
        let model = make_model_with_zone("api_key: sk-12345", ZoneType::Config);
        let findings = vec![make_finding(0.90, 0, 17)];
        let adjusted = scorer.adjust(&model, findings);
        assert_eq!(adjusted.len(), 1);
        assert!((adjusted[0].confidence - 0.95).abs() < 0.001); // boosted by 0.05
    }

    #[test]
    fn test_error_output_reduce() {
        let scorer = make_scorer();
        let model = make_model_with_zone("Error: token abc123", ZoneType::ErrorOutput);
        let findings = vec![make_finding(0.70, 0, 19)];
        let adjusted = scorer.adjust(&model, findings);
        assert_eq!(adjusted.len(), 1);
        assert!((adjusted[0].confidence - 0.55).abs() < 0.001); // reduced by 0.15
    }

    #[test]
    fn test_error_output_suppressed() {
        let scorer = make_scorer();
        let model = make_model_with_zone("Error: token abc123", ZoneType::ErrorOutput);
        let findings = vec![make_finding(0.40, 0, 19)]; // 0.40 - 0.15 = 0.25 < 0.30
        let adjusted = scorer.adjust(&model, findings);
        assert!(adjusted.is_empty()); // suppressed below threshold
    }

    #[test]
    fn test_code_literal_boost() {
        let scorer = make_scorer();
        let model = make_model_with_zone("password = \"secret123\"", ZoneType::Code);
        let findings = vec![make_finding(0.90, 0, 22)];
        let adjusted = scorer.adjust(&model, findings);
        assert_eq!(adjusted.len(), 1);
        // Line has = "..." which matches literal pattern -> +0.05
        assert!((adjusted[0].confidence - 0.95).abs() < 0.001);
    }

    #[test]
    fn test_no_rules_passthrough() {
        let scorer = ZoneScorer::from_patterns(&serde_json::json!({}));
        let model = make_model_with_zone("test", ZoneType::Code);
        let findings = vec![make_finding(0.90, 0, 4)];
        let adjusted = scorer.adjust(&model, findings);
        assert_eq!(adjusted.len(), 1);
        assert_eq!(adjusted[0].confidence, 0.90); // no rules = no change
    }

    #[test]
    fn test_max_confidence_cap() {
        let scorer = make_scorer();
        let model = make_model_with_zone("key: \"value\"", ZoneType::Config);
        let findings = vec![make_finding(0.98, 0, 12)];
        let adjusted = scorer.adjust(&model, findings);
        assert!(adjusted[0].confidence <= 0.99); // capped at max
    }

    #[test]
    fn test_empty_findings() {
        let scorer = make_scorer();
        let model = TextModel::from_text("test");
        let adjusted = scorer.adjust(&model, vec![]);
        assert!(adjusted.is_empty());
    }

    #[test]
    fn test_code_expression_suppress() {
        let scorer = make_scorer();
        // Line is a pure dotted expression — matches expression pattern
        let model = make_model_with_zone("config.api.secret_key", ZoneType::Code);
        let findings = vec![make_finding(0.90, 0, 21)];
        let adjusted = scorer.adjust(&model, findings);
        assert_eq!(adjusted.len(), 1);
        // expression in code zone -> -0.20
        assert!((adjusted[0].confidence - 0.70).abs() < 0.001);
    }

    #[test]
    fn test_unknown_value_context_no_match() {
        let scorer = make_scorer();
        // Line doesn't match literal or expression patterns
        let model = make_model_with_zone("some random text", ZoneType::Code);
        let findings = vec![make_finding(0.90, 0, 16)];
        let adjusted = scorer.adjust(&model, findings);
        assert_eq!(adjusted.len(), 1);
        // No rule matches (code, unknown) -> no change
        assert_eq!(adjusted[0].confidence, 0.90);
    }

    #[test]
    fn test_expression_suppressed_below_threshold() {
        let scorer = make_scorer();
        let model = make_model_with_zone("config.api.secret_key", ZoneType::Code);
        // 0.45 - 0.20 = 0.25 < 0.30 threshold
        let findings = vec![make_finding(0.45, 0, 21)];
        let adjusted = scorer.adjust(&model, findings);
        assert!(adjusted.is_empty()); // suppressed
    }

    #[test]
    fn test_multiple_findings_mixed() {
        let scorer = make_scorer();
        let model = make_model_with_zone("Error: token abc123 and key def456", ZoneType::ErrorOutput);
        let findings = vec![
            make_finding(0.70, 0, 19), // 0.70 - 0.15 = 0.55 (kept)
            make_finding(0.40, 20, 34), // 0.40 - 0.15 = 0.25 (suppressed)
        ];
        let adjusted = scorer.adjust(&model, findings);
        assert_eq!(adjusted.len(), 1);
        assert!((adjusted[0].confidence - 0.55).abs() < 0.001);
    }

    #[test]
    fn test_confidence_clamp_to_zero() {
        // Build scorer with a very aggressive negative delta
        let scorer = ZoneScorer::from_patterns(&serde_json::json!({
            "zone_scoring": {
                "suppression_threshold": 0.0, // don't suppress, just clamp
                "max_confidence": 0.99,
                "rules": [
                    {"name": "extreme_reduce", "zone_type": "error_output", "value_context": "any", "delta": -0.90}
                ],
                "value_context_detection": {
                    "literal_patterns": [],
                    "expression_patterns": []
                }
            }
        }));
        let model = make_model_with_zone("Error: something", ZoneType::ErrorOutput);
        let findings = vec![make_finding(0.50, 0, 16)];
        let adjusted = scorer.adjust(&model, findings);
        assert_eq!(adjusted.len(), 1);
        // 0.50 - 0.90 = -0.40, clamped to 0.0
        assert_eq!(adjusted[0].confidence, 0.0);
    }
}
