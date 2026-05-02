//! Key-name scoring for secret/credential detection.
//!
//! Port of Python `data_classifier/engines/secret_scanner.py`:
//! - `_camel_to_snake`        (line 631-637)
//! - `_match_key_pattern`     (line 607-623)
//! - `_score_key_name`        (line 640-672)
//! - `_compute_tiered_score`  (line 1025-1080)
//! - `_is_compound_non_secret`(line 300-305)
//! - `_has_anti_indicator`    (line 1082-1100)

use std::sync::OnceLock;

use regex::Regex;

use crate::secret_detector::{config::SecretConfig, entropy, fp_filters};

// ---------------------------------------------------------------------------
// Public return type
// ---------------------------------------------------------------------------

/// The result of scoring a key name against the dictionary.
#[derive(Debug, Clone, PartialEq)]
pub struct KeyScore {
    pub score: f64,
    pub tier: String,
    pub subtype: String,
}

// ---------------------------------------------------------------------------
// KeyEntry — one row from the secret_key_names array
// ---------------------------------------------------------------------------

/// A single entry loaded from `patterns["secret_key_names"]`.
pub struct KeyEntry {
    pub pattern: String,
    pub score: f64,
    pub match_type: String, // "substring" | "word_boundary" | "suffix"
    pub tier: String,
    pub subtype: String,
    compiled_re: Option<Regex>,
}

impl KeyEntry {
    fn new(pattern: String, score: f64, match_type: String, tier: String, subtype: String) -> Self {
        // Pre-compile regex for word_boundary and suffix match types.
        let compiled_re = match match_type.as_str() {
            "word_boundary" => {
                let pat = format!(r"(^|[_\-\s.]){}($|[_\-\s.])", regex::escape(&pattern));
                Regex::new(&pat).ok()
            }
            "suffix" => {
                let pat = format!(r"[_\-\s.]{}$", regex::escape(&pattern));
                Regex::new(&pat).ok()
            }
            _ => None,
        };
        Self {
            pattern,
            score,
            match_type,
            tier,
            subtype,
            compiled_re,
        }
    }
}

// ---------------------------------------------------------------------------
// KeyScorer
// ---------------------------------------------------------------------------

/// Scores key names against a dictionary of secret-bearing key patterns.
pub struct KeyScorer {
    entries: Vec<KeyEntry>,
}

impl KeyScorer {
    /// Build from the top-level patterns JSON.
    ///
    /// Reads entries from `patterns["secret_key_names"]` array.  Each entry
    /// must have `pattern`, `score`, `match_type`, `tier`, and `subtype` fields.
    pub fn from_patterns(patterns: &serde_json::Value) -> Self {
        let mut entries = Vec::new();
        if let Some(arr) = patterns.get("secret_key_names").and_then(|v| v.as_array()) {
            for item in arr {
                let pattern = item.get("pattern").and_then(|v| v.as_str()).unwrap_or("").to_string();
                let score = item.get("score").and_then(|v| v.as_f64()).unwrap_or(0.0);
                let match_type = item
                    .get("match_type")
                    .and_then(|v| v.as_str())
                    .unwrap_or("substring")
                    .to_string();
                let tier = item.get("tier").and_then(|v| v.as_str()).unwrap_or("").to_string();
                let subtype = item
                    .get("subtype")
                    .and_then(|v| v.as_str())
                    .unwrap_or("OPAQUE_SECRET")
                    .to_string();

                if !pattern.is_empty() {
                    entries.push(KeyEntry::new(pattern, score, match_type, tier, subtype));
                }
            }
        }
        Self { entries }
    }

    /// Score a key name, returning the best matching `KeyScore`.
    ///
    /// Converts the key to snake_case first so that camelCase names like
    /// `privateKey` match the `private_key` dictionary entry.
    pub fn score_key_name(&self, key: &str) -> KeyScore {
        score_key_name_with_entries(key, &self.entries)
    }
}

// ---------------------------------------------------------------------------
// camel_to_snake
// ---------------------------------------------------------------------------

/// Convert camelCase to snake_case.
///
/// Mirrors the JS one-liner:
/// ```text
/// .replace(/([a-z0-9])([A-Z])/g, '$1_$2').toLowerCase()
/// ```
/// so "apiKey" → "api_key", "HTMLParser" → "htmlparser" (consecutive caps
/// are not split beyond the lowercase/digit→uppercase boundary).
pub fn camel_to_snake(name: &str) -> String {
    // Pre-compile lazily using OnceLock.
    static RE: OnceLock<Regex> = OnceLock::new();
    let re = RE.get_or_init(|| Regex::new(r"([a-z0-9])([A-Z])").expect("camel_to_snake regex"));

    re.replace_all(name, "${1}_${2}").to_lowercase()
}

// ---------------------------------------------------------------------------
// match_key_pattern (internal helper)
// ---------------------------------------------------------------------------

fn match_key_pattern(key_lower: &str, entry: &KeyEntry) -> bool {
    match entry.match_type.as_str() {
        "word_boundary" | "suffix" => {
            if let Some(re) = &entry.compiled_re {
                re.is_match(key_lower)
            } else {
                // Fallback: substring if compile failed
                key_lower.contains(&entry.pattern)
            }
        }
        // Default: substring
        _ => key_lower.contains(&entry.pattern),
    }
}

// ---------------------------------------------------------------------------
// score_key_name (free function operating on a slice of entries)
// ---------------------------------------------------------------------------

/// Score a key name against a slice of `KeyEntry`s.
///
/// Returns the entry with the highest score.  Ties are broken by iteration
/// order (first highest wins).  Returns `KeyScore { score: 0.0, tier: "",
/// subtype: "OPAQUE_SECRET" }` when no entry matches.
fn score_key_name_with_entries(key: &str, entries: &[KeyEntry]) -> KeyScore {
    let key_lower = camel_to_snake(key);

    let mut best_score = 0.0_f64;
    let mut best_tier = String::new();
    let mut best_subtype = "OPAQUE_SECRET".to_string();

    for entry in entries {
        if entry.score > best_score && match_key_pattern(&key_lower, entry) {
            best_score = entry.score;
            best_tier = entry.tier.clone();
            best_subtype = entry.subtype.clone();
        }
    }

    KeyScore {
        score: best_score,
        tier: best_tier,
        subtype: best_subtype,
    }
}

// ---------------------------------------------------------------------------
// is_compound_non_secret
// ---------------------------------------------------------------------------

/// Return `true` if `key` is a compound name that typically does NOT hold a
/// secret (e.g. `token_address`, `user_id`).
///
/// Port of Python `_is_compound_non_secret` (secret_scanner.py:300-305).
pub fn is_compound_non_secret(key: &str, config: &SecretConfig) -> bool {
    let lower = key.to_lowercase();
    let lower = lower.trim();

    // Explicit allowlist takes priority — these names ARE sensitive even though
    // they end with a "non-secret" suffix.
    if config.non_secret_allowlist.iter().any(|s| s.as_str() == lower) {
        return false;
    }

    // If the key ends with any of the non-secret suffixes, it's not a secret.
    config.non_secret_suffixes.iter().any(|suffix| lower.ends_with(suffix.as_str()))
}

// ---------------------------------------------------------------------------
// tiered_score
// ---------------------------------------------------------------------------

/// Compute a composite confidence score based on the tier of the key-name
/// match and the entropy/diversity of the value.
///
/// Port of Python `_compute_tiered_score` (secret_scanner.py:1025-1080).
///
/// - **definitive**: value must pass the obvious-not-secret filter; score =
///   `key_score × definitive_multiplier`.
/// - **strong**: relative entropy OR diversity must clear a threshold; entropy
///   and evenness bonuses are added.
/// - **contextual**: both relative entropy AND diversity must clear their
///   thresholds; same bonus formula.
pub fn tiered_score(key_score: f64, tier: &str, value: &str, config: &SecretConfig) -> f64 {
    // Pre-filter: reject values that are obviously not credentials regardless
    // of tier (URLs, dates, code expressions, prose, etc.).
    if fp_filters::value_is_obviously_not_secret(value, config.prose_alpha_threshold) {
        return 0.0;
    }

    match tier {
        "definitive" => key_score * config.definitive_multiplier,

        "strong" => {
            let rel = entropy::relative_entropy(value);
            let div = entropy::char_class_diversity(value);
            if rel >= config.relative_entropy_strong || div >= config.diversity_threshold {
                let base = key_score * f64::max(config.strong_min_entropy_score, entropy::score_relative_entropy(rel));
                let evenness_bonus = entropy::char_class_evenness(value) * config.evenness_weight;
                let diversity_bonus =
                    f64::max(0.0, (div as f64) - (config.diversity_threshold as f64)) * config.diversity_bonus_weight;
                f64::min(1.0, base + evenness_bonus + diversity_bonus)
            } else {
                0.0
            }
        }

        // contextual tier — needs both relative entropy AND diversity
        _ => {
            let rel = entropy::relative_entropy(value);
            let div = entropy::char_class_diversity(value);
            if rel >= config.relative_entropy_contextual && div >= config.diversity_threshold {
                let base = key_score * entropy::score_relative_entropy(rel);
                let evenness_bonus = entropy::char_class_evenness(value) * config.evenness_weight;
                let diversity_bonus =
                    f64::max(0.0, (div as f64) - (config.diversity_threshold as f64)) * config.diversity_bonus_weight;
                f64::min(1.0, base + evenness_bonus + diversity_bonus)
            } else {
                0.0
            }
        }
    }
}

// ---------------------------------------------------------------------------
// has_anti_indicator
// ---------------------------------------------------------------------------

/// Return `true` if `key` or `value` contains any of the anti-indicator
/// substrings (case-insensitive).
///
/// Port of Python `_has_anti_indicator` (secret_scanner.py:1082-1100).
pub fn has_anti_indicator(key: &str, value: &str, anti_indicators: &[String]) -> bool {
    let key_lower = key.to_lowercase();
    let value_lower = value.to_lowercase();
    for indicator in anti_indicators {
        let ind_lower = indicator.to_lowercase();
        if key_lower.contains(&ind_lower) || value_lower.contains(&ind_lower) {
            return true;
        }
    }
    false
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::secret_detector::config::SecretConfig;

    // ---- camel_to_snake ----

    #[test]
    fn test_camel_to_snake_basic() {
        assert_eq!(camel_to_snake("apiKey"), "api_key");
    }

    #[test]
    fn test_camel_to_snake_already() {
        assert_eq!(camel_to_snake("api_key"), "api_key");
    }

    #[test]
    fn test_camel_to_snake_multi() {
        assert_eq!(camel_to_snake("myApiKeyName"), "my_api_key_name");
    }

    #[test]
    fn test_camel_to_snake_empty() {
        assert_eq!(camel_to_snake(""), "");
    }

    // ---- is_compound_non_secret ----

    #[test]
    fn test_compound_non_secret_suffix() {
        let config = SecretConfig::default();
        assert!(is_compound_non_secret("token_address", &config));
    }

    #[test]
    fn test_compound_allowlist() {
        let config = SecretConfig::default();
        // session_id is in the allowlist — should return false (IS sensitive)
        assert!(!is_compound_non_secret("session_id", &config));
    }

    #[test]
    fn test_compound_no_match() {
        let config = SecretConfig::default();
        // "password" does not end with any non-secret suffix
        assert!(!is_compound_non_secret("password", &config));
    }

    // ---- has_anti_indicator ----

    #[test]
    fn test_anti_indicator_key() {
        assert!(has_anti_indicator("example_key", "value", &["example".into()]));
    }

    #[test]
    fn test_anti_indicator_value() {
        assert!(has_anti_indicator("key", "test_value", &["test".into()]));
    }

    #[test]
    fn test_anti_indicator_none() {
        assert!(!has_anti_indicator("password", "real_secret", &["example".into()]));
    }

    // ---- tiered_score ----

    #[test]
    fn test_tiered_definitive() {
        let config = SecretConfig::default();
        // "realSecret!@#123" is high entropy + special chars — should pass fp filter
        let score = tiered_score(0.95, "definitive", "realSecret!@#123", &config);
        // definitive = key_score * definitive_multiplier = 0.95 * 0.95 = 0.9025
        assert!((score - 0.95 * 0.95).abs() < 0.01);
    }

    #[test]
    fn test_tiered_strong_low_entropy() {
        let config = SecretConfig::default();
        // "aaaaaa" is all-same-char: near-zero entropy AND diversity=1, both fail gate
        let score = tiered_score(0.80, "strong", "aaaaaa", &config);
        assert_eq!(score, 0.0);
    }

    #[test]
    fn test_tiered_contextual_needs_both() {
        let config = SecretConfig::default();
        // "abcdefghij" is pure lowercase: diversity=1 (<3 threshold) → fails contextual gate
        let score = tiered_score(0.60, "contextual", "abcdefghij", &config);
        assert_eq!(score, 0.0);
    }

    #[test]
    fn test_tiered_obvious_not_secret() {
        let config = SecretConfig::default();
        // URL is obviously not a secret → returns 0.0 regardless of tier
        let score = tiered_score(0.95, "definitive", "https://example.com", &config);
        assert_eq!(score, 0.0);
    }

    // ---- KeyScorer ----

    /// Build a minimal inline patterns JSON for testing KeyScorer.
    fn test_patterns() -> serde_json::Value {
        serde_json::json!({
            "secret_key_names": [
                {
                    "pattern": "api_key",
                    "score": 0.95,
                    "match_type": "word_boundary",
                    "tier": "definitive",
                    "subtype": "API_KEY"
                },
                {
                    "pattern": "password",
                    "score": 0.90,
                    "match_type": "substring",
                    "tier": "strong",
                    "subtype": "PASSWORD_HASH"
                },
                {
                    "pattern": "secret",
                    "score": 0.85,
                    "match_type": "substring",
                    "tier": "strong",
                    "subtype": "OPAQUE_SECRET"
                },
                {
                    "pattern": "private_key",
                    "score": 0.98,
                    "match_type": "suffix",
                    "tier": "definitive",
                    "subtype": "PRIVATE_KEY"
                }
            ]
        })
    }

    #[test]
    fn test_key_scorer_word_boundary_match() {
        let scorer = KeyScorer::from_patterns(&test_patterns());
        let result = scorer.score_key_name("api_key");
        assert!((result.score - 0.95).abs() < 0.001);
        assert_eq!(result.tier, "definitive");
        assert_eq!(result.subtype, "API_KEY");
    }

    #[test]
    fn test_key_scorer_camelcase_normalized() {
        // "apiKey" → "api_key" after camel_to_snake, should match word_boundary entry
        let scorer = KeyScorer::from_patterns(&test_patterns());
        let result = scorer.score_key_name("apiKey");
        assert!((result.score - 0.95).abs() < 0.001);
        assert_eq!(result.subtype, "API_KEY");
    }

    #[test]
    fn test_key_scorer_substring_match() {
        let scorer = KeyScorer::from_patterns(&test_patterns());
        let result = scorer.score_key_name("db_password");
        assert!((result.score - 0.90).abs() < 0.001);
        assert_eq!(result.subtype, "PASSWORD_HASH");
    }

    #[test]
    fn test_key_scorer_suffix_match() {
        let scorer = KeyScorer::from_patterns(&test_patterns());
        // "rsa_private_key" ends with "_private_key" → matches suffix entry
        let result = scorer.score_key_name("rsa_private_key");
        assert!((result.score - 0.98).abs() < 0.001);
        assert_eq!(result.subtype, "PRIVATE_KEY");
    }

    #[test]
    fn test_key_scorer_no_match() {
        let scorer = KeyScorer::from_patterns(&test_patterns());
        let result = scorer.score_key_name("user_name");
        assert_eq!(result.score, 0.0);
        assert_eq!(result.tier, "");
        assert_eq!(result.subtype, "OPAQUE_SECRET");
    }

    #[test]
    fn test_key_scorer_best_score_wins() {
        // "password_secret" should match both "password" (0.90) and "secret" (0.85)
        // → best score is 0.90
        let scorer = KeyScorer::from_patterns(&test_patterns());
        let result = scorer.score_key_name("password_secret");
        assert!((result.score - 0.90).abs() < 0.001);
        assert_eq!(result.subtype, "PASSWORD_HASH");
    }

    #[test]
    fn test_key_scorer_empty_patterns() {
        let patterns = serde_json::json!({});
        let scorer = KeyScorer::from_patterns(&patterns);
        let result = scorer.score_key_name("api_key");
        assert_eq!(result.score, 0.0);
    }

    #[test]
    fn test_tiered_strong_high_entropy_passes() {
        let config = SecretConfig::default();
        // "Xk9$mR2!pL5#nQ7" has high entropy + 4 char classes → strong gate passes
        let score = tiered_score(0.80, "strong", "Xk9$mR2!pL5#nQ7", &config);
        assert!(score > 0.0, "strong tier with high entropy/diversity should score > 0");
    }

    #[test]
    fn test_tiered_contextual_high_entropy_passes() {
        let config = SecretConfig::default();
        // This value has 4 char classes (upper+lower+digit+special) and enough unique
        // chars to push relative_entropy above the contextual threshold (0.7).
        // 32 highly-varied chars → Shannon entropy ≈ 5.0, charset "full" max ≈ 6.57,
        // relative ≈ 0.76 > 0.70.  diversity = 4 >= 3.
        let score = tiered_score(0.60, "contextual", "aB3!cD4@eF5#gH6$iJ7%kL8^mN9&oP0*", &config);
        assert!(score > 0.0, "contextual tier with high entropy and diversity should score > 0");
    }
}
