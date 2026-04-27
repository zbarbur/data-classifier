//! FormatDetector — JSON, XML, YAML, ENV detection in unfenced regions.
//!
//! Mirrors Python format_detector.py. Runs after StructuralDetector.
//! Finds contiguous non-empty candidate regions in unclaimed lines,
//! then tries each format parser: JSON → XML → YAML → ENV.

use regex::Regex;
use serde_json::Value;
use std::collections::HashSet;
use std::sync::LazyLock;

use crate::zone_detector::types::{ZoneBlock, ZoneType};

// ---------------------------------------------------------------------------
// Static patterns
// ---------------------------------------------------------------------------

static KV_PATTERN: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^\s*[\w_.-]+\s*:\s+\S.*$").unwrap()
});

static LIST_PATTERN: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^\s*-\s+.+$").unwrap()
});

static ENV_PATTERN: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^[A-Z][A-Z0-9_]+=.+$").unwrap()
});

static XML_OPEN: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"<\w+[\s>]").unwrap()
});

static XML_CLOSE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"</\w+>").unwrap()
});

static XML_TAG_NAME: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"<(\w+)[\s>]").unwrap()
});

static XML_CLOSE_TAG_NAME: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"</(\w+)>").unwrap()
});

static YAML_KEY_EXTRACT: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(\s*)(.*?)\s*:\s+\S").unwrap()
});

// ---------------------------------------------------------------------------
// FormatDetector
// ---------------------------------------------------------------------------

/// Detect structured format blocks (JSON, XML, YAML, ENV) in unclaimed lines.
pub struct FormatDetector {
    max_blank_gap: usize,
    json_confidence: f64,
    xml_confidence: f64,
    yaml_confidence: f64,
    env_confidence: f64,
    yaml_min_kv_lines: usize,
    yaml_max_key_words: usize,
    yaml_max_prose_ratio: f64,
    xml_min_open_tags: usize,
    xml_min_close_tags: usize,
}

impl FormatDetector {
    pub fn new(patterns: &Value) -> Self {
        let fmt = patterns.get("format").unwrap_or(&Value::Null);
        let g = |key: &str, default: f64| -> f64 {
            fmt.get(key).and_then(|v| v.as_f64()).unwrap_or(default)
        };
        let gu = |key: &str, default: usize| -> usize {
            fmt.get(key)
                .and_then(|v| v.as_u64())
                .map(|n| n as usize)
                .unwrap_or(default)
        };

        Self {
            max_blank_gap: gu("max_blank_gap", 2),
            json_confidence: g("json_confidence", 0.90),
            xml_confidence: g("xml_confidence", 0.80),
            yaml_confidence: g("yaml_confidence", 0.80),
            env_confidence: g("env_confidence", 0.85),
            yaml_min_kv_lines: gu("yaml_min_kv_lines", 3),
            yaml_max_key_words: gu("yaml_max_key_words", 3),
            yaml_max_prose_ratio: g("yaml_max_prose_ratio", 0.50),
            xml_min_open_tags: gu("xml_min_open_tags", 2),
            xml_min_close_tags: gu("xml_min_close_tags", 1),
        }
    }

    /// Detect format zones in unclaimed lines.
    /// Returns (new_blocks, updated_claimed_ranges).
    pub fn detect(
        &self,
        lines: &[&str],
        claimed_ranges: &HashSet<usize>,
    ) -> (Vec<ZoneBlock>, HashSet<usize>) {
        let mut blocks = Vec::new();
        let mut new_claimed = claimed_ranges.clone();

        let regions = self.find_candidate_regions(lines, claimed_ranges);

        for (start, end) in regions {
            let block_lines: Vec<&str> = lines[start..end].to_vec();
            let block_text: String = block_lines.join("\n");
            let non_empty: Vec<&str> = block_lines
                .iter()
                .filter(|l| !l.trim().is_empty())
                .copied()
                .collect();

            let block = if self.try_json(&block_text) {
                Some(ZoneBlock {
                    start_line: start,
                    end_line: end,
                    zone_type: ZoneType::Config,
                    confidence: self.json_confidence,
                    method: "format_json".to_string(),
                    language_hint: "json".to_string(),
                    language_confidence: 0.0,
                    text: String::new(),
                })
            } else if self.looks_like_xml(&block_text) {
                Some(ZoneBlock {
                    start_line: start,
                    end_line: end,
                    zone_type: ZoneType::Markup,
                    confidence: self.xml_confidence,
                    method: "format_xml".to_string(),
                    language_hint: "xml".to_string(),
                    language_confidence: 0.0,
                    text: String::new(),
                })
            } else if self.looks_like_yaml(&non_empty) {
                Some(ZoneBlock {
                    start_line: start,
                    end_line: end,
                    zone_type: ZoneType::Config,
                    confidence: self.yaml_confidence,
                    method: "format_yaml".to_string(),
                    language_hint: "yaml".to_string(),
                    language_confidence: 0.0,
                    text: String::new(),
                })
            } else if self.looks_like_env(&non_empty) {
                Some(ZoneBlock {
                    start_line: start,
                    end_line: end,
                    zone_type: ZoneType::Config,
                    confidence: self.env_confidence,
                    method: "format_env".to_string(),
                    language_hint: "env".to_string(),
                    language_confidence: 0.0,
                    text: String::new(),
                })
            } else {
                None
            };

            if let Some(b) = block {
                for idx in start..end {
                    new_claimed.insert(idx);
                }
                blocks.push(b);
            }
        }

        (blocks, new_claimed)
    }

    // ------------------------------------------------------------------
    // Region finding
    // ------------------------------------------------------------------

    fn find_candidate_regions(
        &self,
        lines: &[&str],
        claimed_ranges: &HashSet<usize>,
    ) -> Vec<(usize, usize)> {
        let mut regions = Vec::new();
        let n = lines.len();
        let mut i = 0;

        while i < n {
            if claimed_ranges.contains(&i) || lines[i].trim().is_empty() {
                i += 1;
                continue;
            }

            let region_start = i;
            let mut j = i;
            let mut blank_streak = 0;

            while j < n {
                if claimed_ranges.contains(&j) {
                    break;
                }
                if !lines[j].trim().is_empty() {
                    blank_streak = 0;
                    j += 1;
                } else {
                    blank_streak += 1;
                    if blank_streak > self.max_blank_gap {
                        j = j - blank_streak + 1;
                        break;
                    }
                    j += 1;
                }
            }

            // Trim trailing blank lines
            let mut region_end = j;
            while region_end > region_start && lines[region_end - 1].trim().is_empty() {
                region_end -= 1;
            }

            let non_empty_count = lines[region_start..region_end]
                .iter()
                .filter(|l| !l.trim().is_empty())
                .count();

            if non_empty_count >= 2 {
                regions.push((region_start, region_end));
            }

            i = if j > i { j } else { i + 1 };
        }

        regions
    }

    // ------------------------------------------------------------------
    // Format parsers
    // ------------------------------------------------------------------

    fn try_json(&self, text: &str) -> bool {
        let text = text.trim();
        if text.is_empty() {
            return false;
        }
        if (text.starts_with('{') && text.ends_with('}'))
            || (text.starts_with('[') && text.ends_with(']'))
        {
            serde_json::from_str::<Value>(text).is_ok()
        } else {
            false
        }
    }

    fn looks_like_xml(&self, text: &str) -> bool {
        let text = text.trim();

        let open_count = XML_OPEN.find_iter(text).count();
        let close_count = XML_CLOSE.find_iter(text).count();

        if open_count < self.xml_min_open_tags || close_count < self.xml_min_close_tags {
            return false;
        }

        // Require at least one matched pair
        let open_names: HashSet<String> = XML_TAG_NAME
            .captures_iter(text)
            .filter_map(|c| c.get(1).map(|m| m.as_str().to_lowercase()))
            .collect();
        let close_names: HashSet<String> = XML_CLOSE_TAG_NAME
            .captures_iter(text)
            .filter_map(|c| c.get(1).map(|m| m.as_str().to_lowercase()))
            .collect();

        !open_names.is_disjoint(&close_names)
    }

    fn looks_like_yaml(&self, lines: &[&str]) -> bool {
        let kv_lines = lines
            .iter()
            .filter(|l| KV_PATTERN.is_match(l))
            .count();
        let list_lines = lines
            .iter()
            .filter(|l| LIST_PATTERN.is_match(l))
            .count();
        let non_empty: Vec<&&str> = lines.iter().filter(|l| !l.trim().is_empty()).collect();
        let non_empty_count = non_empty.len();

        if kv_lines < self.yaml_min_kv_lines {
            return false;
        }

        // Reject blocks that are mostly prose
        let prose_lines = non_empty
            .iter()
            .filter(|l| {
                let stripped = l.trim();
                let total = stripped.chars().count().max(1);
                let alpha = stripped
                    .chars()
                    .filter(|c| c.is_alphabetic() || c.is_whitespace())
                    .count();
                alpha as f64 / total as f64 > 0.85
            })
            .count();
        if prose_lines as f64 / non_empty_count.max(1) as f64 > self.yaml_max_prose_ratio {
            return false;
        }

        // Reject blocks where most "keys" are long multi-word phrases
        let mut long_key_count = 0;
        for l in lines {
            if let Some(caps) = YAML_KEY_EXTRACT.captures(l) {
                if let Some(key_match) = caps.get(2) {
                    let key = key_match.as_str().trim();
                    if key.split_whitespace().count() > self.yaml_max_key_words {
                        long_key_count += 1;
                    }
                }
            }
        }
        if long_key_count as f64 > kv_lines as f64 * 0.5 {
            return false;
        }

        let yaml_lines = kv_lines + list_lines;
        yaml_lines as f64 / non_empty_count.max(1) as f64 > 0.5
    }

    fn looks_like_env(&self, lines: &[&str]) -> bool {
        let non_empty: Vec<&&str> = lines.iter().filter(|l| !l.trim().is_empty()).collect();
        let env_matches = non_empty
            .iter()
            .filter(|l| ENV_PATTERN.is_match(l.trim()))
            .count();
        env_matches >= 2 && env_matches as f64 / non_empty.len().max(1) as f64 > 0.5
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_detector() -> FormatDetector {
        FormatDetector::new(&serde_json::json!({
            "format": {
                "min_non_empty_lines": 5,
                "max_blank_gap": 2,
                "json_confidence": 0.90,
                "xml_confidence": 0.80,
                "yaml_confidence": 0.80,
                "env_confidence": 0.85,
                "yaml_min_kv_lines": 3,
                "yaml_max_key_words": 3,
                "yaml_max_prose_ratio": 0.50,
                "xml_min_open_tags": 2,
                "xml_min_close_tags": 1
            }
        }))
    }

    #[test]
    fn test_json_detected() {
        let d = make_detector();
        let lines = vec![
            "{",
            r#"  "name": "test","#,
            r#"  "value": 42"#,
            "}",
        ];
        let refs: Vec<&str> = lines.iter().map(|s| s.as_ref()).collect();
        let (blocks, _) = d.detect(&refs, &HashSet::new());
        assert_eq!(blocks.len(), 1);
        assert_eq!(blocks[0].zone_type, ZoneType::Config);
        assert_eq!(blocks[0].language_hint, "json");
    }

    #[test]
    fn test_xml_detected() {
        let d = make_detector();
        let lines = vec![
            "<root>",
            "  <item>hello</item>",
            "  <item>world</item>",
            "</root>",
        ];
        let refs: Vec<&str> = lines.iter().map(|s| s.as_ref()).collect();
        let (blocks, _) = d.detect(&refs, &HashSet::new());
        assert_eq!(blocks.len(), 1);
        assert_eq!(blocks[0].zone_type, ZoneType::Markup);
    }

    #[test]
    fn test_yaml_detected() {
        let d = make_detector();
        let lines = vec![
            "name: test-service",
            "version: 1.0.0",
            "port: 8080",
            "debug: true",
        ];
        let refs: Vec<&str> = lines.iter().map(|s| s.as_ref()).collect();
        let (blocks, _) = d.detect(&refs, &HashSet::new());
        assert_eq!(blocks.len(), 1);
        assert_eq!(blocks[0].language_hint, "yaml");
    }

    #[test]
    fn test_env_detected() {
        let d = make_detector();
        let lines = vec![
            "DATABASE_URL=postgres://localhost/db",
            "API_KEY=sk-1234567890",
            "DEBUG=true",
        ];
        let refs: Vec<&str> = lines.iter().map(|s| s.as_ref()).collect();
        let (blocks, _) = d.detect(&refs, &HashSet::new());
        assert_eq!(blocks.len(), 1);
        assert_eq!(blocks[0].language_hint, "env");
    }

    #[test]
    fn test_claimed_lines_skipped() {
        let d = make_detector();
        let lines = vec![
            "{",
            r#"  "a": 1"#,
            "}",
        ];
        let refs: Vec<&str> = lines.iter().map(|s| s.as_ref()).collect();
        let claimed: HashSet<usize> = (0..3).collect();
        let (blocks, _) = d.detect(&refs, &claimed);
        assert!(blocks.is_empty());
    }
}
