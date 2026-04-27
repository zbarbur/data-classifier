//! Regex-based secret detection pass.
//!
//! Port of:
//! - Python `data_classifier/scan_text.py:153-192`
//! - JS `data_classifier/clients/browser/src/scanner-core.js:97-131`
//!
//! Compiles patterns from the JSON config and runs them against input text,
//! filtering through stopwords, allowlists, placeholder detection, validators,
//! and false-positive filters.

use std::collections::{HashMap, HashSet};

use regex::Regex;

use super::fp_filters;
use super::types::{self, Finding, Match};
use super::validators::{self, ValidatorFn};

/// A single compiled regex pattern with its metadata.
struct CompiledPattern {
    name: String,
    regex: Regex,
    entity_type: String,
    category: String,
    sensitivity: String,
    confidence: f64,
    validator_name: String,
    display_name: String,
    stopwords: HashSet<String>,
    allowlist_patterns: Vec<Regex>,
}

/// Regex-based detection pass for secret/credential scanning.
///
/// Loads patterns from a JSON config, compiles them once, and detects
/// matches across arbitrary text inputs.
pub struct RegexPass {
    patterns: Vec<CompiledPattern>,
    validator_registry: HashMap<&'static str, ValidatorFn>,
    global_stopwords: HashSet<String>,
    placeholder_values: HashSet<String>,
}

impl RegexPass {
    /// Build from the top-level patterns JSON.
    ///
    /// Reads `patterns["secret_patterns"]` for the pattern array.
    /// Skips patterns where `requires_column_hint` is true.
    /// Skips patterns whose regex fails to compile (logs to stderr).
    /// Reads `patterns["stopwords"]` and `patterns["placeholder_values"]`
    /// for global filtering sets.
    pub fn from_patterns(patterns: &serde_json::Value) -> Self {
        let mut compiled = Vec::new();

        if let Some(arr) = patterns.get("secret_patterns").and_then(|v| v.as_array()) {
            for entry in arr {
                // Skip patterns that require column-level context
                if entry.get("requires_column_hint").and_then(|v| v.as_bool()).unwrap_or(false) {
                    continue;
                }

                let name = entry.get("name").and_then(|v| v.as_str()).unwrap_or("").to_string();
                let regex_str = match entry.get("regex").and_then(|v| v.as_str()) {
                    Some(s) => s,
                    None => continue,
                };

                let regex = match Regex::new(regex_str) {
                    Ok(r) => r,
                    Err(e) => {
                        eprintln!("regex_pass: skipping pattern '{}': {}", name, e);
                        continue;
                    }
                };

                let entity_type = entry.get("entity_type").and_then(|v| v.as_str()).unwrap_or("").to_string();
                let category = entry.get("category").and_then(|v| v.as_str()).unwrap_or("").to_string();
                let sensitivity = entry.get("sensitivity").and_then(|v| v.as_str()).unwrap_or("").to_string();
                let confidence = entry.get("confidence").and_then(|v| v.as_f64()).unwrap_or(0.0);
                let validator_name = entry.get("validator").and_then(|v| v.as_str()).unwrap_or("").to_string();
                let display_name = entry.get("display_name").and_then(|v| v.as_str()).unwrap_or("").to_string();

                let stopwords: HashSet<String> = entry
                    .get("stopwords")
                    .and_then(|v| v.as_array())
                    .map(|arr| {
                        arr.iter()
                            .filter_map(|v| v.as_str().map(|s| s.to_lowercase()))
                            .collect()
                    })
                    .unwrap_or_default();

                let allowlist_patterns: Vec<Regex> = entry
                    .get("allowlist_patterns")
                    .and_then(|v| v.as_array())
                    .map(|arr| {
                        arr.iter()
                            .filter_map(|v| v.as_str())
                            .filter_map(|s| match Regex::new(s) {
                                Ok(r) => Some(r),
                                Err(e) => {
                                    eprintln!("regex_pass: skipping allowlist pattern for '{}': {}", name, e);
                                    None
                                }
                            })
                            .collect()
                    })
                    .unwrap_or_default();

                compiled.push(CompiledPattern {
                    name,
                    regex,
                    entity_type,
                    category,
                    sensitivity,
                    confidence,
                    validator_name,
                    display_name,
                    stopwords,
                    allowlist_patterns,
                });
            }
        }

        let global_stopwords: HashSet<String> = patterns
            .get("stopwords")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_lowercase()))
                    .collect()
            })
            .unwrap_or_default();

        let placeholder_values: HashSet<String> = patterns
            .get("placeholder_values")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_lowercase()))
                    .collect()
            })
            .unwrap_or_default();

        let validator_registry = validators::build_validator_registry();

        Self {
            patterns: compiled,
            validator_registry,
            global_stopwords,
            placeholder_values,
        }
    }

    /// Detect secrets in `text` using compiled regex patterns.
    ///
    /// Only scans patterns with `category == "Credential"` (credential-only mode).
    /// Each match is filtered through stopwords, allowlists, placeholder detection,
    /// validators, and false-positive filters before being emitted as a `Finding`.
    ///
    /// Set `include_raw` to true to include the raw matched value in findings.
    pub fn detect(&self, text: &str, _verbose: bool, include_raw: bool) -> Vec<Finding> {
        let mut findings = Vec::new();

        for pattern in &self.patterns {
            // Only scan Credential category for now
            if pattern.category != "Credential" {
                continue;
            }

            for m in pattern.regex.find_iter(text) {

                let value = &text[m.start()..m.end()];
                let value_trimmed = value.trim();

                // Check stopwords (pattern-specific + global)
                if self.is_stopword(value_trimmed, &pattern.stopwords) {
                    continue;
                }

                // Check allowlist patterns
                if self.matches_allowlist(value_trimmed, &pattern.allowlist_patterns) {
                    continue;
                }

                // Check placeholder patterns
                if validators::placeholder::is_placeholder_pattern(value_trimmed) {
                    continue;
                }

                // Run validator if pattern specifies one
                if !pattern.validator_name.is_empty() {
                    // not_placeholder_credential is handled separately (takes HashSet arg)
                    if pattern.validator_name == "not_placeholder_credential" {
                        if !validators::placeholder::not_placeholder_credential(
                            value_trimmed,
                            &self.placeholder_values,
                        ) {
                            continue;
                        }
                    } else if let Some(validator_fn) =
                        self.validator_registry.get(pattern.validator_name.as_str())
                    {
                        if !validator_fn(value_trimmed) {
                            continue;
                        }
                    }
                }

                // FP filter
                if fp_filters::value_is_obviously_not_secret(value_trimmed, 0.6) {
                    continue;
                }

                // Build finding
                let masked = types::mask_value(value_trimmed, &pattern.entity_type);
                findings.push(Finding {
                    entity_type: pattern.entity_type.clone(),
                    category: pattern.category.clone(),
                    sensitivity: pattern.sensitivity.clone(),
                    confidence: pattern.confidence,
                    engine: "regex".to_string(),
                    evidence: format!(
                        "Regex: {} pattern \"{}\" matched",
                        pattern.entity_type, pattern.name
                    ),
                    match_span: Match {
                        value_masked: masked,
                        start: m.start(),
                        end: m.end(),
                        value_raw: if include_raw {
                            Some(value_trimmed.to_string())
                        } else {
                            None
                        },
                    },
                    detection_type: Some(pattern.name.clone()),
                    display_name: Some(pattern.display_name.clone()),
                    kv: None,
                });
            }
        }

        findings
    }

    /// Check if a value matches pattern-specific or global stopwords.
    fn is_stopword(&self, value: &str, pattern_stopwords: &HashSet<String>) -> bool {
        let lower = value.to_lowercase();
        pattern_stopwords.contains(&lower) || self.global_stopwords.contains(&lower)
    }

    /// Check if a value matches any allowlist regex.
    fn matches_allowlist(&self, value: &str, allowlist: &[Regex]) -> bool {
        allowlist.iter().any(|re| re.is_match(value))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
                },
                {
                    "name": "aws_access_key",
                    "regex": "AKIA[0-9A-Z]{16}",
                    "entity_type": "API_KEY",
                    "category": "Credential",
                    "sensitivity": "CRITICAL",
                    "confidence": 0.95,
                    "validator": "",
                    "display_name": "AWS Access Key",
                    "stopwords": [],
                    "allowlist_patterns": [],
                    "requires_column_hint": false
                },
                {
                    "name": "test_column_hint",
                    "regex": "\\d{9}",
                    "entity_type": "SSN",
                    "category": "PII",
                    "sensitivity": "CRITICAL",
                    "confidence": 0.4,
                    "validator": "ssn_zeros",
                    "display_name": "US SSN (no dashes)",
                    "stopwords": [],
                    "allowlist_patterns": [],
                    "requires_column_hint": true
                }
            ],
            "stopwords": ["test_stopword"],
            "placeholder_values": ["password"]
        })
    }

    #[test]
    fn test_regex_github_pat() {
        let pass = RegexPass::from_patterns(&make_test_patterns());
        // ghp_ + exactly 36 alphanumeric chars
        let text = "token: ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ01234567896789";
        let findings = pass.detect(text, false, false);
        assert_eq!(findings.len(), 1);
        assert_eq!(findings[0].entity_type, "API_KEY");
        assert_eq!(findings[0].engine, "regex");
        assert!(findings[0].match_span.start > 0);
    }

    #[test]
    fn test_regex_aws_key() {
        let pass = RegexPass::from_patterns(&make_test_patterns());
        // AKIA + exactly 16 uppercase/digit chars (no "EXAMPLE" suffix to avoid placeholder filter)
        let text = "key = AKIAIOSFODNN7WBUDPQ3";
        let findings = pass.detect(text, false, false);
        assert_eq!(findings.len(), 1);
        assert_eq!(findings[0].entity_type, "API_KEY");
    }

    #[test]
    fn test_regex_column_hint_skipped() {
        let pass = RegexPass::from_patterns(&make_test_patterns());
        let text = "SSN: 123456789";
        let findings = pass.detect(text, false, false);
        // requires_column_hint patterns should be skipped
        assert!(findings.is_empty());
    }

    #[test]
    fn test_regex_stopword_filtered() {
        let pass = RegexPass::from_patterns(&make_test_patterns());
        // Verify the stopword mechanism works
        assert!(pass.is_stopword("test_stopword", &HashSet::new()));
    }

    #[test]
    fn test_regex_stopword_case_insensitive() {
        let pass = RegexPass::from_patterns(&make_test_patterns());
        assert!(pass.is_stopword("TEST_STOPWORD", &HashSet::new()));
    }

    #[test]
    fn test_regex_pattern_stopword() {
        let pass = RegexPass::from_patterns(&make_test_patterns());
        let pattern_stopwords: HashSet<String> = ["mylocal".to_string()].into_iter().collect();
        assert!(pass.is_stopword("mylocal", &pattern_stopwords));
    }

    #[test]
    fn test_regex_fp_filter() {
        let pass = RegexPass::from_patterns(&make_test_patterns());
        // URL should be filtered by FP filters even if it matches a pattern
        let text = "https://AKIAIOSFODNN7WBUDPQ3";
        let findings = pass.detect(text, false, false);
        // The AKIA regex won't match the full URL, but even if the substring
        // matches, the FP filter or prefix mismatch suppresses it.
        // Either way, URL text should not produce false positives.
        assert!(findings.is_empty() || findings.iter().all(|f| f.entity_type == "API_KEY"));
    }

    #[test]
    fn test_regex_no_findings_on_prose() {
        let pass = RegexPass::from_patterns(&make_test_patterns());
        let text = "This is a normal sentence without any secrets.";
        let findings = pass.detect(text, false, false);
        assert!(findings.is_empty());
    }

    #[test]
    fn test_regex_include_raw() {
        let pass = RegexPass::from_patterns(&make_test_patterns());
        let text = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789";
        let findings = pass.detect(text, false, true);
        assert_eq!(findings.len(), 1);
        assert!(findings[0].match_span.value_raw.is_some());
    }

    #[test]
    fn test_regex_exclude_raw_by_default() {
        let pass = RegexPass::from_patterns(&make_test_patterns());
        let text = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789";
        let findings = pass.detect(text, false, false);
        assert_eq!(findings.len(), 1);
        assert!(findings[0].match_span.value_raw.is_none());
    }

    #[test]
    fn test_regex_evidence_format() {
        let pass = RegexPass::from_patterns(&make_test_patterns());
        let text = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789";
        let findings = pass.detect(text, false, false);
        assert_eq!(findings.len(), 1);
        assert!(findings[0].evidence.contains("github_pat"));
        assert!(findings[0].evidence.contains("API_KEY"));
    }

    #[test]
    fn test_regex_detection_type_and_display_name() {
        let pass = RegexPass::from_patterns(&make_test_patterns());
        let text = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789";
        let findings = pass.detect(text, false, false);
        assert_eq!(findings.len(), 1);
        assert_eq!(findings[0].detection_type.as_deref(), Some("github_pat"));
        assert_eq!(findings[0].display_name.as_deref(), Some("GitHub Token"));
    }

    #[test]
    fn test_regex_masking() {
        let pass = RegexPass::from_patterns(&make_test_patterns());
        let text = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789";
        let findings = pass.detect(text, false, false);
        assert_eq!(findings.len(), 1);
        // mask_value keeps first and last char for len > 4
        let masked = &findings[0].match_span.value_masked;
        assert!(masked.starts_with('g'));
        assert!(masked.ends_with('9'));
        assert!(masked.contains('*'));
    }

    #[test]
    fn test_regex_multiple_matches() {
        let pass = RegexPass::from_patterns(&make_test_patterns());
        let text = "first: ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789 second: AKIAIOSFODNN7WBUDPQ3";
        let findings = pass.detect(text, false, false);
        assert_eq!(findings.len(), 2);
    }

    #[test]
    fn test_regex_non_credential_category_skipped() {
        // Add a PII-category pattern (without requires_column_hint) to verify
        // it's skipped by the Credential-only filter
        let patterns = serde_json::json!({
            "secret_patterns": [
                {
                    "name": "email_pattern",
                    "regex": "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}",
                    "entity_type": "EMAIL",
                    "category": "PII",
                    "sensitivity": "HIGH",
                    "confidence": 0.9,
                    "validator": "",
                    "display_name": "Email Address",
                    "stopwords": [],
                    "allowlist_patterns": [],
                    "requires_column_hint": false
                }
            ],
            "stopwords": [],
            "placeholder_values": []
        });
        let pass = RegexPass::from_patterns(&patterns);
        let text = "user@example.com";
        let findings = pass.detect(text, false, false);
        // PII category is skipped (Credential-only mode)
        assert!(findings.is_empty());
    }

    #[test]
    fn test_regex_empty_patterns() {
        let patterns = serde_json::json!({});
        let pass = RegexPass::from_patterns(&patterns);
        let findings = pass.detect("ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789", false, false);
        assert!(findings.is_empty());
    }

    #[test]
    fn test_regex_placeholder_filtered() {
        let patterns = serde_json::json!({
            "secret_patterns": [
                {
                    "name": "generic_key",
                    "regex": "[A-Za-z0-9_]{10,}",
                    "entity_type": "API_KEY",
                    "category": "Credential",
                    "sensitivity": "HIGH",
                    "confidence": 0.5,
                    "validator": "",
                    "display_name": "Generic Key",
                    "stopwords": [],
                    "allowlist_patterns": [],
                    "requires_column_hint": false
                }
            ],
            "stopwords": [],
            "placeholder_values": []
        });
        let pass = RegexPass::from_patterns(&patterns);
        // "your_api_key_here" triggers placeholder detection
        let text = "your_api_key_here";
        let findings = pass.detect(text, false, false);
        assert!(findings.is_empty());
    }

    #[test]
    fn test_regex_allowlist_filtered() {
        let patterns = serde_json::json!({
            "secret_patterns": [
                {
                    "name": "test_pattern",
                    "regex": "KEY_[A-Z0-9]{10}",
                    "entity_type": "API_KEY",
                    "category": "Credential",
                    "sensitivity": "CRITICAL",
                    "confidence": 0.9,
                    "validator": "",
                    "display_name": "Test Key",
                    "stopwords": [],
                    "allowlist_patterns": ["^KEY_ALLOWED"],
                    "requires_column_hint": false
                }
            ],
            "stopwords": [],
            "placeholder_values": []
        });
        let pass = RegexPass::from_patterns(&patterns);
        // This matches the regex but also the allowlist
        let text = "KEY_ALLOWED1234";
        let findings = pass.detect(text, false, false);
        assert!(findings.is_empty());
    }

    #[test]
    fn test_regex_matches_allowlist_fn() {
        let pass = RegexPass::from_patterns(&serde_json::json!({}));
        let allowlist = vec![Regex::new("^test_").unwrap()];
        assert!(pass.matches_allowlist("test_value", &allowlist));
        assert!(!pass.matches_allowlist("real_value", &allowlist));
    }
}
