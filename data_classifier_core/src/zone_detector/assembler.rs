//! BlockAssembler — block grouping, gap bridging, bracket validation, repetitive structure.
//!
//! Mirrors Python assembler.py. Converts per-line scores and types into
//! grouped ZoneBlocks.

use std::collections::HashMap;

use crate::zone_detector::block_validator::{count_code_constructs, has_math_notation};
use crate::zone_detector::config::ZoneConfig;
use crate::zone_detector::types::{ZoneBlock, ZoneType};
use serde_json::Value;

/// Converts per-line scores and types into grouped ZoneBlocks.
pub struct BlockAssembler {
    min_block_lines: usize,
    min_confidence: f64,
    short_block_min_score: f64,
    short_block_min_lines: usize,
    max_comment_gap: usize,
    repetitive_threshold: f64,
}

/// Per-line type annotation from negative filter.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LineType {
    ErrorOutput,
    None,
}

/// Internal run representation.
struct Run {
    start: usize,
    end: usize,
    run_type: RunType,
    scores: Vec<f64>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum RunType {
    Code,
    ErrorOutput,
}

impl BlockAssembler {
    pub fn new(patterns: &Value, config: &ZoneConfig) -> Self {
        let assembly = patterns.get("assembly").unwrap_or(&Value::Null);
        let g = |key: &str, default: f64| -> f64 {
            assembly.get(key).and_then(|v| v.as_f64()).unwrap_or(default)
        };
        let gu = |key: &str, default: usize| -> usize {
            assembly
                .get(key)
                .and_then(|v| v.as_u64())
                .map(|n| n as usize)
                .unwrap_or(default)
        };

        Self {
            min_block_lines: if config.min_block_lines > 0 {
                config.min_block_lines
            } else {
                gu("min_block_lines", 8)
            },
            min_confidence: if config.min_confidence > 0.0 {
                config.min_confidence
            } else {
                g("min_confidence", 0.50)
            },
            short_block_min_score: g("short_block_min_score", 0.50),
            short_block_min_lines: gu("short_block_min_lines", 3),
            max_comment_gap: gu("max_comment_gap", 4),
            repetitive_threshold: g("repetitive_threshold", 0.50),
        }
    }

    /// Main entry: convert per-line data into ZoneBlocks.
    pub fn assemble(
        &self,
        lines: &[&str],
        scores: &[f64],
        line_types: &[LineType],
    ) -> Vec<ZoneBlock> {
        if lines.is_empty() {
            return Vec::new();
        }

        let runs = self.group_runs(scores, line_types, lines);
        let runs = self.bridge_gaps(runs);
        let mut blocks: Vec<ZoneBlock> = Vec::new();

        for run in runs {
            let start = run.start;
            let end = run.end;
            let block_lines = &lines[start..end];
            let block_scores = &scores[start..end];
            let mut zone_type = match run.run_type {
                RunType::Code => ZoneType::Code,
                RunType::ErrorOutput => ZoneType::ErrorOutput,
            };
            let line_count = end - start;

            // Compute average score
            let non_zero: Vec<f64> = block_scores.iter().copied().filter(|&s| s > 0.0).collect();
            let avg_score = if non_zero.is_empty() {
                0.0
            } else {
                non_zero.iter().sum::<f64>() / non_zero.len() as f64
            };

            // Compute code constructs (used for both short-block filter and validation)
            let block_text = block_lines.join("\n");
            let evidence = if zone_type == ZoneType::Code {
                count_code_constructs(&block_text)
            } else {
                0
            };

            // Adaptive min_block_lines
            if line_count < self.min_block_lines {
                if line_count < self.short_block_min_lines {
                    continue;
                }
                if avg_score < self.short_block_min_score && evidence < 2 {
                    continue;
                }
            }

            // Repetitive structure check
            if let Some(_prefix) = self.detect_repetitive_structure(block_lines, None) {
                if zone_type == ZoneType::Code {
                    zone_type = ZoneType::ErrorOutput;
                }
            }

            // Compute confidence
            let high_ratio = block_scores
                .iter()
                .filter(|&&s| s >= 0.4)
                .count() as f64
                / block_scores.len().max(1) as f64;

            let mut confidence = if zone_type == ZoneType::ErrorOutput {
                let typed_ratio = line_types[start..end]
                    .iter()
                    .filter(|t| **t == LineType::ErrorOutput)
                    .count() as f64
                    / (end - start).max(1) as f64;
                Self::compute_confidence(typed_ratio * 0.5, typed_ratio, block_lines)
            } else {
                Self::compute_confidence(avg_score, high_ratio, block_lines)
            };

            // Block-level code construct validation
            if zone_type == ZoneType::Code {
                if evidence == 0 {
                    continue;
                } else if has_math_notation(&block_text) && evidence <= 2 {
                    continue;
                } else if evidence >= 3 {
                    confidence = (confidence + 0.10).min(0.95);
                }
            }

            if confidence < self.min_confidence {
                continue;
            }

            blocks.push(ZoneBlock {
                start_line: start,
                end_line: end,
                zone_type,
                confidence,
                method: "syntax_score".to_string(),
                language_hint: String::new(),
                language_confidence: 0.0,
                text: block_text,
            });
        }

        blocks.sort_by_key(|b| b.start_line);
        blocks
    }

    /// Detect repetitive prefix patterns in a block.
    pub fn detect_repetitive_structure(
        &self,
        lines: &[&str],
        threshold: Option<f64>,
    ) -> Option<String> {
        let threshold = threshold.unwrap_or(self.repetitive_threshold);
        let non_empty: Vec<&&str> = lines.iter().filter(|l| !l.trim().is_empty()).collect();
        if non_empty.len() < 3 {
            return None;
        }

        let mut prefixes: Vec<String> = Vec::new();
        for ln in &non_empty {
            let stripped = ln.trim();
            let tokens: Vec<&str> = stripped.splitn(3, char::is_whitespace).collect();
            if tokens.len() >= 2 {
                prefixes.push(format!("{} {}", tokens[0], tokens[1]));
            } else if !tokens.is_empty() {
                prefixes.push(tokens[0].to_string());
            }
        }

        if prefixes.is_empty() {
            return None;
        }

        // Count most common prefix
        let mut counter: HashMap<&str, usize> = HashMap::new();
        for p in &prefixes {
            *counter.entry(p.as_str()).or_insert(0) += 1;
        }
        let (most_common, count) = counter
            .into_iter()
            .max_by_key(|&(_, c)| c)
            .unwrap();
        let ratio = count as f64 / non_empty.len() as f64;

        if ratio >= threshold {
            Some(most_common.to_string())
        } else {
            None
        }
    }

    // ------------------------------------------------------------------
    // Internal helpers
    // ------------------------------------------------------------------

    fn group_runs(&self, scores: &[f64], line_types: &[LineType], lines: &[&str]) -> Vec<Run> {
        let n = scores.len();
        if n == 0 {
            return Vec::new();
        }

        let mut runs: Vec<Run> = Vec::new();
        let mut current_start: Option<usize> = None;
        let mut current_type: Option<RunType> = None;
        let mut current_scores: Vec<f64> = Vec::new();
        let mut consecutive_zero_nonblank = 0;

        for i in 0..n {
            let is_blank = lines[i].trim().is_empty();
            let has_score = scores[i] > 0.0;
            let is_error = line_types[i] == LineType::ErrorOutput;

            let line_want_type = if is_error {
                Some(RunType::ErrorOutput)
            } else if has_score {
                Some(RunType::Code)
            } else {
                None
            };

            // Blank lines carry no information — skip without breaking
            if is_blank && !has_score && !is_error {
                consecutive_zero_nonblank = 0;
                continue;
            }

            // Non-blank zero-score non-error line
            if !is_blank && !has_score && !is_error {
                consecutive_zero_nonblank += 1;
                if consecutive_zero_nonblank >= 3 {
                    if let Some(start) = current_start {
                        let end_pos = i - consecutive_zero_nonblank + 1;
                        if end_pos > start {
                            runs.push(Run {
                                start,
                                end: end_pos,
                                run_type: current_type.take().unwrap_or(RunType::Code),
                                scores: current_scores.clone(),
                            });
                        }
                        current_start = None;
                        current_type = None;
                        current_scores.clear();
                    }
                }
                continue;
            }

            // Active line
            consecutive_zero_nonblank = 0;

            if current_start.is_none() {
                current_start = Some(i);
                current_type = line_want_type;
                current_scores = vec![scores[i]];
            } else if line_want_type.is_some()
                && current_type.is_some()
                && line_want_type != current_type
            {
                // Type transition
                runs.push(Run {
                    start: current_start.unwrap(),
                    end: i,
                    run_type: current_type.take().unwrap(),
                    scores: current_scores.clone(),
                });
                current_start = Some(i);
                current_type = line_want_type;
                current_scores = vec![scores[i]];
            } else {
                current_scores.push(scores[i]);
                if line_want_type.is_some() {
                    current_type = line_want_type;
                }
            }
        }

        // Close final run
        if let Some(start) = current_start {
            runs.push(Run {
                start,
                end: lines.len(),
                run_type: current_type.unwrap_or(RunType::Code),
                scores: current_scores,
            });
        }

        runs
    }

    fn bridge_gaps(&self, runs: Vec<Run>) -> Vec<Run> {
        if runs.len() <= 1 {
            return runs;
        }

        let mut merged: Vec<Run> = Vec::new();
        let mut iter = runs.into_iter();
        merged.push(iter.next().unwrap());

        for run in iter {
            let prev = merged.last_mut().unwrap();
            let gap = run.start.saturating_sub(prev.end);
            let same_type = prev.run_type == run.run_type;

            if same_type && gap <= self.max_comment_gap {
                prev.end = run.end;
                prev.scores.extend(run.scores);
            } else {
                merged.push(run);
            }
        }

        merged
    }

    fn compute_confidence(avg_score: f64, high_ratio: f64, block_lines: &[&str]) -> f64 {
        let mut conf = 0.40 + avg_score;
        let n = block_lines.len();

        if n >= 50 {
            conf += 0.10;
        } else if n >= 20 {
            conf += 0.05;
        }

        if high_ratio >= 0.70 {
            conf += 0.05;
        }

        conf.min(0.95)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_assembler() -> BlockAssembler {
        BlockAssembler::new(
            &serde_json::json!({
                "assembly": {
                    "min_block_lines": 3,
                    "min_confidence": 0.50,
                    "short_block_min_score": 0.40,
                    "short_block_min_lines": 3,
                    "max_blank_gap": 4,
                    "max_comment_gap": 4,
                    "repetitive_threshold": 0.50
                }
            }),
            &ZoneConfig {
                min_block_lines: 3,
                min_confidence: 0.50,
                ..ZoneConfig::default()
            },
        )
    }

    #[test]
    fn test_empty_input() {
        let a = make_assembler();
        let blocks = a.assemble(&[], &[], &[]);
        assert!(blocks.is_empty());
    }

    #[test]
    fn test_simple_code_block() {
        let a = make_assembler();
        let lines: Vec<&str> = vec![
            "def process(data):",
            "    result = []",
            "    for item in data:",
            "        result.append(item)",
            "    return result",
        ];
        let scores = vec![0.6, 0.5, 0.5, 0.5, 0.5];
        let types = vec![LineType::None; 5];
        let blocks = a.assemble(&lines, &scores, &types);
        assert_eq!(blocks.len(), 1);
        assert_eq!(blocks[0].zone_type, ZoneType::Code);
    }

    #[test]
    fn test_error_output_block() {
        let a = make_assembler();
        let lines: Vec<&str> = vec![
            "Traceback (most recent call last):",
            "  File \"test.py\", line 1, in <module>",
            "    raise ValueError()",
            "ValueError: invalid input",
        ];
        let scores = vec![0.0; 4];
        let types = vec![
            LineType::ErrorOutput,
            LineType::ErrorOutput,
            LineType::ErrorOutput,
            LineType::ErrorOutput,
        ];
        let blocks = a.assemble(&lines, &scores, &types);
        assert_eq!(blocks.len(), 1);
        assert_eq!(blocks[0].zone_type, ZoneType::ErrorOutput);
    }

    #[test]
    fn test_repetitive_structure_detected() {
        let a = make_assembler();
        let lines = vec![
            "2024-01-01 INFO Starting service",
            "2024-01-01 INFO Loading config",
            "2024-01-01 INFO Ready",
            "2024-01-01 INFO Listening on port 8080",
        ];
        let result = a.detect_repetitive_structure(&lines, None);
        assert!(result.is_some(), "expected repetitive prefix");
    }

    #[test]
    fn test_non_repetitive() {
        let a = make_assembler();
        let lines = vec![
            "def foo():",
            "    x = 1",
            "    return x",
        ];
        let result = a.detect_repetitive_structure(&lines, None);
        assert!(result.is_none());
    }
}
