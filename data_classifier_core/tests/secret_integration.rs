// data_classifier_core/tests/secret_integration.rs
//
// Integration tests for the SecretOrchestrator full pipeline.
// Uses representative patterns covering each detection pass.

use data_classifier_core::secret_detector::redaction;
use data_classifier_core::secret_detector::SecretOrchestrator;

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
            }
        ],
        "secret_key_names": [
            {"pattern": "password", "score": 0.95, "match_type": "word_boundary", "tier": "definitive", "subtype": "OPAQUE_SECRET"},
            {"pattern": "api_key", "score": 0.90, "match_type": "word_boundary", "tier": "definitive", "subtype": "API_KEY"},
            {"pattern": "secret", "score": 0.85, "match_type": "word_boundary", "tier": "definitive", "subtype": "OPAQUE_SECRET"},
            {"pattern": "token", "score": 0.70, "match_type": "word_boundary", "tier": "strong", "subtype": "OPAQUE_SECRET"}
        ],
        "stopwords": [],
        "placeholder_values": ["password", "changeme", "your_api_key_here"]
    })
}

// === Regex pass tests ===

#[test]
fn test_github_pat_detected() {
    let orch = SecretOrchestrator::from_patterns(&make_patterns());
    let text = "export GITHUB_TOKEN=ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789";
    let findings = orch.detect_secrets(text);
    assert_eq!(findings.len(), 1);
    assert_eq!(findings[0].entity_type, "API_KEY");
    assert_eq!(findings[0].engine, "regex");
    assert!(findings[0].confidence > 0.95);
    // Verify span points to the actual token
    assert_eq!(
        &text[findings[0].match_span.start..findings[0].match_span.end],
        "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"
    );
}

#[test]
fn test_aws_key_detected() {
    let orch = SecretOrchestrator::from_patterns(&make_patterns());
    // Use a value that does not end in "EXAMPLE" (placeholder suffix rule)
    let text = "aws_access_key_id = AKIAIOSFODNN7WBUDPQ3";
    let findings = orch.detect_secrets(text);
    assert!(
        findings.iter().any(|f| f.entity_type == "API_KEY" && f.engine == "regex"),
        "expected a regex API_KEY finding, got: {:?}",
        findings
    );
}

// === KV pass tests ===

#[test]
fn test_kv_password_detected() {
    let orch = SecretOrchestrator::from_patterns(&make_patterns());
    let text = "db_password = \"S3cureP@ss!xyz\"";
    let findings = orch.detect_secrets(text);
    assert!(
        findings.iter().any(|f| f.engine == "secret_scanner" && f.entity_type == "OPAQUE_SECRET"),
        "expected a secret_scanner OPAQUE_SECRET finding, got: {:?}",
        findings
    );
}

#[test]
fn test_kv_env_secret() {
    let orch = SecretOrchestrator::from_patterns(&make_patterns());
    let text = "export SECRET_KEY=\"aB1!cD2@eF3#gH4$\"";
    let findings = orch.detect_secrets(text);
    assert!(!findings.is_empty(), "expected at least one finding, got none");
}

// === PEM pass tests ===

#[test]
fn test_pem_private_key() {
    let orch = SecretOrchestrator::from_patterns(&make_patterns());
    let text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA1234...\n-----END RSA PRIVATE KEY-----";
    let findings = orch.detect_secrets(text);
    assert_eq!(
        findings.len(),
        1,
        "expected exactly 1 PRIVATE_KEY finding, got: {:?}",
        findings
    );
    assert_eq!(findings[0].entity_type, "PRIVATE_KEY");
    assert!(
        (findings[0].confidence - 0.95).abs() < 1e-10,
        "expected confidence 0.95, got {}",
        findings[0].confidence
    );
}

#[test]
fn test_pem_public_key_ignored() {
    let orch = SecretOrchestrator::from_patterns(&make_patterns());
    let text = "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkq...\n-----END PUBLIC KEY-----";
    let findings = orch.detect_secrets(text);
    assert!(
        findings.is_empty(),
        "expected no findings for PUBLIC KEY, got: {:?}",
        findings
    );
}

// === Placeholder suppression ===

#[test]
fn test_placeholder_filtered() {
    let orch = SecretOrchestrator::from_patterns(&make_patterns());
    // "YOUR_API_KEY_HERE" matches the "your_*_key" placeholder pattern
    let text = "export API_KEY=YOUR_API_KEY_HERE";
    let findings = orch.detect_secrets(text);
    assert!(
        findings.is_empty(),
        "expected no findings for placeholder value, got: {:?}",
        findings
    );
}

#[test]
fn test_repeated_char_placeholder() {
    let orch = SecretOrchestrator::from_patterns(&make_patterns());
    // 36 'a's after "ghp_" — the repeated-char placeholder pattern fires (8+ identical chars)
    let text = "export GITHUB_TOKEN=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    let findings = orch.detect_secrets(text);
    assert!(
        findings.is_empty(),
        "expected no findings for all-repeated-char token, got: {:?}",
        findings
    );
}

// === FP suppression ===

#[test]
fn test_url_not_detected() {
    let orch = SecretOrchestrator::from_patterns(&make_patterns());
    // URL values are suppressed by the FP filter
    let text = "homepage = \"https://api.example.com/v2/endpoint\"";
    let findings = orch.detect_secrets(text);
    assert!(
        findings.is_empty(),
        "expected no findings for URL value, got: {:?}",
        findings
    );
}

#[test]
fn test_prose_not_detected() {
    let orch = SecretOrchestrator::from_patterns(&make_patterns());
    // Prose text with no key=value structure
    let text = "This is a normal paragraph about password security best practices.";
    let findings = orch.detect_secrets(text);
    assert!(
        findings.is_empty(),
        "expected no findings in prose text, got: {:?}",
        findings
    );
}

// === Dedup ===

#[test]
fn test_dedup_same_span() {
    let orch = SecretOrchestrator::from_patterns(&make_patterns());
    // A GitHub PAT inside a key="value" assignment might match both regex and KV pass;
    // dedup must ensure no findings share the same start position.
    let text = "api_key = \"ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789\"";
    let findings = orch.detect_secrets(text);
    let mut starts: Vec<usize> = findings.iter().map(|f| f.match_span.start).collect();
    starts.dedup();
    assert_eq!(
        starts.len(),
        findings.len(),
        "duplicate start positions after dedup: {:?}",
        findings
    );
}

// === Redaction integration ===

#[test]
fn test_redaction_integration() {
    let orch = SecretOrchestrator::from_patterns(&make_patterns());
    let text = "export GITHUB_TOKEN=ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789";
    let findings = orch.detect_secrets(text);
    assert!(!findings.is_empty(), "expected a finding before redaction test");
    let redacted = redaction::redact(text, &findings, "type-label");
    assert!(
        redacted.contains("[REDACTED:API_KEY]"),
        "expected [REDACTED:API_KEY] in output, got: {}",
        redacted
    );
    assert!(
        !redacted.contains("ghp_"),
        "raw token must not appear in redacted output, got: {}",
        redacted
    );
}

// === Multi-finding ordering ===

#[test]
fn test_multiple_findings_ordered() {
    let orch = SecretOrchestrator::from_patterns(&make_patterns());
    let text =
        "db_password = \"S3cureP@ss!xyz\"\napi_key = \"ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789\"";
    let findings = orch.detect_secrets(text);
    assert!(!findings.is_empty(), "expected at least one finding");
    // Verify ascending start order
    for i in 1..findings.len() {
        assert!(
            findings[i].match_span.start >= findings[i - 1].match_span.start,
            "findings not in ascending start order at index {}: [{i}].start={} < [{}].start={}",
            i,
            findings[i].match_span.start,
            i - 1,
            findings[i - 1].match_span.start
        );
    }
}
