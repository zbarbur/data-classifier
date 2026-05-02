use std::collections::HashSet;
use std::sync::OnceLock;

use super::types::{Finding, Match};

static PEM_RE: OnceLock<fancy_regex::Regex> = OnceLock::new();

fn pem_regex() -> &'static fancy_regex::Regex {
    PEM_RE.get_or_init(|| {
        fancy_regex::Regex::new(r"-----BEGIN\s+([\w\s]+?)-----[\s\S]*?-----END\s+\1-----").unwrap()
    })
}

static PRIVATE_LABELS: OnceLock<HashSet<&'static str>> = OnceLock::new();

fn private_labels() -> &'static HashSet<&'static str> {
    PRIVATE_LABELS.get_or_init(|| {
        [
            "PRIVATE KEY",
            "RSA PRIVATE KEY",
            "EC PRIVATE KEY",
            "DSA PRIVATE KEY",
            "ENCRYPTED PRIVATE KEY",
            "OPENSSH PRIVATE KEY",
            "PGP PRIVATE KEY BLOCK",
        ]
        .into_iter()
        .collect()
    })
}

/// Result of running PEM block detection on a text input.
pub struct PemResult {
    /// Byte ranges of ALL PEM blocks (for opaque pass suppression).
    pub spans: Vec<(usize, usize)>,
    /// Findings for PRIVATE KEY blocks only.
    pub findings: Vec<Finding>,
}

/// Detect PEM blocks in the given text.
///
/// All PEM blocks (public keys, certificates, private keys, etc.) are recorded
/// in `spans` so downstream passes can suppress overlapping detections.
/// Only private key blocks produce `findings`.
pub fn detect_pem_blocks(text: &str) -> PemResult {
    let re = pem_regex();
    let labels = private_labels();
    let mut spans = Vec::new();
    let mut findings = Vec::new();

    for m in re.find_iter(text) {
        let m = match m {
            Ok(m) => m,
            Err(_) => continue,
        };
        let matched = &text[m.start()..m.end()];
        spans.push((m.start(), m.end()));

        // Re-run captures on the matched substring to extract group 1 (the label).
        if let Ok(Some(caps)) = re.captures(matched) {
            if let Some(label_match) = caps.get(1) {
                let label = label_match.as_str().trim().to_uppercase();
                if !labels.contains(label.as_str()) {
                    continue;
                }

                findings.push(Finding {
                    entity_type: "PRIVATE_KEY".to_string(),
                    category: "Credential".to_string(),
                    sensitivity: "CRITICAL".to_string(),
                    confidence: 0.95,
                    engine: "secret_scanner".to_string(),
                    evidence: format!("secret_scanner: PEM block — {}", label),
                    match_span: Match {
                        value_masked: format!("-----BEGIN {}-----...", label),
                        start: m.start(),
                        end: m.end(),
                        value_raw: None,
                    },
                    detection_type: Some("pem_block".to_string()),
                    display_name: Some("Private Key".to_string()),
                    kv: None,
                });
            }
        }
    }

    PemResult { spans, findings }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_pem_private_key() {
        let text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQ...\n-----END RSA PRIVATE KEY-----";
        let result = detect_pem_blocks(text);
        assert_eq!(result.findings.len(), 1);
        assert_eq!(result.findings[0].entity_type, "PRIVATE_KEY");
        assert_eq!(result.findings[0].confidence, 0.95);
        assert_eq!(result.spans.len(), 1);
    }

    #[test]
    fn test_pem_public_key_no_finding() {
        let text = "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkq...\n-----END PUBLIC KEY-----";
        let result = detect_pem_blocks(text);
        assert!(result.findings.is_empty()); // public keys not reported
        assert_eq!(result.spans.len(), 1); // but span still tracked for suppression
    }

    #[test]
    fn test_pem_certificate_no_finding() {
        let text = "-----BEGIN CERTIFICATE-----\nMIIDXTCCAkWgAw...\n-----END CERTIFICATE-----";
        let result = detect_pem_blocks(text);
        assert!(result.findings.is_empty());
        assert_eq!(result.spans.len(), 1);
    }

    #[test]
    fn test_pem_multiple_blocks() {
        let text = "-----BEGIN RSA PRIVATE KEY-----\nkey1\n-----END RSA PRIVATE KEY-----\nsome text\n-----BEGIN CERTIFICATE-----\ncert\n-----END CERTIFICATE-----";
        let result = detect_pem_blocks(text);
        assert_eq!(result.findings.len(), 1); // only private key
        assert_eq!(result.spans.len(), 2); // both blocks tracked
    }

    #[test]
    fn test_pem_openssh() {
        let text = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1r...\n-----END OPENSSH PRIVATE KEY-----";
        let result = detect_pem_blocks(text);
        assert_eq!(result.findings.len(), 1);
        assert!(result.findings[0].evidence.contains("OPENSSH PRIVATE KEY"));
    }

    #[test]
    fn test_pem_ec_private_key() {
        let text = "-----BEGIN EC PRIVATE KEY-----\nMHQCAQEE...\n-----END EC PRIVATE KEY-----";
        let result = detect_pem_blocks(text);
        assert_eq!(result.findings.len(), 1);
    }

    #[test]
    fn test_pem_no_blocks() {
        let result = detect_pem_blocks("just some regular text");
        assert!(result.findings.is_empty());
        assert!(result.spans.is_empty());
    }

    #[test]
    fn test_pem_span_covers_full_block() {
        let prefix = "before ";
        let block = "-----BEGIN RSA PRIVATE KEY-----\nkey\n-----END RSA PRIVATE KEY-----";
        let text = format!("{}{} after", prefix, block);
        let result = detect_pem_blocks(&text);
        assert_eq!(result.spans.len(), 1);
        let (start, end) = result.spans[0];
        assert_eq!(start, prefix.len());
        assert_eq!(&text[start..end], block);
    }
}
