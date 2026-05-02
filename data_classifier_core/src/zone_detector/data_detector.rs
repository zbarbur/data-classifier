//! DataDetector — claims unclaimed blocks exhibiting tabular, CSV, log,
//! or other structured-data patterns.
//!
//! Runs after all code/config/markup detectors (steps 1-10) but before
//! ProseDetector (step 12). Uses `BlockFeatures::extract()` for feature
//! computation.

use std::collections::HashSet;

use crate::zone_detector::features::BlockFeatures;
use crate::zone_detector::types::{ZoneBlock, ZoneType};

// ---------------------------------------------------------------------------
// DataDetector
// ---------------------------------------------------------------------------

/// Detect tabular, CSV, log, and structured-data blocks in unclaimed lines.
pub struct DataDetector {
    pub min_delimiter_density: f64,
    pub min_line_uniformity: f64,
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
    /// Detect structured-data blocks in unclaimed lines.
    ///
    /// Returns `(new_blocks, updated_claimed_set)`.
    pub fn detect(
        &self,
        lines: &[&str],
        claimed: &HashSet<usize>,
    ) -> (Vec<ZoneBlock>, HashSet<usize>) {
        let mut blocks = Vec::new();
        let mut new_claimed = claimed.clone();

        let regions = self.find_unclaimed_regions(lines, claimed);

        for (start, end) in regions {
            // end is exclusive
            let block_lines: Vec<&str> = lines[start..end].to_vec();

            if block_lines.len() < self.min_block_lines {
                continue;
            }

            let feats = BlockFeatures::extract(&block_lines);

            if let Some((hint, confidence)) = self.classify(&block_lines, &feats) {
                let text = block_lines.join("\n");
                let block = ZoneBlock {
                    start_line: start,
                    end_line: end,
                    zone_type: ZoneType::Data,
                    confidence,
                    method: "data_detector".to_string(),
                    language_hint: hint,
                    language_confidence: 0.0,
                    text,
                };
                for idx in start..end {
                    new_claimed.insert(idx);
                }
                blocks.push(block);
            }
        }

        (blocks, new_claimed)
    }

    // ------------------------------------------------------------------
    // Classification rules
    // ------------------------------------------------------------------

    /// Apply classification rules in priority order. Returns `(hint, confidence)`
    /// if any rule matches, or `None` to skip the region.
    fn classify(&self, lines: &[&str], feats: &BlockFeatures) -> Option<(String, f64)> {
        let non_blank_lines: Vec<&str> = lines
            .iter()
            .filter(|l| !l.trim().is_empty())
            .copied()
            .collect();

        if non_blank_lines.is_empty() {
            return None;
        }

        // Rule 1 — Pipe table
        let pipe_count = non_blank_lines
            .iter()
            .filter(|l| l.chars().filter(|&c| c == '|').count() >= 2)
            .count();
        let pipe_ratio = pipe_count as f64 / non_blank_lines.len() as f64;
        if pipe_ratio >= 0.70 {
            let confidence = (0.60 + pipe_ratio * 0.30).min(0.95);
            return Some(("table".to_string(), confidence));
        }

        // Rule 2 — CSV (comma/mixed delimiters)
        if feats.delimiter_density > self.min_delimiter_density
            && feats.line_uniformity > self.min_line_uniformity
            && feats.sentence_score < 0.3
        {
            let confidence =
                (0.55 + feats.delimiter_density * 0.20 + feats.line_uniformity * 0.15).min(0.95);
            return Some(("csv".to_string(), confidence));
        }

        // Rule 3 — Tab-separated
        let tab_count = non_blank_lines
            .iter()
            .filter(|l| l.contains('\t'))
            .count();
        let tab_ratio = tab_count as f64 / non_blank_lines.len() as f64;
        if tab_ratio >= 0.70 && feats.line_uniformity > 0.4 {
            let confidence = (0.60 + feats.line_uniformity * 0.25).min(0.95);
            return Some(("csv".to_string(), confidence));
        }

        // Rule 4 — Log lines
        // sentence_score guard prevents prose with coincidental shared normalized prefix
        // from being mis-classified as log lines.
        if feats.repeating_prefix
            && feats.line_uniformity > self.min_line_uniformity
            && feats.sentence_score < 0.4
        {
            let confidence = (0.55 + feats.line_uniformity * 0.25).min(0.90);
            return Some(("log".to_string(), confidence));
        }

        // Rule 5 — Structured rows
        if feats.line_uniformity > 0.6
            && feats.numeric_ratio > 0.15
            && feats.sentence_score < 0.2
        {
            let confidence =
                (0.50 + feats.line_uniformity * 0.20 + feats.numeric_ratio * 0.20).min(0.90);
            return Some(("structured".to_string(), confidence));
        }

        None
    }

    // ------------------------------------------------------------------
    // Region finding
    // ------------------------------------------------------------------

    /// Iterate lines and group contiguous unclaimed non-blank lines into
    /// candidate regions. Up to 1 blank line gap is allowed within a region.
    /// Trailing blanks are trimmed from each region.
    ///
    /// Returns a list of `(start, end)` pairs where `end` is exclusive.
    fn find_unclaimed_regions(
        &self,
        lines: &[&str],
        claimed: &HashSet<usize>,
    ) -> Vec<(usize, usize)> {
        let mut regions = Vec::new();
        let n = lines.len();
        let mut i = 0;

        while i < n {
            // Skip claimed or blank lines to find the start of a region
            if claimed.contains(&i) || lines[i].trim().is_empty() {
                i += 1;
                continue;
            }

            let region_start = i;
            let mut j = i;
            let mut blank_streak = 0;

            while j < n {
                if claimed.contains(&j) {
                    // Claimed line terminates the region
                    break;
                }
                if lines[j].trim().is_empty() {
                    blank_streak += 1;
                    if blank_streak > 1 {
                        // More than 1 consecutive blank — stop region
                        break;
                    }
                } else {
                    blank_streak = 0;
                }
                j += 1;
            }

            // Trim trailing blanks
            let mut region_end = j;
            while region_end > region_start && lines[region_end - 1].trim().is_empty() {
                region_end -= 1;
            }

            if region_end > region_start {
                regions.push((region_start, region_end));
            }

            i = j;
        }

        regions
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn detector() -> DataDetector {
        DataDetector::default()
    }

    #[test]
    fn test_csv_detected() {
        // All-numeric rows: uniform char-class profile (digit + comma) → high line_uniformity.
        // "1,2,3,4,5,6,7" = 13 chars, 6 commas → delimiter_density 0.46 > 0.3.
        // sentence_score ≈ 0.2 (only commas add +0.2, no uppercase start or terminal punct).
        let lines = vec![
            "1,2,3,4,5,6,7",
            "8,9,0,1,2,3,4",
            "5,6,7,8,9,0,1",
            "2,3,4,5,6,7,8",
        ];
        let (blocks, _) = detector().detect(&lines, &HashSet::new());
        assert_eq!(blocks.len(), 1, "expected 1 block, got {:?}", blocks);
        assert_eq!(blocks[0].zone_type, ZoneType::Data);
        assert_eq!(blocks[0].language_hint, "csv");
    }

    #[test]
    fn test_log_lines_detected() {
        let lines = vec![
            "2024-01-15 10:23:45 INFO  Starting application server",
            "2024-01-15 10:23:46 DEBUG Loaded configuration from /etc/app.conf",
            "2024-01-15 10:23:47 INFO  Listening on port 8080",
            "2024-01-15 10:23:48 WARN  Connection pool nearly full: 95/100",
        ];
        let (blocks, _) = detector().detect(&lines, &HashSet::new());
        assert_eq!(blocks.len(), 1, "expected 1 block, got {:?}", blocks);
        assert_eq!(blocks[0].zone_type, ZoneType::Data);
        assert_eq!(blocks[0].language_hint, "log");
    }

    #[test]
    fn test_pipe_table_detected() {
        let lines = vec![
            "| Name  | Age | City   |",
            "|-------|-----|--------|",
            "| Alice |  30 | London |",
            "| Bob   |  25 | Paris  |",
        ];
        let (blocks, _) = detector().detect(&lines, &HashSet::new());
        assert_eq!(blocks.len(), 1, "expected 1 block, got {:?}", blocks);
        assert_eq!(blocks[0].zone_type, ZoneType::Data);
        assert_eq!(blocks[0].language_hint, "table");
    }

    #[test]
    fn test_prose_not_detected_as_data() {
        let lines = vec![
            "The quick brown fox jumped over the lazy dog.",
            "It was a bright cold day in April, and the clocks were striking thirteen.",
            "All happy families are alike; each unhappy family is unhappy in its own way.",
        ];
        let (blocks, _) = detector().detect(&lines, &HashSet::new());
        assert!(
            blocks.is_empty(),
            "prose should not be detected as data, got {:?}", blocks
        );
    }

    #[test]
    fn test_skips_claimed_lines() {
        let lines = vec![
            "name,age,email,city",
            "Alice,30,alice@example.com,London",
            "Bob,25,bob@example.com,Paris",
            "Carol,35,carol@example.com,Berlin",
        ];
        // Claim all lines
        let claimed: HashSet<usize> = (0..lines.len()).collect();
        let (blocks, _) = detector().detect(&lines, &claimed);
        assert!(
            blocks.is_empty(),
            "all claimed lines should produce no blocks, got {:?}", blocks
        );
    }
}
