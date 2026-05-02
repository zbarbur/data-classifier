//! Entropy and character-class heuristics for secret/credential detection.
//!
//! Ports from Python `heuristic_engine.py` (shannon, diversity, evenness)
//! and `secret_scanner.py` (charset detection, relative entropy, scoring).

use std::collections::HashMap;

// Maximum theoretical entropy per charset (log2 of alphabet size).
const MAX_ENTROPY_HEX: f64 = 4.0; // log2(16)
const MAX_ENTROPY_BASE64: f64 = 6.0; // log2(64)
const MAX_ENTROPY_ALPHANUMERIC: f64 = 5.954_196_310_386_876; // log2(62)
const MAX_ENTROPY_FULL: f64 = 6.569_855_608_330_948; // log2(95)

/// Compute Shannon entropy in bits per character.
///
/// H = -sum(p_i * log2(p_i)) where p_i = freq(char_i) / total_length.
/// Returns 0.0 for empty strings.
pub fn shannon_entropy(value: &str) -> f64 {
    if value.is_empty() {
        return 0.0;
    }
    let mut freq: HashMap<char, usize> = HashMap::new();
    let mut length: usize = 0;
    for c in value.chars() {
        *freq.entry(c).or_insert(0) += 1;
        length += 1;
    }
    let len_f = length as f64;
    let mut entropy = 0.0_f64;
    for &count in freq.values() {
        let prob = count as f64 / len_f;
        if prob > 0.0 {
            entropy -= prob * prob.log2();
        }
    }
    entropy
}

/// Detect the character set of a value for entropy threshold selection.
///
/// Returns one of: `"hex"`, `"base64"`, `"alphanumeric"`, `"full"`.
/// - hex: all chars match `[0-9a-fA-F]`
/// - base64: all chars match `[A-Za-z0-9+/=]`
/// - alphanumeric: all chars match `[A-Za-z0-9]` (subset of base64, so unreachable in practice)
/// - full: anything else
pub fn detect_charset(value: &str) -> &'static str {
    if !value.is_empty() && value.chars().all(|c| c.is_ascii_hexdigit()) {
        return "hex";
    }
    if !value.is_empty()
        && value
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '+' || c == '/' || c == '=')
    {
        return "base64";
    }
    if !value.is_empty() && value.chars().all(|c| c.is_ascii_alphanumeric()) {
        return "alphanumeric";
    }
    "full"
}

/// Compute entropy as a fraction of the theoretical maximum for the detected charset.
///
/// Returns `min(1.0, shannon_entropy(value) / max_entropy_for_charset)`.
/// Returns 0.0 for empty strings.
pub fn relative_entropy(value: &str) -> f64 {
    if value.is_empty() {
        return 0.0;
    }
    let entropy = shannon_entropy(value);
    let charset = detect_charset(value);
    let max_entropy = match charset {
        "hex" => MAX_ENTROPY_HEX,
        "base64" => MAX_ENTROPY_BASE64,
        "alphanumeric" => MAX_ENTROPY_ALPHANUMERIC,
        _ => MAX_ENTROPY_FULL,
    };
    if max_entropy == 0.0 {
        return 0.0;
    }
    f64::min(1.0, entropy / max_entropy)
}

/// Count how many character classes are present in a value (0-4).
///
/// Classes: lowercase, uppercase, digits, symbols (non-whitespace non-alnum
/// is counted as symbol by the Python original, but the Python code uses
/// `else` which catches whitespace too — we mirror that behavior).
pub fn char_class_diversity(value: &str) -> usize {
    if value.is_empty() {
        return 0;
    }
    let mut has_lower = false;
    let mut has_upper = false;
    let mut has_digit = false;
    let mut has_special = false;
    for c in value.chars() {
        if c.is_uppercase() {
            has_upper = true;
        } else if c.is_lowercase() {
            has_lower = true;
        } else if c.is_ascii_digit() {
            has_digit = true;
        } else {
            has_special = true;
        }
    }
    [has_lower, has_upper, has_digit, has_special]
        .iter()
        .filter(|&&b| b)
        .count()
}

/// Normalized Shannon entropy over the 4-class character histogram.
///
/// Classes: uppercase, lowercase, digits, symbols.
/// Only classes that are present contribute. If 0 or 1 class is present,
/// returns 0.0. Otherwise returns `h / h_max` where `h_max = log2(num_present)`.
/// Result is in `[0.0, 1.0]`.
pub fn char_class_evenness(value: &str) -> f64 {
    if value.is_empty() {
        return 0.0;
    }
    // counts: [upper, lower, digit, symbol]
    let mut counts = [0_usize; 4];
    for c in value.chars() {
        if c.is_uppercase() {
            counts[0] += 1;
        } else if c.is_lowercase() {
            counts[1] += 1;
        } else if c.is_ascii_digit() {
            counts[2] += 1;
        } else {
            counts[3] += 1;
        }
    }
    let n: usize = counts.iter().sum();
    if n == 0 {
        return 0.0;
    }
    let n_f = n as f64;
    let present: Vec<f64> = counts.iter().filter(|&&c| c > 0).map(|&c| c as f64 / n_f).collect();
    let num_classes = present.len();
    if num_classes <= 1 {
        return 0.0;
    }
    let h: f64 = -present.iter().map(|&p| p * p.log2()).sum::<f64>();
    let h_max = (num_classes as f64).log2();
    h / h_max
}

/// Gate function: convert relative entropy to a 0.0-1.0 score.
///
/// If `rel < 0.5`, returns 0.0. Otherwise returns `min(1.0, rel)`.
pub fn score_relative_entropy(rel: f64) -> f64 {
    if rel < 0.5 {
        return 0.0;
    }
    f64::min(1.0, rel)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_shannon_entropy_uniform() {
        let e = shannon_entropy("abcd");
        assert!((e - 2.0).abs() < 0.001); // 4 distinct chars, log2(4)=2.0
    }

    #[test]
    fn test_shannon_entropy_single_char() {
        assert_eq!(shannon_entropy("aaaa"), 0.0);
    }

    #[test]
    fn test_shannon_entropy_empty() {
        assert_eq!(shannon_entropy(""), 0.0);
    }

    #[test]
    fn test_detect_charset_hex() {
        assert_eq!(detect_charset("0123456789abcdef"), "hex");
    }

    #[test]
    fn test_detect_charset_base64() {
        assert_eq!(detect_charset("ABCDabcd0123+/="), "base64");
    }

    #[test]
    fn test_detect_charset_full() {
        assert_eq!(detect_charset("hello world!@#"), "full");
    }

    #[test]
    fn test_relative_entropy_range() {
        let r = relative_entropy("aB3!cD4@eF5#");
        assert!(r > 0.0 && r <= 1.0);
    }

    #[test]
    fn test_relative_entropy_empty() {
        assert_eq!(relative_entropy(""), 0.0);
    }

    #[test]
    fn test_char_class_diversity_1() {
        assert_eq!(char_class_diversity("abc"), 1);
    }

    #[test]
    fn test_char_class_diversity_2() {
        assert_eq!(char_class_diversity("aBc"), 2);
    }

    #[test]
    fn test_char_class_diversity_3() {
        assert_eq!(char_class_diversity("aB1"), 3);
    }

    #[test]
    fn test_char_class_diversity_4() {
        assert_eq!(char_class_diversity("aB1!"), 4);
    }

    #[test]
    fn test_char_class_evenness_single() {
        assert_eq!(char_class_evenness("aaaa"), 0.0);
    }

    #[test]
    fn test_char_class_evenness_even() {
        let e = char_class_evenness("aaBB");
        assert!((e - 1.0).abs() < 0.001);
    }

    #[test]
    fn test_score_relative_entropy_below() {
        assert_eq!(score_relative_entropy(0.3), 0.0);
    }

    #[test]
    fn test_score_relative_entropy_above() {
        assert!((score_relative_entropy(0.7) - 0.7).abs() < 0.001);
    }

    #[test]
    fn test_score_relative_entropy_cap() {
        assert_eq!(score_relative_entropy(1.5), 1.0);
    }
}
