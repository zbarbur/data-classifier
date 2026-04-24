//! NegativeFilter — FP suppression signals.
//!
//! Mirrors Python negative.py. Runs after SyntaxDetector to suppress false
//! positives. Operates on a per-line basis (check_line) and on full blocks
//! (check_list_prefix).

use fancy_regex::Regex;
use serde_json::Value;

/// Result of checking a line against negative signals.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum NegativeResult {
    /// Line matches an error output pattern
    ErrorOutput,
    /// Line matches math, prose, dialog, or ratio patterns
    Suppress,
}

fn alpha_ratio(line: &str) -> f64 {
    let stripped = line.trim();
    if stripped.is_empty() {
        return 0.0;
    }
    let count = stripped
        .chars()
        .filter(|c| c.is_alphabetic() || c.is_whitespace())
        .count();
    count as f64 / stripped.chars().count() as f64
}

fn compile_patterns(v: &Value, key: &str) -> Vec<Regex> {
    v.get(key)
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|p| p.as_str().and_then(|s| Regex::new(s).ok()))
                .collect()
        })
        .unwrap_or_default()
}

/// Suppress false-positive zone detections using known non-code signal patterns.
pub struct NegativeFilter {
    error_output: Vec<Regex>,
    dialog_pats: Vec<Regex>,
    dialog_min_alpha: f64,
    math_pats: Vec<Regex>,
    ratio_pats: Vec<Regex>,
    prose_re: Regex,
    prose_min_alpha: f64,
    list_prefix_re: Regex,
    list_threshold: f64,
}

impl NegativeFilter {
    pub fn new(patterns: &Value) -> Self {
        let neg = patterns.get("negative").unwrap_or(&Value::Null);

        let error_output = compile_patterns(neg, "error_output");

        let dialog_cfg = neg.get("dialog").unwrap_or(&Value::Null);
        let dialog_pats: Vec<Regex> = dialog_cfg
            .get("patterns")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|p| p.as_str().and_then(|s| Regex::new(s).ok()))
                    .collect()
            })
            .unwrap_or_default();
        let dialog_min_alpha = dialog_cfg
            .get("min_alpha_ratio")
            .and_then(|v| v.as_f64())
            .unwrap_or(0.70);

        let math_pats = compile_patterns(neg, "math");
        let ratio_pats = compile_patterns(neg, "ratio");

        let prose_cfg = neg.get("prose").unwrap_or(&Value::Null);
        let prose_pattern = prose_cfg
            .get("pattern")
            .and_then(|v| v.as_str())
            .unwrap_or(r"^[A-Z][a-z].+[.!?]$");
        let prose_re = Regex::new(prose_pattern)
            .unwrap_or_else(|_| Regex::new(r"^[A-Z][a-z].+[.!?]$").expect("default"));
        let prose_min_alpha = prose_cfg
            .get("min_alpha_ratio")
            .and_then(|v| v.as_f64())
            .unwrap_or(0.75);

        let list_cfg = neg.get("list_prefix").unwrap_or(&Value::Null);
        let list_pattern = list_cfg
            .get("pattern")
            .and_then(|v| v.as_str())
            .unwrap_or(r"^\s*(?:\d+[.):]?\s+|[-\u2022*]\s+|[a-z][.)]\s+)");
        let list_prefix_re = Regex::new(list_pattern)
            .unwrap_or_else(|_| Regex::new(r"^\s*(?:\d+[.):]?\s+|[-*]\s+|[a-z][.)]\s+)").expect("default"));
        let list_threshold = list_cfg
            .get("threshold")
            .and_then(|v| v.as_f64())
            .unwrap_or(0.70);

        Self {
            error_output,
            dialog_pats,
            dialog_min_alpha,
            math_pats,
            ratio_pats,
            prose_re,
            prose_min_alpha,
            list_prefix_re,
            list_threshold,
        }
    }

    /// Check a single line against negative signals.
    pub fn check_line(&self, line: &str) -> Option<NegativeResult> {
        // 1. Math patterns -> Suppress
        for pat in &self.math_pats {
            if pat.is_match(line).unwrap_or(false) {
                return Some(NegativeResult::Suppress);
            }
        }

        // 2. Error output patterns -> ErrorOutput
        for pat in &self.error_output {
            if pat.is_match(line).unwrap_or(false) {
                return Some(NegativeResult::ErrorOutput);
            }
        }

        // 3. Prose pattern -> Suppress
        if self.prose_re.is_match(line).unwrap_or(false)
            && alpha_ratio(line) > self.prose_min_alpha
        {
            return Some(NegativeResult::Suppress);
        }

        // 4. Dialog patterns -> Suppress
        for pat in &self.dialog_pats {
            if pat.is_match(line).unwrap_or(false)
                && alpha_ratio(line) > self.dialog_min_alpha
            {
                return Some(NegativeResult::Suppress);
            }
        }

        // 5. Ratio patterns -> Suppress
        for pat in &self.ratio_pats {
            if pat.is_match(line).unwrap_or(false) {
                return Some(NegativeResult::Suppress);
            }
        }

        None
    }

    /// Return `true` if >threshold of non-empty lines match the list prefix pattern.
    pub fn check_list_prefix(&self, lines: &[&str]) -> bool {
        let non_empty: Vec<&&str> = lines.iter().filter(|l| !l.trim().is_empty()).collect();
        if non_empty.is_empty() {
            return false;
        }
        let matched = non_empty
            .iter()
            .filter(|l| self.list_prefix_re.is_match(l).unwrap_or(false))
            .count();
        (matched as f64 / non_empty.len() as f64) > self.list_threshold
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_filter() -> NegativeFilter {
        NegativeFilter::new(&serde_json::json!({
            "negative": {
                "error_output": [
                    "^\\s*Traceback \\(most recent call last\\)",
                    "^\\w+Error:\\s",
                    "^\\w+Exception:\\s"
                ],
                "dialog": {
                    "patterns": ["^\\s*[A-Z][a-z]{1,20}:\\s*\""],
                    "min_alpha_ratio": 0.70
                },
                "math": [
                    "\\\\frac|\\\\begin|\\\\end|\\\\sum"
                ],
                "ratio": [
                    "^\\s*\\d+:\\d+\\s"
                ],
                "prose": {
                    "pattern": "^[A-Z][a-z].+[.!?]$",
                    "min_alpha_ratio": 0.75
                },
                "list_prefix": {
                    "pattern": "^\\s*(?:\\d+[.):]?\\s+|[-*]\\s+|[a-z][.)]\\s+)",
                    "threshold": 0.70
                }
            }
        }))
    }

    #[test]
    fn test_error_output_detected() {
        let f = make_filter();
        assert_eq!(
            f.check_line("TypeError: cannot read property"),
            Some(NegativeResult::ErrorOutput)
        );
    }

    #[test]
    fn test_traceback_detected() {
        let f = make_filter();
        assert_eq!(
            f.check_line("Traceback (most recent call last):"),
            Some(NegativeResult::ErrorOutput)
        );
    }

    #[test]
    fn test_math_suppressed() {
        let f = make_filter();
        assert_eq!(
            f.check_line(r"\frac{a}{b} + \sum_{i=0}"),
            Some(NegativeResult::Suppress)
        );
    }

    #[test]
    fn test_prose_suppressed() {
        let f = make_filter();
        assert_eq!(
            f.check_line("The quick brown fox jumps over the lazy dog."),
            Some(NegativeResult::Suppress)
        );
    }

    #[test]
    fn test_code_not_suppressed() {
        let f = make_filter();
        assert_eq!(f.check_line("def foo(x): return x + 1"), None);
    }

    #[test]
    fn test_list_prefix() {
        let f = make_filter();
        let lines = vec![
            "1. First item",
            "2. Second item",
            "3. Third item",
            "4. Fourth item",
        ];
        let refs: Vec<&str> = lines.iter().map(|s| s.as_ref()).collect();
        assert!(f.check_list_prefix(&refs));
    }
}
