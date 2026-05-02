//! ScopeTracker — bracket continuation and indentation-based scope tracking.
//!
//! Mirrors Python scope.py. Runs after SyntaxDetector to adjust scores for
//! lines that belong to an open scope or are continuations of a multi-line
//! statement. Only promotes zero-scored lines; never suppresses scored lines.
//!
//! Two passes:
//!   1. Bracket continuation — unclosed `(`, `[`, `{` propagate the parent
//!      line's score to subsequent zero-scored lines.
//!   2. Indentation scope — lines ending with `:` or `{` open a scope;
//!      more-indented zero-scored lines inherit the opener's score.

use serde_json::Value;
use std::collections::HashSet;

fn get_f64(v: &Value, key: &str, default: f64) -> f64 {
    v.get(key).and_then(|v| v.as_f64()).unwrap_or(default)
}

/// Adjust per-line scores based on scope context.
pub struct ScopeTracker {
    inherit_factor: f64,
    continuation_factor: f64,
    min_parent_score: f64,
}

impl ScopeTracker {
    pub fn new(patterns: &Value) -> Self {
        let scope_cfg = patterns
            .get("scope")
            .unwrap_or(&Value::Null);
        Self {
            inherit_factor: get_f64(scope_cfg, "scope_inherit_factor", 0.5),
            continuation_factor: get_f64(scope_cfg, "continuation_inherit_factor", 0.9),
            min_parent_score: get_f64(scope_cfg, "min_parent_score", 0.3),
        }
    }

    /// Return a new score list with scope/continuation adjustments.
    ///
    /// Only promotes zero-scored lines. Claimed lines (score < 0) and
    /// already-scored lines are never changed.
    pub fn adjust_scores(
        &self,
        lines: &[&str],
        scores: &[f64],
        claimed_ranges: &HashSet<usize>,
    ) -> Vec<f64> {
        let mut result: Vec<f64> = scores.to_vec();
        let n = lines.len();

        // --- Pass 1: Bracket continuation ---
        let mut open_count: i32 = 0;
        let mut parent_score: f64 = 0.0;

        for i in 0..n {
            if claimed_ranges.contains(&i) || result[i] < 0.0 {
                open_count = 0;
                parent_score = 0.0;
                continue;
            }

            // Inherit from parent if in continuation and current is zero
            if open_count > 0
                && result[i] == 0.0
                && parent_score >= self.min_parent_score
            {
                result[i] = parent_score * self.continuation_factor;
            }

            // Update bracket tracking
            let delta = Self::net_brackets(lines[i]);
            open_count = (open_count + delta).max(0);

            // Track parent score (most recent scored line)
            if result[i] >= self.min_parent_score {
                parent_score = result[i];
            }
        }

        // --- Pass 2: Indentation scope ---
        let mut scope_indent: i32 = -1;
        let mut scope_score: f64 = 0.0;

        for i in 0..n {
            if claimed_ranges.contains(&i) || result[i] < 0.0 {
                scope_indent = -1;
                scope_score = 0.0;
                continue;
            }

            let stripped = lines[i].trim();
            if stripped.is_empty() {
                continue; // skip blanks, preserve scope
            }

            let indent = (lines[i].len() - lines[i].trim_start().len()) as i32;

            // Check if we've exited the scope
            if scope_indent >= 0 && indent <= scope_indent {
                scope_indent = -1;
                scope_score = 0.0;
            }

            // Inherit scope score for zero-scored lines inside scope
            if scope_indent >= 0
                && result[i] == 0.0
                && scope_score >= self.min_parent_score
            {
                result[i] = scope_score * self.inherit_factor;
            }

            // Open new scope: scored line ending with ':' or '{'
            if result[i] >= self.min_parent_score
                && (stripped.ends_with(':') || stripped.ends_with('{'))
            {
                scope_indent = indent;
                scope_score = result[i];
            }
        }

        result
    }

    /// Count net unclosed brackets (openers minus closers).
    /// Skips brackets inside quoted strings.
    fn net_brackets(line: &str) -> i32 {
        let mut in_string: Option<char> = None;
        let mut net: i32 = 0;
        let mut prev = '\0';

        for ch in line.chars() {
            if ch == '"' || ch == '\'' {
                if in_string.is_none() {
                    in_string = Some(ch);
                } else if in_string == Some(ch) && prev != '\\' {
                    in_string = None;
                }
                prev = ch;
                continue;
            }
            if in_string.is_some() {
                prev = ch;
                continue;
            }
            match ch {
                '(' | '[' | '{' => net += 1,
                ')' | ']' | '}' => net -= 1,
                _ => {}
            }
            prev = ch;
        }
        net
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_tracker() -> ScopeTracker {
        ScopeTracker::new(&serde_json::json!({
            "scope": {
                "scope_inherit_factor": 0.5,
                "continuation_inherit_factor": 0.9,
                "min_parent_score": 0.3
            }
        }))
    }

    #[test]
    fn test_bracket_continuation() {
        let t = make_tracker();
        let lines = vec![
            "result = func(",
            "    arg1,",
            "    arg2",
            ")",
        ];
        let scores = vec![0.5, 0.0, 0.0, 0.0];
        let result = t.adjust_scores(&lines, &scores, &HashSet::new());
        // Lines 1,2 should be promoted (inside open paren)
        assert!(result[1] > 0.0, "arg1 should be promoted, got {}", result[1]);
        assert!(result[2] > 0.0, "arg2 should be promoted, got {}", result[2]);
    }

    #[test]
    fn test_indentation_scope() {
        let t = make_tracker();
        let lines = vec![
            "def foo():",
            "    # some comment",
            "    pass",
        ];
        let scores = vec![0.5, 0.0, 0.0];
        let result = t.adjust_scores(&lines, &scores, &HashSet::new());
        assert!(result[1] > 0.0, "indented line should be promoted");
        assert!(result[2] > 0.0, "pass should be promoted");
    }

    #[test]
    fn test_claimed_lines_unmodified() {
        let t = make_tracker();
        let lines = vec!["code", "claimed", "code"];
        let scores = vec![0.5, -1.0, 0.5];
        let claimed: HashSet<usize> = [1].into_iter().collect();
        let result = t.adjust_scores(&lines, &scores, &claimed);
        assert_eq!(result[1], -1.0);
    }

    #[test]
    fn test_net_brackets() {
        assert_eq!(ScopeTracker::net_brackets("func(a, b)"), 0);
        assert_eq!(ScopeTracker::net_brackets("func(a,"), 1);
        assert_eq!(ScopeTracker::net_brackets(")"), -1);
        // Brackets inside strings are ignored
        assert_eq!(ScopeTracker::net_brackets(r#"x = "hello(""#), 0);
    }
}
