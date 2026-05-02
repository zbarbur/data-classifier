use std::sync::OnceLock;

use regex::Regex;

use super::KVPair;

/// Regex matching a YAML key-value line: `key: value` (applied per-line).
/// Groups: 1=key, 2=raw value (may include trailing whitespace/comments).
static YAML_KV_RE: OnceLock<Regex> = OnceLock::new();

fn yaml_kv_regex() -> &'static Regex {
    YAML_KV_RE.get_or_init(|| {
        Regex::new(r"^\s*([a-zA-Z_][\w.\-]*)\s*:\s+(.+)$").expect("YAML_KV_RE must compile")
    })
}

/// Extract key-value pairs from YAML-like text (line-by-line, flat/nested).
///
/// This is NOT a full YAML parser — it matches simple scalar assignments
/// (mimicking Python's line-regex approach) and ignores complex structures.
///
/// Rules:
/// - Processes text line by line; the regex has no `(?m)` flag.
/// - Requires at least 2 matching KV lines before returning any results
///   (avoids false-positives on random colons in prose).
/// - Skips values that start with `{`, `[`, `|`, or `>` (complex YAML).
/// - Skips values that contain `: ` (nested mapping keys, not scalars).
/// - Strips surrounding `"..."` or `'...'` from values.
/// - Offsets point to the value content in the original text.
pub fn parse_yaml_with_spans(text: &str) -> Vec<KVPair> {
    let re = yaml_kv_regex();
    let mut candidates: Vec<KVPair> = Vec::new();

    for (line_start, line_end) in line_ranges(text) {
        let line = &text[line_start..line_end];
        let Some(caps) = re.captures(line) else {
            continue;
        };

        let key_group = match caps.get(1) {
            Some(g) => g,
            None => continue,
        };
        let val_group = match caps.get(2) {
            Some(g) => g,
            None => continue,
        };

        let raw_value = val_group.as_str().trim();

        // Skip complex YAML structures
        if raw_value.starts_with('{')
            || raw_value.starts_with('[')
            || raw_value.starts_with('|')
            || raw_value.starts_with('>')
        {
            continue;
        }
        // Skip comment-only lines
        if raw_value.starts_with('#') {
            continue;
        }
        // Skip nested mapping keys: if the value itself contains `: ` it is
        // a mapping header line consumed by the greedy `.+`, not a scalar.
        // (e.g. `database: password: secret` is a sign the parser ate too much)
        if raw_value.contains(": ") {
            continue;
        }
        // Also skip if value ends with `:` (another mapping key indicator)
        if raw_value.ends_with(':') {
            continue;
        }

        let key = key_group.as_str().to_string();

        // Compute absolute offsets for value in original text.
        // val_group offsets are relative to `line` which starts at `line_start`.
        let val_abs_start = line_start + val_group.start();
        let val_abs_end = line_start + val_group.end();

        let (value, value_start, value_end) =
            strip_quotes_with_offsets(raw_value, text, val_abs_start, val_abs_end);

        if value.is_empty() {
            continue;
        }

        candidates.push(KVPair {
            key,
            value,
            value_start,
            value_end,
        });
    }

    // Only return results if we have at least 2 KV lines (anti-FP heuristic)
    if candidates.len() < 2 {
        return Vec::new();
    }

    candidates
}

/// Iterate over lines in `text`, yielding `(start, end)` byte ranges.
/// The range excludes the trailing `\n` (and `\r` for CRLF).
fn line_ranges(text: &str) -> impl Iterator<Item = (usize, usize)> + '_ {
    let mut pos = 0usize;
    std::iter::from_fn(move || {
        if pos >= text.len() {
            return None;
        }
        let start = pos;
        let rest = &text[pos..];
        let end = match rest.find('\n') {
            Some(nl) => {
                pos = start + nl + 1;
                // Trim trailing \r for CRLF
                if nl > 0 && rest.as_bytes()[nl - 1] == b'\r' {
                    start + nl - 1
                } else {
                    start + nl
                }
            }
            None => {
                pos = text.len();
                text.len()
            }
        };
        Some((start, end))
    })
}

/// Strip surrounding `"..."` or `'...'` and return the inner value + adjusted offsets.
///
/// `raw` is the trimmed value string. `abs_start` is the byte offset in the
/// original `text` where the (untrimmed) value match begins.
fn strip_quotes_with_offsets(
    raw: &str,
    text: &str,
    abs_start: usize,
    _abs_end: usize,
) -> (String, usize, usize) {
    // Skip leading whitespace in original text to find content start
    let leading_ws = text[abs_start..]
        .bytes()
        .take_while(|b| b.is_ascii_whitespace())
        .count();
    let content_start = abs_start + leading_ws;

    if (raw.starts_with('"') && raw.ends_with('"') && raw.len() >= 2)
        || (raw.starts_with('\'') && raw.ends_with('\'') && raw.len() >= 2)
    {
        let inner = &raw[1..raw.len() - 1];
        let value_start = content_start + 1; // skip opening quote
        let value_end = value_start + inner.len();
        (inner.to_string(), value_start, value_end)
    } else {
        let value_end = content_start + raw.len();
        (raw.to_string(), content_start, value_end)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_yaml_simple() {
        let text = "database:\n  password: secret123\n  host: localhost";
        let pairs = parse_yaml_with_spans(text);
        assert!(
            pairs.iter().any(|p| p.key == "password" && p.value == "secret123"),
            "expected password=secret123 in {:?}",
            pairs
        );
    }

    #[test]
    fn test_yaml_quoted() {
        let text = "api_key: \"sk-12345\"\nport: 8080";
        let pairs = parse_yaml_with_spans(text);
        assert!(
            pairs.iter().any(|p| p.key == "api_key" && p.value == "sk-12345"),
            "expected api_key=sk-12345 in {:?}",
            pairs
        );
    }

    #[test]
    fn test_yaml_single_quoted() {
        let text = "token: 'my-token'\nhost: example.com";
        let pairs = parse_yaml_with_spans(text);
        assert!(
            pairs.iter().any(|p| p.key == "token" && p.value == "my-token"),
            "expected token=my-token in {:?}",
            pairs
        );
    }

    #[test]
    fn test_yaml_single_line_rejected() {
        // Only 1 KV line — should return empty
        let text = "not: yaml";
        let pairs = parse_yaml_with_spans(text);
        assert!(pairs.is_empty(), "expected empty for single KV, got {:?}", pairs);
    }

    #[test]
    fn test_yaml_skips_complex_values() {
        let text = "nested: {a: b}\nplain: value\nother: hello";
        let pairs = parse_yaml_with_spans(text);
        assert!(!pairs.iter().any(|p| p.key == "nested"), "nested complex value should be skipped");
        assert!(pairs.iter().any(|p| p.key == "plain" && p.value == "value"));
    }

    #[test]
    fn test_yaml_multiline_config() {
        let text =
            "database:\n  host: db.example.com\n  port: 5432\n  password: s3cr3t\n  name: mydb";
        let pairs = parse_yaml_with_spans(text);
        assert!(pairs.iter().any(|p| p.key == "password" && p.value == "s3cr3t"));
        assert!(pairs.iter().any(|p| p.key == "host" && p.value == "db.example.com"));
    }

    #[test]
    fn test_yaml_offset_correctness() {
        let text = "api_key: sk-abc123\nregion: us-east-1";
        let pairs = parse_yaml_with_spans(text);
        let ak = pairs.iter().find(|p| p.key == "api_key").expect("api_key not found");
        assert_eq!(&text[ak.value_start..ak.value_end], "sk-abc123");
    }

    #[test]
    fn test_yaml_quoted_offset_correctness() {
        let text = "password: \"hunter2\"\nusername: admin";
        let pairs = parse_yaml_with_spans(text);
        let pw = pairs.iter().find(|p| p.key == "password").expect("password not found");
        assert_eq!(&text[pw.value_start..pw.value_end], "hunter2");
    }
}
