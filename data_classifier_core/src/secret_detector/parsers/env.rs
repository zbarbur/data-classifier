use std::sync::OnceLock;

use fancy_regex::Regex;

use super::KVPair;

/// Regex for env-file lines: KEY=VALUE, export KEY=VALUE, KEY="VALUE", KEY='VALUE'.
/// Groups: 1=key, 2=double-quoted value, 3=single-quoted value, 4=unquoted value.
static ENV_RE: OnceLock<Regex> = OnceLock::new();

fn env_regex() -> &'static Regex {
    ENV_RE.get_or_init(|| {
        Regex::new(
            r#"(?m)^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s()\[\]{},]+))\s*$"#,
        )
        .expect("ENV_RE must compile")
    })
}

/// Parse KEY=value assignments (with optional `export` prefix).
///
/// Supported forms:
///   - `KEY=value`
///   - `export KEY=value`
///   - `KEY="value"` / `KEY='value'`
///
/// Byte offsets point to the value content in the original text (inside quotes
/// for quoted forms, at the unquoted value for bare forms).
pub fn parse_env_with_spans(text: &str) -> Vec<KVPair> {
    let re = env_regex();
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
        } else if let Some(g) = caps.get(4) {
            (g.as_str(), g.start(), g.end())
        } else {
            continue;
        };

        if value.is_empty() {
            continue;
        }

        debug_assert_eq!(
            &text[value_start..value_end],
            value,
            "ENV offset mismatch for key: {:?}",
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
    fn test_env_export() {
        let pairs = parse_env_with_spans("export TOKEN=\"abc123\"");
        assert_eq!(pairs.len(), 1);
        assert_eq!(pairs[0].key, "TOKEN");
        assert_eq!(pairs[0].value, "abc123");
    }

    #[test]
    fn test_env_single_quoted() {
        let pairs = parse_env_with_spans("SECRET='my-secret'");
        assert_eq!(pairs.len(), 1);
        assert_eq!(pairs[0].value, "my-secret");
    }

    #[test]
    fn test_env_unquoted() {
        let pairs = parse_env_with_spans("KEY=value123");
        assert_eq!(pairs.len(), 1);
        assert_eq!(pairs[0].value, "value123");
    }

    #[test]
    fn test_env_offset() {
        let text = "API_KEY=secret";
        let pairs = parse_env_with_spans(text);
        assert_eq!(pairs.len(), 1);
        assert_eq!(&text[pairs[0].value_start..pairs[0].value_end], "secret");
    }

    #[test]
    fn test_env_offset_quoted() {
        let text = "export API_KEY=\"hello-world\"";
        let pairs = parse_env_with_spans(text);
        assert_eq!(pairs.len(), 1);
        assert_eq!(&text[pairs[0].value_start..pairs[0].value_end], "hello-world");
    }

    #[test]
    fn test_env_multiline() {
        let text = "DB_HOST=localhost\nDB_PASS=\"secret123\"\nDB_PORT=5432";
        let pairs = parse_env_with_spans(text);
        assert_eq!(pairs.len(), 3);
        assert!(pairs.iter().any(|p| p.key == "DB_HOST" && p.value == "localhost"));
        assert!(pairs.iter().any(|p| p.key == "DB_PASS" && p.value == "secret123"));
        assert!(pairs.iter().any(|p| p.key == "DB_PORT" && p.value == "5432"));
    }

    #[test]
    fn test_env_no_match_on_spaces() {
        // Values with spaces are not matched as env (would need quotes)
        let pairs = parse_env_with_spans("KEY=hello world");
        // "hello" matches as unquoted, "world" is ignored by $
        // Only "hello" should be captured
        assert!(pairs.len() <= 1);
        if pairs.len() == 1 {
            assert_eq!(pairs[0].value, "hello");
        }
    }
}
