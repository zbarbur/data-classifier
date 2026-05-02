//! Pre-screen fast path — rejects ~97% of prompts that contain no code.
//!
//! Mirrors Python pre_screen.py. Must have zero false negatives.

use std::collections::HashSet;
use std::sync::LazyLock;

static PRESCREEN_CHARS: LazyLock<HashSet<char>> = LazyLock::new(|| {
    "{}()[];=<>|&@#$^~".chars().collect()
});

const DENSITY_THRESHOLD: f64 = 0.03;

/// Return `true` if text MIGHT contain code/structured blocks.
///
/// `false` means definitely no blocks — skip all detectors.
pub fn pre_screen(text: &str) -> bool {
    if text.is_empty() || text.trim().is_empty() {
        return false;
    }

    // Check 1: fence markers
    if text.contains("```") || text.contains("~~~") {
        return true;
    }

    // Check 2: syntactic character density
    let total = text.chars().count();
    let syn_count = text.chars().filter(|c| PRESCREEN_CHARS.contains(c)).count();
    if syn_count as f64 / total as f64 > DENSITY_THRESHOLD {
        return true;
    }

    // Check 3: indentation patterns
    if text.contains("\n    ") || text.contains("\n\t") {
        return true;
    }

    // Check 4: closing tags (markup)
    if text.contains("</") {
        return true;
    }

    false
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_empty() {
        assert!(!pre_screen(""));
        assert!(!pre_screen("   "));
    }

    #[test]
    fn test_fence_markers() {
        assert!(pre_screen("Here is code:\n```python\nprint(1)\n```"));
        assert!(pre_screen("~~~\nsome block\n~~~"));
    }

    #[test]
    fn test_syntactic_density() {
        assert!(pre_screen("if (x > 0) { return y; }"));
    }

    #[test]
    fn test_indentation() {
        assert!(pre_screen("def foo():\n    return 1"));
    }

    #[test]
    fn test_markup_tags() {
        assert!(pre_screen("<div>hello</div>"));
    }

    #[test]
    fn test_plain_prose_rejected() {
        assert!(!pre_screen("This is just a simple sentence about the weather today."));
    }
}
