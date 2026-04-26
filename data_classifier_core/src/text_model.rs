use crate::zone_detector::ZoneType;

/// Zone annotation for a single line, populated by the zone detector.
#[derive(Debug, Clone)]
pub struct ZoneAnnotation {
    pub zone_type: ZoneType,
    pub confidence: f64,
    pub language_hint: String,
    pub block_index: usize,
    pub is_literal_context: bool,
}

/// Information about a single line of text.
#[derive(Debug, Clone)]
pub struct LineInfo {
    pub offset_start: usize, // byte offset of line start in original text
    pub offset_end: usize,   // byte offset of line end in original text (exclusive of newline)
    pub content: String,
    pub zone: Option<ZoneAnnotation>,
}

/// Shared text representation: lines with byte offsets and optional zone annotations.
#[derive(Debug, Clone)]
pub struct TextModel {
    pub text: String,
    pub lines: Vec<LineInfo>,
}

impl TextModel {
    /// Build a TextModel from raw text. Zone annotations are None until populated.
    pub fn from_text(text: &str) -> Self {
        let mut lines = Vec::new();
        let mut offset = 0;
        for line_content in text.split('\n') {
            let end = offset + line_content.len();
            lines.push(LineInfo {
                offset_start: offset,
                offset_end: end,
                content: line_content.to_string(),
                zone: None,
            });
            offset = end + 1; // +1 for the \n character
        }
        Self {
            text: text.to_string(),
            lines,
        }
    }

    /// Find the line index for a byte offset.
    /// Returns 0 if offset is before the first line.
    pub fn line_at_offset(&self, offset: usize) -> usize {
        for (i, line) in self.lines.iter().enumerate() {
            if offset >= line.offset_start && offset <= line.offset_end {
                return i;
            }
        }
        // If offset is past the end, return last line
        if !self.lines.is_empty() {
            self.lines.len() - 1
        } else {
            0
        }
    }

    /// Populate zone annotations from PromptZones output.
    /// For each zone block, annotate every line in [start_line, end_line) with the zone info.
    /// is_literal_context is true if the line contains quote characters (' or ").
    pub fn annotate_zones(&mut self, zones: &crate::zone_detector::PromptZones) {
        for (block_idx, block) in zones.blocks.iter().enumerate() {
            for line_idx in block.start_line..block.end_line {
                if line_idx < self.lines.len() {
                    let content = &self.lines[line_idx].content;
                    let is_literal = content.contains('"') || content.contains('\'');
                    self.lines[line_idx].zone = Some(ZoneAnnotation {
                        zone_type: block.zone_type.clone(),
                        confidence: block.confidence,
                        language_hint: block.language_hint.clone(),
                        block_index: block_idx,
                        is_literal_context: is_literal,
                    });
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::zone_detector::{PromptZones, ZoneBlock, ZoneType};

    #[test]
    fn test_from_text_single_line() {
        let model = TextModel::from_text("hello");
        assert_eq!(model.lines.len(), 1);
        assert_eq!(model.lines[0].content, "hello");
        assert_eq!(model.lines[0].offset_start, 0);
        assert_eq!(model.lines[0].offset_end, 5);
        assert!(model.lines[0].zone.is_none());
    }

    #[test]
    fn test_from_text_multi_line() {
        let model = TextModel::from_text("line1\nline2\nline3");
        assert_eq!(model.lines.len(), 3);
        assert_eq!(model.lines[0].content, "line1");
        assert_eq!(model.lines[0].offset_start, 0);
        assert_eq!(model.lines[0].offset_end, 5);
        assert_eq!(model.lines[1].content, "line2");
        assert_eq!(model.lines[1].offset_start, 6);
        assert_eq!(model.lines[1].offset_end, 11);
        assert_eq!(model.lines[2].content, "line3");
        assert_eq!(model.lines[2].offset_start, 12);
        assert_eq!(model.lines[2].offset_end, 17);
    }

    #[test]
    fn test_from_text_empty() {
        let model = TextModel::from_text("");
        assert_eq!(model.lines.len(), 1); // split produces one empty element
        assert_eq!(model.lines[0].content, "");
    }

    #[test]
    fn test_line_at_offset_start() {
        let model = TextModel::from_text("aaa\nbbb\nccc");
        assert_eq!(model.line_at_offset(0), 0);
        assert_eq!(model.line_at_offset(2), 0);
    }

    #[test]
    fn test_line_at_offset_middle() {
        let model = TextModel::from_text("aaa\nbbb\nccc");
        assert_eq!(model.line_at_offset(4), 1); // 'b' at offset 4
        assert_eq!(model.line_at_offset(6), 1);
    }

    #[test]
    fn test_line_at_offset_last() {
        let model = TextModel::from_text("aaa\nbbb\nccc");
        assert_eq!(model.line_at_offset(8), 2); // 'c' at offset 8
    }

    #[test]
    fn test_line_at_offset_past_end() {
        let model = TextModel::from_text("aaa\nbbb");
        assert_eq!(model.line_at_offset(100), 1); // past end → last line
    }

    #[test]
    fn test_annotate_zones_basic() {
        let mut model = TextModel::from_text("prose\ndef foo():\n    pass\nmore prose");
        let zones = PromptZones {
            prompt_id: "test".to_string(),
            total_lines: 4,
            blocks: vec![ZoneBlock {
                start_line: 1,
                end_line: 3,
                zone_type: ZoneType::Code,
                confidence: 0.95,
                method: "syntax_score".to_string(),
                language_hint: "python".to_string(),
                language_confidence: 0.9,
                text: String::new(),
            }],
        };
        model.annotate_zones(&zones);

        // Line 0 (prose) — no zone
        assert!(model.lines[0].zone.is_none());

        // Line 1 (def foo():) — code zone
        let z1 = model.lines[1].zone.as_ref().unwrap();
        assert_eq!(z1.zone_type, ZoneType::Code);
        assert_eq!(z1.confidence, 0.95);
        assert_eq!(z1.language_hint, "python");
        assert_eq!(z1.block_index, 0);

        // Line 2 (    pass) — code zone
        assert!(model.lines[2].zone.is_some());

        // Line 3 (more prose) — no zone
        assert!(model.lines[3].zone.is_none());
    }

    #[test]
    fn test_annotate_literal_context() {
        let mut model = TextModel::from_text("password = \"secret\"\nresult = compute()");
        let zones = PromptZones {
            prompt_id: "test".to_string(),
            total_lines: 2,
            blocks: vec![ZoneBlock {
                start_line: 0,
                end_line: 2,
                zone_type: ZoneType::Code,
                confidence: 0.90,
                method: "syntax_score".to_string(),
                language_hint: "python".to_string(),
                language_confidence: 0.8,
                text: String::new(),
            }],
        };
        model.annotate_zones(&zones);

        // Line 0 has quotes → is_literal_context = true
        assert!(model.lines[0].zone.as_ref().unwrap().is_literal_context);

        // Line 1 has no quotes → is_literal_context = false
        assert!(!model.lines[1].zone.as_ref().unwrap().is_literal_context);
    }

    #[test]
    fn test_annotate_multiple_blocks() {
        let mut model = TextModel::from_text("prose\ncode1\ncode2\nprose\nconfig1\nconfig2");
        let zones = PromptZones {
            prompt_id: "test".to_string(),
            total_lines: 6,
            blocks: vec![
                ZoneBlock {
                    start_line: 1,
                    end_line: 3,
                    zone_type: ZoneType::Code,
                    confidence: 0.95,
                    method: "test".to_string(),
                    language_hint: "python".to_string(),
                    language_confidence: 0.9,
                    text: String::new(),
                },
                ZoneBlock {
                    start_line: 4,
                    end_line: 6,
                    zone_type: ZoneType::Config,
                    confidence: 0.90,
                    method: "test".to_string(),
                    language_hint: "yaml".to_string(),
                    language_confidence: 0.8,
                    text: String::new(),
                },
            ],
        };
        model.annotate_zones(&zones);

        assert!(model.lines[0].zone.is_none());
        assert_eq!(model.lines[1].zone.as_ref().unwrap().zone_type, ZoneType::Code);
        assert_eq!(model.lines[1].zone.as_ref().unwrap().block_index, 0);
        assert!(model.lines[3].zone.is_none());
        assert_eq!(model.lines[4].zone.as_ref().unwrap().zone_type, ZoneType::Config);
        assert_eq!(model.lines[4].zone.as_ref().unwrap().block_index, 1);
    }

    #[test]
    fn test_text_slice_matches_offsets() {
        let text = "hello\nworld\nfoo";
        let model = TextModel::from_text(text);
        for line in &model.lines {
            assert_eq!(&text[line.offset_start..line.offset_end], line.content);
        }
    }
}
