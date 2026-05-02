//! Zone detector — identifies code, markup, config, and other structured
//! blocks within LLM prompts.
//!
//! Pipeline order (mirrors Python implementation):
//! 1. Pre-screen fast path
//! 2. StructuralDetector → fenced blocks, delimiter pairs
//! 3. FormatDetector → JSON/XML/YAML on unclaimed lines
//! 4. SyntaxDetector → per-line scoring with fragment boost
//! 5. ScopeTracker → bracket continuation + indentation scope
//! 6. NegativeFilter → FP suppression
//! 7. BlockAssembler → group scored lines into blocks
//! 8. BlockValidator → construct counting, math indicator check
//! 9. LanguageDetector → enrich blocks with language info
//! 10. Merge adjacent compatible blocks
//! 11. DataDetector → tabular/CSV/log/structured-data on unclaimed lines
//! 12. ProseDetector → NaturalLanguage on remaining unclaimed lines

mod types;
mod config;
mod block_validator;
mod tokenizer;
mod syntax;
mod pre_screen;
mod structural;
mod format_detector;
mod scope;
mod negative;
mod assembler;
mod language;
mod features;
mod data_detector;
mod prose_detector;

pub use types::*;
pub use config::ZoneConfig;
pub use features::BlockFeatures;
pub use data_detector::DataDetector;

use assembler::{BlockAssembler, LineType};
use format_detector::FormatDetector;
use language::LanguageDetector;
use negative::{NegativeFilter, NegativeResult};
use pre_screen::pre_screen;
use prose_detector::ProseDetector;
use scope::ScopeTracker;
use structural::StructuralDetector;
use syntax::SyntaxDetector;

use serde_json::Value;
use std::collections::HashSet;

/// Cascade pipeline that wires all zone detectors together.
pub struct ZoneOrchestrator {
    config: ZoneConfig,
    structural: StructuralDetector,
    format: FormatDetector,
    syntax: SyntaxDetector,
    negative: NegativeFilter,
    assembler: BlockAssembler,
    language: LanguageDetector,
    scope: ScopeTracker,
    data: DataDetector,
    prose: ProseDetector,
}

/// Compatible type pairs for post-merge.
fn types_compatible(a: &ZoneType, b: &ZoneType) -> bool {
    matches!(
        (a, b),
        (ZoneType::Code, ZoneType::ErrorOutput) | (ZoneType::ErrorOutput, ZoneType::Code)
    )
}

impl ZoneOrchestrator {
    /// Build from parsed zone_patterns.json and config.
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
            data: DataDetector::default(),
            prose: ProseDetector::default(),
        }
    }

    /// Build with default config from parsed zone_patterns.json.
    pub fn new(config: &ZoneConfig) -> Self {
        // When no patterns provided, use an empty object.
        // All modules fall back to their defaults.
        let patterns = Value::Object(serde_json::Map::new());
        Self::from_patterns(&patterns, config)
    }

    /// Run the full detection pipeline on `text`.
    pub fn detect_zones(&self, text: &str, prompt_id: &str) -> PromptZones {
        // 1. Handle empty input
        if text.is_empty() || text.trim().is_empty() {
            return PromptZones {
                prompt_id: prompt_id.to_string(),
                total_lines: 0,
                blocks: vec![],
            };
        }

        let lines: Vec<&str> = text.split('\n').collect();
        let total_lines = lines.len();

        // 2. Pre-screen fast path
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

        // 3. Structural detection (fenced blocks + delimiter pairs)
        let (struct_blocks, mut claimed_ranges) = if self.config.structural_enabled {
            self.structural.detect(&lines)
        } else {
            (Vec::new(), HashSet::new())
        };

        // 4. Format detection on unclaimed lines
        let (format_blocks, new_claimed) = if self.config.format_enabled {
            self.format.detect(&lines, &claimed_ranges)
        } else {
            (Vec::new(), claimed_ranges.clone())
        };
        claimed_ranges = new_claimed;

        // 5. Syntax scoring (claimed lines get -1.0)
        let mut scores = if self.config.syntax_enabled {
            self.syntax.score_lines(&lines, &claimed_ranges)
        } else {
            vec![0.0; total_lines]
        };

        // 5.5. Scope tracking
        scores = self.scope.adjust_scores(&lines, &scores, &claimed_ranges);

        // 6. Negative filter on unclaimed lines
        let mut line_types: Vec<LineType> = vec![LineType::None; total_lines];
        if self.config.negative_filter_enabled {
            for i in 0..total_lines {
                if claimed_ranges.contains(&i) {
                    continue;
                }
                match self.negative.check_line(lines[i]) {
                    Some(NegativeResult::ErrorOutput) => {
                        line_types[i] = LineType::ErrorOutput;
                        scores[i] = 0.0;
                    }
                    Some(NegativeResult::Suppress) => {
                        scores[i] = 0.0;
                    }
                    None => {}
                }
            }

            // Absorb error interior
            Self::absorb_error_interior(&mut line_types, &mut scores, &claimed_ranges, total_lines);

            // List prefix check
            let unclaimed_lines: Vec<&str> = (0..total_lines)
                .filter(|i| !claimed_ranges.contains(i))
                .map(|i| lines[i])
                .collect();
            if self.negative.check_list_prefix(&unclaimed_lines) {
                for i in 0..total_lines {
                    if !claimed_ranges.contains(&i) && scores[i] > 0.0 {
                        scores[i] = 0.0;
                    }
                }
            }
        }

        // 7. Block assembly
        let mut syntax_blocks = if self.config.syntax_enabled {
            self.assembler.assemble(&lines, &scores, &line_types)
        } else {
            Vec::new()
        };

        // 8. Language detection enrichment
        if self.config.language_detection_enabled {
            for block in &mut syntax_blocks {
                let block_lines: Vec<&str> = lines[block.start_line..block.end_line].to_vec();
                let hits = self.syntax.fragment_hits_for_block(&block_lines);
                let (lang, lang_conf, _) = self.language.detect_language(&block_lines, &hits);
                block.language_hint = lang;
                block.language_confidence = lang_conf;
            }
        }

        // 9. Merge all blocks, sort, filter
        let mut all_blocks: Vec<ZoneBlock> = Vec::new();
        all_blocks.extend(struct_blocks);
        all_blocks.extend(format_blocks);
        all_blocks.extend(syntax_blocks);
        all_blocks.sort_by_key(|b| b.start_line);
        all_blocks.retain(|b| b.confidence >= self.config.min_confidence);

        // 10. Merge adjacent compatible blocks
        all_blocks = Self::merge_adjacent(all_blocks, &lines);

        // 10b. Templating-host language merge — when a code block has a
        // language hint that natively embeds markup (PHP/JSX/Vue/etc.), and
        // there are nearby markup or other code blocks, collapse them all
        // into a single host-language code block. Treats e.g. PHP+HTML+JS
        // as one cohesive program rather than three separate zones.
        all_blocks = Self::merge_templating_host(all_blocks);

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
    }

    // ------------------------------------------------------------------
    // Internal helpers
    // ------------------------------------------------------------------

    /// Merge adjacent blocks of same or compatible types.
    fn merge_adjacent(blocks: Vec<ZoneBlock>, lines: &[&str]) -> Vec<ZoneBlock> {
        if blocks.len() < 2 {
            return blocks;
        }

        let mut merged: Vec<ZoneBlock> = Vec::new();
        let mut iter = blocks.into_iter();
        merged.push(iter.next().unwrap());

        for b in iter {
            let prev = merged.last_mut().unwrap();
            let same = prev.zone_type == b.zone_type;
            let compatible = types_compatible(&prev.zone_type, &b.zone_type);
            let adjacent = b.start_line <= prev.end_line + 1;

            if adjacent && (same || compatible) {
                prev.end_line = prev.end_line.max(b.end_line);
                prev.confidence = prev.confidence.max(b.confidence);
                prev.text = lines[prev.start_line..prev.end_line].join("\n");
            } else {
                merged.push(b);
            }
        }

        merged
    }

    /// Reclassify unclaimed lines between error_output lines as error_output.
    fn absorb_error_interior(
        line_types: &mut [LineType],
        scores: &mut [f64],
        claimed_ranges: &HashSet<usize>,
        total_lines: usize,
    ) {
        for i in 0..total_lines {
            if claimed_ranges.contains(&i) || line_types[i] != LineType::None {
                continue;
            }

            // Look for error_output neighbour above
            let mut has_error_above = false;
            if i > 0 {
                for j in (0..i).rev() {
                    if claimed_ranges.contains(&j) {
                        break;
                    }
                    if line_types[j] == LineType::ErrorOutput {
                        has_error_above = true;
                        break;
                    }
                    if line_types[j] == LineType::None && scores[j] <= 0.0 {
                        break;
                    }
                }
            }

            // Look for error_output neighbour below
            let mut has_error_below = false;
            for j in (i + 1)..total_lines {
                if claimed_ranges.contains(&j) {
                    break;
                }
                if line_types[j] == LineType::ErrorOutput {
                    has_error_below = true;
                    break;
                }
                if line_types[j] == LineType::None && scores[j] <= 0.0 {
                    break;
                }
            }

            if has_error_above && has_error_below {
                line_types[i] = LineType::ErrorOutput;
                scores[i] = 0.0;
            }
        }
    }

    /// Templating-host language merge.
    ///
    /// When the prompt contains a code block whose `language_hint` is a
    /// host language that natively embeds markup (PHP, JSX/TSX, Vue, ERB,
    /// Jinja, etc.) and there are also nearby markup or other code blocks,
    /// collapse them all into a single code block. The host language hint
    /// is preserved.
    ///
    /// Rationale: a `.php` file with PHP + HTML + `<script>` JS is one
    /// cohesive program — labeling each language as a separate zone is
    /// syntactically correct but semantically misleading for downstream
    /// prompt-analysis (intent / risk).
    fn merge_templating_host(blocks: Vec<ZoneBlock>) -> Vec<ZoneBlock> {
        const HOSTS: &[&str] = &[
            "php", "jsx", "tsx", "vue", "svelte", "erb", "twig", "jinja",
            "jinja2", "handlebars", "asp", "jsp", "razor",
        ];

        // Find host-language code blocks
        let host_indices: Vec<usize> = blocks
            .iter()
            .enumerate()
            .filter(|(_, b)| {
                b.zone_type == ZoneType::Code
                    && HOSTS.contains(&b.language_hint.to_lowercase().as_str())
            })
            .map(|(i, _)| i)
            .collect();

        if host_indices.is_empty() {
            return blocks;
        }

        // For each host block, find the contiguous run of nearby non-NL
        // blocks (markup + code) and merge them into one
        let mut keep: Vec<bool> = vec![true; blocks.len()];
        let mut merged: Vec<ZoneBlock> = Vec::new();

        // Use the first host block to anchor the merge — its language hint wins.
        // Bounds = min(start) to max(end) of all non-NL blocks in the prompt.
        let host = &blocks[host_indices[0]];
        let host_lang = host.language_hint.clone();

        let non_nl_indices: Vec<usize> = blocks
            .iter()
            .enumerate()
            .filter(|(_, b)| {
                matches!(
                    b.zone_type,
                    ZoneType::Code | ZoneType::Markup | ZoneType::Config | ZoneType::Data
                )
            })
            .map(|(i, _)| i)
            .collect();

        if non_nl_indices.len() <= 1 {
            return blocks;
        }

        let start_line = non_nl_indices.iter().map(|&i| blocks[i].start_line).min().unwrap_or(0);
        let end_line = non_nl_indices.iter().map(|&i| blocks[i].end_line).max().unwrap_or(0);
        let max_conf = non_nl_indices
            .iter()
            .map(|&i| blocks[i].confidence)
            .fold(0.0_f64, f64::max);

        for i in &non_nl_indices {
            keep[*i] = false;
        }

        merged.push(ZoneBlock {
            start_line,
            end_line,
            zone_type: ZoneType::Code,
            confidence: max_conf,
            method: "templating_host_merge".to_string(),
            language_hint: host_lang,
            language_confidence: host.language_confidence,
            text: String::new(),
        });

        // Keep all NL blocks plus our new merged block
        let mut result: Vec<ZoneBlock> = blocks
            .into_iter()
            .zip(keep.iter())
            .filter(|(_, k)| **k)
            .map(|(b, _)| b)
            .collect();
        result.extend(merged);
        result.sort_by_key(|b| b.start_line);
        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_orchestrator() -> ZoneOrchestrator {
        let patterns = serde_json::json!({
            "lang_tag_map": {
                "python": {"type": "code", "lang": "python"},
                "json": {"type": "config", "lang": "json"},
                "bash": {"type": "cli_shell", "lang": "bash"}
            },
            "structural": {
                "fenced_confidence": 0.95,
                "delimiter_confidence": 0.90
            },
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
            },
            "syntax": {
                "syntactic_chars": "{}()[];=<>|&!@#$^*/\\~",
                "syntactic_endings": "{;)],:",
                "strict_keywords": ["def", "const", "fn", "pub", "struct", "enum",
                    "async", "await", "yield", "lambda", "println", "printf",
                    "console", "void", "boolean", "fmt", "std", "mut", "impl",
                    "sizeof", "typedef", "extern", "volatile", "register",
                    "defer", "chan", "fallthrough", "namespace", "goto",
                    "System", "val", "var", "elif"],
                "contextual_keywords": ["import", "from", "class", "function", "return",
                    "if", "else", "for", "while", "do", "try", "except", "catch",
                    "throw", "throws", "finally", "new", "let", "local",
                    "public", "private", "protected", "static", "abstract",
                    "int", "string", "bool", "float", "double", "char", "long",
                    "package", "interface", "implements", "extends", "override",
                    "raise", "assert", "include", "require", "module", "export",
                    "default", "trait", "match", "use", "switch", "case", "break",
                    "continue", "type", "using", "unsafe", "virtual", "select",
                    "go", "self", "super", "this"],
                "assignment_pattern": "^\\s*[a-zA-Z_]\\w*\\s*[:=]",
                "scoring_weights": {
                    "syn_density_high": 0.15, "syn_density_high_weight": 0.30,
                    "syn_density_med": 0.08, "syn_density_med_weight": 0.15,
                    "keyword_multi_weight": 0.30, "keyword_single_weight": 0.15,
                    "line_ending_weight": 0.10, "assignment_weight": 0.10,
                    "indentation_weight": 0.05, "fragment_match_boost": 0.25
                },
                "fragment_patterns": {
                    "c_family": [
                        "^\\s*(if|else|for|while|switch|case|return|break|continue)\\s*[\\({]",
                        "^\\s*(const|let|var|int|string|bool|boolean|float|double|void|char|long|auto)\\s+\\w+",
                        "[{};]\\s*$"
                    ],
                    "python": [
                        "^\\s*(def|class|import|from|return|yield|raise|assert|pass|del|global|nonlocal)\\s",
                        "^\\s*(if|elif|else|for|while|try|except|finally|with|as|match|case)\\s.*:\\s*(#.*)?$"
                    ]
                },
                "context": {
                    "self_weight": 0.70, "neighbor_weight": 0.20,
                    "transition_colon_boost": 0.10, "transition_phrase_boost": 0.15,
                    "comment_bridge_factor": 0.80
                },
                "comment_marker_pattern":
                    "^\\s*(?:#(?!include|define|ifdef|ifndef|endif|pragma)|//|--|/\\*|\\*(?!/)| \\*\\s|%|REM\\s)"
            },
            "tokenizer": {
                "semantic_weights": {
                    "code_dot_boost": 1.3, "code_operator_boost": 1.2,
                    "prose_suppress": 0.0, "data_suppress": 0.0,
                    "no_ident_suppress": 0.0, "min_ident_for_prose": 4,
                    "max_keyword_for_prose": 1, "data_string_ratio_threshold": 0.4,
                    "expression_call_boost": 0.10, "expression_data_suppress": -0.10
                }
            },
            "scope": {
                "scope_inherit_factor": 0.5,
                "continuation_inherit_factor": 0.9,
                "min_parent_score": 0.3
            },
            "negative": {
                "error_output": [
                    "^\\s*Traceback \\(most recent call last\\)",
                    "^\\w+Error:\\s"
                ],
                "dialog": {"patterns": [], "min_alpha_ratio": 0.70},
                "math": ["\\\\frac|\\\\begin|\\\\sum"],
                "ratio": [],
                "prose": {"pattern": "^[A-Z][a-z].+[.!?]$", "min_alpha_ratio": 0.75},
                "list_prefix": {
                    "pattern": "^\\s*(?:\\d+[.):]?\\s+|[-*]\\s+|[a-z][.)]\\s+)",
                    "threshold": 0.70
                }
            },
            "assembly": {
                "min_block_lines": 3,
                "min_confidence": 0.50,
                "short_block_min_score": 0.40,
                "short_block_min_lines": 3,
                "max_blank_gap": 4,
                "max_comment_gap": 4,
                "repetitive_threshold": 0.50
            },
            "language": {
                "c_family_markers": {
                    "javascript": ["\\bconsole\\.\\w+", "\\bdocument\\.\\w+"],
                    "java": ["\\bSystem\\.out\\.", "\\bpublic\\s+static\\s+void\\s+main"]
                }
            }
        });
        let config = ZoneConfig {
            min_block_lines: 3,
            min_confidence: 0.50,
            ..ZoneConfig::default()
        };
        ZoneOrchestrator::from_patterns(&patterns, &config)
    }

    #[test]
    fn test_empty_input() {
        let o = make_orchestrator();
        let result = o.detect_zones("", "test");
        assert_eq!(result.total_lines, 0);
        assert!(result.blocks.is_empty());
    }

    #[test]
    fn test_pure_prose_gets_natural_language_block() {
        let o = make_orchestrator();
        let result = o.detect_zones("This is a simple sentence about the weather.", "test");
        assert!(!result.blocks.is_empty(), "prose should get a block");
        assert_eq!(result.blocks[0].zone_type, ZoneType::NaturalLanguage);
    }

    #[test]
    fn test_fenced_python_block() {
        let o = make_orchestrator();
        let text = "Here is some code:\n```python\ndef foo():\n    return 42\n```\nThat's it.";
        let result = o.detect_zones(text, "test");
        assert!(!result.blocks.is_empty(), "should detect fenced block");
        let code_block = result.blocks.iter().find(|b| b.zone_type == ZoneType::Code);
        assert!(code_block.is_some(), "should have a Code block");
        assert_eq!(code_block.unwrap().language_hint, "python");
    }

    #[test]
    fn test_unfenced_code_detected() {
        let o = make_orchestrator();
        let text = [
            "def process(data):",
            "    result = []",
            "    for item in data:",
            "        result.append(item)",
            "    return result",
            "",
            "output = process([1, 2, 3])",
        ]
        .join("\n");
        let result = o.detect_zones(&text, "test");
        assert!(
            !result.blocks.is_empty(),
            "should detect unfenced code block"
        );
        assert_eq!(result.blocks[0].zone_type, ZoneType::Code);
    }

    #[test]
    fn test_json_format_detected() {
        let o = make_orchestrator();
        let text = "{\n  \"name\": \"test\",\n  \"value\": 42,\n  \"active\": true\n}";
        let result = o.detect_zones(text, "test");
        assert!(
            !result.blocks.is_empty(),
            "should detect JSON block"
        );
        assert_eq!(result.blocks[0].zone_type, ZoneType::Config);
    }

    #[test]
    fn test_pipeline_produces_correct_line_counts() {
        let o = make_orchestrator();
        let text = "line 1\nline 2\nline 3";
        let result = o.detect_zones(text, "test");
        assert_eq!(result.total_lines, 3);
    }
}
