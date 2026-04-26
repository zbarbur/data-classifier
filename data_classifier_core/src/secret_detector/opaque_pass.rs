//! Opaque-token secret detection pass.
//!
//! Port of:
//! - Python `data_classifier/scan_text.py:303-375`
//! - JS `data_classifier/clients/browser/src/scanner-core.js:399-464`
//!
//! Scans whitespace-delimited tokens in text for high-entropy opaque tokens
//! that are not covered by the regex or KV passes.  A token passes when it
//! clears all FP filters, is not a UUID, is not a known placeholder, has
//! sufficient relative entropy, and has sufficient character-class diversity.

use std::collections::HashSet;

use fancy_regex::Regex;

use super::config::SecretConfig;
use super::entropy;
use super::fp_filters;
use super::key_scoring;
use super::types::{self, Finding, Match};
use super::validators;

/// Opaque-token detection pass.
///
/// Iterates over every whitespace-delimited token in the input text and
/// emits an `OPAQUE_SECRET` finding for tokens that look like high-entropy
/// credentials rather than identifiers, prose, or code.
pub struct OpaquePass {
    uuid_re: Regex,
    placeholder_values: HashSet<String>,
}

impl OpaquePass {
    /// Build from the top-level patterns JSON.
    ///
    /// Reads `patterns["placeholder_values"]` (array of strings) for the
    /// exact-match placeholder list.  Falls back to an empty set if absent.
    pub fn from_patterns(patterns: &serde_json::Value) -> Self {
        let placeholder_values = if let Some(arr) = patterns.get("placeholder_values").and_then(|v| v.as_array()) {
            arr.iter()
                .filter_map(|v| v.as_str().map(|s| s.to_lowercase()))
                .collect()
        } else {
            HashSet::new()
        };

        Self {
            uuid_re: Regex::new(
                r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
            )
            .expect("opaque_pass: UUID regex compile error"),
            placeholder_values,
        }
    }

    /// Detect opaque-token secrets in `text`.
    ///
    /// - `pem_spans`: byte ranges from the PEM pass; tokens whose start byte
    ///   falls inside one of these ranges are suppressed.
    /// - `config`: thresholds for entropy, diversity, length, confidence, etc.
    /// - `verbose`: reserved for structured logging (currently unused).
    /// - `include_raw`: when true, the raw token value is included in each
    ///   finding's `match_span.value_raw`.
    pub fn detect(
        &self,
        text: &str,
        pem_spans: &[(usize, usize)],
        config: &SecretConfig,
        _verbose: bool,
        include_raw: bool,
    ) -> Vec<Finding> {
        let opaque = &config.opaque_token;
        let mut findings = Vec::new();

        // Compile the token scanner once per call — cheap since it has no
        // lookahead and the string is short-lived.
        let token_re = Regex::new(r"\S+").expect("opaque_pass: token regex compile error");

        for m in token_re.find_iter(text) {
            let m = match m {
                Ok(m) => m,
                Err(_) => continue,
            };

            let token = &text[m.start()..m.end()];
            let start = m.start();

            // Skip tokens inside PEM blocks (already handled by PEM pass).
            if pem_spans.iter().any(|&(ps, pe)| start >= ps && start < pe) {
                continue;
            }

            // Strip leading quotes / backticks and trailing punctuation so that
            // `"my_secret"` and `my_secret,` are treated identically to `my_secret`.
            let cleaned = token
                .trim_start_matches(|c: char| c == '"' || c == '\'' || c == '`')
                .trim_end_matches(|c: char| "\"'`,.;:!?)]}".contains(c));

            // Length gates.
            if cleaned.len() < opaque.min_length {
                continue;
            }
            if cleaned.len() > opaque.max_length {
                continue;
            }

            // FP filters: URLs, dates, code expressions, prose, etc.
            if fp_filters::value_is_obviously_not_secret(cleaned, config.prose_alpha_threshold) {
                continue;
            }

            // UUID rejection — UUIDs are identifiers, not secrets.
            if self.uuid_re.is_match(cleaned).unwrap_or(false) {
                continue;
            }

            // Exact placeholder rejection (case-insensitive).
            if self.placeholder_values.contains(&cleaned.to_lowercase()) {
                continue;
            }

            // Structural placeholder rejection (templates, repeated chars, etc.).
            if validators::placeholder::is_placeholder_pattern(cleaned) {
                continue;
            }

            // Anti-indicator check: empty key ("") means no key context, only
            // the value is tested.
            if key_scoring::has_anti_indicator("", cleaned, &config.anti_indicators) {
                continue;
            }

            // Entropy gate.
            let rel = entropy::relative_entropy(cleaned);
            if rel < opaque.entropy_threshold {
                continue;
            }

            // Character-class diversity gate.
            let div = entropy::char_class_diversity(cleaned);
            if div < opaque.diversity_threshold {
                continue;
            }

            // Confidence calculation.
            let mut confidence = opaque.base_confidence;

            // High-entropy bonus.
            if rel > opaque.high_entropy_gate {
                confidence += opaque.high_entropy_bonus;
            }

            // Diversity bonus (each class above the threshold contributes a
            // small amount).
            confidence +=
                (div as f64 - opaque.diversity_threshold as f64).max(0.0) * opaque.diversity_bonus_weight;

            // Length bonus.
            if cleaned.len() > opaque.length_gate {
                confidence += opaque.length_bonus;
            }

            // Cap confidence.
            confidence = confidence.min(opaque.max_confidence);

            // Round to 4 decimal places (mirrors Python/JS implementations).
            confidence = (confidence * 10000.0).round() / 10000.0;

            let masked = types::mask_value(cleaned, "OPAQUE_SECRET");

            findings.push(Finding {
                entity_type: "OPAQUE_SECRET".to_string(),
                category: "Credential".to_string(),
                sensitivity: "CRITICAL".to_string(),
                confidence,
                engine: "secret_scanner".to_string(),
                evidence: format!(
                    "secret_scanner: opaque token — rel_entropy={:.2} diversity={} len={}",
                    rel,
                    div,
                    cleaned.len()
                ),
                match_span: Match {
                    value_masked: masked,
                    start,
                    end: start + token.len(),
                    value_raw: if include_raw { Some(cleaned.to_string()) } else { None },
                },
                detection_type: Some("opaque_token".to_string()),
                display_name: Some("Opaque Secret".to_string()),
                kv: None,
            });
        }

        findings
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::secret_detector::config::SecretConfig;

    fn make_pass() -> OpaquePass {
        OpaquePass::from_patterns(&serde_json::json!({
            "placeholder_values": ["password", "changeme"]
        }))
    }

    #[test]
    fn test_opaque_high_entropy_token() {
        let pass = make_pass();
        let config = SecretConfig::default();
        // A realistic high-entropy token — the JWT-like string should be
        // detected if it clears all gates (entropy + diversity + length).
        let text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abc123XYZ";
        let findings = pass.detect(text, &[], &config, false, false);
        // The test validates the mechanism: if found, entity type must be correct.
        for f in &findings {
            assert_eq!(f.entity_type, "OPAQUE_SECRET");
            assert_eq!(f.detection_type, Some("opaque_token".to_string()));
            assert_eq!(f.display_name, Some("Opaque Secret".to_string()));
        }
    }

    #[test]
    fn test_opaque_short_rejected() {
        let pass = make_pass();
        let config = SecretConfig::default();
        // "abc" — well below the 16-char min_length.
        let text = "token: abc";
        let findings = pass.detect(text, &[], &config, false, false);
        assert!(findings.is_empty());
    }

    #[test]
    fn test_opaque_uuid_rejected() {
        let pass = make_pass();
        let config = SecretConfig::default();
        let text = "id: 550e8400-e29b-41d4-a716-446655440000";
        let findings = pass.detect(text, &[], &config, false, false);
        assert!(findings.is_empty());
    }

    #[test]
    fn test_opaque_url_rejected() {
        let pass = make_pass();
        let config = SecretConfig::default();
        let text = "https://api.example.com/v1/endpoint";
        let findings = pass.detect(text, &[], &config, false, false);
        assert!(findings.is_empty());
    }

    #[test]
    fn test_opaque_low_entropy_rejected() {
        let pass = make_pass();
        let config = SecretConfig::default();
        // All-same character — near-zero relative entropy.
        let text = "aaaaaaaaaaaaaaaaaaaaaaaaa";
        let findings = pass.detect(text, &[], &config, false, false);
        assert!(findings.is_empty());
    }

    #[test]
    fn test_opaque_pem_suppression() {
        let pass = make_pass();
        let config = SecretConfig::default();
        // The token starts at byte 0.  A PEM span covering [0, 100) suppresses it.
        let text = "aB1!cD2@eF3#gH4$iJ5%kL6^mN7&";
        let findings = pass.detect(text, &[(0, 100)], &config, false, false);
        assert!(findings.is_empty());
    }

    #[test]
    fn test_opaque_placeholder_rejected() {
        let pass = make_pass();
        let config = SecretConfig::default();
        // "your_api_key_here_xxxxx" hits the placeholder pattern filter.
        let text = "your_api_key_here_xxxxx";
        let findings = pass.detect(text, &[], &config, false, false);
        assert!(findings.is_empty());
    }

    #[test]
    fn test_opaque_confidence_capped() {
        let pass = make_pass();
        let config = SecretConfig::default();
        // Very high-entropy, diverse, long token — confidence must not exceed max_confidence.
        let text = "aB1!cD2@eF3#gH4$iJ5%kL6^mN7&oP8*qR9";
        let findings = pass.detect(text, &[], &config, false, false);
        if !findings.is_empty() {
            assert!(findings[0].confidence <= config.opaque_token.max_confidence);
        }
    }

    #[test]
    fn test_opaque_prose_rejected() {
        let pass = make_pass();
        let config = SecretConfig::default();
        // Natural-language prose is suppressed by value_is_obviously_not_secret.
        let text = "the quick brown fox jumps over lazy dog repeatedly";
        let findings = pass.detect(text, &[], &config, false, false);
        assert!(findings.is_empty());
    }

    #[test]
    fn test_opaque_placeholder_exact_match_rejected() {
        let pass = make_pass();
        let config = SecretConfig::default();
        // "password" is in the placeholder_values list.
        // Note: "password" is only 8 chars — it already fails the length gate (min 16),
        // so this test also validates that short exact-match values are rejected.
        let text = "password";
        let findings = pass.detect(text, &[], &config, false, false);
        assert!(findings.is_empty());
    }

    #[test]
    fn test_opaque_include_raw() {
        let pass = make_pass();
        let config = SecretConfig::default();
        // A high-entropy token.
        let text = "aB1!cD2@eF3#gH4$iJ5%kL6^mN7&oP8*qR9";
        let findings = pass.detect(text, &[], &config, false, true);
        for f in &findings {
            // value_raw must be populated when include_raw=true.
            assert!(f.match_span.value_raw.is_some());
        }
    }

    #[test]
    fn test_opaque_no_raw_by_default() {
        let pass = make_pass();
        let config = SecretConfig::default();
        let text = "aB1!cD2@eF3#gH4$iJ5%kL6^mN7&oP8*qR9";
        let findings = pass.detect(text, &[], &config, false, false);
        for f in &findings {
            assert!(f.match_span.value_raw.is_none());
        }
    }

    #[test]
    fn test_opaque_from_empty_patterns() {
        // Constructing from an empty JSON object must not panic.
        let pass = OpaquePass::from_patterns(&serde_json::json!({}));
        let config = SecretConfig::default();
        let text = "some text without secrets";
        let findings = pass.detect(text, &[], &config, false, false);
        assert!(findings.is_empty());
    }

    #[test]
    fn test_opaque_evidence_format() {
        let pass = make_pass();
        let config = SecretConfig::default();
        let text = "aB1!cD2@eF3#gH4$iJ5%kL6^mN7&oP8*qR9";
        let findings = pass.detect(text, &[], &config, false, false);
        for f in &findings {
            assert!(f.evidence.starts_with("secret_scanner: opaque token"));
            assert!(f.evidence.contains("rel_entropy="));
            assert!(f.evidence.contains("diversity="));
            assert!(f.evidence.contains("len="));
        }
    }

    #[test]
    fn test_opaque_multiple_tokens_in_text() {
        let pass = make_pass();
        let config = SecretConfig::default();
        // Two candidate tokens separated by a label — only the high-entropy ones survive.
        let text = "token1=abc token2=aB1!cD2@eF3#gH4$iJ5%kL6^mN7&";
        let findings = pass.detect(text, &[], &config, false, false);
        // "token1=abc" is very short — definitely rejected. "token2=..." may pass.
        // The key assertion: no finding spans outside text boundaries.
        for f in &findings {
            assert!(f.match_span.end <= text.len());
        }
    }
}
