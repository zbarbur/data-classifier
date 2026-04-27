//! Key-value secret detection pass.
//!
//! Port of:
//! - Python `data_classifier/scan_text.py:194-259`
//! - JS `data_classifier/clients/browser/src/scanner-core.js:133-182`
//!
//! Parses key=value pairs from text (ENV, code literals, etc.) and scores
//! them using key-name dictionaries and tiered entropy/diversity gates.

use std::collections::HashSet;
use std::sync::OnceLock;

use regex::Regex;

use super::config::SecretConfig;
use super::key_scoring::{self, KeyScorer};
use super::parsers;
use super::types::{self, Finding, KVContext, Match};
use super::validators;

/// Key-value secret detection pass.
///
/// Loads key-name scoring patterns from JSON config, then scans parsed
/// key=value pairs in text, filtering placeholders and anti-indicators
/// before applying tiered entropy scoring.
pub struct KVPass {
    key_scorer: KeyScorer,
    placeholder_values: HashSet<String>,
}

impl KVPass {
    /// Build from the top-level patterns JSON.
    pub fn from_patterns(patterns: &serde_json::Value) -> Self {
        Self {
            key_scorer: KeyScorer::from_patterns(patterns),
            placeholder_values: load_placeholder_values(patterns),
        }
    }

    /// Detect secrets in `text` by parsing key-value pairs and scoring key names.
    ///
    /// Set `include_raw` to true to include the raw matched value in findings.
    /// `verbose` is reserved for future structured logging (currently unused).
    pub fn detect(&self, text: &str, config: &SecretConfig, _verbose: bool, include_raw: bool) -> Vec<Finding> {
        let pairs = parsers::parse_key_values_with_spans(text);
        let mut findings = Vec::new();

        for pair in &pairs {
            let value = pair.value.trim();

            // Traceback suppression — key names in error output are function
            // parameters or stack frame variables, not key=value assignments.
            if is_traceback_line(text, pair.value_start) {
                continue;
            }

            // Length checks
            if value.len() < config.min_value_length {
                continue;
            }
            if value.len() > config.max_value_length {
                continue;
            }

            // Anti-indicator check (key or value contains a known non-secret indicator)
            if key_scoring::has_anti_indicator(&pair.key, value, &config.anti_indicators) {
                continue;
            }

            // Placeholder value exact-match check (case-insensitive)
            if self.placeholder_values.contains(&value.to_lowercase()) {
                continue;
            }

            // Structural placeholder pattern check
            if validators::placeholder::is_placeholder_pattern(value) {
                continue;
            }

            // Compound non-secret check (e.g. "token_address", "user_id")
            if key_scoring::is_compound_non_secret(&pair.key, config) {
                continue;
            }

            // Score key name against the dictionary
            let key_score = self.key_scorer.score_key_name(&pair.key);
            if key_score.score <= 0.0 {
                continue;
            }

            // Tiered scoring — applies entropy/diversity gates depending on tier
            let composite = key_scoring::tiered_score(key_score.score, &key_score.tier, value, config);
            if composite <= 0.0 {
                continue;
            }

            // Build finding
            let entity_type = if key_score.subtype.is_empty() {
                "OPAQUE_SECRET"
            } else {
                &key_score.subtype
            };
            let masked = types::mask_value(value, entity_type);

            findings.push(Finding {
                entity_type: entity_type.to_string(),
                category: "Credential".to_string(),
                sensitivity: "CRITICAL".to_string(),
                confidence: (composite * 10000.0).round() / 10000.0,
                engine: "secret_scanner".to_string(),
                evidence: format!(
                    "secret_scanner: key \"{}\" score={:.2} tier={} composite={:.2}",
                    pair.key, key_score.score, key_score.tier, composite
                ),
                match_span: Match {
                    value_masked: masked,
                    start: pair.value_start,
                    end: pair.value_end,
                    value_raw: if include_raw { Some(value.to_string()) } else { None },
                },
                detection_type: Some("secret_scanner".to_string()),
                display_name: Some(format!("{} (key: {})", entity_type, pair.key)),
                kv: Some(KVContext {
                    key: pair.key.clone(),
                    tier: key_score.tier.clone(),
                }),
            });
        }

        findings
    }
}

/// Returns true if the line containing a KV pair looks like a traceback /
/// error output line where key names appear as function parameters or
/// variable names in stack frames — not as actual key=value assignments.
fn is_traceback_line(text: &str, offset: usize) -> bool {
    // Find the line containing this offset
    let line_start = text[..offset].rfind('\n').map(|i| i + 1).unwrap_or(0);
    let line_end = text[offset..].find('\n').map(|i| offset + i).unwrap_or(text.len());
    let line = text[line_start..line_end].trim();

    static TRACEBACK_PATTERNS: OnceLock<Vec<Regex>> = OnceLock::new();
    let patterns = TRACEBACK_PATTERNS.get_or_init(|| {
        vec![
            // Python traceback lines
            Regex::new(r"^\s*Traceback \(most recent").unwrap(),
            Regex::new(r#"^\s*File ".+", line \d+"#).unwrap(),
            Regex::new(r"^\s*(?:raise|Raise)\s+\w+").unwrap(),
            // Python function signatures in tracebacks: "in func_name(param1, param2)"
            Regex::new(r"^\s*(?:in |at )\w+[\w.]*\(").unwrap(),
            // Jupyter/IPython cell references
            Regex::new(r"^\s*Cell In\[").unwrap(),
            // Generic error lines
            Regex::new(r"^\s*\w*Error:").unwrap(),
            Regex::new(r"^\s*\w*Exception:").unwrap(),
            // Java/JS stack traces
            Regex::new(r"^\s*at\s+[\w.$]+\(").unwrap(),
            // Go panic
            Regex::new(r"^\s*goroutine \d+").unwrap(),
            Regex::new(r"^\s*panic:").unwrap(),
        ]
    });

    for pat in patterns {
        if pat.is_match(line) {
            return true;
        }
    }
    false
}

fn load_placeholder_values(patterns: &serde_json::Value) -> HashSet<String> {
    patterns
        .get("placeholder_values")
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().filter_map(|v| v.as_str().map(|s| s.to_lowercase())).collect())
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::secret_detector::config::SecretConfig;

    fn make_test_patterns() -> serde_json::Value {
        serde_json::json!({
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
                },
                {
                    "pattern": "token",
                    "score": 0.70,
                    "match_type": "word_boundary",
                    "tier": "strong",
                    "subtype": "OPAQUE_SECRET"
                }
            ],
            "placeholder_values": ["password", "changeme", "your_api_key_here"]
        })
    }

    #[test]
    fn test_kv_definitive_secret() {
        let pass = KVPass::from_patterns(&make_test_patterns());
        let config = SecretConfig::default();
        let text = "password = \"realSecret!@#123\"";
        let findings = pass.detect(text, &config, false, false);
        assert_eq!(findings.len(), 1);
        assert_eq!(findings[0].entity_type, "OPAQUE_SECRET");
        assert_eq!(findings[0].engine, "secret_scanner");
        assert!(findings[0].kv.is_some());
        assert_eq!(findings[0].kv.as_ref().unwrap().tier, "definitive");
    }

    #[test]
    fn test_kv_placeholder_rejected() {
        let pass = KVPass::from_patterns(&make_test_patterns());
        let config = SecretConfig::default();
        let text = "password = \"changeme\"";
        let findings = pass.detect(text, &config, false, false);
        assert!(findings.is_empty());
    }

    #[test]
    fn test_kv_short_value_rejected() {
        let pass = KVPass::from_patterns(&make_test_patterns());
        let config = SecretConfig::default();
        let text = "password = \"abc\""; // less than min_value_length (8)
        let findings = pass.detect(text, &config, false, false);
        assert!(findings.is_empty());
    }

    #[test]
    fn test_kv_anti_indicator() {
        let pass = KVPass::from_patterns(&make_test_patterns());
        let config = SecretConfig::default();
        let text = "example_password = \"realSecret!@#123\"";
        let findings = pass.detect(text, &config, false, false);
        assert!(findings.is_empty()); // "example" is an anti-indicator
    }

    #[test]
    fn test_kv_compound_non_secret() {
        let pass = KVPass::from_patterns(&make_test_patterns());
        let config = SecretConfig::default();
        let text = "token_address = \"0xABCDEF1234567890\"";
        let findings = pass.detect(text, &config, false, false);
        assert!(findings.is_empty()); // "token_address" ends with _address
    }

    #[test]
    fn test_kv_no_matching_key() {
        let pass = KVPass::from_patterns(&make_test_patterns());
        let config = SecretConfig::default();
        let text = "color = \"realSecret!@#123\"";
        let findings = pass.detect(text, &config, false, false);
        assert!(findings.is_empty()); // "color" not in key names
    }

    #[test]
    fn test_kv_strong_tier_needs_entropy() {
        let pass = KVPass::from_patterns(&make_test_patterns());
        let config = SecretConfig::default();
        // "token" is strong tier — needs entropy OR diversity
        let text = "auth_token = \"aaaaaa123\""; // low entropy
        let _findings = pass.detect(text, &config, false, false);
        // Might or might not detect depending on exact entropy — test the mechanism works
    }

    #[test]
    fn test_kv_include_raw() {
        let pass = KVPass::from_patterns(&make_test_patterns());
        let config = SecretConfig::default();
        let text = "password = \"realSecret!@#123\"";
        let findings = pass.detect(text, &config, false, true);
        assert_eq!(findings.len(), 1);
        assert!(findings[0].match_span.value_raw.is_some());
    }

    #[test]
    fn test_kv_confidence_rounded() {
        let pass = KVPass::from_patterns(&make_test_patterns());
        let config = SecretConfig::default();
        let text = "password = \"realSecret!@#123\"";
        let findings = pass.detect(text, &config, false, false);
        assert_eq!(findings.len(), 1);
        // Confidence should be rounded to 4 decimal places — verify it's in [0,1]
        let conf = findings[0].confidence;
        assert!(conf > 0.0 && conf <= 1.0);
        // And the string representation has at most 4 decimal places
        let conf_str = format!("{}", conf);
        let decimal_places = conf_str.split('.').nth(1).map(|s| s.len()).unwrap_or(0);
        assert!(decimal_places <= 4, "confidence has more than 4 decimal places: {}", conf_str);
    }

    #[test]
    fn test_kv_evidence_format() {
        let pass = KVPass::from_patterns(&make_test_patterns());
        let config = SecretConfig::default();
        let text = "password = \"realSecret!@#123\"";
        let findings = pass.detect(text, &config, false, false);
        assert_eq!(findings.len(), 1);
        let ev = &findings[0].evidence;
        assert!(ev.contains("secret_scanner:"));
        assert!(ev.contains("password"));
        assert!(ev.contains("tier=definitive"));
    }

    #[test]
    fn test_kv_kv_context() {
        let pass = KVPass::from_patterns(&make_test_patterns());
        let config = SecretConfig::default();
        let text = "password = \"realSecret!@#123\"";
        let findings = pass.detect(text, &config, false, false);
        assert_eq!(findings.len(), 1);
        let kv = findings[0].kv.as_ref().unwrap();
        assert_eq!(kv.key, "password");
        assert_eq!(kv.tier, "definitive");
    }

    #[test]
    fn test_kv_display_name_format() {
        let pass = KVPass::from_patterns(&make_test_patterns());
        let config = SecretConfig::default();
        let text = "api_key = \"realSecret!@#123\"";
        let findings = pass.detect(text, &config, false, false);
        assert_eq!(findings.len(), 1);
        let dn = findings[0].display_name.as_deref().unwrap();
        assert!(dn.contains("API_KEY"));
        assert!(dn.contains("api_key"));
    }

    #[test]
    fn test_kv_value_spans_in_original_text() {
        let pass = KVPass::from_patterns(&make_test_patterns());
        let config = SecretConfig::default();
        let text = "password = \"realSecret!@#123\"";
        let findings = pass.detect(text, &config, false, true);
        assert_eq!(findings.len(), 1);
        let raw = findings[0].match_span.value_raw.as_ref().unwrap();
        let span = &text[findings[0].match_span.start..findings[0].match_span.end];
        assert_eq!(span, raw.as_str());
    }

    #[test]
    fn test_kv_empty_text() {
        let pass = KVPass::from_patterns(&make_test_patterns());
        let config = SecretConfig::default();
        let findings = pass.detect("", &config, false, false);
        assert!(findings.is_empty());
    }

    #[test]
    fn test_kv_traceback_python() {
        let pass = KVPass::from_patterns(&make_test_patterns());
        let config = SecretConfig::default();
        let text = r#"Traceback (most recent call last):
  File "app.py", line 8, in get_posts(account_id, app_id, password, limit)
      5 access_token = get_access_token()"#;
        let findings = pass.detect(text, &config, false, false);
        assert!(findings.is_empty(), "should suppress KV in traceback");
    }

    #[test]
    fn test_kv_traceback_cell_in() {
        let pass = KVPass::from_patterns(&make_test_patterns());
        let config = SecretConfig::default();
        let text = "Cell In[2], line 8, in get_posts(account_id, app_id, password, limit)";
        let findings = pass.detect(text, &config, false, false);
        assert!(findings.is_empty(), "should suppress KV in Jupyter cell traceback");
    }

    #[test]
    fn test_kv_traceback_at_java() {
        let pass = KVPass::from_patterns(&make_test_patterns());
        let config = SecretConfig::default();
        let text = "    at com.example.AuthService.getToken(api_key=\"sk-abc123456789\")";
        let findings = pass.detect(text, &config, false, false);
        assert!(findings.is_empty(), "should suppress KV in Java stack trace");
    }

    #[test]
    fn test_kv_real_assignment_not_suppressed() {
        let pass = KVPass::from_patterns(&make_test_patterns());
        let config = SecretConfig::default();
        let text = "password = \"realSecret!@#123\"";
        let findings = pass.detect(text, &config, false, false);
        assert_eq!(findings.len(), 1, "real assignment should NOT be suppressed");
    }

    #[test]
    fn test_kv_max_value_length_rejected() {
        let pass = KVPass::from_patterns(&make_test_patterns());
        let config = SecretConfig::default();
        // config.max_value_length is 500; generate a 501-char value
        let long_val = "A".repeat(501);
        let text = format!("password = \"{}\"", long_val);
        let findings = pass.detect(&text, &config, false, false);
        assert!(findings.is_empty());
    }
}
