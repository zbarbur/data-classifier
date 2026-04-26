pub mod code_literals;
pub mod env;
pub mod json;

/// A key-value pair extracted from structured text, with byte offsets into the
/// original text pointing to the value content (not including surrounding quotes).
#[derive(Debug, Clone)]
pub struct KVPair {
    pub key: String,
    pub value: String,
    /// Byte offset of start of value content in original text.
    pub value_start: usize,
    /// Byte offset of end of value content in original text (exclusive).
    pub value_end: usize,
}

/// Parse key-value pairs from free text with exact byte offsets.
///
/// Tries ENV and code literal parsers (JSON flattening is used differently).
/// Deduplicates by (key, value) pair. ENV parser runs first so its entry wins
/// when both parsers match the same assignment.
pub fn parse_key_values_with_spans(text: &str) -> Vec<KVPair> {
    let mut results = Vec::new();
    results.extend(env::parse_env_with_spans(text));
    results.extend(code_literals::parse_code_literals_with_spans(text));
    dedup_pairs(&mut results);
    results
}

fn dedup_pairs(pairs: &mut Vec<KVPair>) {
    let mut seen = std::collections::HashSet::new();
    pairs.retain(|p| seen.insert((p.key.clone(), p.value.clone())));
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_env_simple() {
        let pairs = parse_key_values_with_spans("API_KEY=sk-12345");
        assert_eq!(pairs.len(), 1);
        assert_eq!(pairs[0].key, "API_KEY");
        assert_eq!(pairs[0].value, "sk-12345");
    }

    #[test]
    fn test_env_quoted() {
        let pairs = parse_key_values_with_spans("export SECRET=\"my-secret\"");
        assert_eq!(pairs.len(), 1);
        assert_eq!(pairs[0].key, "SECRET");
        assert_eq!(pairs[0].value, "my-secret");
    }

    #[test]
    fn test_code_literal() {
        let pairs = parse_key_values_with_spans("password = \"abc123\"");
        assert_eq!(pairs.len(), 1);
        assert_eq!(pairs[0].key, "password");
        assert_eq!(pairs[0].value, "abc123");
    }

    #[test]
    fn test_dedup() {
        // ENV and code_literals may both match the same pair
        let text = "TOKEN=\"secret123\"";
        let pairs = parse_key_values_with_spans(text);
        // Should be deduped to 1
        let token_pairs: Vec<_> = pairs.iter().filter(|p| p.key == "TOKEN").collect();
        assert_eq!(token_pairs.len(), 1);
    }

    #[test]
    fn test_offset_correctness() {
        let text = "export API_KEY=\"hello-world\"";
        let pairs = parse_key_values_with_spans(text);
        assert_eq!(pairs.len(), 1);
        let p = &pairs[0];
        // The value "hello-world" should be extractable from the text using offsets
        assert_eq!(&text[p.value_start..p.value_end], "hello-world");
    }

    #[test]
    fn test_multiple_lines() {
        let text = "DB_HOST=localhost\nDB_PASS=\"secret123\"\nDB_PORT=5432";
        let pairs = parse_key_values_with_spans(text);
        assert!(pairs.len() >= 3);
    }
}
