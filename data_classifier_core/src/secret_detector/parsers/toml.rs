use std::sync::OnceLock;

use fancy_regex::Regex;

use super::KVPair;

/// Regex for TOML section headers: `[section]` or `[section.sub]`.
static TOML_SECTION_RE: OnceLock<Regex> = OnceLock::new();
/// Regex for TOML key-value lines: `key = value`.
static TOML_KV_RE: OnceLock<Regex> = OnceLock::new();

fn toml_section_regex() -> &'static Regex {
    TOML_SECTION_RE.get_or_init(|| {
        Regex::new(r"(?m)^\s*\[([^\]]+)\]\s*$").expect("TOML_SECTION_RE must compile")
    })
}

fn toml_kv_regex() -> &'static Regex {
    TOML_KV_RE.get_or_init(|| {
        Regex::new(r#"(?m)^\s*([a-zA-Z_][\w.\-]*)\s*=\s*(.+)$"#).expect("TOML_KV_RE must compile")
    })
}

/// Extract key-value pairs from TOML-like text.
///
/// - Tracks `[section]` headers; keys are prefixed as `"section.key"`.
/// - Strips surrounding `"..."` or `'...'` from values.
/// - Skips inline-table and array values.
/// - Offsets point to value content (inside quotes for quoted values).
pub fn parse_toml_with_spans(text: &str) -> Vec<KVPair> {
    let section_re = toml_section_regex();
    let kv_re = toml_kv_regex();

    let mut results = Vec::new();
    let mut current_section: Option<String> = None;

    for line_range in line_ranges(text) {
        let (line_start, line_end) = line_range;
        let line = &text[line_start..line_end];

        // Check if this is a section header
        if let Ok(Some(caps)) = section_re.captures(line) {
            if let Some(g) = caps.get(1) {
                current_section = Some(g.as_str().trim().to_string());
            }
            continue;
        }

        // Try to match a key-value line
        let Ok(Some(caps)) = kv_re.captures(line) else {
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

        // Skip inline tables and arrays
        if raw_value.starts_with('{') || raw_value.starts_with('[') {
            continue;
        }
        // Skip TOML multi-line string starters
        if raw_value.starts_with("\"\"\"") || raw_value.starts_with("'''") {
            continue;
        }
        // Skip comment-only "values"
        if raw_value.starts_with('#') {
            continue;
        }

        let bare_key = key_group.as_str().to_string();
        let key = match &current_section {
            Some(section) => format!("{}.{}", section, bare_key),
            None => bare_key,
        };

        // Compute absolute offsets for value in original text
        let val_abs_start = line_start + val_group.start();
        let val_abs_end = line_start + val_group.end();

        let (value, value_start, value_end) =
            strip_quotes_with_offsets(raw_value, text, val_abs_start, val_abs_end);

        if value.is_empty() {
            continue;
        }

        results.push(KVPair {
            key,
            value,
            value_start,
            value_end,
        });
    }

    results
}

/// Iterate over lines returning (start, end) byte ranges in `text`.
/// The range does NOT include the trailing `\n`.
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
fn strip_quotes_with_offsets(
    raw: &str,
    text: &str,
    abs_start: usize,
    _abs_end: usize,
) -> (String, usize, usize) {
    // Walk forward to skip any leading whitespace before the value content
    let leading_ws = text[abs_start..]
        .bytes()
        .take_while(|b| b.is_ascii_whitespace())
        .count();
    let content_start = abs_start + leading_ws;

    // Strip inline comment from unquoted values: `value # comment`
    let raw = strip_inline_comment(raw);

    if (raw.starts_with('"') && raw.ends_with('"') && raw.len() >= 2)
        || (raw.starts_with('\'') && raw.ends_with('\'') && raw.len() >= 2)
    {
        let inner = &raw[1..raw.len() - 1];
        let value_start = content_start + 1;
        let value_end = value_start + inner.len();
        (inner.to_string(), value_start, value_end)
    } else {
        let value_end = content_start + raw.len();
        (raw.to_string(), content_start, value_end)
    }
}

/// Remove trailing `# comment` from an unquoted TOML value.
fn strip_inline_comment(s: &str) -> &str {
    // Only strip if not inside quotes
    if s.starts_with('"') || s.starts_with('\'') {
        return s;
    }
    match s.find('#') {
        Some(idx) => s[..idx].trim_end(),
        None => s,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_toml_flat() {
        let text = "api_key = \"sk-12345\"\nport = 8080";
        let pairs = parse_toml_with_spans(text);
        assert!(
            pairs.iter().any(|p| p.key == "api_key" && p.value == "sk-12345"),
            "expected api_key=sk-12345 in {:?}",
            pairs
        );
    }

    #[test]
    fn test_toml_section() {
        let text = "[database]\npassword = \"secret\"\nhost = \"localhost\"";
        let pairs = parse_toml_with_spans(text);
        assert!(
            pairs.iter().any(|p| p.key == "database.password" && p.value == "secret"),
            "expected database.password=secret in {:?}",
            pairs
        );
        assert!(
            pairs.iter().any(|p| p.key == "database.host" && p.value == "localhost"),
            "expected database.host=localhost in {:?}",
            pairs
        );
    }

    #[test]
    fn test_toml_nested_section() {
        let text = "[auth.credentials]\ntoken = \"abc123\"\nexpiry = 3600";
        let pairs = parse_toml_with_spans(text);
        assert!(
            pairs.iter().any(|p| p.key == "auth.credentials.token" && p.value == "abc123"),
            "expected auth.credentials.token in {:?}",
            pairs
        );
    }

    #[test]
    fn test_toml_no_section() {
        let text = "title = \"My App\"\nversion = \"1.0\"";
        let pairs = parse_toml_with_spans(text);
        assert!(pairs.iter().any(|p| p.key == "title" && p.value == "My App"));
        assert!(pairs.iter().any(|p| p.key == "version" && p.value == "1.0"));
    }

    #[test]
    fn test_toml_skips_inline_table() {
        let text = "[section]\ntable = {key = \"val\"}\nplain = \"hello\"";
        let pairs = parse_toml_with_spans(text);
        assert!(!pairs.iter().any(|p| p.key == "section.table"), "inline table should be skipped");
        assert!(pairs.iter().any(|p| p.key == "section.plain"));
    }

    #[test]
    fn test_toml_single_quoted() {
        let text = "[creds]\npassword = 'hunter2'\nuser = 'admin'";
        let pairs = parse_toml_with_spans(text);
        assert!(pairs.iter().any(|p| p.key == "creds.password" && p.value == "hunter2"));
    }

    #[test]
    fn test_toml_offset_correctness() {
        let text = "[db]\npassword = \"s3cr3t\"\nhost = \"localhost\"";
        let pairs = parse_toml_with_spans(text);
        let pw = pairs.iter().find(|p| p.key == "db.password").expect("db.password not found");
        assert_eq!(&text[pw.value_start..pw.value_end], "s3cr3t");
    }

    #[test]
    fn test_toml_unquoted_offset() {
        let text = "[server]\nport = 8080\nhost = myhost";
        let pairs = parse_toml_with_spans(text);
        let port = pairs.iter().find(|p| p.key == "server.port").expect("server.port not found");
        assert_eq!(&text[port.value_start..port.value_end], "8080");
    }
}
