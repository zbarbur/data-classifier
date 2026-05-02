use super::KVPair;

/// Parse text as JSON, flatten nested objects with dot notation.
///
/// Returns key-value pairs. For strings, offsets point to the value content
/// inside the quotes. For non-string primitives (numbers, bools), offsets
/// point to the bare value in the text. Offset tracking uses a forward-only
/// cursor to avoid matching earlier occurrences of the same value.
///
/// Top-level arrays and non-object JSON are rejected (return empty).
pub fn parse_json_with_spans(text: &str) -> Vec<KVPair> {
    let data: serde_json::Value = match serde_json::from_str(text) {
        Ok(v) => v,
        Err(_) => return Vec::new(),
    };

    if !data.is_object() {
        return Vec::new();
    }

    let mut results = Vec::new();
    let mut cursor = 0usize;
    flatten_value(&data, "", text, &mut cursor, &mut results);
    results
}

fn flatten_value(
    value: &serde_json::Value,
    prefix: &str,
    text: &str,
    cursor: &mut usize,
    results: &mut Vec<KVPair>,
) {
    match value {
        serde_json::Value::Object(map) => {
            for (k, v) in map {
                let full_key = if prefix.is_empty() {
                    k.clone()
                } else {
                    format!("{}.{}", prefix, k)
                };
                flatten_value(v, &full_key, text, cursor, results);
            }
        }
        serde_json::Value::Array(arr) => {
            for (i, item) in arr.iter().enumerate() {
                let full_key = format!("{}[{}]", prefix, i);
                flatten_value(item, &full_key, text, cursor, results);
            }
        }
        serde_json::Value::Null => {
            // skip nulls
        }
        leaf => {
            push_json_pair(leaf, prefix, text, cursor, results);
        }
    }
}

fn push_json_pair(
    value: &serde_json::Value,
    key: &str,
    text: &str,
    cursor: &mut usize,
    results: &mut Vec<KVPair>,
) {
    let str_val = match value {
        serde_json::Value::String(s) => s.clone(),
        serde_json::Value::Number(n) => n.to_string(),
        serde_json::Value::Bool(b) => b.to_string(),
        _ => return,
    };

    // Find the offset of this value in the original text.
    // For strings: JSON-encode the value (adds quotes + escape sequences) and
    // search for that encoded form; the span is inside the surrounding quotes.
    // For non-strings: search for the bare representation.
    let (value_start, value_end) = find_value_offset(value, &str_val, text, *cursor);

    if value_end > value_start {
        *cursor = value_end;
    }

    results.push(KVPair {
        key: key.to_string(),
        value: str_val,
        value_start,
        value_end,
    });
}

fn find_value_offset(
    value: &serde_json::Value,
    str_val: &str,
    text: &str,
    from: usize,
) -> (usize, usize) {
    match value {
        serde_json::Value::String(_) => {
            // JSON-encode to get the on-wire representation including quotes and escapes.
            let encoded = serde_json::to_string(value).unwrap_or_default();
            if let Some(pos) = text[from..].find(&encoded) {
                let abs = from + pos;
                // encoded starts and ends with '"'; value content is between them.
                let value_start = abs + 1;
                let value_end = abs + encoded.len() - 1;
                (value_start, value_end)
            } else {
                // Fallback: bare search
                if let Some(pos) = text[from..].find(str_val) {
                    let abs = from + pos;
                    (abs, abs + str_val.len())
                } else {
                    (0, 0)
                }
            }
        }
        _ => {
            // Non-string: bare search for the representation
            if let Some(pos) = text[from..].find(str_val) {
                let abs = from + pos;
                (abs, abs + str_val.len())
            } else {
                (0, 0)
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_json_flat() {
        let text = r#"{"api_key": "sk-12345", "port": 8080}"#;
        let pairs = parse_json_with_spans(text);
        assert!(pairs.iter().any(|p| p.key == "api_key" && p.value == "sk-12345"));
        assert!(pairs.iter().any(|p| p.key == "port" && p.value == "8080"));
    }

    #[test]
    fn test_json_nested() {
        let text = r#"{"db": {"password": "secret", "host": "localhost"}}"#;
        let pairs = parse_json_with_spans(text);
        assert!(pairs.iter().any(|p| p.key == "db.password" && p.value == "secret"));
    }

    #[test]
    fn test_json_array() {
        let text = r#"{"keys": ["key1", "key2"]}"#;
        let pairs = parse_json_with_spans(text);
        assert!(pairs.iter().any(|p| p.key == "keys[0]" && p.value == "key1"));
    }

    #[test]
    fn test_json_not_object() {
        let pairs = parse_json_with_spans("[1, 2, 3]");
        assert!(pairs.is_empty()); // arrays at top level rejected
    }

    #[test]
    fn test_json_invalid() {
        let pairs = parse_json_with_spans("not json at all");
        assert!(pairs.is_empty());
    }

    #[test]
    fn test_json_string_offset() {
        let text = r#"{"api_key": "sk-12345"}"#;
        let pairs = parse_json_with_spans(text);
        let p = pairs.iter().find(|p| p.key == "api_key").unwrap();
        assert_eq!(&text[p.value_start..p.value_end], "sk-12345");
    }

    #[test]
    fn test_json_boolean() {
        let text = r#"{"enabled": true}"#;
        let pairs = parse_json_with_spans(text);
        assert!(pairs.iter().any(|p| p.key == "enabled" && p.value == "true"));
    }

    #[test]
    fn test_json_null_skipped() {
        let text = r#"{"key": null, "other": "val"}"#;
        let pairs = parse_json_with_spans(text);
        assert!(!pairs.iter().any(|p| p.key == "key"));
        assert!(pairs.iter().any(|p| p.key == "other"));
    }
}
