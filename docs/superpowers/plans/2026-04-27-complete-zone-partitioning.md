# Complete Zone Partitioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every block of text gets a zone type + confidence — no unlabeled gaps. Two new detector passes (DataDetector, ProseDetector) fill the gaps left by existing detectors.

**Architecture:** Add `BlockFeatures` extraction, `DataDetector` (step 11), and `ProseDetector` (step 12) to the existing 10-step zone pipeline in `data_classifier_core/src/zone_detector/`. The pre-screen fast path is updated to produce prose blocks instead of returning empty. The feature struct is designed for future meta-classifier promotion.

**Tech Stack:** Rust, regex crate, existing zone_detector infrastructure (ZoneBlock, ZoneType, ZoneOrchestrator).

**Spec:** `docs/superpowers/specs/2026-04-27-complete-zone-partitioning-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/zone_detector/features.rs` | Create | `BlockFeatures` struct + extraction from line slices |
| `src/zone_detector/data_detector.rs` | Create | Step 11: detect tabular/CSV/log blocks in unclaimed lines |
| `src/zone_detector/prose_detector.rs` | Create | Step 12: classify remaining lines as natural_language |
| `src/zone_detector/mod.rs` | Modify | Wire steps 11-12 into pipeline, update pre-screen path |
| `src/zone_detector/config.rs` | Modify | Add `data_detector_enabled`, `prose_detector_enabled` flags |
| `src/zone_detector/pre_screen.rs` | Modify | Return classification hint instead of bare bool |
| `tests/zone_partitioning.rs` | Create | Integration tests for complete partitioning |

---

### Task 1: BlockFeatures struct and extraction

**Files:**
- Create: `data_classifier_core/src/zone_detector/features.rs`

- [ ] **Step 1: Write the failing test**

Add to the bottom of `features.rs`:

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_features_prose_paragraph() {
        let lines = vec![
            "The quick brown fox jumps over the lazy dog.",
            "This is a second sentence with normal structure.",
            "And here is a third line of natural text.",
        ];
        let f = BlockFeatures::extract(&lines);
        assert!(f.alpha_space_ratio > 0.85, "prose should have high alpha ratio: {}", f.alpha_space_ratio);
        assert!(f.sentence_score > 0.5, "prose should have sentence structure: {}", f.sentence_score);
        assert!(f.code_keyword_density < 0.05, "prose should have no code keywords: {}", f.code_keyword_density);
        assert!(f.syntactic_char_ratio < 0.02, "prose should have low syntactic chars: {}", f.syntactic_char_ratio);
        assert!(f.delimiter_density < 0.1, "prose should have low delimiter density: {}", f.delimiter_density);
    }

    #[test]
    fn test_features_csv_data() {
        let lines = vec![
            "name,email,phone,city",
            "Alice,alice@example.com,555-0101,NYC",
            "Bob,bob@example.com,555-0102,LA",
            "Charlie,charlie@example.com,555-0103,Chicago",
        ];
        let f = BlockFeatures::extract(&lines);
        assert!(f.delimiter_density > 0.3, "CSV should have high delimiter density: {}", f.delimiter_density);
        assert!(f.line_uniformity > 0.5, "CSV should have uniform lines: {}", f.line_uniformity);
        assert!(f.sentence_score < 0.3, "CSV should have low sentence score: {}", f.sentence_score);
    }

    #[test]
    fn test_features_log_lines() {
        let lines = vec![
            "2024-01-15 10:23:01 INFO  Starting application",
            "2024-01-15 10:23:02 INFO  Loading config from /etc/app.conf",
            "2024-01-15 10:23:02 WARN  Config key missing: timeout",
            "2024-01-15 10:23:03 ERROR Connection refused: 10.0.0.5:5432",
        ];
        let f = BlockFeatures::extract(&lines);
        assert!(f.repeating_prefix, "log lines should have repeating prefix");
        assert!(f.line_uniformity > 0.5, "log lines should be uniform: {}", f.line_uniformity);
    }

    #[test]
    fn test_features_code_block() {
        let lines = vec![
            "def process(data):",
            "    result = []",
            "    for item in data:",
            "        result.append(item)",
            "    return result",
        ];
        let f = BlockFeatures::extract(&lines);
        assert!(f.code_keyword_density > 0.3, "code should have keyword density: {}", f.code_keyword_density);
        assert!(f.indentation_pattern, "code should have indentation");
        assert!(f.syntactic_char_ratio > 0.02, "code should have syntactic chars: {}", f.syntactic_char_ratio);
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
        let lines = vec!["Hello world."];
        let f = BlockFeatures::extract(&lines);
        assert_eq!(f.block_lines, 1);
        assert!(f.alpha_space_ratio > 0.9);
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd data_classifier_core && /Users/guyguzner/.cargo/bin/cargo test features::tests --no-default-features 2>&1 | tail -5`
Expected: FAIL — module `features` not found

- [ ] **Step 3: Write the implementation**

Create `data_classifier_core/src/zone_detector/features.rs`:

```rust
//! Block feature extraction for zone classification.
//!
//! Extracts a `BlockFeatures` struct from a slice of lines. Designed as the
//! feature vector for hand-tuned scoring (v1) and future meta-classifier
//! promotion (v2).

use std::collections::HashSet;
use std::sync::LazyLock;

static CODE_KEYWORDS: LazyLock<HashSet<&'static str>> = LazyLock::new(|| {
    [
        "def", "class", "function", "return", "if", "else", "for", "while",
        "import", "from", "const", "let", "var", "fn", "pub", "struct",
        "enum", "match", "try", "except", "catch", "throw", "new", "async",
        "await", "yield", "lambda", "void", "int", "string", "bool",
        "static", "public", "private", "interface", "implements", "extends",
        "package", "module", "export", "require", "include", "use",
        "switch", "case", "break", "continue",
    ]
    .into_iter()
    .collect()
});

static SYNTACTIC_CHARS: &str = "{}()[];=<>|&@#$^~";

/// Feature vector extracted from a block of lines.
///
/// All ratio fields are normalized to [0.0, 1.0].
/// Designed for both hand-tuned scoring and future classifier training.
#[derive(Debug, Clone)]
pub struct BlockFeatures {
    // -- Prose signals --
    /// Fraction of characters that are alphabetic or whitespace.
    pub alpha_space_ratio: f64,
    /// Sentence structure score: capitals after periods, commas, question marks.
    pub sentence_score: f64,
    /// Mean word length in characters.
    pub avg_word_length: f64,
    /// Coefficient of variation of line lengths (std_dev / mean).
    pub line_length_cv: f64,

    // -- Data signals --
    /// Average ratio of delimiter chars (|, \t, ,) per line.
    pub delimiter_density: f64,
    /// Structural similarity across lines (0.0 = varied, 1.0 = identical structure).
    pub line_uniformity: f64,
    /// Fraction of whitespace-delimited tokens that are numeric.
    pub numeric_ratio: f64,
    /// Whether lines share a common prefix pattern (timestamps, log levels).
    pub repeating_prefix: bool,

    // -- Negative signals (code absence) --
    /// Fraction of words that are code keywords.
    pub code_keyword_density: f64,
    /// Fraction of characters that are syntactic ({, }, (, ), ;, =, etc.).
    pub syntactic_char_ratio: f64,
    /// Whether lines show consistent indentation (2+ levels).
    pub indentation_pattern: bool,

    // -- Block metadata --
    /// Number of lines in the block.
    pub block_lines: usize,
    /// Ratio of blank lines to total lines.
    pub blank_line_ratio: f64,
}

impl BlockFeatures {
    /// Extract features from a slice of line strings.
    pub fn extract(lines: &[&str]) -> Self {
        if lines.is_empty() {
            return Self::empty();
        }

        let non_blank: Vec<&&str> = lines.iter().filter(|l| !l.trim().is_empty()).collect();
        let non_blank_count = non_blank.len().max(1);
        let total_chars: usize = lines.iter().map(|l| l.len()).sum();
        let total_chars_f = total_chars.max(1) as f64;

        // Alpha + space ratio
        let alpha_space: usize = lines
            .iter()
            .flat_map(|l| l.chars())
            .filter(|c| c.is_alphabetic() || c.is_whitespace())
            .count();
        let alpha_space_ratio = alpha_space as f64 / total_chars_f;

        // Sentence structure score
        let sentence_score = Self::compute_sentence_score(lines);

        // Average word length
        let words: Vec<&str> = lines
            .iter()
            .flat_map(|l| l.split_whitespace())
            .collect();
        let avg_word_length = if words.is_empty() {
            0.0
        } else {
            words.iter().map(|w| w.len()).sum::<usize>() as f64 / words.len() as f64
        };

        // Line length coefficient of variation
        let line_lengths: Vec<f64> = non_blank.iter().map(|l| l.len() as f64).collect();
        let line_length_cv = Self::coefficient_of_variation(&line_lengths);

        // Delimiter density (|, \t, ,)
        let delimiter_count: usize = lines
            .iter()
            .flat_map(|l| l.chars())
            .filter(|c| *c == '|' || *c == '\t' || *c == ',')
            .count();
        let delimiter_density = delimiter_count as f64 / non_blank_count as f64;

        // Line uniformity — compare char-class profiles across lines
        let line_uniformity = Self::compute_line_uniformity(&non_blank);

        // Numeric ratio
        let numeric_tokens = words.iter().filter(|w| Self::is_numeric_token(w)).count();
        let numeric_ratio = if words.is_empty() {
            0.0
        } else {
            numeric_tokens as f64 / words.len() as f64
        };

        // Repeating prefix
        let repeating_prefix = Self::detect_repeating_prefix(&non_blank);

        // Code keyword density
        let keyword_hits = words
            .iter()
            .filter(|w| CODE_KEYWORDS.contains(w.to_lowercase().trim_end_matches(|c: char| !c.is_alphanumeric())))
            .count();
        let code_keyword_density = if words.is_empty() {
            0.0
        } else {
            keyword_hits as f64 / words.len() as f64
        };

        // Syntactic char ratio
        let syn_count: usize = lines
            .iter()
            .flat_map(|l| l.chars())
            .filter(|c| SYNTACTIC_CHARS.contains(*c))
            .count();
        let syntactic_char_ratio = syn_count as f64 / total_chars_f;

        // Indentation pattern
        let indented_lines = non_blank
            .iter()
            .filter(|l| l.starts_with("    ") || l.starts_with('\t'))
            .count();
        let indentation_pattern = non_blank.len() >= 3
            && indented_lines as f64 / non_blank.len() as f64 > 0.4;

        // Block metadata
        let blank_count = lines.iter().filter(|l| l.trim().is_empty()).count();
        let blank_line_ratio = blank_count as f64 / lines.len() as f64;

        Self {
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
            block_lines: lines.len(),
            blank_line_ratio,
        }
    }

    fn empty() -> Self {
        Self {
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
        }
    }

    /// Sentence structure: fraction of non-blank lines that look like sentences
    /// (start with uppercase, contain commas or periods, end with punctuation).
    fn compute_sentence_score(lines: &[&str]) -> f64 {
        let non_blank: Vec<&&str> = lines.iter().filter(|l| !l.trim().is_empty()).collect();
        if non_blank.is_empty() {
            return 0.0;
        }

        let mut score_sum = 0.0;
        for line in &non_blank {
            let trimmed = line.trim();
            let mut line_score = 0.0;

            // Starts with uppercase letter
            if trimmed.chars().next().map(|c| c.is_uppercase()).unwrap_or(false) {
                line_score += 0.3;
            }
            // Contains commas (clause structure)
            if trimmed.contains(',') {
                line_score += 0.2;
            }
            // Ends with sentence-terminal punctuation
            if trimmed.ends_with('.') || trimmed.ends_with('!') || trimmed.ends_with('?') {
                line_score += 0.3;
            }
            // Contains spaces (multi-word)
            if trimmed.matches(' ').count() >= 3 {
                line_score += 0.2;
            }

            score_sum += line_score.min(1.0);
        }

        score_sum / non_blank.len() as f64
    }

    /// Coefficient of variation = std_dev / mean. Returns 0.0 for empty/single.
    fn coefficient_of_variation(values: &[f64]) -> f64 {
        if values.len() < 2 {
            return 0.0;
        }
        let mean = values.iter().sum::<f64>() / values.len() as f64;
        if mean < 1.0 {
            return 0.0;
        }
        let variance = values.iter().map(|v| (v - mean).powi(2)).sum::<f64>() / values.len() as f64;
        variance.sqrt() / mean
    }

    /// Compare character-class profiles across lines.
    /// Each line gets a profile: (alpha_ratio, digit_ratio, punct_ratio).
    /// Uniformity = 1.0 - average pairwise distance.
    fn compute_line_uniformity(non_blank: &[&&str]) -> f64 {
        if non_blank.len() < 2 {
            return 0.0;
        }

        let profiles: Vec<[f64; 3]> = non_blank
            .iter()
            .map(|l| {
                let len = l.len().max(1) as f64;
                let alpha = l.chars().filter(|c| c.is_alphabetic()).count() as f64 / len;
                let digit = l.chars().filter(|c| c.is_ascii_digit()).count() as f64 / len;
                let punct = l.chars().filter(|c| c.is_ascii_punctuation()).count() as f64 / len;
                [alpha, digit, punct]
            })
            .collect();

        // Average profile
        let n = profiles.len() as f64;
        let avg = [
            profiles.iter().map(|p| p[0]).sum::<f64>() / n,
            profiles.iter().map(|p| p[1]).sum::<f64>() / n,
            profiles.iter().map(|p| p[2]).sum::<f64>() / n,
        ];

        // Average distance from mean profile
        let avg_dist: f64 = profiles
            .iter()
            .map(|p| {
                ((p[0] - avg[0]).powi(2) + (p[1] - avg[1]).powi(2) + (p[2] - avg[2]).powi(2)).sqrt()
            })
            .sum::<f64>()
            / n;

        // Invert: small distance = high uniformity. Clamp to [0, 1].
        (1.0 - avg_dist * 3.0).clamp(0.0, 1.0)
    }

    /// Check if 60%+ of non-blank lines share a common prefix (first 10 chars).
    fn detect_repeating_prefix(non_blank: &[&&str]) -> bool {
        if non_blank.len() < 3 {
            return false;
        }
        // Extract first-10-char prefix, normalized (digits→0, letters→a)
        let prefixes: Vec<String> = non_blank
            .iter()
            .map(|l| {
                l.chars()
                    .take(10)
                    .map(|c| {
                        if c.is_ascii_digit() { '0' }
                        else if c.is_alphabetic() { 'a' }
                        else { c }
                    })
                    .collect()
            })
            .collect();

        // Most common prefix
        let mut counts = std::collections::HashMap::new();
        for p in &prefixes {
            *counts.entry(p.as_str()).or_insert(0usize) += 1;
        }
        let max_count = counts.values().max().copied().unwrap_or(0);
        max_count as f64 / non_blank.len() as f64 >= 0.60
    }

    fn is_numeric_token(token: &str) -> bool {
        let stripped = token.trim_matches(|c: char| c == ',' || c == '.' || c == '%' || c == '$' || c == '-' || c == '+');
        !stripped.is_empty() && stripped.chars().all(|c| c.is_ascii_digit() || c == '.' || c == ',')
    }
}
```

- [ ] **Step 4: Register the module in mod.rs**

Add `mod features;` and `pub use features::BlockFeatures;` to `data_classifier_core/src/zone_detector/mod.rs`:

```rust
// After existing module declarations (line ~28):
mod features;

// After existing pub use (line ~29):
pub use features::BlockFeatures;
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd data_classifier_core && /Users/guyguzner/.cargo/bin/cargo test features::tests 2>&1 | tail -15`
Expected: 6 tests pass

- [ ] **Step 6: Commit**

```bash
git add data_classifier_core/src/zone_detector/features.rs data_classifier_core/src/zone_detector/mod.rs
git commit -m "feat(zones): add BlockFeatures struct and extraction"
```

---

### Task 2: DataDetector — step 11

**Files:**
- Create: `data_classifier_core/src/zone_detector/data_detector.rs`
- Modify: `data_classifier_core/src/zone_detector/mod.rs`

- [ ] **Step 1: Write the failing test**

Add to `data_detector.rs`:

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;

    #[test]
    fn test_csv_detected() {
        let lines: Vec<&str> = vec![
            "name,email,phone",
            "Alice,alice@example.com,555-0101",
            "Bob,bob@example.com,555-0102",
            "Charlie,charlie@example.com,555-0103",
        ];
        let claimed: HashSet<usize> = HashSet::new();
        let det = DataDetector::default();
        let (blocks, new_claimed) = det.detect(&lines, &claimed);
        assert_eq!(blocks.len(), 1, "should detect CSV block");
        assert_eq!(blocks[0].zone_type, ZoneType::Data);
        assert_eq!(blocks[0].language_hint, "csv");
        assert!(!new_claimed.is_empty());
    }

    #[test]
    fn test_log_lines_detected() {
        let lines: Vec<&str> = vec![
            "2024-01-15 10:23:01 INFO  Starting application",
            "2024-01-15 10:23:02 INFO  Loading config",
            "2024-01-15 10:23:02 WARN  Config key missing",
            "2024-01-15 10:23:03 ERROR Connection refused",
        ];
        let claimed: HashSet<usize> = HashSet::new();
        let det = DataDetector::default();
        let (blocks, _) = det.detect(&lines, &claimed);
        assert_eq!(blocks.len(), 1, "should detect log block");
        assert_eq!(blocks[0].zone_type, ZoneType::Data);
        assert_eq!(blocks[0].language_hint, "log");
    }

    #[test]
    fn test_pipe_table_detected() {
        let lines: Vec<&str> = vec![
            "| Name    | Score | Grade |",
            "|---------|-------|-------|",
            "| Alice   | 95    | A     |",
            "| Bob     | 87    | B     |",
        ];
        let claimed: HashSet<usize> = HashSet::new();
        let det = DataDetector::default();
        let (blocks, _) = det.detect(&lines, &claimed);
        assert_eq!(blocks.len(), 1, "should detect pipe table");
        assert_eq!(blocks[0].zone_type, ZoneType::Data);
        assert_eq!(blocks[0].language_hint, "table");
    }

    #[test]
    fn test_prose_not_detected_as_data() {
        let lines: Vec<&str> = vec![
            "The quick brown fox jumps over the lazy dog.",
            "This is a normal paragraph about nothing in particular.",
            "It should not be classified as data.",
        ];
        let claimed: HashSet<usize> = HashSet::new();
        let det = DataDetector::default();
        let (blocks, _) = det.detect(&lines, &claimed);
        assert!(blocks.is_empty(), "prose should not be detected as data");
    }

    #[test]
    fn test_skips_claimed_lines() {
        let lines: Vec<&str> = vec![
            "name,email,phone",
            "Alice,alice@example.com,555-0101",
            "Bob,bob@example.com,555-0102",
        ];
        let claimed: HashSet<usize> = [0, 1, 2].into_iter().collect();
        let det = DataDetector::default();
        let (blocks, _) = det.detect(&lines, &claimed);
        assert!(blocks.is_empty(), "should skip claimed lines");
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd data_classifier_core && /Users/guyguzner/.cargo/bin/cargo test data_detector::tests --no-default-features 2>&1 | tail -5`
Expected: FAIL — module not found

- [ ] **Step 3: Write the implementation**

Create `data_classifier_core/src/zone_detector/data_detector.rs`:

```rust
//! DataDetector — step 11 of the zone pipeline.
//!
//! Claims unclaimed blocks that exhibit tabular, CSV, log, or structured-data
//! patterns. Runs after all code/config/markup detectors but before ProseDetector.

use std::collections::HashSet;

use crate::zone_detector::features::BlockFeatures;
use crate::zone_detector::types::{ZoneBlock, ZoneType};

/// Thresholds for data classification.
pub struct DataDetector {
    /// Minimum delimiter density (|, \t, ,) to trigger CSV/table detection.
    pub min_delimiter_density: f64,
    /// Minimum line uniformity for log/structured detection.
    pub min_line_uniformity: f64,
    /// Minimum block size (lines) to consider.
    pub min_block_lines: usize,
}

impl Default for DataDetector {
    fn default() -> Self {
        Self {
            min_delimiter_density: 0.3,
            min_line_uniformity: 0.5,
            min_block_lines: 3,
        }
    }
}

impl DataDetector {
    /// Detect data blocks in unclaimed lines.
    ///
    /// Returns detected blocks and the updated claimed set.
    pub fn detect(
        &self,
        lines: &[&str],
        claimed: &HashSet<usize>,
    ) -> (Vec<ZoneBlock>, HashSet<usize>) {
        let mut blocks = Vec::new();
        let mut new_claimed = claimed.clone();

        // Find contiguous unclaimed non-empty regions
        let regions = Self::find_unclaimed_regions(lines, claimed);

        for (start, end) in regions {
            let block_lines: Vec<&str> = lines[start..end].to_vec();
            if block_lines.len() < self.min_block_lines {
                continue;
            }

            let features = BlockFeatures::extract(&block_lines);

            // Classify based on features
            if let Some((hint, confidence)) = self.classify_data(&features, &block_lines) {
                blocks.push(ZoneBlock {
                    start_line: start,
                    end_line: end,
                    zone_type: ZoneType::Data,
                    confidence,
                    method: "data_detector".to_string(),
                    language_hint: hint,
                    language_confidence: 0.0,
                    text: block_lines.join("\n"),
                });
                for i in start..end {
                    new_claimed.insert(i);
                }
            }
        }

        (blocks, new_claimed)
    }

    /// Classify a block as data, returning (sub_hint, confidence) or None.
    fn classify_data(&self, f: &BlockFeatures, lines: &[&str]) -> Option<(String, f64)> {
        // 1. Pipe-delimited table: most lines have 2+ pipe chars
        let pipe_lines = lines
            .iter()
            .filter(|l| !l.trim().is_empty())
            .filter(|l| l.matches('|').count() >= 2)
            .count();
        let non_blank = lines.iter().filter(|l| !l.trim().is_empty()).count().max(1);
        if pipe_lines as f64 / non_blank as f64 >= 0.70 {
            let conf = 0.60 + (pipe_lines as f64 / non_blank as f64) * 0.30;
            return Some(("table".to_string(), conf.min(0.95)));
        }

        // 2. CSV: high comma density + uniform lines + low sentence score
        if f.delimiter_density > self.min_delimiter_density
            && f.line_uniformity > self.min_line_uniformity
            && f.sentence_score < 0.3
        {
            let conf = 0.55 + f.delimiter_density.min(1.0) * 0.20 + f.line_uniformity * 0.15;
            return Some(("csv".to_string(), conf.min(0.95)));
        }

        // 3. Tab-separated
        let tab_lines = lines
            .iter()
            .filter(|l| !l.trim().is_empty())
            .filter(|l| l.contains('\t'))
            .count();
        if tab_lines as f64 / non_blank as f64 >= 0.70 && f.line_uniformity > 0.4 {
            let conf = 0.60 + f.line_uniformity * 0.25;
            return Some(("csv".to_string(), conf.min(0.95)));
        }

        // 4. Log lines: repeating prefix + uniform structure
        if f.repeating_prefix && f.line_uniformity > self.min_line_uniformity {
            let conf = 0.55 + f.line_uniformity * 0.25;
            return Some(("log".to_string(), conf.min(0.90)));
        }

        // 5. Structured rows: high uniformity + numeric content + not prose
        if f.line_uniformity > 0.6 && f.numeric_ratio > 0.15 && f.sentence_score < 0.2 {
            let conf = 0.50 + f.line_uniformity * 0.20 + f.numeric_ratio.min(0.5) * 0.20;
            return Some(("structured".to_string(), conf.min(0.90)));
        }

        None
    }

    /// Find contiguous unclaimed, non-empty line regions. Allows up to 1 blank
    /// line gap within a region.
    fn find_unclaimed_regions(
        lines: &[&str],
        claimed: &HashSet<usize>,
    ) -> Vec<(usize, usize)> {
        let mut regions = Vec::new();
        let mut i = 0;
        while i < lines.len() {
            // Skip claimed or blank
            if claimed.contains(&i) || lines[i].trim().is_empty() {
                i += 1;
                continue;
            }
            // Start of a region
            let start = i;
            let mut end = i;
            let mut consecutive_blank = 0;
            while end < lines.len() {
                if claimed.contains(&end) {
                    break;
                }
                if lines[end].trim().is_empty() {
                    consecutive_blank += 1;
                    if consecutive_blank > 1 {
                        break;
                    }
                } else {
                    consecutive_blank = 0;
                }
                end += 1;
            }
            // Trim trailing blanks
            while end > start && lines[end - 1].trim().is_empty() {
                end -= 1;
            }
            if end > start {
                regions.push((start, end));
            }
            i = end;
        }
        regions
    }
}
```

- [ ] **Step 4: Register module in mod.rs**

Add after the `features` module declaration:

```rust
mod data_detector;
```

- [ ] **Step 5: Run tests**

Run: `cd data_classifier_core && /Users/guyguzner/.cargo/bin/cargo test data_detector::tests 2>&1 | tail -15`
Expected: 5 tests pass

- [ ] **Step 6: Commit**

```bash
git add data_classifier_core/src/zone_detector/data_detector.rs data_classifier_core/src/zone_detector/mod.rs
git commit -m "feat(zones): add DataDetector — step 11 (CSV/table/log detection)"
```

---

### Task 3: ProseDetector — step 12

**Files:**
- Create: `data_classifier_core/src/zone_detector/prose_detector.rs`
- Modify: `data_classifier_core/src/zone_detector/mod.rs`

- [ ] **Step 1: Write the failing test**

Add to `prose_detector.rs`:

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;

    #[test]
    fn test_prose_paragraph() {
        let lines: Vec<&str> = vec![
            "The quick brown fox jumps over the lazy dog.",
            "This is a second sentence with normal structure.",
            "And here is a third line of natural text.",
        ];
        let claimed: HashSet<usize> = HashSet::new();
        let det = ProseDetector::default();
        let blocks = det.detect(&lines, &claimed);
        assert_eq!(blocks.len(), 1);
        assert_eq!(blocks[0].zone_type, ZoneType::NaturalLanguage);
        assert!(blocks[0].confidence > 0.70, "clear prose should be >0.70: {}", blocks[0].confidence);
        assert_eq!(blocks[0].method, "prose_detector");
    }

    #[test]
    fn test_short_ambiguous_fragment() {
        let lines: Vec<&str> = vec!["ok", "sure"];
        let claimed: HashSet<usize> = HashSet::new();
        let det = ProseDetector::default();
        let blocks = det.detect(&lines, &claimed);
        assert_eq!(blocks.len(), 1);
        assert!(blocks[0].confidence < 0.50, "short fragment should be low confidence: {}", blocks[0].confidence);
    }

    #[test]
    fn test_skips_claimed_lines() {
        let lines: Vec<&str> = vec![
            "This is prose.",
            "def code():",
            "More prose here.",
        ];
        let claimed: HashSet<usize> = [1].into_iter().collect();
        let det = ProseDetector::default();
        let blocks = det.detect(&lines, &claimed);
        // Should produce 2 blocks (lines 0 and 2), not 1
        assert_eq!(blocks.len(), 2);
    }

    #[test]
    fn test_empty_input() {
        let lines: Vec<&str> = vec![];
        let claimed: HashSet<usize> = HashSet::new();
        let det = ProseDetector::default();
        let blocks = det.detect(&lines, &claimed);
        assert!(blocks.is_empty());
    }

    #[test]
    fn test_all_claimed() {
        let lines: Vec<&str> = vec!["line 1", "line 2"];
        let claimed: HashSet<usize> = [0, 1].into_iter().collect();
        let det = ProseDetector::default();
        let blocks = det.detect(&lines, &claimed);
        assert!(blocks.is_empty());
    }

    #[test]
    fn test_confidence_clamped() {
        let lines: Vec<&str> = vec![
            "This is a beautifully crafted sentence with proper punctuation.",
            "It has commas, periods, and question marks?",
            "Multiple paragraphs of flowing natural language text.",
            "The kind of text that is clearly prose, not code.",
            "And it goes on for several lines to build confidence.",
        ];
        let claimed: HashSet<usize> = HashSet::new();
        let det = ProseDetector::default();
        let blocks = det.detect(&lines, &claimed);
        assert_eq!(blocks.len(), 1);
        assert!(blocks[0].confidence <= 0.95, "confidence must be clamped: {}", blocks[0].confidence);
        assert!(blocks[0].confidence >= 0.20);
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd data_classifier_core && /Users/guyguzner/.cargo/bin/cargo test prose_detector::tests --no-default-features 2>&1 | tail -5`
Expected: FAIL — module not found

- [ ] **Step 3: Write the implementation**

Create `data_classifier_core/src/zone_detector/prose_detector.rs`:

```rust
//! ProseDetector — step 12 of the zone pipeline.
//!
//! Claims all remaining unclaimed lines as `NaturalLanguage` blocks with a
//! confidence score derived from BlockFeatures. This is the final pass — after
//! it runs, every line belongs to exactly one block.

use std::collections::HashSet;

use crate::zone_detector::features::BlockFeatures;
use crate::zone_detector::types::{ZoneBlock, ZoneType};

/// Hand-tuned weights for prose confidence scoring (v1).
/// Will be replaced by trained classifier weights in v2.
pub struct ProseDetector {
    pub w_alpha: f64,
    pub w_sentence: f64,
    pub w_no_keywords: f64,
    pub w_no_syntax: f64,
    pub w_size: f64,
}

impl Default for ProseDetector {
    fn default() -> Self {
        Self {
            w_alpha: 0.25,
            w_sentence: 0.25,
            w_no_keywords: 0.20,
            w_no_syntax: 0.15,
            w_size: 0.15,
        }
    }
}

impl ProseDetector {
    /// Classify all unclaimed lines as natural_language blocks.
    pub fn detect(
        &self,
        lines: &[&str],
        claimed: &HashSet<usize>,
    ) -> Vec<ZoneBlock> {
        let mut blocks = Vec::new();
        let regions = Self::find_unclaimed_regions(lines, claimed);

        for (start, end) in regions {
            let block_lines: Vec<&str> = lines[start..end].to_vec();
            let features = BlockFeatures::extract(&block_lines);
            let confidence = self.score_prose(&features);

            blocks.push(ZoneBlock {
                start_line: start,
                end_line: end,
                zone_type: ZoneType::NaturalLanguage,
                confidence,
                method: "prose_detector".to_string(),
                language_hint: String::new(),
                language_confidence: 0.0,
                text: block_lines.join("\n"),
            });
        }

        blocks
    }

    /// Compute prose confidence from features using hand-tuned weights.
    fn score_prose(&self, f: &BlockFeatures) -> f64 {
        let size_signal = match f.block_lines {
            0..=1 => 0.2,
            2..=3 => 0.4,
            4..=7 => 0.7,
            _ => 1.0,
        };

        let raw = self.w_alpha * f.alpha_space_ratio
            + self.w_sentence * f.sentence_score
            + self.w_no_keywords * (1.0 - f.code_keyword_density).max(0.0)
            + self.w_no_syntax * (1.0 - f.syntactic_char_ratio * 10.0).max(0.0)
            + self.w_size * size_signal;

        raw.clamp(0.20, 0.95)
    }

    /// Find contiguous unclaimed line regions (including single-line gaps).
    fn find_unclaimed_regions(
        lines: &[&str],
        claimed: &HashSet<usize>,
    ) -> Vec<(usize, usize)> {
        let mut regions = Vec::new();
        let mut i = 0;
        while i < lines.len() {
            if claimed.contains(&i) {
                i += 1;
                continue;
            }
            let start = i;
            while i < lines.len() && !claimed.contains(&i) {
                i += 1;
            }
            // Trim trailing blank lines
            let mut end = i;
            while end > start && lines[end - 1].trim().is_empty() {
                end -= 1;
            }
            if end > start {
                regions.push((start, end));
            }
        }
        regions
    }
}
```

- [ ] **Step 4: Register module in mod.rs**

Add after `data_detector`:

```rust
mod prose_detector;
```

- [ ] **Step 5: Run tests**

Run: `cd data_classifier_core && /Users/guyguzner/.cargo/bin/cargo test prose_detector::tests 2>&1 | tail -15`
Expected: 6 tests pass

- [ ] **Step 6: Commit**

```bash
git add data_classifier_core/src/zone_detector/prose_detector.rs data_classifier_core/src/zone_detector/mod.rs
git commit -m "feat(zones): add ProseDetector — step 12 (natural_language with confidence)"
```

---

### Task 4: Wire steps 11-12 into the pipeline

**Files:**
- Modify: `data_classifier_core/src/zone_detector/mod.rs`
- Modify: `data_classifier_core/src/zone_detector/config.rs`

- [ ] **Step 1: Add config flags**

In `data_classifier_core/src/zone_detector/config.rs`, add two fields to `ZoneConfig`:

```rust
pub struct ZoneConfig {
    pub pre_screen_enabled: bool,
    pub structural_enabled: bool,
    pub format_enabled: bool,
    pub syntax_enabled: bool,
    pub negative_filter_enabled: bool,
    pub language_detection_enabled: bool,
    pub data_detector_enabled: bool,   // NEW
    pub prose_detector_enabled: bool,  // NEW
    pub min_block_lines: usize,
    pub min_confidence: f64,
    pub max_parse_attempts: usize,
}
```

And update the `Default` impl:

```rust
impl Default for ZoneConfig {
    fn default() -> Self {
        Self {
            pre_screen_enabled: true,
            structural_enabled: true,
            format_enabled: true,
            syntax_enabled: true,
            negative_filter_enabled: true,
            language_detection_enabled: true,
            data_detector_enabled: true,   // NEW
            prose_detector_enabled: true,  // NEW
            min_block_lines: 8,
            min_confidence: 0.50,
            max_parse_attempts: 10,
        }
    }
}
```

- [ ] **Step 2: Wire into the orchestrator**

In `data_classifier_core/src/zone_detector/mod.rs`:

Add imports after existing use statements:

```rust
use data_detector::DataDetector;
use prose_detector::ProseDetector;
```

Add fields to `ZoneOrchestrator`:

```rust
pub struct ZoneOrchestrator {
    config: ZoneConfig,
    structural: StructuralDetector,
    format: FormatDetector,
    syntax: SyntaxDetector,
    negative: NegativeFilter,
    assembler: BlockAssembler,
    language: LanguageDetector,
    scope: ScopeTracker,
    data: DataDetector,       // NEW
    prose: ProseDetector,     // NEW
}
```

Update `from_patterns`:

```rust
pub fn from_patterns(patterns: &Value, config: &ZoneConfig) -> Self {
    Self {
        config: config.clone(),
        structural: StructuralDetector::new(patterns),
        format: FormatDetector::new(patterns),
        syntax: SyntaxDetector::new(patterns),
        negative: NegativeFilter::new(patterns),
        assembler: BlockAssembler::new(patterns, config),
        language: LanguageDetector::new(patterns),
        scope: ScopeTracker::new(patterns),
        data: DataDetector::default(),       // NEW
        prose: ProseDetector::default(),     // NEW
    }
}
```

- [ ] **Step 3: Add steps 11-12 to detect_zones**

In the `detect_zones` method of `ZoneOrchestrator`, after step 10 (merge adjacent) and before constructing the return value, add:

```rust
        // 10. Merge adjacent compatible blocks
        all_blocks = Self::merge_adjacent(all_blocks, &lines);

        // Build claimed set from all existing blocks
        let mut all_claimed: HashSet<usize> = HashSet::new();
        for b in &all_blocks {
            for i in b.start_line..b.end_line {
                all_claimed.insert(i);
            }
        }

        // 11. Data detection on unclaimed lines
        if self.config.data_detector_enabled {
            let (data_blocks, new_claimed) = self.data.detect(&lines, &all_claimed);
            all_claimed = new_claimed;
            all_blocks.extend(data_blocks);
        }

        // 12. Prose detection on remaining unclaimed lines
        if self.config.prose_detector_enabled {
            let prose_blocks = self.prose.detect(&lines, &all_claimed);
            all_blocks.extend(prose_blocks);
        }

        // Re-sort after adding new blocks
        all_blocks.sort_by_key(|b| b.start_line);

        PromptZones {
            prompt_id: prompt_id.to_string(),
            total_lines,
            blocks: all_blocks,
        }
```

- [ ] **Step 4: Update pre-screen fast path**

In `detect_zones`, change the pre-screen block (around line 102) from returning empty to running prose/data detection:

```rust
        // 2. Pre-screen fast path — skip code detection but still classify
        if self.config.pre_screen_enabled && !pre_screen(text) {
            // No code signals — skip steps 3-10, go straight to data/prose
            let mut blocks = Vec::new();
            let mut claimed: HashSet<usize> = HashSet::new();

            if self.config.data_detector_enabled {
                let (data_blocks, new_claimed) = self.data.detect(&lines, &claimed);
                claimed = new_claimed;
                blocks.extend(data_blocks);
            }
            if self.config.prose_detector_enabled {
                let prose_blocks = self.prose.detect(&lines, &claimed);
                blocks.extend(prose_blocks);
            }

            blocks.sort_by_key(|b| b.start_line);

            return PromptZones {
                prompt_id: prompt_id.to_string(),
                total_lines,
                blocks,
            };
        }
```

- [ ] **Step 5: Run all tests**

Run: `cd data_classifier_core && /Users/guyguzner/.cargo/bin/cargo test 2>&1 | grep "test result:"`
Expected: All tests pass (existing + new). The `test_pure_prose_no_blocks` test will now return blocks — update it:

```rust
    #[test]
    fn test_pure_prose_gets_natural_language_block() {
        let o = make_orchestrator();
        let result = o.detect_zones("This is a simple sentence about the weather.", "test");
        assert!(!result.blocks.is_empty(), "prose should get a block");
        assert_eq!(result.blocks[0].zone_type, ZoneType::NaturalLanguage);
    }
```

- [ ] **Step 6: Commit**

```bash
git add data_classifier_core/src/zone_detector/mod.rs data_classifier_core/src/zone_detector/config.rs
git commit -m "feat(zones): wire DataDetector + ProseDetector into pipeline (steps 11-12)"
```

---

### Task 5: Integration tests — complete partitioning

**Files:**
- Create: `data_classifier_core/tests/zone_partitioning.rs`

- [ ] **Step 1: Write integration tests**

```rust
//! Integration tests for complete zone partitioning.
//!
//! Verifies that every line in the input belongs to exactly one block
//! after the full pipeline runs.

use data_classifier_core::zone_detector::{ZoneConfig, ZoneOrchestrator, ZoneType};

fn make_orchestrator() -> ZoneOrchestrator {
    let config = ZoneConfig {
        min_block_lines: 1, // allow single-line blocks for partitioning
        min_confidence: 0.0, // don't filter by confidence
        ..ZoneConfig::default()
    };
    ZoneOrchestrator::new(&config)
}

/// Helper: verify every line [0..total_lines) is covered by exactly one block.
fn assert_complete_partition(blocks: &[data_classifier_core::zone_detector::ZoneBlock], total_lines: usize) {
    let mut covered = vec![false; total_lines];
    for b in blocks {
        for i in b.start_line..b.end_line {
            assert!(
                !covered[i],
                "line {} covered by multiple blocks",
                i
            );
            covered[i] = true;
        }
    }
    for (i, c) in covered.iter().enumerate() {
        assert!(c, "line {} not covered by any block", i);
    }
}

#[test]
fn test_pure_prose_fully_partitioned() {
    let o = make_orchestrator();
    let text = "This is a paragraph about the weather.\nIt has multiple sentences.\nAll natural language.";
    let result = o.detect_zones(text, "test");
    assert!(!result.blocks.is_empty());
    assert_complete_partition(&result.blocks, result.total_lines);
    assert!(result.blocks.iter().all(|b| b.zone_type == ZoneType::NaturalLanguage));
}

#[test]
fn test_code_plus_prose_fully_partitioned() {
    let o = make_orchestrator();
    let text = "Please help me fix this code:\n\n```python\ndef foo():\n    return 42\n```\n\nThe function should return 43 instead.";
    let result = o.detect_zones(text, "test");
    assert_complete_partition(&result.blocks, result.total_lines);
    assert!(result.blocks.iter().any(|b| b.zone_type == ZoneType::Code));
    assert!(result.blocks.iter().any(|b| b.zone_type == ZoneType::NaturalLanguage));
}

#[test]
fn test_csv_data_detected_in_mixed() {
    let o = make_orchestrator();
    let text = "Here is the data:\n\nname,email,phone\nAlice,alice@example.com,555-0101\nBob,bob@example.com,555-0102\nCharlie,charlie@example.com,555-0103\n\nPlease check it.";
    let result = o.detect_zones(text, "test");
    assert_complete_partition(&result.blocks, result.total_lines);
    assert!(
        result.blocks.iter().any(|b| b.zone_type == ZoneType::Data),
        "should detect data block, got: {:?}",
        result.blocks.iter().map(|b| (&b.zone_type, b.start_line, b.end_line)).collect::<Vec<_>>()
    );
}

#[test]
fn test_every_block_has_confidence() {
    let o = make_orchestrator();
    let text = "Hello world.\n\ndef foo():\n    pass\n\nGoodbye.";
    let result = o.detect_zones(text, "test");
    for b in &result.blocks {
        assert!(
            b.confidence >= 0.20,
            "block {:?} at {}-{} has confidence {} < 0.20",
            b.zone_type, b.start_line, b.end_line, b.confidence
        );
    }
}

#[test]
fn test_empty_input_no_blocks() {
    let o = make_orchestrator();
    let result = o.detect_zones("", "test");
    assert!(result.blocks.is_empty());
}

#[test]
fn test_single_line_prose() {
    let o = make_orchestrator();
    let result = o.detect_zones("Just one line of text.", "test");
    assert_eq!(result.blocks.len(), 1);
    assert_eq!(result.blocks[0].zone_type, ZoneType::NaturalLanguage);
}
```

- [ ] **Step 2: Run tests**

Run: `cd data_classifier_core && /Users/guyguzner/.cargo/bin/cargo test zone_partitioning 2>&1 | tail -15`
Expected: 6 tests pass

- [ ] **Step 3: Commit**

```bash
git add data_classifier_core/tests/zone_partitioning.rs
git commit -m "test(zones): integration tests for complete zone partitioning"
```

---

### Task 6: Update scan script for zone summary

**Files:**
- Modify: `scripts/scan_wildchat_unified.py`

- [ ] **Step 1: Add zone_summary to scan index output**

In `scripts/scan_wildchat_unified.py`, after the detector result is parsed, compute a zone summary for every prompt (not just candidates). Change the record building to include:

```python
# Build zone summary from blocks
zone_summary = {}
for z in zones:
    zt = z.get("zone_type", "unknown")
    lines_in_zone = z.get("end_line", 0) - z.get("start_line", 0)
    conf = z.get("confidence", 0.0)
    if zt not in zone_summary:
        zone_summary[zt] = {"lines": 0, "max_conf": 0.0}
    zone_summary[zt]["lines"] += lines_in_zone
    zone_summary[zt]["max_conf"] = max(zone_summary[zt]["max_conf"], conf)
```

Add `"zone_summary": zone_summary` to the candidate record dict.

- [ ] **Step 2: Add scan_index output for all prompts**

Add a second output file `scan_index.jsonl` that writes a lightweight record for every prompt (not just candidates):

```python
index_record = {
    "prompt_id": prompt_id,
    "prompt_length": len(text),
    "zone_summary": zone_summary,
    "num_secrets": len(findings),
    "max_secret_confidence": max((f.get("confidence", 0) for f in findings), default=0.0),
}
f_index.write(json.dumps(index_record, ensure_ascii=False) + "\n")
f_index.flush()
```

Open `scan_index.jsonl` in append mode alongside `candidates.jsonl`, with the same resume logic (skip existing prompt_ids).

- [ ] **Step 3: Test with a small scan**

Run: `.venv/bin/python scripts/scan_wildchat_unified.py --limit 100 2>&1 | tail -20`
Expected: Creates both `candidates.jsonl` and `scan_index.jsonl`. Index has 100 records, each with `zone_summary`.

- [ ] **Step 4: Commit**

```bash
git add scripts/scan_wildchat_unified.py
git commit -m "feat(scan): add zone_summary to candidates + scan_index.jsonl for all prompts"
```

---

## Self-Review

**1. Spec coverage:**
- Pipeline integration (steps 11-12) → Task 4
- Feature extraction (BlockFeatures) → Task 1
- Data detection → Task 2
- Prose detection → Task 3
- Pre-screen fast path update → Task 4 step 4
- Complete partitioning guarantee → Task 5
- Scan output changes → Task 6
- ZoneScorer rules → deferred (spec says "additive to existing config" — can be done by adding JSON entries to unified_patterns.json, no code change needed)

**2. Placeholder scan:** No TBDs, TODOs, or vague instructions found. All steps have complete code.

**3. Type consistency:**
- `BlockFeatures::extract(&[&str])` — consistent across Tasks 1, 2, 3
- `DataDetector::detect(&[&str], &HashSet<usize>) -> (Vec<ZoneBlock>, HashSet<usize>)` — consistent in Tasks 2, 4
- `ProseDetector::detect(&[&str], &HashSet<usize>) -> Vec<ZoneBlock>` — consistent in Tasks 3, 4
- `ZoneConfig` fields `data_detector_enabled`, `prose_detector_enabled` — consistent in Tasks 4

Plan complete and saved to `docs/superpowers/plans/2026-04-27-complete-zone-partitioning.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?