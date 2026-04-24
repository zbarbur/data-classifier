//! Block-level code construct validator — mirrors Python block_validator.py.
//!
//! Scans a candidate block for recognizable programming constructs
//! and math/LaTeX indicators. Used by the assembler to:
//! - Suppress blocks with 0 constructs (not code)
//! - Suppress math notation blocks with weak evidence (≤2 constructs)
//! - Boost blocks with strong evidence (3+ constructs)

use fancy_regex::Regex;
use std::sync::LazyLock;

// --- Construct patterns ---

static FUNC_DEF_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?m)^\s*(?:def|function|func|fn|sub)\s+[a-zA-Z_]\w*\s*\(").unwrap()
});

static ASSIGNMENT_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?m)^\s*[a-zA-Z_]\w*(?:\.\w+)*\s*(?::?\s*\w+\s*)?=(?!=)\s*\S").unwrap()
});

static IMPORT_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#"(?m)^\s*(?:import|from|#include|require|using|package)\s+[\w"'<{./]"#).unwrap()
});

static CLASS_DEF_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?m)^\s*(?:class|struct|enum|interface|trait)\s+[A-Za-z_]\w*\s*[(\{:<]").unwrap()
});

static CONTROL_FLOW_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?m)^\s*(?:if|else\s*if|elif|for|while|switch|match)\s*[(\{]").unwrap()
});

static METHOD_CHAIN_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"\b[a-zA-Z_]\w*\.[a-zA-Z_]\w*\s*\(").unwrap()
});

static DECORATOR_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?m)^\s*@[a-zA-Z_]\w*").unwrap()
});

static PREPROCESSOR_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?m)^\s*#(?:define|ifdef|ifndef|endif|pragma|import)\s").unwrap()
});

static RETURN_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?m)^\s*(?:return|raise|throw|yield)\s+\S").unwrap()
});

static SEMICOLON_STMT_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?m)\S.*;\s*$").unwrap()
});

static FUNC_CALL_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?<!\\)\b[a-zA-Z_]\w*\(").unwrap()
});

static SQL_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?mi)^\s*(?:CREATE\s+TABLE|SELECT\s+.+\s+FROM\s|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|ALTER\s+TABLE|DROP\s+TABLE)").unwrap()
});

static R_ASSIGNMENT_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?m)^\s*[a-zA-Z_][\w.]*\s*<-\s*\S").unwrap()
});

// --- Math / LaTeX negative indicators ---

static LATEX_CMD_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"\\(?:left|right|frac|cdot|sum|int|sqrt|begin|end|text|mathbb|infty|partial|nabla)\b").unwrap()
});

static UNICODE_MATH_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"[∑∏∫∂∇λΔΣΩπμθαβγδεζηξρστφχψω≈≠≤≥±∓∈∉⊂⊃∪∩∞⟹]").unwrap()
});

/// Count distinct code construct types found in the block text.
/// Each pattern is counted at most once. Returns 0–13.
pub fn count_code_constructs(block_text: &str) -> usize {
    let patterns: &[&LazyLock<Regex>] = &[
        &FUNC_DEF_RE,
        &ASSIGNMENT_RE,
        &IMPORT_RE,
        &CLASS_DEF_RE,
        &CONTROL_FLOW_RE,
        &METHOD_CHAIN_RE,
        &DECORATOR_RE,
        &PREPROCESSOR_RE,
        &RETURN_RE,
        &SEMICOLON_STMT_RE,
        &FUNC_CALL_RE,
        &SQL_RE,
        &R_ASSIGNMENT_RE,
    ];

    patterns
        .iter()
        .filter(|pat| pat.is_match(block_text).unwrap_or(false))
        .count()
}

/// Return true if the block contains LaTeX commands or Unicode math symbols.
pub fn has_math_notation(block_text: &str) -> bool {
    LATEX_CMD_RE.is_match(block_text).unwrap_or(false)
        || UNICODE_MATH_RE.is_match(block_text).unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_python_function() {
        let block = "def process(data):\n    result = []\n    for item in data:\n        result.append(item)\n    return result";
        assert!(count_code_constructs(block) >= 3);
    }

    #[test]
    fn test_javascript_class() {
        let block = "class MyApp {\n  constructor() {\n    this.data = [];\n  }\n  render() {\n    return this.data;\n  }\n}";
        assert!(count_code_constructs(block) >= 3);
    }

    #[test]
    fn test_midjourney_template_zero() {
        let block = "Structure:\n[1] = a concept\n[2] = a detailed description of [1]\n[3] = a detailed description of the scene";
        assert_eq!(count_code_constructs(block), 0);
    }

    #[test]
    fn test_latex_is_math() {
        assert!(has_math_notation(r"\left( 2^x \right)^2 \cdot \frac{2^7}{2^5}"));
    }

    #[test]
    fn test_unicode_math() {
        assert!(has_math_notation("z_i=e^(λ_i Δt)⟹λ_i"));
    }

    #[test]
    fn test_real_code_not_math() {
        assert!(!has_math_notation("def process(data):\n    return result"));
    }
}
