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

    // Use captures_iter directly — group positions are absolute (relative to
    // the full input text), avoiding the double-match offset bug from
    // find_iter + captures on a substring.
    for caps in re.captures_iter(text).flatten() {
        let key = match caps.get(1) {
            Some(g) => g.as_str(),
            None => continue,
        };

        let (value, value_start, value_end) = if let Some(g) = caps.get(2) {
            (g.as_str(), g.start(), g.end())
        } else if let Some(g) = caps.get(3) {
            (g.as_str(), g.start(), g.end())
        } else {
            continue;
        };

        if value.is_empty() {
            continue;
        }

        // Reject values containing newlines — real key=value assignments
        // are single-line. Multi-line matches indicate the regex matched
        // across a string boundary (e.g. `password: "Enter password: ");`
        // inside a function call argument).
        if value.contains('\n') {
            continue;
        }

        debug_assert_eq!(
            &text[value_start..value_end],
            value,
            "code_literals offset mismatch for key: {:?}",
            key
        );

        results.push(KVPair {
            key: key.to_string(),
            value: value.to_string(),
            value_start,
            value_end,
        });
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

    #[test]
    fn test_code_multiline_offset_accuracy() {
        // Reproduces the span bug: key=value on line 2, same value used later.
        // The span must point to the FIRST occurrence (the assignment).
        let text = "import os\nsome_code()\nACCESS_TOKEN = \"EAABwSecret123\"\nprint(ACCESS_TOKEN)\nurl = f\"...{ACCESS_TOKEN}\"";
        let pairs = parse_code_literals_with_spans(text);
        let token_pairs: Vec<_> = pairs.iter().filter(|p| p.key == "ACCESS_TOKEN").collect();
        assert_eq!(token_pairs.len(), 1, "should find exactly 1 ACCESS_TOKEN pair");
        let p = token_pairs[0];
        assert_eq!(p.value, "EAABwSecret123");
        // The critical check: span must point to the actual value in the text
        assert_eq!(
            &text[p.value_start..p.value_end],
            "EAABwSecret123",
            "span must point to the value, got: {:?} at {}..{}",
            &text[p.value_start..p.value_end.min(text.len())],
            p.value_start,
            p.value_end
        );
        // Verify it's on line 2 (0-indexed), not later
        let line_no = text[..p.value_start].matches('\n').count();
        assert_eq!(line_no, 2, "should be on line 2 (the assignment)");
    }
}
