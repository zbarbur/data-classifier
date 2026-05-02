use serde::{Deserialize, Serialize};

/// Configuration for the opaque-token detection sub-pipeline.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OpaqueTokenConfig {
    pub min_length: usize,
    pub max_length: usize,
    pub entropy_threshold: f64,
    pub diversity_threshold: usize,
    pub base_confidence: f64,
    pub max_confidence: f64,
    pub high_entropy_bonus: f64,
    pub high_entropy_gate: f64,
    pub length_bonus: f64,
    pub length_gate: usize,
    pub diversity_bonus_weight: f64,
}

impl Default for OpaqueTokenConfig {
    fn default() -> Self {
        Self {
            min_length: 16,
            max_length: 512,
            entropy_threshold: 0.80,
            diversity_threshold: 4,
            base_confidence: 0.30,
            max_confidence: 0.55,
            high_entropy_bonus: 0.10,
            high_entropy_gate: 0.90,
            length_bonus: 0.05,
            length_gate: 24,
            diversity_bonus_weight: 0.05,
        }
    }
}

/// Top-level configuration for the secret detection pipeline.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SecretConfig {
    pub min_value_length: usize,
    pub max_value_length: usize,
    pub definitive_multiplier: f64,
    pub strong_min_entropy_score: f64,
    pub relative_entropy_strong: f64,
    pub relative_entropy_contextual: f64,
    pub diversity_threshold: usize,
    pub evenness_weight: f64,
    pub diversity_bonus_weight: f64,
    pub prose_alpha_threshold: f64,
    pub opaque_token: OpaqueTokenConfig,
    pub anti_indicators: Vec<String>,
    pub non_secret_suffixes: Vec<String>,
    pub non_secret_allowlist: Vec<String>,
}

impl Default for SecretConfig {
    fn default() -> Self {
        Self {
            min_value_length: 8,
            max_value_length: 500,
            definitive_multiplier: 0.95,
            strong_min_entropy_score: 0.6,
            relative_entropy_strong: 0.5,
            relative_entropy_contextual: 0.7,
            diversity_threshold: 3,
            evenness_weight: 0.15,
            diversity_bonus_weight: 0.05,
            prose_alpha_threshold: 0.6,
            opaque_token: OpaqueTokenConfig::default(),
            anti_indicators: vec![
                "example".to_string(),
                "test".to_string(),
                "placeholder".to_string(),
                "changeme".to_string(),
            ],
            non_secret_suffixes: vec![
                "_address".to_string(),
                "_field".to_string(),
                "_id".to_string(),
                "_name".to_string(),
                "_type".to_string(),
                "_code".to_string(),
                "_status".to_string(),
                "_state".to_string(),
                "_mode".to_string(),
                "_format".to_string(),
                "_version".to_string(),
                "_level".to_string(),
                "_class".to_string(),
                "_category".to_string(),
                "_label".to_string(),
                "_tag".to_string(),
                "_flag".to_string(),
                "_count".to_string(),
                "_index".to_string(),
                "_path".to_string(),
                "_url".to_string(),
            ],
            non_secret_allowlist: vec![
                "session_id".to_string(),
                "auth_id".to_string(),
                "client_id".to_string(),
            ],
        }
    }
}

impl SecretConfig {
    /// Build a SecretConfig from the top-level patterns JSON.
    ///
    /// Reads values from `patterns["secret_scanner"]`, falling back to
    /// defaults for any missing or unparseable field.
    pub fn from_json(patterns: &serde_json::Value) -> Self {
        let section = &patterns["secret_scanner"];
        let mut config = SecretConfig::default();

        if let Some(v) = section.get("min_value_length").and_then(|v| v.as_u64()) {
            config.min_value_length = v as usize;
        }
        if let Some(v) = section.get("max_value_length").and_then(|v| v.as_u64()) {
            config.max_value_length = v as usize;
        }
        if let Some(v) = section.get("definitive_multiplier").and_then(|v| v.as_f64()) {
            config.definitive_multiplier = v;
        }
        if let Some(v) = section.get("strong_min_entropy_score").and_then(|v| v.as_f64()) {
            config.strong_min_entropy_score = v;
        }
        if let Some(v) = section.get("relative_entropy_strong").and_then(|v| v.as_f64()) {
            config.relative_entropy_strong = v;
        }
        if let Some(v) = section.get("relative_entropy_contextual").and_then(|v| v.as_f64()) {
            config.relative_entropy_contextual = v;
        }
        if let Some(v) = section.get("diversity_threshold").and_then(|v| v.as_u64()) {
            config.diversity_threshold = v as usize;
        }
        if let Some(v) = section.get("evenness_weight").and_then(|v| v.as_f64()) {
            config.evenness_weight = v;
        }
        if let Some(v) = section.get("diversity_bonus_weight").and_then(|v| v.as_f64()) {
            config.diversity_bonus_weight = v;
        }
        if let Some(v) = section.get("prose_alpha_threshold").and_then(|v| v.as_f64()) {
            config.prose_alpha_threshold = v;
        }

        // Opaque-token sub-config
        let opaque = &section["opaque_token"];
        if let Some(v) = opaque.get("min_length").and_then(|v| v.as_u64()) {
            config.opaque_token.min_length = v as usize;
        }
        if let Some(v) = opaque.get("max_length").and_then(|v| v.as_u64()) {
            config.opaque_token.max_length = v as usize;
        }
        if let Some(v) = opaque.get("entropy_threshold").and_then(|v| v.as_f64()) {
            config.opaque_token.entropy_threshold = v;
        }
        if let Some(v) = opaque.get("diversity_threshold").and_then(|v| v.as_u64()) {
            config.opaque_token.diversity_threshold = v as usize;
        }
        if let Some(v) = opaque.get("base_confidence").and_then(|v| v.as_f64()) {
            config.opaque_token.base_confidence = v;
        }
        if let Some(v) = opaque.get("max_confidence").and_then(|v| v.as_f64()) {
            config.opaque_token.max_confidence = v;
        }
        if let Some(v) = opaque.get("high_entropy_bonus").and_then(|v| v.as_f64()) {
            config.opaque_token.high_entropy_bonus = v;
        }
        if let Some(v) = opaque.get("high_entropy_gate").and_then(|v| v.as_f64()) {
            config.opaque_token.high_entropy_gate = v;
        }
        if let Some(v) = opaque.get("length_bonus").and_then(|v| v.as_f64()) {
            config.opaque_token.length_bonus = v;
        }
        if let Some(v) = opaque.get("length_gate").and_then(|v| v.as_u64()) {
            config.opaque_token.length_gate = v as usize;
        }
        if let Some(v) = opaque.get("diversity_bonus_weight").and_then(|v| v.as_f64()) {
            config.opaque_token.diversity_bonus_weight = v;
        }

        // Anti-indicators list
        if let Some(arr) = section.get("anti_indicators").and_then(|v| v.as_array()) {
            let items: Vec<String> = arr.iter().filter_map(|v| v.as_str().map(String::from)).collect();
            if !items.is_empty() {
                config.anti_indicators = items;
            }
        }

        // Non-secret suffixes
        if let Some(arr) = section.get("non_secret_suffixes").and_then(|v| v.as_array()) {
            let items: Vec<String> = arr.iter().filter_map(|v| v.as_str().map(String::from)).collect();
            if !items.is_empty() {
                config.non_secret_suffixes = items;
            }
        }

        // Non-secret allowlist
        if let Some(arr) = section.get("non_secret_allowlist").and_then(|v| v.as_array()) {
            let items: Vec<String> = arr.iter().filter_map(|v| v.as_str().map(String::from)).collect();
            if !items.is_empty() {
                config.non_secret_allowlist = items;
            }
        }

        config
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config_values() {
        let config = SecretConfig::default();
        assert_eq!(config.min_value_length, 8);
        assert_eq!(config.max_value_length, 500);
        assert!((config.definitive_multiplier - 0.95).abs() < 1e-10);
        assert_eq!(config.anti_indicators.len(), 4);
        assert_eq!(config.non_secret_suffixes.len(), 21);
        assert_eq!(config.non_secret_allowlist.len(), 3);

        let opaque = &config.opaque_token;
        assert_eq!(opaque.min_length, 16);
        assert_eq!(opaque.max_length, 512);
        assert!((opaque.entropy_threshold - 0.80).abs() < 1e-10);
        assert_eq!(opaque.diversity_threshold, 4);
        assert!((opaque.base_confidence - 0.30).abs() < 1e-10);
        assert!((opaque.max_confidence - 0.55).abs() < 1e-10);
    }

    #[test]
    fn test_from_json_empty() {
        let patterns = serde_json::json!({});
        let config = SecretConfig::from_json(&patterns);
        // Should fall back to all defaults
        assert_eq!(config.min_value_length, 8);
        assert_eq!(config.opaque_token.min_length, 16);
    }

    #[test]
    fn test_from_json_overrides() {
        let patterns = serde_json::json!({
            "secret_scanner": {
                "min_value_length": 12,
                "max_value_length": 1000,
                "opaque_token": {
                    "min_length": 20,
                    "entropy_threshold": 0.8
                },
                "anti_indicators": ["demo", "sample"]
            }
        });
        let config = SecretConfig::from_json(&patterns);
        assert_eq!(config.min_value_length, 12);
        assert_eq!(config.max_value_length, 1000);
        assert_eq!(config.opaque_token.min_length, 20);
        assert!((config.opaque_token.entropy_threshold - 0.8).abs() < 1e-10);
        // Non-overridden opaque fields keep defaults
        assert_eq!(config.opaque_token.max_length, 512);
        // Overridden list
        assert_eq!(config.anti_indicators, vec!["demo", "sample"]);
        // Non-overridden lists keep defaults
        assert_eq!(config.non_secret_suffixes.len(), 21);
    }
}
