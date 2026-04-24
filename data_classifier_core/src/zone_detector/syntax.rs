//! SyntaxDetector — line scoring, fragment matching, context window.
//!
//! Mirrors Python syntax.py. Runs after StructuralDetector and FormatDetector.
//! Operates only on unclaimed lines. Produces per-line syntax scores consumed
//! by the BlockAssembler.
//!
//! Pipeline:
//! 1. `line_syntax_score()` — 5-feature raw score + semantic modifier + expression adjustment
//! 2. `score_with_fragments()` — adds fragment-family boost
//! 3. `score_lines()` — 3-pass: raw → context smoothing → multi-line comment bridge

use fancy_regex::Regex;
use serde_json::Value;
use std::collections::{HashMap, HashSet};

use crate::zone_detector::tokenizer::{tokenize_line, TokenProfile};

// ---------------------------------------------------------------------------
// Helpers for extracting config values from serde_json::Value
// ---------------------------------------------------------------------------

fn get_f64(v: &Value, key: &str, default: f64) -> f64 {
    v.get(key).and_then(|v| v.as_f64()).unwrap_or(default)
}

fn get_usize(v: &Value, key: &str, default: usize) -> usize {
    v.get(key)
        .and_then(|v| v.as_u64())
        .map(|n| n as usize)
        .unwrap_or(default)
}

fn get_str_list(v: &Value, key: &str) -> Vec<String> {
    v.get(key)
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default()
}

/// Line-level syntax scorer with fragment matching and context smoothing.
pub struct SyntaxDetector {
    // --- character sets ---
    syntactic_chars: HashSet<char>,
    syntactic_endings: HashSet<char>,

    // --- two-tier keyword matching ---
    strict_kw_re: Option<Regex>,
    contextual_kw_re: Option<Regex>,

    // --- assignment pattern ---
    assignment_re: Regex,

    // --- scoring weights ---
    syn_density_high: f64,
    syn_density_high_weight: f64,
    syn_density_med: f64,
    syn_density_med_weight: f64,
    keyword_multi_weight: f64,
    keyword_single_weight: f64,
    line_ending_weight: f64,
    assignment_weight: f64,
    indentation_weight: f64,
    fragment_match_boost: f64,

    // --- fragment patterns (family → compiled patterns), ordered ---
    fragment_families: Vec<(String, Vec<Regex>)>,

    // --- context weights ---
    self_weight: f64,
    neighbor_weight: f64,
    transition_colon_boost: f64,
    transition_phrase_boost: f64,
    comment_bridge_factor: f64,

    // --- intro phrase and comment marker ---
    intro_phrase_re: Regex,
    comment_marker_re: Regex,

    // --- tokenizer integration ---
    keyword_set: HashSet<String>,
    code_dot_boost: f64,
    code_operator_boost: f64,
    prose_suppress: f64,
    data_suppress: f64,
    no_ident_suppress: f64,
    min_ident_for_prose: usize,
    max_keyword_for_prose: usize,
    data_string_ratio_threshold: f64,
    expr_call_boost: f64,
    expr_data_suppress: f64,
    func_call_re: Regex,
}

impl SyntaxDetector {
    /// Build from the full `zone_patterns.json` value.
    pub fn new(patterns: &Value) -> Self {
        let null = Value::Null;
        let syntax = patterns.get("syntax").unwrap_or(&null);
        let empty_obj = Value::Object(serde_json::Map::new());

        // --- character sets ---
        let syn_chars_str = syntax
            .get("syntactic_chars")
            .and_then(|v| v.as_str())
            .unwrap_or("{}()[];=<>|&!@#$^*/\\~");
        let syntactic_chars: HashSet<char> = syn_chars_str.chars().collect();

        let syn_endings_str = syntax
            .get("syntactic_endings")
            .and_then(|v| v.as_str())
            .unwrap_or("{;)],:");
        let syntactic_endings: HashSet<char> = syn_endings_str.chars().collect();

        // --- two-tier keywords ---
        let strict = get_str_list(syntax, "strict_keywords");
        let contextual = get_str_list(syntax, "contextual_keywords");

        let strict_kw_re = if !strict.is_empty() {
            let alt = strict
                .iter()
                .map(|k| fancy_regex::escape(k))
                .collect::<Vec<_>>()
                .join("|");
            Regex::new(&format!(r"\b(?:{})\b", alt)).ok()
        } else {
            None
        };

        let contextual_kw_re = if !contextual.is_empty() {
            let alt = contextual
                .iter()
                .map(|k| fancy_regex::escape(k))
                .collect::<Vec<_>>()
                .join("|");
            Regex::new(&format!(r"\b(?:{})\b", alt)).ok()
        } else {
            None
        };

        // --- assignment pattern ---
        let assignment_pattern = syntax
            .get("assignment_pattern")
            .and_then(|v| v.as_str())
            .unwrap_or(r"^\s*[a-zA-Z_]\w*\s*[:=]");
        let assignment_re = Regex::new(assignment_pattern)
            .unwrap_or_else(|_| Regex::new(r"^\s*[a-zA-Z_]\w*\s*[:=]").expect("default"));

        // --- scoring weights ---
        let sw = syntax.get("scoring_weights").unwrap_or(&empty_obj);
        let syn_density_high = get_f64(sw, "syn_density_high", 0.15);
        let syn_density_high_weight = get_f64(sw, "syn_density_high_weight", 0.30);
        let syn_density_med = get_f64(sw, "syn_density_med", 0.08);
        let syn_density_med_weight = get_f64(sw, "syn_density_med_weight", 0.15);
        let keyword_multi_weight = get_f64(sw, "keyword_multi_weight", 0.30);
        let keyword_single_weight = get_f64(sw, "keyword_single_weight", 0.15);
        let line_ending_weight = get_f64(sw, "line_ending_weight", 0.10);
        let assignment_weight = get_f64(sw, "assignment_weight", 0.10);
        let indentation_weight = get_f64(sw, "indentation_weight", 0.05);
        let fragment_match_boost = get_f64(sw, "fragment_match_boost", 0.25);

        // --- fragment patterns (order-preserving) ---
        let fragment_families: Vec<(String, Vec<Regex>)> = syntax
            .get("fragment_patterns")
            .and_then(|v| v.as_object())
            .map(|obj| {
                obj.iter()
                    .map(|(family, pats)| {
                        let compiled: Vec<Regex> = pats
                            .as_array()
                            .map(|arr| {
                                arr.iter()
                                    .filter_map(|p| p.as_str().and_then(|s| Regex::new(s).ok()))
                                    .collect()
                            })
                            .unwrap_or_default();
                        (family.clone(), compiled)
                    })
                    .collect()
            })
            .unwrap_or_default();

        // --- context weights ---
        let ctx = syntax.get("context").unwrap_or(&empty_obj);
        let self_weight = get_f64(ctx, "self_weight", 0.70);
        let neighbor_weight = get_f64(ctx, "neighbor_weight", 0.20);
        let transition_colon_boost = get_f64(ctx, "transition_colon_boost", 0.10);
        let transition_phrase_boost = get_f64(ctx, "transition_phrase_boost", 0.15);
        let comment_bridge_factor = get_f64(ctx, "comment_bridge_factor", 0.80);

        // --- intro phrase and comment marker ---
        let intro_pattern = syntax
            .get("intro_phrase_pattern")
            .and_then(|v| v.as_str())
            .unwrap_or(
                r"(?:example|code|output|command|result|script|snippet|run this|here is|as follows|shown below|see below).*:?\s*$",
            );
        // Python uses re.IGNORECASE → prepend (?i)
        let intro_default = r"(?i)(?:example|code|output|command|result|script|snippet|run this|here is|as follows|shown below|see below).*:?\s*$";
        let intro_phrase_re = Regex::new(&format!("(?i){}", intro_pattern))
            .unwrap_or_else(|_| Regex::new(intro_default).expect("default"));

        let comment_pattern = syntax
            .get("comment_marker_pattern")
            .and_then(|v| v.as_str())
            .unwrap_or(
                r"^\s*(?:#(?!include|define|ifdef|ifndef|endif|pragma)|//|--|/\*|\*(?!/)| \*\s|%|REM\s)",
            );
        let comment_default = r"^\s*(?:#(?!include|define|ifdef|ifndef|endif|pragma)|//|--|/\*|\*(?!/)| \*\s|%|REM\s)";
        let comment_marker_re = Regex::new(comment_pattern)
            .unwrap_or_else(|_| Regex::new(comment_default).expect("default"));

        // --- tokenizer integration ---
        // Tokenizer only knows strict keywords (contextual are validated by
        // structural context, which the tokenizer can't check).
        let keyword_set: HashSet<String> = strict.into_iter().collect();

        let tok = patterns
            .get("tokenizer")
            .and_then(|v| v.get("semantic_weights"))
            .unwrap_or(&empty_obj);
        let code_dot_boost = get_f64(tok, "code_dot_boost", 1.3);
        let code_operator_boost = get_f64(tok, "code_operator_boost", 1.2);
        let prose_suppress = get_f64(tok, "prose_suppress", 0.3);
        let data_suppress = get_f64(tok, "data_suppress", 0.4);
        let no_ident_suppress = get_f64(tok, "no_ident_suppress", 0.3);
        let min_ident_for_prose = get_usize(tok, "min_ident_for_prose", 4);
        let max_keyword_for_prose = get_usize(tok, "max_keyword_for_prose", 1);
        let data_string_ratio_threshold = get_f64(tok, "data_string_ratio_threshold", 0.4);
        let expr_call_boost = get_f64(tok, "expression_call_boost", 0.10);
        let expr_data_suppress = get_f64(tok, "expression_data_suppress", -0.10);
        let func_call_re = Regex::new(r"\b[a-zA-Z_]\w*\s*\(").unwrap();

        Self {
            syntactic_chars,
            syntactic_endings,
            strict_kw_re,
            contextual_kw_re,
            assignment_re,
            syn_density_high,
            syn_density_high_weight,
            syn_density_med,
            syn_density_med_weight,
            keyword_multi_weight,
            keyword_single_weight,
            line_ending_weight,
            assignment_weight,
            indentation_weight,
            fragment_match_boost,
            fragment_families,
            self_weight,
            neighbor_weight,
            transition_colon_boost,
            transition_phrase_boost,
            comment_bridge_factor,
            intro_phrase_re,
            comment_marker_re,
            keyword_set,
            code_dot_boost,
            code_operator_boost,
            prose_suppress,
            data_suppress,
            no_ident_suppress,
            min_ident_for_prose,
            max_keyword_for_prose,
            data_string_ratio_threshold,
            expr_call_boost,
            expr_data_suppress,
            func_call_re,
        }
    }

    // ------------------------------------------------------------------
    // line_syntax_score
    // ------------------------------------------------------------------

    /// Compute a 0.0–1.0 syntax score for a single line.
    pub fn line_syntax_score(&self, line: &str) -> f64 {
        let stripped = line.trim();
        if stripped.is_empty() {
            return 0.0;
        }

        let mut score = 0.0;

        // 1. syntactic char density
        let char_count = stripped.chars().count();
        let syn_count = stripped
            .chars()
            .filter(|c| self.syntactic_chars.contains(c))
            .count();
        let density = syn_count as f64 / char_count as f64;
        if density > self.syn_density_high {
            score += self.syn_density_high_weight;
        } else if density > self.syn_density_med {
            score += self.syn_density_med_weight;
        }

        // 2. keyword matches (two-tier: strict always, contextual with validation)
        let kw_hits = self.count_keywords(stripped);
        if kw_hits >= 2 {
            score += self.keyword_multi_weight;
        } else if kw_hits >= 1 {
            score += self.keyword_single_weight;
        }

        // 3. syntactic line ending
        if let Some(last_char) = stripped.chars().last() {
            if self.syntactic_endings.contains(&last_char) {
                score += self.line_ending_weight;
            }
        }

        // 4. assignment pattern
        if self.assignment_re.is_match(stripped).unwrap_or(false) {
            score += self.assignment_weight;
        }

        // 5. indentation (>= 2 spaces or tabs)
        let leading = line.len() - line.trim_start().len();
        if leading >= 2 {
            score += self.indentation_weight;
        }

        // --- Semantic modifier (tokenizer-based) ---
        let mut profile = tokenize_line(stripped, &self.keyword_set);
        // Override keyword_count with the structurally-validated count.
        // The tokenizer only knows strict keywords; contextual keywords that
        // passed validation should also count so the modifier's prose_suppress
        // rule doesn't fire on lines like "public static void main(...)".
        profile.keyword_count = kw_hits;
        let modifier = self.semantic_modifier(&profile);
        score *= modifier;

        // --- Expression adjustment (tie-breaker) ---
        score += self.expression_adjustment(&profile, stripped);

        score.clamp(0.0, 1.0)
    }

    /// Count keywords with structural validation.
    ///
    /// Strict keywords (def, async, const, ...) always count.
    /// Contextual keywords (for, function, class, ...) only count when
    /// accompanied by code structure — at the start of the line, followed
    /// by a structural token within 20 chars, or preceded by a dot.
    fn count_keywords(&self, line: &str) -> usize {
        let mut count = 0;

        // Strict: always count
        if let Some(ref re) = self.strict_kw_re {
            count += re.find_iter(line).filter_map(|m| m.ok()).count();
        }

        // Contextual: validate structural context
        if let Some(ref re) = self.contextual_kw_re {
            for m in re.find_iter(line) {
                let m = match m {
                    Ok(m) => m,
                    Err(_) => continue,
                };
                let pos = m.start();
                let after = &line[m.end()..];
                let before = &line[..pos];

                // Valid if at start of line (after whitespace)
                if before.trim().is_empty() {
                    count += 1;
                    continue;
                }

                // Valid if a structural token appears within 20 chars.
                // Catches: static void main(  /  new MyClass(  /  let x =
                // Rejects: "generator for a generative AI"
                if after
                    .chars()
                    .take(20)
                    .any(|c| matches!(c, '(' | '{' | '[' | ':' | '='))
                {
                    count += 1;
                    continue;
                }

                // Valid if preceded by dot: obj.this, self.match
                if before.ends_with('.') {
                    count += 1;
                }
            }
        }

        count
    }

    /// Score multiplier based on token profile.
    ///
    /// Returns a value in [0.0, 1.3] that scales the raw syntax score.
    /// Code patterns boost, prose/data patterns suppress.
    fn semantic_modifier(&self, profile: &TokenProfile) -> f64 {
        // Code: identifiers + dot access (method calls, chaining)
        if profile.dot_access_count >= 1 && profile.identifier_count >= 1 {
            return self.code_dot_boost;
        }

        // Code: identifiers + operators (assignments, comparisons)
        if profile.identifier_count >= 1 && profile.operator_count >= 1 {
            return self.code_operator_boost;
        }

        // Prose: many word-like tokens, no code structure
        if profile.identifier_count >= self.min_ident_for_prose
            && profile.operator_count == 0
            && profile.dot_access_count == 0
            && profile.keyword_count <= self.max_keyword_for_prose
        {
            return self.prose_suppress;
        }

        // Data: dominated by string literals (but not if a keyword is present —
        // e.g. #include "file.h" has high string ratio but is code)
        if profile.string_ratio > self.data_string_ratio_threshold && profile.keyword_count == 0 {
            return self.data_suppress;
        }

        // No identifiers or keywords at all (non-Latin text with parens, etc.)
        if profile.identifier_count == 0 && profile.keyword_count == 0 && profile.total_tokens > 0 {
            return self.no_ident_suppress;
        }

        1.0
    }

    /// Small score adjustment for expression-level signals.
    ///
    /// Returns [-0.10, +0.10] added after the semantic modifier.
    /// Catches function calls that lack operators (e.g. `print(data)`)
    /// and penalizes pure number/string rows.
    fn expression_adjustment(&self, profile: &TokenProfile, line: &str) -> f64 {
        // Function call: ident( — boost when identifier + parens
        if self.func_call_re.is_match(line).unwrap_or(false) && profile.identifier_count >= 1 {
            return self.expr_call_boost;
        }

        // All numbers/strings with no identifiers or keywords — data row
        if profile.identifier_count == 0 && profile.keyword_count == 0 {
            if profile.number_count + profile.string_count > 0 {
                return self.expr_data_suppress;
            }
        }

        0.0
    }

    // ------------------------------------------------------------------
    // score_with_fragments
    // ------------------------------------------------------------------

    /// Score a line and identify which fragment family matches (if any).
    ///
    /// Returns `(score, family_name)` — family is `None` when no fragment matches.
    pub fn score_with_fragments(&self, line: &str) -> (f64, Option<String>) {
        let score = self.line_syntax_score(line);

        for (family, patterns) in &self.fragment_families {
            for pat in patterns {
                if pat.is_match(line).unwrap_or(false) {
                    return ((score + self.fragment_match_boost).min(1.0), Some(family.clone()));
                }
            }
        }

        (score, None)
    }

    // ------------------------------------------------------------------
    // score_lines (context window)
    // ------------------------------------------------------------------

    /// Score every line, applying context window smoothing.
    ///
    /// Claimed lines receive `-1.0` so downstream consumers can skip them.
    pub fn score_lines(&self, lines: &[&str], claimed_ranges: &HashSet<usize>) -> Vec<f64> {
        let n = lines.len();

        // --- pass 1: raw scores (including fragment boost) ---
        let raw: Vec<f64> = (0..n)
            .map(|i| {
                if claimed_ranges.contains(&i) {
                    -1.0
                } else {
                    self.score_with_fragments(lines[i]).0
                }
            })
            .collect();

        // --- pass 2: context-aware smoothing ---
        let mut result: Vec<f64> = raw.clone();

        for i in 0..n {
            if raw[i] < 0.0 {
                continue; // claimed — keep -1.0
            }

            // neighbor average (skip negatives / out-of-range)
            let mut neighbors: Vec<f64> = Vec::with_capacity(2);
            if i > 0 && raw[i - 1] >= 0.0 {
                neighbors.push(raw[i - 1]);
            }
            if i < n - 1 && raw[i + 1] >= 0.0 {
                neighbors.push(raw[i + 1]);
            }
            let neighbor_avg = if neighbors.is_empty() {
                0.0
            } else {
                neighbors.iter().sum::<f64>() / neighbors.len() as f64
            };

            // transition boost
            let mut transition_boost = 0.0;
            if i > 0 && raw[i - 1] >= 0.0 {
                let prev_stripped = lines[i - 1].trim_end();
                if let Some(last) = prev_stripped.chars().last() {
                    if (last == ':' || last == '{') && raw[i - 1] > 0.2 {
                        transition_boost = self.transition_colon_boost;
                    }
                }
                if self
                    .intro_phrase_re
                    .is_match(lines[i - 1])
                    .unwrap_or(false)
                {
                    transition_boost = transition_boost.max(self.transition_phrase_boost);
                }
            }

            // single-line comment bridge
            let mut comment_bridge = 0.0;
            if raw[i] == 0.0
                && neighbor_avg > 0.3
                && self
                    .comment_marker_re
                    .is_match(lines[i])
                    .unwrap_or(false)
            {
                comment_bridge = neighbor_avg * self.comment_bridge_factor;
            }

            let blended = raw[i] * self.self_weight
                + neighbor_avg * self.neighbor_weight
                + transition_boost
                + comment_bridge;
            result[i] = blended;
        }

        // --- pass 3: multi-line comment block bridge ---
        // The per-line comment bridge (pass 2) only works for isolated
        // comment lines next to code. Multi-line comment blocks (/** ... */)
        // have interior lines whose neighbors are also 0-score comments.
        // This pass finds contiguous comment blocks and bridges them all
        // if they're adjacent to code on either side.
        let mut i = 0;
        while i < n {
            if result[i] != 0.0
                || raw[i] < 0.0
                || !self
                    .comment_marker_re
                    .is_match(lines[i])
                    .unwrap_or(false)
            {
                i += 1;
                continue;
            }
            // Found a zero-score comment line — find the full block
            let block_start = i;
            while i < n
                && result[i] == 0.0
                && raw[i] >= 0.0
                && self
                    .comment_marker_re
                    .is_match(lines[i])
                    .unwrap_or(false)
            {
                i += 1;
            }
            let block_end = i; // exclusive

            // Check for code near above (scan up to 3 lines past blank/closing lines)
            let mut above = 0.0f64;
            let scan_above = block_start.min(3);
            for offset in 1..=scan_above {
                let j = block_start - offset;
                if raw[j] < 0.0 {
                    break;
                }
                if result[j] > above {
                    above = result[j];
                }
                if above > 0.2 {
                    break;
                }
            }

            // Check for code near below (scan up to 4 lines)
            let mut below = 0.0f64;
            let scan_below_end = (block_end + 4).min(n);
            for j in block_end..scan_below_end {
                if raw[j] < 0.0 {
                    break;
                }
                if result[j] > below {
                    below = result[j];
                }
                if below > 0.2 {
                    break;
                }
            }

            if above > 0.2 || below > 0.2 {
                let bridge = above.max(below) * self.comment_bridge_factor;
                for j in block_start..block_end {
                    result[j] = bridge;
                }
            }
        }

        result
    }

    // ------------------------------------------------------------------
    // fragment_hits_for_block
    // ------------------------------------------------------------------

    /// Count how many lines match each fragment family.
    ///
    /// Used by LanguageDetector to identify the dominant language family
    /// in a block.
    pub fn fragment_hits_for_block(&self, lines: &[&str]) -> HashMap<String, usize> {
        let mut hits: HashMap<String, usize> = HashMap::new();
        for line in lines {
            for (family, patterns) in &self.fragment_families {
                for pat in patterns {
                    if pat.is_match(line).unwrap_or(false) {
                        *hits.entry(family.clone()).or_insert(0) += 1;
                        break; // one hit per family per line
                    }
                }
            }
        }
        hits
    }

}

#[cfg(test)]
mod tests {
    use super::*;

    /// Build a minimal zone_patterns config matching the real JSON defaults.
    fn test_patterns() -> Value {
        serde_json::json!({
            "syntax": {
                "syntactic_chars": "{}()[];=<>|&!@#$^*/\\~",
                "syntactic_endings": "{;)],:",
                "strict_keywords": [
                    "def", "elif", "const", "val", "var",
                    "async", "await", "yield", "lambda",
                    "impl", "fn", "pub", "mut", "struct", "enum",
                    "sizeof", "typedef", "extern", "volatile", "register",
                    "defer", "chan", "fallthrough", "namespace", "goto",
                    "println", "printf", "fmt", "console", "System", "std",
                    "boolean", "void"
                ],
                "contextual_keywords": [
                    "import", "from", "class", "function", "return",
                    "if", "else", "for", "while", "do",
                    "try", "except", "catch", "throw", "throws", "finally",
                    "new", "let", "local",
                    "public", "private", "protected", "static", "abstract",
                    "int", "string", "bool", "float", "double", "char", "long",
                    "package", "interface", "implements", "extends", "override",
                    "raise", "assert",
                    "include", "require", "module", "export", "default",
                    "trait", "match", "use",
                    "switch", "case", "break", "continue",
                    "type", "using", "unsafe", "virtual", "select", "go",
                    "self", "super", "this"
                ],
                "assignment_pattern": "^\\s*[a-zA-Z_]\\w*\\s*[:=]",
                "scoring_weights": {
                    "syn_density_high": 0.15,
                    "syn_density_high_weight": 0.30,
                    "syn_density_med": 0.08,
                    "syn_density_med_weight": 0.15,
                    "keyword_multi_weight": 0.30,
                    "keyword_single_weight": 0.15,
                    "line_ending_weight": 0.10,
                    "assignment_weight": 0.10,
                    "indentation_weight": 0.05,
                    "fragment_match_boost": 0.25
                },
                "fragment_patterns": {
                    "c_family": [
                        "^\\s*(if|else|for|while|switch|case|return|break|continue)\\s*[\\({]",
                        "^\\s*(const|let|var|int|string|bool|boolean|float|double|void|char|long|auto)\\s+\\w+",
                        "[{};]\\s*$"
                    ],
                    "python": [
                        "^\\s*(def|class|import|from|return|yield|raise|assert|pass|del|global|nonlocal)\\s",
                        "^\\s*(if|elif|else|for|while|try|except|finally|with|as|match|case)\\s.*:\\s*(#.*)?$",
                        "^\\s*@\\w+"
                    ]
                },
                "context": {
                    "self_weight": 0.70,
                    "neighbor_weight": 0.20,
                    "transition_colon_boost": 0.10,
                    "transition_phrase_boost": 0.15,
                    "comment_bridge_factor": 0.80
                },
                "intro_phrase_pattern":
                    "(?:example|code|output|command|result|script|snippet|run this|here is|as follows|shown below|see below).*:?\\s*$",
                "comment_marker_pattern":
                    "^\\s*(?:#(?!include|define|ifdef|ifndef|endif|pragma)|//|--|/\\*|\\*(?!/)| \\*\\s|%|REM\\s)"
            },
            "tokenizer": {
                "semantic_weights": {
                    "code_dot_boost": 1.3,
                    "code_operator_boost": 1.2,
                    "prose_suppress": 0.0,
                    "data_suppress": 0.0,
                    "no_ident_suppress": 0.0,
                    "min_ident_for_prose": 4,
                    "max_keyword_for_prose": 1,
                    "data_string_ratio_threshold": 0.4,
                    "expression_call_boost": 0.10,
                    "expression_data_suppress": -0.10
                }
            }
        })
    }

    fn make_detector() -> SyntaxDetector {
        SyntaxDetector::new(&test_patterns())
    }

    // ---- line_syntax_score ----

    #[test]
    fn test_empty_line_scores_zero() {
        let d = make_detector();
        assert_eq!(d.line_syntax_score(""), 0.0);
        assert_eq!(d.line_syntax_score("   "), 0.0);
    }

    #[test]
    fn test_python_def_scores_high() {
        let d = make_detector();
        let score = d.line_syntax_score("def process(data):");
        // Should get: keyword (def) + syntactic endings (:) + density + assignment-like
        assert!(score > 0.3, "expected > 0.3, got {}", score);
    }

    #[test]
    fn test_prose_scores_low() {
        let d = make_detector();
        let score = d.line_syntax_score("This is a simple English sentence about nothing.");
        // Prose suppress should drive this near zero
        assert!(score < 0.1, "expected < 0.1, got {}", score);
    }

    #[test]
    fn test_indented_code_gets_bonus() {
        let d = make_detector();
        let base = d.line_syntax_score("result = data + 1;");
        let indented = d.line_syntax_score("    result = data + 1;");
        assert!(
            indented > base,
            "indented {} should be > base {}",
            indented,
            base
        );
    }

    // ---- count_keywords ----

    #[test]
    fn test_strict_keywords_always_count() {
        let d = make_detector();
        // "def" is strict — should count even mid-sentence
        let count = d.count_keywords("the def keyword is important");
        assert!(count >= 1, "expected >= 1, got {}", count);
    }

    #[test]
    fn test_contextual_rejected_in_prose() {
        let d = make_detector();
        // "for" is contextual — "generator for a generative AI" has no structural context
        let count = d.count_keywords("generator for a generative AI");
        assert_eq!(count, 0, "expected 0, got {}", count);
    }

    #[test]
    fn test_contextual_accepted_at_line_start() {
        let d = make_detector();
        let count = d.count_keywords("for (i = 0; i < n; i++) {");
        assert!(count >= 1, "expected >= 1, got {}", count);
    }

    #[test]
    fn test_contextual_accepted_with_structural_token() {
        let d = make_detector();
        // "static void main(" — "static" and "void" are contextual,
        // and "(" appears within 20 chars
        let count = d.count_keywords("public static void main(String[] args) {");
        assert!(count >= 2, "expected >= 2, got {}", count);
    }

    // ---- score_with_fragments ----

    #[test]
    fn test_fragment_boost_applied() {
        let d = make_detector();
        let (base_score, _) = (d.line_syntax_score("x = 1"), None::<String>);
        let (frag_score, family) = d.score_with_fragments("def process(data):");
        // "def" matches the python fragment family
        assert!(family.is_some(), "expected a family match");
        assert_eq!(family.unwrap(), "python");
        assert!(
            frag_score > base_score,
            "fragment score {} should exceed base {}",
            frag_score,
            base_score
        );
    }

    // ---- score_lines ----

    #[test]
    fn test_claimed_lines_get_negative() {
        let d = make_detector();
        let lines = vec!["def foo():", "    return 1", "plain text"];
        let claimed: HashSet<usize> = [0].into_iter().collect();
        let scores = d.score_lines(&lines, &claimed);
        assert_eq!(scores[0], -1.0);
        assert!(scores[1] > 0.0);
    }

    #[test]
    fn test_context_smoothing() {
        let d = make_detector();
        // A weak line between two strong lines should be boosted
        let lines = vec![
            "def foo():",
            "x = 1",         // moderate
            "    return x;",  // strong
        ];
        let scores = d.score_lines(&lines, &HashSet::new());
        // Middle line gets neighbor boost from both sides
        assert!(scores[1] > 0.0, "middle line should score > 0");
    }

    #[test]
    fn test_single_comment_bridge() {
        let d = make_detector();
        let lines = vec![
            "def foo():",
            "    x = 1",
            "    # compute result",  // comment between code
            "    return x",
        ];
        let scores = d.score_lines(&lines, &HashSet::new());
        // Comment line should be bridged (nonzero)
        assert!(
            scores[2] > 0.0,
            "comment between code should be bridged, got {}",
            scores[2]
        );
    }

    #[test]
    fn test_multiline_comment_bridge() {
        let d = make_detector();
        let lines = vec![
            "def foo():",
            "    x = 1",
            "    # first comment line",
            "    # second comment line",
            "    # third comment line",
            "    return x",
        ];
        let scores = d.score_lines(&lines, &HashSet::new());
        // All comment lines should be bridged by pass 3
        for j in 2..5 {
            assert!(
                scores[j] > 0.0,
                "comment line {} should be bridged, got {}",
                j,
                scores[j]
            );
        }
    }

    // ---- fragment_hits_for_block ----

    #[test]
    fn test_fragment_hits() {
        let d = make_detector();
        let lines = vec![
            "def process(data):",
            "    for item in data:",
            "    return result",
        ];
        let hits = d.fragment_hits_for_block(&lines);
        assert!(
            hits.get("python").copied().unwrap_or(0) >= 2,
            "expected >= 2 python hits, got {:?}",
            hits
        );
    }

    // ---- semantic modifier ----

    #[test]
    fn test_dot_access_boosts() {
        let d = make_detector();
        // console.log has dot access → code_dot_boost (1.3)
        let score = d.line_syntax_score("console.log(result)");
        assert!(score > 0.3, "dot access line should score well, got {}", score);
    }

    #[test]
    fn test_data_string_suppressed() {
        let d = make_detector();
        // A line dominated by strings with no keywords → data_suppress (0.0)
        let score = d.line_syntax_score(r#""hello", "world", "test""#);
        assert!(score < 0.1, "string-dominated line should be suppressed, got {}", score);
    }

    // ---- expression adjustment ----

    #[test]
    fn test_func_call_boost() {
        let d = make_detector();
        // print(data) — function call without operators
        let score = d.line_syntax_score("print(data)");
        assert!(score > 0.0, "function call should get some score, got {}", score);
    }
}
