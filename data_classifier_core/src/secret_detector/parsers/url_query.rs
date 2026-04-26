use super::{url_decode, KVPair};

/// Extract key-value pairs from the query string of a URL.
///
/// Finds the `?` in `text`, takes everything after it (up to the first space
/// or end-of-string), splits on `&`, and for each segment splits on the first
/// `=`.  Both keys and values are URL-decoded.
///
/// Offsets point to the decoded value content.  Because URL-decoding may change
/// byte length, the offsets reflect the **encoded** value's position in the
/// original text (i.e. the raw bytes before decoding).
pub fn parse_url_query_with_spans(text: &str) -> Vec<KVPair> {
    // Find '?' — everything after it is the query string
    let query_start = match text.find('?') {
        Some(idx) => idx + 1, // position after '?'
        None => return Vec::new(),
    };

    // Take up to first whitespace or end-of-string
    let query_raw = &text[query_start..];
    let query_end_offset = query_raw
        .bytes()
        .position(|b| b.is_ascii_whitespace())
        .unwrap_or(query_raw.len());
    let query = &query_raw[..query_end_offset];

    if query.is_empty() {
        return Vec::new();
    }

    let mut results = Vec::new();
    let mut offset = query_start; // absolute offset into `text` of current segment start

    for segment in query.split('&') {
        let seg_len = segment.len();

        if let Some(eq_pos) = segment.find('=') {
            let raw_key = &segment[..eq_pos];
            let raw_value = &segment[eq_pos + 1..];

            let key = url_decode(raw_key);
            let value = url_decode(raw_value);

            if !key.is_empty() && !value.is_empty() {
                // value_start: after the '=' in the original text
                let value_start = offset + eq_pos + 1;
                let value_end = value_start + raw_value.len();

                results.push(KVPair {
                    key,
                    value,
                    value_start,
                    value_end,
                });
            }
        }

        // Advance offset by segment length + 1 for the '&' separator
        offset += seg_len + 1;
    }

    results
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_url_query_basic() {
        let text = "https://api.example.com?api_key=sk123&format=json";
        let pairs = parse_url_query_with_spans(text);
        assert!(
            pairs.iter().any(|p| p.key == "api_key" && p.value == "sk123"),
            "expected api_key=sk123 in {:?}",
            pairs
        );
        assert!(pairs.iter().any(|p| p.key == "format" && p.value == "json"));
    }

    #[test]
    fn test_url_query_encoded_value() {
        let text = "https://example.com?pass=hello%20world";
        let pairs = parse_url_query_with_spans(text);
        assert!(
            pairs.iter().any(|p| p.value == "hello world"),
            "expected decoded 'hello world' in {:?}",
            pairs
        );
    }

    #[test]
    fn test_url_query_plus_space() {
        let text = "https://example.com?q=hello+world&token=abc";
        let pairs = parse_url_query_with_spans(text);
        assert!(
            pairs.iter().any(|p| p.key == "q" && p.value == "hello world"),
            "expected 'hello world' (+ decoded) in {:?}",
            pairs
        );
    }

    #[test]
    fn test_url_query_no_query() {
        let pairs = parse_url_query_with_spans("https://example.com/path");
        assert!(pairs.is_empty(), "expected empty when no '?'");
    }

    #[test]
    fn test_url_query_empty_after_question_mark() {
        let pairs = parse_url_query_with_spans("https://example.com?");
        assert!(pairs.is_empty(), "expected empty for empty query string");
    }

    #[test]
    fn test_url_query_offset_correctness() {
        let text = "https://example.com?token=abc123&other=xyz";
        let pairs = parse_url_query_with_spans(text);
        let tok = pairs.iter().find(|p| p.key == "token").expect("token not found");
        // value_start/value_end point to the raw (encoded) value in original text
        assert_eq!(&text[tok.value_start..tok.value_end], "abc123");
    }

    #[test]
    fn test_url_query_percent_encoded_key() {
        let text = "https://example.com?api%5Fkey=mytoken";
        let pairs = parse_url_query_with_spans(text);
        // api%5Fkey decodes to api_key
        assert!(
            pairs.iter().any(|p| p.key == "api_key" && p.value == "mytoken"),
            "expected decoded key api_key in {:?}",
            pairs
        );
    }

    #[test]
    fn test_url_query_multiple_params() {
        let text = "https://api.example.com?client_id=abc&client_secret=xyz789&scope=read";
        let pairs = parse_url_query_with_spans(text);
        assert_eq!(pairs.len(), 3);
        assert!(pairs.iter().any(|p| p.key == "client_secret" && p.value == "xyz789"));
    }

    #[test]
    fn test_url_query_stops_at_whitespace() {
        let text = "https://example.com?token=abc def=ghi";
        let pairs = parse_url_query_with_spans(text);
        // "token=abc" before the space, "def=ghi" after should be ignored
        assert!(pairs.iter().any(|p| p.key == "token" && p.value == "abc"));
        assert!(!pairs.iter().any(|p| p.key == "def"), "should stop at whitespace");
    }

    #[test]
    fn test_url_query_segment_without_value() {
        // Segment with no '=' should be silently skipped
        let text = "https://example.com?flag&token=abc123";
        let pairs = parse_url_query_with_spans(text);
        assert!(pairs.iter().any(|p| p.key == "token" && p.value == "abc123"));
    }
}
