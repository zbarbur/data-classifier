use std::sync::OnceLock;

use fancy_regex::Regex;

use super::KVPair;

/// Regex for code-style string literal assignments.
///
/// Matches:
///   - `key = "value"` / `key = 'value'`
///   - `key := "value"` / `key := 'value'`
///   - `key: "value"` / `key: 'value'`
///
/// Groups: 1=key, 2=double-quoted value, 3=single-quoted value.
/// Value length is capped at 500 characters to avoid catastrophic backtracking
/// and to skip multi-line strings that are unlikely secrets.
static CODE_RE: OnceLock<Regex> = OnceLock::new();

fn code_regex() -> &'static Regex {
    CODE_RE.get_or_init(|| {
        Regex::new(r#"([A-Za-z_][A-Za-z0-9_]*)\s*(?::=|:|=)\s*(?:"([^"]{1,500})"|'([^']{1,500})')"#)
            .expect("CODE_RE must compile")
    })
}

/// Parse key = "value" and key: "value" assignments in code.
///
/// Byte offsets point to the value content in the original text (inside quotes).
pub fn parse_code_literals_with_spans(text: &str) -> Vec<KVPair> {
    let re = code_regex();
    let mut results = Vec::new();

    for m in re.find_iter(text).flatten() {
        if let Ok(Some(caps)) = re.captures(&text[m.start()..]) {
            let key = match caps.get(1) {
                Some(g) => &text[m.start() + g.start()..m.start() + g.end()],
                None => continue,
            };

            let (value, value_start, value_end) = if let Some(g) = caps.get(2) {
                // Double-quoted: opening '"' is at g.start() - 1 relative to match start.
                let abs_quote_open = m.start() + g.start() - 1;
                let abs_value_start = abs_quote_open + 1;
                let abs_value_end = abs_value_start + (g.end() - g.start());
                let val = &text[abs_value_start..abs_value_end];
                (val, abs_value_start, abs_value_end)
            } else if let Some(g) = caps.get(3) {
                // Single-quoted
                let abs_quote_open = m.start() + g.start() - 1;
                let abs_value_start = abs_quote_open + 1;
                let abs_value_end = abs_value_start + (g.end() - g.start());
                let val = &text[abs_value_start..abs_value_end];
                (val, abs_value_start, abs_value_end)
            } else {
                continue;
            };

            if value.is_empty() {
                continue;
            }

            debug_assert_eq!(
                &text[value_start..value_end],
                value,
                "code_literals offset mismatch on match: {:?}",
                &text[m.start()..m.end()]
            );

            results.push(KVPair {
                key: key.to_string(),
                value: value.to_string(),
                value_start,
                value_end,
            });
        }
    }

    results
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_code_equals() {
        let pairs = parse_code_literals_with_spans("password = \"abc123\"");
        assert_eq!(pairs.len(), 1);
        assert_eq!(pairs[0].key, "password");
        assert_eq!(pairs[0].value, "abc123");
    }

    #[test]
    fn test_code_colon() {
        let pairs = parse_code_literals_with_spans("secret: 'mypass'");
        assert_eq!(pairs.len(), 1);
        assert_eq!(pairs[0].value, "mypass");
    }

    #[test]
    fn test_code_walrus() {
        let pairs = parse_code_literals_with_spans("token := \"xyz\"");
        assert_eq!(pairs.len(), 1);
        assert_eq!(pairs[0].value, "xyz");
    }

    #[test]
    fn test_code_offset() {
        let text = "api_key = \"hello\"";
        let pairs = parse_code_literals_with_spans(text);
        assert_eq!(pairs.len(), 1);
        assert_eq!(&text[pairs[0].value_start..pairs[0].value_end], "hello");
    }

    #[test]
    fn test_code_long_value_rejected() {
        let long_val = "a".repeat(501);
        let text = format!("key = \"{}\"", long_val);
        let pairs = parse_code_literals_with_spans(&text);
        assert!(pairs.is_empty()); // >500 chars rejected
    }

    #[test]
    fn test_code_single_quoted_offset() {
        let text = "db_pass: 'mysecret'";
        let pairs = parse_code_literals_with_spans(text);
        assert_eq!(pairs.len(), 1);
        assert_eq!(&text[pairs[0].value_start..pairs[0].value_end], "mysecret");
    }

    #[test]
    fn test_code_multiple_assignments() {
        let text = "host = \"localhost\"\npass = \"secret456\"";
        let pairs = parse_code_literals_with_spans(text);
        assert_eq!(pairs.len(), 2);
        assert!(pairs.iter().any(|p| p.key == "host" && p.value == "localhost"));
        assert!(pairs.iter().any(|p| p.key == "pass" && p.value == "secret456"));
    }
}
