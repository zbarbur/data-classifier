pub mod config;
pub mod entropy;
pub mod parsers;
pub mod types;
pub mod validators;
pub mod fp_filters;
pub mod key_scoring;
pub mod kv_pass;
pub mod opaque_pass;
pub mod pem_pass;
pub mod regex_pass;
// pub mod pattern_matcher;

use config::SecretConfig;
use types::Finding;

/// Top-level orchestrator for secret/credential detection.
///
/// Compiles configuration once, then detects across many inputs.
pub struct SecretOrchestrator {
    config: SecretConfig,
}

impl SecretOrchestrator {
    /// Build from the top-level patterns JSON.
    pub fn from_patterns(patterns: &serde_json::Value) -> Self {
        Self {
            config: SecretConfig::from_json(patterns),
        }
    }

    /// Detect secrets in the given text. Placeholder — returns empty until
    /// sub-pipelines (regex matcher, opaque-token, KV extractor) are wired.
    pub fn detect_secrets(&self, _text: &str) -> Vec<Finding> {
        Vec::new()
    }

    /// Access the loaded configuration (useful for tests).
    pub fn config(&self) -> &SecretConfig {
        &self.config
    }
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
    fn test_detect_secrets_placeholder_returns_empty() {
        let patterns = serde_json::json!({});
        let orch = SecretOrchestrator::from_patterns(&patterns);
        let findings = orch.detect_secrets("sk-abc123def456");
        assert!(findings.is_empty());
    }
}
