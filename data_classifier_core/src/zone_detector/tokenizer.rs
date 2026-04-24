//! Line tokenizer — mirrors Python tokenizer.py.
//!
//! Extracts a TokenProfile from a single line by categorizing
//! characters into identifiers, keywords, operators, strings,
//! numbers, dot access, and delimiters.

use fancy_regex::Regex;
use std::collections::HashSet;
use std::sync::LazyLock;

/// Token distribution profile for a single line.
#[derive(Debug, Clone, Default)]
pub struct TokenProfile {
    pub identifier_count: usize,
    pub keyword_count: usize,
    pub operator_count: usize,
    pub dot_access_count: usize,
    pub string_count: usize,
    pub number_count: usize,
    pub delimiter_count: usize,
    pub total_tokens: usize,
    pub string_ratio: f64,
    pub identifier_ratio: f64,
}

static STRING_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#"(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`)"#).unwrap()
});

static NUMBER_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"\b(?:0[xXbBoO][\da-fA-F_]+|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?)\b").unwrap()
});

static DOT_ACCESS_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"\b[a-zA-Z_]\w*\.[a-zA-Z_]\w*").unwrap()
});

static IDENTIFIER_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"\b[a-zA-Z_]\w*\b").unwrap()
});

static OPERATOR_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"[+\-*/=<>!&|^~%]+").unwrap()
});

static DELIMITER_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"[{}()\[\];,:]").unwrap()
});

/// Tokenize a single line and return its profile.
///
/// Extraction order (matches Python):
/// 1. Remove string literals
/// 2. Count numbers (on string-free text)
/// 3. Remove numbers, then count dot access
/// 4. Count identifiers, separating keywords
/// 5. Count operators and delimiters
pub fn tokenize_line(line: &str, keywords: &HashSet<String>) -> TokenProfile {
    let trimmed = line.trim();
    if trimmed.is_empty() {
        return TokenProfile::default();
    }

    // 1. Remove strings, count them
    let string_count = STRING_RE.find_iter(trimmed).count();
    let no_strings = STRING_RE.replace_all(trimmed, " ").to_string();

    // 2. Count numbers
    let number_count = NUMBER_RE.find_iter(&no_strings).count();

    // 3. Remove numbers, then count dot access
    let no_numbers = NUMBER_RE.replace_all(&no_strings, " ").to_string();
    let dot_access_count = DOT_ACCESS_RE.find_iter(&no_numbers).count();

    // 4. Count identifiers and keywords
    let mut identifier_count = 0;
    let mut keyword_count = 0;
    for m in IDENTIFIER_RE.find_iter(&no_strings) {
        if let Ok(m) = m {
            let word = m.as_str();
            if keywords.contains(word) {
                keyword_count += 1;
            } else {
                identifier_count += 1;
            }
        }
    }

    // 5. Operators and delimiters
    let operator_count = OPERATOR_RE.find_iter(&no_strings).count();
    let delimiter_count = DELIMITER_RE.find_iter(&no_strings).count();

    let total_tokens = identifier_count + keyword_count + operator_count
        + string_count + number_count + delimiter_count;
    let string_ratio = if total_tokens > 0 {
        string_count as f64 / total_tokens as f64
    } else {
        0.0
    };
    let identifier_ratio = if total_tokens > 0 {
        identifier_count as f64 / total_tokens as f64
    } else {
        0.0
    };

    TokenProfile {
        identifier_count,
        keyword_count,
        operator_count,
        dot_access_count,
        string_count,
        number_count,
        delimiter_count,
        total_tokens,
        string_ratio,
        identifier_ratio,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn kw_set() -> HashSet<String> {
        ["def", "return", "if", "else", "for", "while", "import", "from", "class"]
            .iter()
            .map(|s| s.to_string())
            .collect()
    }

    #[test]
    fn test_empty_line() {
        let p = tokenize_line("", &HashSet::new());
        assert_eq!(p.total_tokens, 0);
    }

    #[test]
    fn test_python_assignment() {
        let p = tokenize_line("result = process(data)", &kw_set());
        assert!(p.identifier_count >= 2);
        assert!(p.operator_count >= 1);
    }

    #[test]
    fn test_dot_access() {
        let p = tokenize_line("self.data.append(item)", &kw_set());
        assert!(p.dot_access_count >= 1);
    }

    #[test]
    fn test_keywords_counted() {
        let p = tokenize_line("def process(data):", &kw_set());
        assert_eq!(p.keyword_count, 1); // "def"
    }

    #[test]
    fn test_prose_no_operators() {
        let p = tokenize_line("This is a simple English sentence about nothing.", &kw_set());
        assert_eq!(p.operator_count, 0);
        assert_eq!(p.dot_access_count, 0);
    }
}
