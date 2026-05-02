//! StructuralDetector — fenced blocks and delimiter pairs.
//!
//! Mirrors Python structural.py. Runs first in the pipeline. Claims line
//! ranges for ``` / ~~~ fenced blocks and delimiter pairs (<script>, <style>).
//!
//! Note: /* */ and <!-- --> are NOT claimed — they are part of surrounding
//! code/markup context. The syntax scorer's comment_bridge handles them.

use regex::Regex;
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::sync::LazyLock;

use crate::zone_detector::types::{ZoneBlock, ZoneType};

// ---------------------------------------------------------------------------
// Static patterns
// ---------------------------------------------------------------------------

static FENCE_OPEN: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(`{3,}|~{3,})\s*(\w[\w.-]*)?\s*$").unwrap()
});

static FENCE_CLOSE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(`{3,}|~{3,})\s*$").unwrap()
});

static CODE_KEYWORDS: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"\b(?:import|from|def|class|function|return|if|else|for|while|try|except|catch|var|let|const|public|private|static|void|int|struct|enum|fn|match)\b",
    )
    .unwrap()
});

static SYNTACTIC_CHARS: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"[{}()\[\];=<>|&!@#$^*/\\~]").unwrap()
});

static SCRIPT_OPEN: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)<script(?:\s[^>]*)?>").unwrap()
});

static SCRIPT_CLOSE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)</script>").unwrap()
});

static STYLE_OPEN: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)<style(?:\s[^>]*)?>").unwrap()
});

static STYLE_CLOSE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)</style>").unwrap()
});

// ---------------------------------------------------------------------------
// Interior classification
// ---------------------------------------------------------------------------

/// Classify untagged fence interior as NaturalLanguage or Code.
fn classify_interior(inner_lines: &[&str]) -> ZoneType {
    let non_empty: Vec<&&str> = inner_lines.iter().filter(|l| !l.trim().is_empty()).collect();
    if non_empty.is_empty() {
        return ZoneType::Code;
    }

    let alpha_ratios: Vec<f64> = non_empty
        .iter()
        .map(|l| {
            let total = l.chars().count().max(1);
            let alpha_space = l.chars().filter(|c| c.is_alphabetic() || c.is_whitespace()).count();
            alpha_space as f64 / total as f64
        })
        .collect();
    let avg_alpha = alpha_ratios.iter().sum::<f64>() / alpha_ratios.len() as f64;

    let kw_hits = non_empty
        .iter()
        .filter(|l| CODE_KEYWORDS.is_match(l))
        .count();

    let syn_hits = non_empty
        .iter()
        .filter(|l| {
            let total = l.chars().count().max(1);
            let syn_count = SYNTACTIC_CHARS.find_iter(l).count();
            syn_count as f64 / total as f64 > 0.05
        })
        .count();

    if avg_alpha > 0.80 && kw_hits == 0 && (syn_hits as f64) < non_empty.len() as f64 * 0.2 {
        ZoneType::NaturalLanguage
    } else {
        ZoneType::Code
    }
}

// ---------------------------------------------------------------------------
// StructuralDetector
// ---------------------------------------------------------------------------

/// Detect fenced blocks and delimiter pairs (<script>, <style>).
pub struct StructuralDetector {
    lang_tag_map: HashMap<String, (ZoneType, String)>,
    fenced_confidence: f64,
    delimiter_confidence: f64,
}

impl StructuralDetector {
    pub fn new(patterns: &Value) -> Self {
        // Build lang_tag_map: tag -> (zone_type, language_hint)
        let mut lang_tag_map = HashMap::new();
        if let Some(map) = patterns.get("lang_tag_map").and_then(|v| v.as_object()) {
            for (tag, entry) in map {
                if let (Some(type_str), Some(lang)) = (
                    entry.get("type").and_then(|v| v.as_str()),
                    entry.get("lang").and_then(|v| v.as_str()),
                ) {
                    if let Some(zone_type) = ZoneType::from_str(type_str) {
                        let hint = if lang.is_empty() {
                            tag.clone()
                        } else {
                            lang.to_string()
                        };
                        lang_tag_map.insert(tag.to_lowercase(), (zone_type, hint));
                    }
                }
            }
        }

        let structural = patterns.get("structural").unwrap_or(&Value::Null);
        let fenced_confidence = structural
            .get("fenced_confidence")
            .and_then(|v| v.as_f64())
            .unwrap_or(0.95);
        let delimiter_confidence = structural
            .get("delimiter_confidence")
            .and_then(|v| v.as_f64())
            .unwrap_or(0.90);

        Self {
            lang_tag_map,
            fenced_confidence,
            delimiter_confidence,
        }
    }

    /// Detect structural zones. Returns (blocks, claimed_line_indices).
    pub fn detect(&self, lines: &[&str]) -> (Vec<ZoneBlock>, HashSet<usize>) {
        let mut blocks = Vec::new();
        let mut claimed: HashSet<usize> = HashSet::new();

        // Fenced blocks
        let fenced = self.detect_fenced(lines);
        for b in &fenced {
            for idx in b.start_line..b.end_line {
                claimed.insert(idx);
            }
        }
        blocks.extend(fenced);

        // Delimiter pairs (<script>, <style>)
        let delim = self.detect_delimiters(lines, &claimed);
        for b in &delim {
            for idx in b.start_line..b.end_line {
                claimed.insert(idx);
            }
        }
        blocks.extend(delim);

        (blocks, claimed)
    }

    /// Detect ``` and ~~~ fenced blocks.
    fn detect_fenced(&self, lines: &[&str]) -> Vec<ZoneBlock> {
        let mut blocks = Vec::new();
        let mut i = 0;

        while i < lines.len() {
            let trimmed = lines[i].trim();
            let m = match FENCE_OPEN.captures(trimmed) {
                Some(m) => m,
                None => {
                    i += 1;
                    continue;
                }
            };

            let fence_str = m.get(1).unwrap().as_str();
            let fence_char = fence_str.chars().next().unwrap();
            let fence_len = fence_str.len();
            let raw_tag = m
                .get(2)
                .map(|m| m.as_str().to_lowercase())
                .unwrap_or_default();
            let start = i;

            // Find matching closing fence
            let mut j = i + 1;
            while j < lines.len() {
                let close_trimmed = lines[j].trim();
                if let Some(cm) = FENCE_CLOSE.captures(close_trimmed) {
                    let close_str = cm.get(1).unwrap().as_str();
                    if close_str.chars().next().unwrap() == fence_char && close_str.len() >= fence_len {
                        break;
                    }
                }
                j += 1;
            }
            let end = (j + 1).min(lines.len());

            // Determine zone type and language hint
            let (zone_type, language_hint) = if !raw_tag.is_empty() {
                if let Some((zt, hint)) = self.lang_tag_map.get(&raw_tag) {
                    (zt.clone(), hint.clone())
                } else {
                    (ZoneType::Code, raw_tag)
                }
            } else {
                let interior = &lines[(start + 1)..end.saturating_sub(1).max(start + 1)];
                let zone_type = classify_interior(interior);
                (zone_type, String::new())
            };

            blocks.push(ZoneBlock {
                start_line: start,
                end_line: end,
                zone_type,
                confidence: self.fenced_confidence,
                method: "structural_fence".to_string(),
                language_hint,
                language_confidence: 0.0,
                text: String::new(),
            });
            i = end;
        }

        blocks
    }

    /// Detect <script> and <style> delimiter pairs.
    fn detect_delimiters(&self, lines: &[&str], fenced_ranges: &HashSet<usize>) -> Vec<ZoneBlock> {
        let mut blocks = Vec::new();
        let text = lines.join("\n");

        // Build char-offset to line-number mapping
        let offset_to_line = Self::build_offset_map(lines);
        let n = lines.len();

        let char_to_line = |offset: usize| -> usize {
            if offset >= offset_to_line.len() {
                n.saturating_sub(1)
            } else {
                offset_to_line[offset]
            }
        };

        let mut claimed = fenced_ranges.clone();

        // <script> ... </script>
        Self::detect_tag_pair(
            &text,
            &SCRIPT_OPEN,
            &SCRIPT_CLOSE,
            ZoneType::Code,
            "javascript",
            self.delimiter_confidence,
            &char_to_line,
            &mut claimed,
            &mut blocks,
        );

        // <style> ... </style>
        Self::detect_tag_pair(
            &text,
            &STYLE_OPEN,
            &STYLE_CLOSE,
            ZoneType::Code,
            "css",
            self.delimiter_confidence,
            &char_to_line,
            &mut claimed,
            &mut blocks,
        );

        blocks
    }

    /// Build a byte-offset to line-number mapping.
    ///
    /// regex returns byte offsets (not character offsets), so this map
    /// must also be byte-based. One entry per byte of the joined text.
    fn build_offset_map(lines: &[&str]) -> Vec<usize> {
        let mut map = Vec::new();
        for (lineno, line) in lines.iter().enumerate() {
            // line.len() is byte count — matches regex byte offsets
            for _ in 0..line.len() {
                map.push(lineno);
            }
            map.push(lineno); // '\n' separator (1 byte)
        }
        map
    }

    /// Detect open/close tag pairs in text and append blocks.
    #[allow(clippy::too_many_arguments)]
    fn detect_tag_pair(
        text: &str,
        open_re: &Regex,
        close_re: &Regex,
        zone_type: ZoneType,
        lang_hint: &str,
        confidence: f64,
        char_to_line: &dyn Fn(usize) -> usize,
        claimed: &mut HashSet<usize>,
        blocks: &mut Vec<ZoneBlock>,
    ) {
        for m_open in open_re.find_iter(text) {
            let start_line = char_to_line(m_open.start());
            if claimed.contains(&start_line) {
                continue;
            }

            let after = &text[m_open.end()..];
            let m_close = match close_re.find(after) {
                Some(m) => m,
                None => continue,
            };
            let close_off = m_open.end() + m_close.end();
            let end_line = char_to_line(close_off - 1) + 1;

            if (start_line..end_line).any(|ln| claimed.contains(&ln)) {
                continue;
            }

            blocks.push(ZoneBlock {
                start_line,
                end_line,
                zone_type: zone_type.clone(),
                confidence,
                method: "structural_delimiter".to_string(),
                language_hint: lang_hint.to_string(),
                language_confidence: 0.0,
                text: String::new(),
            });

            for ln in start_line..end_line {
                claimed.insert(ln);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_detector() -> StructuralDetector {
        StructuralDetector::new(&serde_json::json!({
            "lang_tag_map": {
                "python": {"type": "code", "lang": "python"},
                "py": {"type": "code", "lang": "python"},
                "json": {"type": "config", "lang": "json"},
                "html": {"type": "markup", "lang": "html"},
                "sql": {"type": "query", "lang": "sql"},
                "bash": {"type": "cli_shell", "lang": "bash"}
            },
            "structural": {
                "fenced_confidence": 0.95,
                "delimiter_confidence": 0.90
            }
        }))
    }

    #[test]
    fn test_fenced_python_block() {
        let d = make_detector();
        let lines = vec![
            "Here is code:",
            "```python",
            "def foo():",
            "    return 1",
            "```",
        ];
        let (blocks, claimed) = d.detect(&lines);
        assert_eq!(blocks.len(), 1);
        assert_eq!(blocks[0].zone_type, ZoneType::Code);
        assert_eq!(blocks[0].language_hint, "python");
        assert_eq!(blocks[0].start_line, 1);
        assert_eq!(blocks[0].end_line, 5);
        assert!(claimed.contains(&1));
        assert!(claimed.contains(&4));
        assert!(!claimed.contains(&0));
    }

    #[test]
    fn test_untagged_fence_classifies_interior() {
        let d = make_detector();
        let lines = vec![
            "```",
            "This is just some plain text",
            "with no code keywords at all",
            "```",
        ];
        let (blocks, _) = d.detect(&lines);
        assert_eq!(blocks.len(), 1);
        assert_eq!(blocks[0].zone_type, ZoneType::NaturalLanguage);
    }

    #[test]
    fn test_script_tag_detected() {
        let d = make_detector();
        let lines = vec![
            "<html>",
            "<script>",
            "console.log('hello');",
            "</script>",
            "</html>",
        ];
        let (blocks, claimed) = d.detect(&lines);
        assert!(blocks.len() >= 1);
        let script_block = blocks.iter().find(|b| b.language_hint == "javascript");
        assert!(script_block.is_some());
        assert!(claimed.contains(&1));
    }

    #[test]
    fn test_no_blocks_in_prose() {
        let d = make_detector();
        let lines = vec![
            "Just a normal sentence.",
            "Nothing to detect here.",
        ];
        let (blocks, claimed) = d.detect(&lines);
        assert!(blocks.is_empty());
        assert!(claimed.is_empty());
    }

    #[test]
    fn test_style_tag_detected() {
        let d = make_detector();
        let lines = vec![
            "<html>",
            "<style>",
            "body { color: red; }",
            "</style>",
            "</html>",
        ];
        let (blocks, _) = d.detect(&lines);
        let style_block = blocks.iter().find(|b| b.language_hint == "css");
        assert!(style_block.is_some(), "should detect <style> block");
    }

    #[test]
    fn test_untagged_fence_with_code_interior() {
        let d = make_detector();
        let lines = vec![
            "```",
            "def foo():",
            "    return bar(x)",
            "```",
        ];
        let (blocks, _) = d.detect(&lines);
        assert_eq!(blocks.len(), 1);
        assert_eq!(blocks[0].zone_type, ZoneType::Code);
    }

    #[test]
    fn test_tilde_fence() {
        let d = make_detector();
        let lines = vec![
            "~~~json",
            r#"{"key": "value"}"#,
            "~~~",
        ];
        let (blocks, _) = d.detect(&lines);
        assert_eq!(blocks.len(), 1);
        assert_eq!(blocks[0].language_hint, "json");
        assert_eq!(blocks[0].zone_type, ZoneType::Config);
    }

    #[test]
    fn test_nested_fences_longer_close() {
        let d = make_detector();
        // Closing fence must be >= opening fence length
        let lines = vec![
            "````python",
            "code here",
            "```",           // too short — doesn't close
            "more code",
            "````",          // this closes
        ];
        let (blocks, _) = d.detect(&lines);
        assert_eq!(blocks.len(), 1);
        assert_eq!(blocks[0].start_line, 0);
        assert_eq!(blocks[0].end_line, 5);
    }
}
