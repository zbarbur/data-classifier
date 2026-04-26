use super::types::Finding;

/// Redact secrets in text using the specified strategy.
/// Strategies: "type-label", "asterisk", "placeholder", "none".
pub fn redact(text: &str, findings: &[Finding], strategy: &str) -> String {
    if strategy == "none" || findings.is_empty() {
        return text.to_string();
    }

    // Sort findings right-to-left by start position (descending)
    // This ensures earlier offsets remain valid as we modify the string
    let mut sorted: Vec<&Finding> = findings.iter().collect();
    sorted.sort_by(|a, b| b.match_span.start.cmp(&a.match_span.start));

    let mut result = text.to_string();
    let mut left_bound = usize::MAX;

    for finding in &sorted {
        let start = finding.match_span.start;
        let end = finding.match_span.end;

        // Skip overlapping replacements
        if end > left_bound {
            continue;
        }
        if start >= result.len() || end > result.len() {
            continue;
        }

        let replacement = match strategy {
            "type-label" => format!("[REDACTED:{}]", finding.entity_type),
            "asterisk" => "*".repeat(end - start),
            "placeholder" => "«secret»".to_string(),
            _ => continue, // unknown strategy = skip
        };

        result = format!("{}{}{}", &result[..start], replacement, &result[end..]);
        left_bound = start;
    }

    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::secret_detector::types::{Finding, Match};

    fn make_finding(entity_type: &str, start: usize, end: usize) -> Finding {
        Finding {
            entity_type: entity_type.to_string(),
            category: "Credential".to_string(),
            sensitivity: "CRITICAL".to_string(),
            confidence: 0.95,
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

    #[test]
    fn test_redact_type_label() {
        let text = "key = sk-proj-abc123def456";
        let findings = vec![make_finding("API_KEY", 6, 26)];
        let result = redact(text, &findings, "type-label");
        assert_eq!(result, "key = [REDACTED:API_KEY]");
    }

    #[test]
    fn test_redact_asterisk() {
        let text = "key = secret123";
        let findings = vec![make_finding("API_KEY", 6, 15)];
        let result = redact(text, &findings, "asterisk");
        assert_eq!(result, "key = *********");
    }

    #[test]
    fn test_redact_placeholder() {
        let text = "key = secret123";
        let findings = vec![make_finding("API_KEY", 6, 15)];
        let result = redact(text, &findings, "placeholder");
        assert_eq!(result, "key = «secret»");
    }

    #[test]
    fn test_redact_none() {
        let text = "key = secret123";
        let findings = vec![make_finding("API_KEY", 6, 15)];
        let result = redact(text, &findings, "none");
        assert_eq!(result, text);
    }

    #[test]
    fn test_redact_multiple() {
        let text = "a = secret1 b = secret2";
        let findings = vec![
            make_finding("API_KEY", 4, 11),
            make_finding("API_KEY", 16, 23),
        ];
        let result = redact(text, &findings, "type-label");
        assert_eq!(result, "a = [REDACTED:API_KEY] b = [REDACTED:API_KEY]");
    }

    #[test]
    fn test_redact_empty_findings() {
        let text = "no secrets here";
        let result = redact(text, &[], "type-label");
        assert_eq!(result, text);
    }

    #[test]
    fn test_redact_overlapping_skipped() {
        let text = "overlapping_secret_value";
        let findings = vec![
            make_finding("TYPE_A", 0, 18), // wider span
            make_finding("TYPE_B", 5, 15), // overlapping narrower span
        ];
        let result = redact(text, &findings, "type-label");
        // Only the wider (first processed = rightmost start, which is TYPE_B at 5..15)
        // Actually right-to-left: TYPE_A starts at 0, TYPE_B starts at 5
        // Sorted descending by start: TYPE_B (5) first, then TYPE_A (0)
        // TYPE_B replaces 5..15, left_bound=5
        // TYPE_A: end=18 > left_bound=5, so skipped
        // Result: "overl[REDACTED:TYPE_B]_value"
        assert!(result.contains("[REDACTED:TYPE_B]"));
    }
}
