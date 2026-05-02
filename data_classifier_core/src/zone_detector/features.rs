//! BlockFeatures — feature extraction for prose/data zone classification.
//!
//! Used by DataDetector and ProseDetector to classify unclaimed text blocks
//! by computing 13 structural features across four groups.

use std::sync::LazyLock;
use std::collections::HashSet;

// ---------------------------------------------------------------------------
// Code keyword set
// ---------------------------------------------------------------------------

static CODE_KEYWORDS: LazyLock<HashSet<&'static str>> = LazyLock::new(|| {
    [
        "def", "class", "function", "return", "if", "else", "for", "while",
        "import", "from", "const", "let", "var", "fn", "pub", "struct", "enum",
        "match", "try", "except", "catch", "throw", "new", "async", "await",
        "yield", "lambda", "void", "int", "string", "bool", "static", "public",
        "private", "interface", "implements", "extends", "package", "module",
        "export", "require", "include", "use", "switch", "case", "break", "continue",
    ]
    .iter()
    .copied()
    .collect()
});

/// Chars treated as syntactic (code-like) punctuation.
const SYNTACTIC_CHARS: &str = "{}()[];=<>|&@#$^~";

// ---------------------------------------------------------------------------
// Public struct
// ---------------------------------------------------------------------------

/// Structural features extracted from a slice of text lines.
///
/// All ratio fields are normalized to [0.0, 1.0].
#[derive(Debug, Clone, PartialEq)]
pub struct BlockFeatures {
    // --- Prose signals ---
    /// Fraction of chars that are alphabetic or whitespace.
    pub alpha_space_ratio: f64,
    /// Sentence structure score (capitals after periods, commas, terminal punctuation).
    pub sentence_score: f64,
    /// Mean word length in chars.
    pub avg_word_length: f64,
    /// Coefficient of variation of line lengths.
    pub line_length_cv: f64,

    // --- Data signals ---
    /// Average ratio of `|`, `\t`, `,` per line.
    pub delimiter_density: f64,
    /// Structural similarity across lines (char-class profile distance).
    pub line_uniformity: f64,
    /// Fraction of tokens that are numbers.
    pub numeric_ratio: f64,
    /// Lines share a common prefix pattern.
    pub repeating_prefix: bool,

    // --- Negative signals (code absence) ---
    /// Fraction of words that are code keywords.
    pub code_keyword_density: f64,
    /// Fraction of chars that are syntactic (`{}()[];=<>|&@#$^~`).
    pub syntactic_char_ratio: f64,
    /// Consistent indentation at 2+ levels covers 40%+ of non-blank lines.
    pub indentation_pattern: bool,

    // --- Block metadata ---
    /// Total line count.
    pub block_lines: usize,
    /// Ratio of blank lines.
    pub blank_line_ratio: f64,
}

impl BlockFeatures {
    /// Extract all 13 features from a slice of line strings.
    pub fn extract(lines: &[&str]) -> BlockFeatures {
        let block_lines = lines.len();

        if block_lines == 0 {
            return BlockFeatures {
                alpha_space_ratio: 0.0,
                sentence_score: 0.0,
                avg_word_length: 0.0,
                line_length_cv: 0.0,
                delimiter_density: 0.0,
                line_uniformity: 0.0,
                numeric_ratio: 0.0,
                repeating_prefix: false,
                code_keyword_density: 0.0,
                syntactic_char_ratio: 0.0,
                indentation_pattern: false,
                block_lines: 0,
                blank_line_ratio: 0.0,
            };
        }

        let blank_count = lines.iter().filter(|l| l.trim().is_empty()).count();
        let blank_line_ratio = blank_count as f64 / block_lines as f64;

        // Aggregate character counts over all text
        let total_chars: usize = lines.iter().map(|l| l.chars().count()).sum();
        let alpha_space_chars: usize = lines
            .iter()
            .flat_map(|l| l.chars())
            .filter(|c| c.is_alphabetic() || c.is_whitespace())
            .count();
        let alpha_space_ratio = if total_chars == 0 {
            0.0
        } else {
            (alpha_space_chars as f64 / total_chars as f64).clamp(0.0, 1.0)
        };

        let syntactic_set: HashSet<char> = SYNTACTIC_CHARS.chars().collect();
        let syntactic_chars: usize = lines
            .iter()
            .flat_map(|l| l.chars())
            .filter(|c| syntactic_set.contains(c))
            .count();
        let syntactic_char_ratio = if total_chars == 0 {
            0.0
        } else {
            (syntactic_chars as f64 / total_chars as f64).clamp(0.0, 1.0)
        };

        let sentence_score = compute_sentence_score(lines);

        // Word-level stats
        let words: Vec<&str> = lines
            .iter()
            .flat_map(|l| l.split_whitespace())
            .collect();
        let avg_word_length = if words.is_empty() {
            0.0
        } else {
            words.iter().map(|w| w.chars().count()).sum::<usize>() as f64 / words.len() as f64
        };

        // Numeric ratio
        let numeric_count = words.iter().filter(|w| is_numeric_token(w)).count();
        let numeric_ratio = if words.is_empty() {
            0.0
        } else {
            (numeric_count as f64 / words.len() as f64).clamp(0.0, 1.0)
        };

        // Code keyword density
        let kw_count = words
            .iter()
            .filter(|w| {
                let lower = w.to_lowercase();
                CODE_KEYWORDS.contains(lower.as_str())
            })
            .count();
        let code_keyword_density = if words.is_empty() {
            0.0
        } else {
            (kw_count as f64 / words.len() as f64).clamp(0.0, 1.0)
        };

        // Line length CV
        let non_blank_lengths: Vec<f64> = lines
            .iter()
            .filter(|l| !l.trim().is_empty())
            .map(|l| l.len() as f64)
            .collect();
        let line_length_cv = coefficient_of_variation(&non_blank_lengths);

        // Delimiter density
        let delimiter_density = compute_delimiter_density(lines);

        // Line uniformity
        let line_uniformity = compute_line_uniformity(lines);

        // Repeating prefix
        let repeating_prefix = detect_repeating_prefix(lines);

        // Indentation pattern
        let indentation_pattern = detect_indentation_pattern(lines);

        BlockFeatures {
            alpha_space_ratio,
            sentence_score,
            avg_word_length,
            line_length_cv,
            delimiter_density,
            line_uniformity,
            numeric_ratio,
            repeating_prefix,
            code_keyword_density,
            syntactic_char_ratio,
            indentation_pattern,
            block_lines,
            blank_line_ratio,
        }
    }
}

// ---------------------------------------------------------------------------
// Helper functions
// ---------------------------------------------------------------------------

/// Score sentence structure for a slice of lines.
///
/// For each non-blank line score 0-1.0:
/// - Starts with uppercase: +0.3
/// - Contains commas: +0.2
/// - Ends with `.`, `!`, or `?`: +0.3
/// - Has 3+ spaces: +0.2
///
/// Returns the average across non-blank lines.
fn compute_sentence_score(lines: &[&str]) -> f64 {
    let scored: Vec<f64> = lines
        .iter()
        .filter(|l| !l.trim().is_empty())
        .map(|line| {
            let mut score = 0.0_f64;
            let trimmed = line.trim();

            if trimmed.starts_with(|c: char| c.is_uppercase()) {
                score += 0.3;
            }
            if trimmed.contains(',') {
                score += 0.2;
            }
            if trimmed.ends_with(['.', '!', '?']) {
                score += 0.3;
            }
            if line.chars().filter(|&c| c == ' ').count() >= 3 {
                score += 0.2;
            }
            score.clamp(0.0, 1.0)
        })
        .collect();

    if scored.is_empty() {
        0.0
    } else {
        scored.iter().sum::<f64>() / scored.len() as f64
    }
}

/// Coefficient of variation: std_dev / mean.
///
/// Returns 0.0 for fewer than 2 values or mean < 1.0.
fn coefficient_of_variation(values: &[f64]) -> f64 {
    if values.len() < 2 {
        return 0.0;
    }
    let mean = values.iter().sum::<f64>() / values.len() as f64;
    if mean < 1.0 {
        return 0.0;
    }
    let variance =
        values.iter().map(|v| (v - mean).powi(2)).sum::<f64>() / values.len() as f64;
    (variance.sqrt() / mean).clamp(0.0, f64::MAX)
}

/// Average ratio of `|`, `\t`, `,` per line.
fn compute_delimiter_density(lines: &[&str]) -> f64 {
    let non_blank: Vec<&&str> = lines.iter().filter(|l| !l.trim().is_empty()).collect();
    if non_blank.is_empty() {
        return 0.0;
    }
    let total: f64 = non_blank
        .iter()
        .map(|line| {
            let len = line.chars().count();
            if len == 0 {
                return 0.0;
            }
            let delim_count = line.chars().filter(|&c| c == '|' || c == '\t' || c == ',').count();
            delim_count as f64 / len as f64
        })
        .sum();
    (total / non_blank.len() as f64).clamp(0.0, 1.0)
}

/// Structural similarity across lines using char-class profiles.
///
/// For each non-blank line compute [alpha_ratio, digit_ratio, punct_ratio].
/// Compute average distance from mean profile.
/// Return `(1.0 - avg_dist * 3.0).clamp(0.0, 1.0)`.
fn compute_line_uniformity(lines: &[&str]) -> f64 {
    let profiles: Vec<[f64; 3]> = lines
        .iter()
        .filter(|l| !l.trim().is_empty())
        .map(|line| {
            let chars: Vec<char> = line.chars().collect();
            let n = chars.len() as f64;
            if n == 0.0 {
                return [0.0, 0.0, 0.0];
            }
            let alpha = chars.iter().filter(|c| c.is_alphabetic()).count() as f64 / n;
            let digit = chars.iter().filter(|c| c.is_numeric()).count() as f64 / n;
            let punct = chars
                .iter()
                .filter(|c| c.is_ascii_punctuation())
                .count() as f64
                / n;
            [alpha, digit, punct]
        })
        .collect();

    if profiles.len() < 2 {
        // Single-line or empty — maximally uniform
        return 1.0;
    }

    // Mean profile
    let mean: [f64; 3] = {
        let mut acc = [0.0_f64; 3];
        for p in &profiles {
            acc[0] += p[0];
            acc[1] += p[1];
            acc[2] += p[2];
        }
        let n = profiles.len() as f64;
        [acc[0] / n, acc[1] / n, acc[2] / n]
    };

    // Average L1 distance from mean
    let avg_dist = profiles
        .iter()
        .map(|p| (p[0] - mean[0]).abs() + (p[1] - mean[1]).abs() + (p[2] - mean[2]).abs())
        .sum::<f64>()
        / profiles.len() as f64;

    (1.0 - avg_dist * 3.0).clamp(0.0, 1.0)
}

/// Normalize a char: digits → '0', letters → 'a', others kept as-is.
fn normalize_char(c: char) -> char {
    if c.is_ascii_digit() {
        '0'
    } else if c.is_alphabetic() {
        'a'
    } else {
        c
    }
}

/// Return true if 60%+ of non-blank lines share the same normalized prefix.
///
/// Considers only the first 10 chars of each line.
/// Requires at least 3 non-blank lines.
fn detect_repeating_prefix(lines: &[&str]) -> bool {
    let non_blank: Vec<&&str> = lines.iter().filter(|l| !l.trim().is_empty()).collect();
    if non_blank.len() < 3 {
        return false;
    }

    // Build normalized prefix map
    let mut prefix_counts: std::collections::HashMap<String, usize> =
        std::collections::HashMap::new();
    for line in &non_blank {
        let prefix: String = line.chars().take(10).map(normalize_char).collect();
        *prefix_counts.entry(prefix).or_insert(0) += 1;
    }

    let threshold = non_blank.len() as f64 * 0.60;
    prefix_counts.values().any(|&count| count as f64 >= threshold)
}

/// Return true if 2+ distinct indentation levels cover 40%+ of non-blank lines.
fn detect_indentation_pattern(lines: &[&str]) -> bool {
    let non_blank: Vec<&&str> = lines.iter().filter(|l| !l.trim().is_empty()).collect();
    if non_blank.len() < 3 {
        return false;
    }

    let indent_levels: Vec<usize> = non_blank
        .iter()
        .map(|line| {
            line.chars()
                .take_while(|c| *c == ' ' || *c == '\t')
                .count()
        })
        .collect();

    let distinct_levels: HashSet<usize> = indent_levels.iter().copied().collect();
    if distinct_levels.len() < 2 {
        return false;
    }

    // At least one non-zero indent level
    let max_indent = *indent_levels.iter().max().unwrap_or(&0);
    if max_indent == 0 {
        return false;
    }

    // 40%+ of non-blank lines are indented
    let indented_count = indent_levels.iter().filter(|&&n| n > 0).count();
    indented_count as f64 / non_blank.len() as f64 >= 0.40
}

/// Return true if the token looks like a number.
///
/// Strip `,.$%-+`, then check that remaining chars are all digits, `.`, or `,`.
fn is_numeric_token(token: &str) -> bool {
    let stripped: String = token
        .chars()
        .filter(|c| !matches!(c, '$' | '%' | '-' | '+'))
        .collect();
    if stripped.is_empty() {
        return false;
    }
    stripped.chars().all(|c| c.is_ascii_digit() || c == '.' || c == ',')
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_features_prose_paragraph() {
        let lines = vec![
            "The quick brown fox jumped over the lazy dog.",
            "It was a bright cold day in April, and the clocks were striking thirteen.",
            "All happy families are alike; each unhappy family is unhappy in its own way.",
            "It is a truth universally acknowledged, that a single man in possession of a fortune.",
            "Call me Ishmael. Some years ago, I thought I would sail about.",
        ];
        let f = BlockFeatures::extract(&lines);

        assert!(f.alpha_space_ratio > 0.85, "alpha_space_ratio={}", f.alpha_space_ratio);
        assert!(f.sentence_score > 0.5, "sentence_score={}", f.sentence_score);
        assert!(f.code_keyword_density < 0.05, "code_keyword_density={}", f.code_keyword_density);
        assert!(f.syntactic_char_ratio < 0.02, "syntactic_char_ratio={}", f.syntactic_char_ratio);
        assert!(f.delimiter_density < 0.1, "delimiter_density={}", f.delimiter_density);
    }

    #[test]
    fn test_features_csv_data() {
        // Numeric-only TSV: all rows have the same char-class profile (digits + tabs)
        // → high delimiter density AND high line uniformity.
        // Each "N\tN\tN\tN\tN\tN\tN\tN\tN\tN" = 9 tabs in 19 chars ≈ 0.47 density.
        let lines = vec![
            "1\t2\t3\t4\t5\t6\t7\t8\t9\t0",
            "10\t20\t30\t40\t50\t60\t70\t80\t90\t0",
            "11\t21\t31\t41\t51\t61\t71\t81\t91\t1",
            "12\t22\t32\t42\t52\t62\t72\t82\t92\t2",
            "13\t23\t33\t43\t53\t63\t73\t83\t93\t3",
            "14\t24\t34\t44\t54\t64\t74\t84\t94\t4",
        ];
        let f = BlockFeatures::extract(&lines);

        assert!(f.delimiter_density > 0.3, "delimiter_density={}", f.delimiter_density);
        assert!(f.line_uniformity > 0.5, "line_uniformity={}", f.line_uniformity);
        assert!(f.sentence_score < 0.3, "sentence_score={}", f.sentence_score);
    }

    #[test]
    fn test_features_log_lines() {
        let lines = vec![
            "2024-01-15 10:23:45 INFO  Starting application server",
            "2024-01-15 10:23:46 DEBUG Loaded configuration from /etc/app.conf",
            "2024-01-15 10:23:47 INFO  Listening on port 8080",
            "2024-01-15 10:23:48 WARN  Connection pool nearly full: 95/100",
            "2024-01-15 10:23:49 ERROR Failed to connect to database: timeout",
            "2024-01-15 10:23:50 INFO  Retrying connection attempt 1/3",
        ];
        let f = BlockFeatures::extract(&lines);

        assert!(f.repeating_prefix, "repeating_prefix should be true for timestamp-prefixed log lines");
        assert!(f.line_uniformity > 0.5, "line_uniformity={}", f.line_uniformity);
    }

    #[test]
    fn test_features_code_block() {
        let lines = vec![
            "def process_data(items):",
            "    result = []",
            "    for item in items:",
            "        if item.is_valid():",
            "            result.append(item.transform())",
            "        else:",
            "            continue",
            "    return result",
        ];
        let f = BlockFeatures::extract(&lines);

        assert!(f.code_keyword_density > 0.3, "code_keyword_density={}", f.code_keyword_density);
        assert!(f.indentation_pattern, "indentation_pattern should be true");
        assert!(f.syntactic_char_ratio > 0.02, "syntactic_char_ratio={}", f.syntactic_char_ratio);
    }

    #[test]
    fn test_features_empty_block() {
        let lines: Vec<&str> = vec![];
        let f = BlockFeatures::extract(&lines);

        assert_eq!(f.block_lines, 0);
        assert_eq!(f.alpha_space_ratio, 0.0);
    }

    #[test]
    fn test_features_single_line() {
        let lines = vec!["The quick brown fox jumps over the lazy dog."];
        let f = BlockFeatures::extract(&lines);

        assert_eq!(f.block_lines, 1);
        assert!(f.alpha_space_ratio > 0.9, "alpha_space_ratio={}", f.alpha_space_ratio);
    }
}
