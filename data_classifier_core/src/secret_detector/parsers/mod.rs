pub mod code_literals;
pub mod connection_str;
pub mod env;
pub mod json;
pub mod toml;
pub mod url_query;
pub mod yaml;

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

/// URL-decode a percent-encoded string.
///
/// - `%XX` sequences are converted to the corresponding byte (ASCII only).
/// - `+` is converted to a space (application/x-www-form-urlencoded).
/// - Invalid `%` sequences (truncated or non-hex) are passed through as-is.
pub fn url_decode(input: &str) -> String {
    let mut result = String::with_capacity(input.len());
    let mut bytes = input.bytes().peekable();
    while let Some(b) = bytes.next() {
        if b == b'%' {
            // Try to read two hex digits
            match (bytes.next(), bytes.next()) {
                (Some(h1), Some(h2)) => {
                    let hex = format!("{}{}", h1 as char, h2 as char);
                    match u8::from_str_radix(&hex, 16) {
                        Ok(byte) => result.push(byte as char),
                        Err(_) => {
                            // Not valid hex — pass through literally
                            result.push('%');
                            result.push(h1 as char);
                            result.push(h2 as char);
                        }
                    }
                }
                (Some(h1), None) => {
                    result.push('%');
                    result.push(h1 as char);
                }
                _ => {
                    result.push('%');
                }
            }
        } else if b == b'+' {
            result.push(' ');
        } else {
            result.push(b as char);
        }
    }
    result
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

    #[test]
    fn test_url_decode_percent() {
        assert_eq!(url_decode("hello%20world"), "hello world");
        assert_eq!(url_decode("p%40ss"), "p@ss");
    }

    #[test]
    fn test_url_decode_plus() {
        assert_eq!(url_decode("hello+world"), "hello world");
    }

    #[test]
    fn test_url_decode_invalid_percent() {
        // Truncated — pass through literally
        assert_eq!(url_decode("hello%"), "hello%");
        assert_eq!(url_decode("hello%2"), "hello%2");
    }

    #[test]
    fn test_url_decode_no_encoding() {
        assert_eq!(url_decode("plaintext"), "plaintext");
    }
}
