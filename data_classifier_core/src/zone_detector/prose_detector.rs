//! ProseDetector — claims all remaining unclaimed lines as NaturalLanguage blocks.
//!
//! This is the final pass in the zone pipeline (step 12). After it runs, every
//! line belongs to exactly one block. Uses `BlockFeatures::extract()` for scoring.

use std::collections::HashSet;

use crate::zone_detector::features::BlockFeatures;
use crate::zone_detector::types::{ZoneBlock, ZoneType};

// ---------------------------------------------------------------------------
// ProseDetector
// ---------------------------------------------------------------------------

/// Classify all remaining unclaimed lines as `NaturalLanguage` blocks.
///
/// Hand-tuned weights for v1 scoring — see `detect()` for formula.
pub struct ProseDetector {
    pub w_alpha: f64,       // default 0.25
    pub w_sentence: f64,    // default 0.25
    pub w_no_keywords: f64, // default 0.20
    pub w_no_syntax: f64,   // default 0.15
    pub w_size: f64,        // default 0.15
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
    /// Classify all remaining unclaimed lines as `NaturalLanguage` blocks.
    ///
    /// Unlike `DataDetector`, this does NOT return an updated claimed set —
    /// it claims everything remaining, so there is nothing left to track.
    ///
    /// Scoring formula:
    /// ```text
    /// size_signal = match block_lines {
    ///     0..=1 => 0.2,
    ///     2..=3 => 0.4,
    ///     4..=7 => 0.7,
    ///     _     => 1.0,
    /// }
    ///
    /// confidence = w_alpha      * alpha_space_ratio
    ///            + w_sentence   * sentence_score
    ///            + w_no_keywords * (1.0 - code_keyword_density).max(0.0)
    ///            + w_no_syntax  * (1.0 - syntactic_char_ratio * 10.0).max(0.0)
    ///            + w_size       * size_signal
    ///
    /// Clamped to [0.20, 0.95]
    /// ```
    pub fn detect(&self, lines: &[&str], claimed: &HashSet<usize>) -> Vec<ZoneBlock> {
        let regions = self.find_unclaimed_regions(lines, claimed);
        let mut blocks = Vec::new();

        for (start, end) in regions {
            // end is exclusive
            let block_lines: Vec<&str> = lines[start..end].to_vec();
            let feats = BlockFeatures::extract(&block_lines);
            let confidence = self.score(&feats);
            let text = block_lines.join("\n");

            blocks.push(ZoneBlock {
                start_line: start,
                end_line: end,
                zone_type: ZoneType::NaturalLanguage,
                confidence,
                method: "prose_detector".to_string(),
                language_hint: String::new(),
                language_confidence: 0.0,
                text,
            });
        }

        blocks
    }

    // ------------------------------------------------------------------
    // Scoring
    // ------------------------------------------------------------------

    fn score(&self, feats: &BlockFeatures) -> f64 {
        let size_signal = match feats.block_lines {
            0..=1 => 0.2,
            2..=3 => 0.4,
            4..=7 => 0.7,
            _ => 1.0,
        };

        let raw = self.w_alpha * feats.alpha_space_ratio
            + self.w_sentence * feats.sentence_score
            + self.w_no_keywords * (1.0 - feats.code_keyword_density).max(0.0)
            + self.w_no_syntax * (1.0 - feats.syntactic_char_ratio * 10.0).max(0.0)
            + self.w_size * size_signal;

        // Short ambiguous fragments (≤3 lines, no sentence structure) are
        // penalised — they lack evidence that they are prose rather than
        // isolated tokens or code fragments.
        let confidence = if feats.block_lines <= 3 && feats.sentence_score < 0.1 {
            raw * 0.60
        } else {
            raw
        };

        confidence.clamp(0.20, 0.95)
    }

    // ------------------------------------------------------------------
    // Region finding
    // ------------------------------------------------------------------

    /// Iterate lines and group contiguous unclaimed lines (blanks included —
    /// prose can contain blank lines between paragraphs) into regions.
    ///
    /// - Trailing blank lines are trimmed from each region.
    /// - Regions that are entirely blank are skipped.
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
            // Skip claimed lines
            if claimed.contains(&i) {
                i += 1;
                continue;
            }

            let region_start = i;
            let mut j = i;

            // Extend the region as long as lines are unclaimed
            while j < n && !claimed.contains(&j) {
                j += 1;
            }

            // Trim trailing blank lines
            let mut region_end = j;
            while region_end > region_start && lines[region_end - 1].trim().is_empty() {
                region_end -= 1;
            }

            // Skip all-blank regions
            let all_blank = (region_start..region_end).all(|k| lines[k].trim().is_empty());
            if region_end > region_start && !all_blank {
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

    fn detector() -> ProseDetector {
        ProseDetector::default()
    }

    /// 3 clear prose sentences → 1 block, NaturalLanguage, confidence > 0.70,
    /// method = "prose_detector".
    #[test]
    fn test_prose_paragraph() {
        let lines = vec![
            "The quick brown fox jumped over the lazy dog.",
            "It was a bright cold day in April, and the clocks were striking thirteen.",
            "All happy families are alike; each unhappy family is unhappy in its own way.",
        ];
        let blocks = detector().detect(&lines, &HashSet::new());
        assert_eq!(blocks.len(), 1, "expected 1 block, got {:?}", blocks);
        let b = &blocks[0];
        assert_eq!(b.zone_type, ZoneType::NaturalLanguage);
        assert_eq!(b.method, "prose_detector");
        assert!(
            b.confidence > 0.70,
            "expected confidence > 0.70, got {}",
            b.confidence
        );
    }

    /// 2 short words → 1 block, confidence < 0.50.
    #[test]
    fn test_short_ambiguous_fragment() {
        let lines = vec!["foo", "bar"];
        let blocks = detector().detect(&lines, &HashSet::new());
        assert_eq!(blocks.len(), 1, "expected 1 block, got {:?}", blocks);
        let b = &blocks[0];
        assert!(
            b.confidence < 0.50,
            "expected confidence < 0.50, got {}",
            b.confidence
        );
    }

    /// Lines [0, 2] unclaimed, line [1] claimed → 2 separate blocks.
    #[test]
    fn test_skips_claimed_lines() {
        let lines = vec![
            "First unclaimed line.",
            "This line is claimed.",
            "Second unclaimed line.",
        ];
        let mut claimed = HashSet::new();
        claimed.insert(1_usize);
        let blocks = detector().detect(&lines, &claimed);
        assert_eq!(blocks.len(), 2, "expected 2 blocks, got {:?}", blocks);
        assert_eq!(blocks[0].start_line, 0);
        assert_eq!(blocks[0].end_line, 1);
        assert_eq!(blocks[1].start_line, 2);
        assert_eq!(blocks[1].end_line, 3);
    }

    /// Empty lines → no blocks.
    #[test]
    fn test_empty_input() {
        let lines: Vec<&str> = vec![];
        let blocks = detector().detect(&lines, &HashSet::new());
        assert!(blocks.is_empty(), "expected no blocks, got {:?}", blocks);
    }

    /// All lines claimed → no blocks.
    #[test]
    fn test_all_claimed() {
        let lines = vec![
            "The quick brown fox jumped over the lazy dog.",
            "It was a bright cold day in April.",
        ];
        let claimed: HashSet<usize> = (0..lines.len()).collect();
        let blocks = detector().detect(&lines, &claimed);
        assert!(blocks.is_empty(), "expected no blocks, got {:?}", blocks);
    }

    /// 5 clear prose sentences → confidence in [0.20, 0.95].
    #[test]
    fn test_confidence_clamped() {
        let lines = vec![
            "The quick brown fox jumped over the lazy dog.",
            "It was a bright cold day in April, and the clocks were striking thirteen.",
            "All happy families are alike; each unhappy family is unhappy in its own way.",
            "It is a truth universally acknowledged, that a single man in possession of a fortune.",
            "Call me Ishmael. Some years ago I thought I would sail about a little.",
        ];
        let blocks = detector().detect(&lines, &HashSet::new());
        assert_eq!(blocks.len(), 1, "expected 1 block, got {:?}", blocks);
        let c = blocks[0].confidence;
        assert!(
            c >= 0.20 && c <= 0.95,
            "confidence {} not in [0.20, 0.95]",
            c
        );
    }
}
