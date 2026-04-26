use std::collections::HashSet;
use std::sync::OnceLock;

use fancy_regex::Regex as FancyRegex;

/// Returns true if `value` matches any known placeholder pattern.
///
/// Port of Python secret_scanner.py:191-237 (`_PLACEHOLDER_PATTERNS`).
/// Uses `fancy_regex` for the backreference pattern (#2); all others use
/// the standard `regex`-equivalent API exposed by `fancy_regex`.
pub fn is_placeholder_pattern(value: &str) -> bool {
    static PATTERNS: OnceLock<Vec<FancyRegex>> = OnceLock::new();
    let patterns = PATTERNS.get_or_init(|| {
        let raw: &[&str] = &[
            // 1. 5+ consecutive X/x
            r"(?i)[xX]{5,}",
            // 2. 8+ repeated identical chars (backreference — requires fancy_regex)
            r"(.)\1{7,}",
            // 3. Angle-bracket placeholder <...>
            r"<[^>]{1,80}>",
            // 4. Square-bracket ALL_CAPS placeholder [FOO_BAR]
            r"(?i)^\[[A-Z_]{2,}\]$",
            // 5. "your_api_key_here" style
            r"(?i)your[_\-\s].*(key|token|secret|password|credential)",
            // 6. "put your ..."
            r"(?i)put[_\-\s]?your",
            // 7. "insert your ..."
            r"(?i)insert[_\-\s]?your",
            // 8. "replace me/with/this"
            r"(?i)replace[_\-\s]?(me|with|this)",
            // 9. literal "placeholder"
            r"(?i)placeholder",
            // 10. literal "redacted"
            r"(?i)redacted",
            // 11. word "example"
            r"(?i)\bexample\b",
            // 12. starts with "sample_" or "sample-"
            r"(?i)^sample[_\-]",
            // 13. starts with "dummy_", "dummy-", or "dummy"
            r"(?i)^dummy[_\-]?",
            // 14. mustache / jinja {{...}}
            r"\{\{.*\}\}",
            // 15. shell variable ${SOME_VAR}
            r"\$\{[A-Z_]+\}",
            // 16. ends with "EXAMPLE"
            r"(?i)EXAMPLE$",
            // 17. "(key|token|secret|password) here"
            r"(?i)(key|token|secret|password)[_\-\s]here",
            // 18. "goes here"
            r"(?i)goes[_\-\s]here",
            // 19. changeme / foobar / todo / fixme
            r"(?i)\b(changeme|foobar|todo|fixme)\b",
        ];
        raw.iter()
            .map(|p| FancyRegex::new(p).expect("placeholder pattern compile error"))
            .collect()
    });

    for pat in patterns {
        if pat.is_match(value).unwrap_or(false) {
            return true;
        }
    }
    false
}

/// Returns true if `value` is NOT a placeholder credential.
///
/// Port of Python validators.py:507-534 (`not_placeholder_credential`).
/// Checks:
/// 1. Exact match in `known_placeholders` (case-insensitive trimmed)
/// 2. 5+ consecutive X/x
/// 3. 8+ consecutive identical non-X characters
/// 4. Template prefixes (your_, my_, insert_, put_, replace_, add_, enter_)
pub fn not_placeholder_credential(value: &str, known_placeholders: &HashSet<String>) -> bool {
    let trimmed = value.trim();
    let lower = trimmed.to_lowercase();

    // 1. Exact match in known placeholders set
    if known_placeholders.contains(&lower) {
        return false;
    }

    // 2. 5+ consecutive X/x
    static XXXXX: OnceLock<FancyRegex> = OnceLock::new();
    let xxxxx = XXXXX.get_or_init(|| FancyRegex::new(r"[xX]{5,}").unwrap());
    if xxxxx.is_match(trimmed).unwrap_or(false) {
        return false;
    }

    // 3. 8+ consecutive identical characters (non-X)
    static REPEAT: OnceLock<FancyRegex> = OnceLock::new();
    let repeat = REPEAT.get_or_init(|| FancyRegex::new(r"(.)\1{7,}").unwrap());
    if repeat.is_match(trimmed).unwrap_or(false) {
        return false;
    }

    // 4. Template prefixes
    static TEMPLATE: OnceLock<FancyRegex> = OnceLock::new();
    let template = TEMPLATE.get_or_init(|| {
        FancyRegex::new(
            r#"(?i)(?:^|[=:\s"'])(?:your[_\-\s]|my[_\-\s]|insert[_\-\s]|put[_\-\s]|replace[_\-\s]|add[_\-\s]|enter[_\-\s])"#,
        )
        .unwrap()
    });
    if template.is_match(trimmed).unwrap_or(false) {
        return false;
    }

    true
}

#[cfg(test)]
mod tests {
    use super::*;

    // --- is_placeholder_pattern ---

    #[test]
    fn test_placeholder_xxxxx() {
        assert!(is_placeholder_pattern("xxxxxkey"));
    }

    #[test]
    fn test_placeholder_xxxxx_upper() {
        assert!(is_placeholder_pattern("XXXXXTOKEN"));
    }

    #[test]
    fn test_placeholder_repeated() {
        assert!(is_placeholder_pattern("aaaaaaaaa"));
    }

    #[test]
    fn test_placeholder_repeated_numbers() {
        assert!(is_placeholder_pattern("111111111"));
    }

    #[test]
    fn test_placeholder_template() {
        assert!(is_placeholder_pattern("your_api_key_here"));
    }

    #[test]
    fn test_placeholder_your_token() {
        assert!(is_placeholder_pattern("your-secret-token"));
    }

    #[test]
    fn test_placeholder_angle_bracket() {
        assert!(is_placeholder_pattern("<API_KEY>"));
    }

    #[test]
    fn test_placeholder_square_bracket() {
        assert!(is_placeholder_pattern("[MY_TOKEN]"));
    }

    #[test]
    fn test_placeholder_mustache() {
        assert!(is_placeholder_pattern("{{API_KEY}}"));
    }

    #[test]
    fn test_placeholder_shell_var() {
        assert!(is_placeholder_pattern("${SECRET_KEY}"));
    }

    #[test]
    fn test_placeholder_changeme() {
        assert!(is_placeholder_pattern("changeme"));
    }

    #[test]
    fn test_placeholder_foobar() {
        assert!(is_placeholder_pattern("foobar"));
    }

    #[test]
    fn test_placeholder_todo() {
        assert!(is_placeholder_pattern("todo"));
    }

    #[test]
    fn test_placeholder_fixme() {
        assert!(is_placeholder_pattern("fixme"));
    }

    #[test]
    fn test_placeholder_redacted() {
        assert!(is_placeholder_pattern("redacted_value"));
    }

    #[test]
    fn test_placeholder_example_word() {
        assert!(is_placeholder_pattern("this is an example token"));
    }

    #[test]
    fn test_placeholder_example_suffix() {
        assert!(is_placeholder_pattern("API_KEY_EXAMPLE"));
    }

    #[test]
    fn test_placeholder_sample_prefix() {
        assert!(is_placeholder_pattern("sample_token"));
    }

    #[test]
    fn test_placeholder_dummy_prefix() {
        assert!(is_placeholder_pattern("dummy_key"));
    }

    #[test]
    fn test_placeholder_token_here() {
        assert!(is_placeholder_pattern("token_here"));
    }

    #[test]
    fn test_placeholder_goes_here() {
        assert!(is_placeholder_pattern("password goes here"));
    }

    #[test]
    fn test_placeholder_put_your() {
        assert!(is_placeholder_pattern("put_your_token_here"));
    }

    #[test]
    fn test_placeholder_replace_with() {
        assert!(is_placeholder_pattern("replace with actual key"));
    }

    #[test]
    fn test_not_placeholder_real_openai() {
        assert!(!is_placeholder_pattern("sk-proj-abc123def456"));
    }

    #[test]
    fn test_not_placeholder_real_aws() {
        assert!(!is_placeholder_pattern("AKIAIOSFODNN7EXAMPLE_NOT_MATCHING"));
    }

    #[test]
    fn test_not_placeholder_random_hex() {
        assert!(!is_placeholder_pattern("a3f9c2b1d4e8f7a0"));
    }

    // --- not_placeholder_credential ---

    #[test]
    fn test_credential_placeholder_in_set() {
        let set: HashSet<String> = ["password".to_string()].into_iter().collect();
        assert!(!not_placeholder_credential("password", &set));
    }

    #[test]
    fn test_credential_placeholder_case_insensitive() {
        let set: HashSet<String> = ["password".to_string()].into_iter().collect();
        assert!(!not_placeholder_credential("PASSWORD", &set));
    }

    #[test]
    fn test_credential_xxxxx() {
        let set: HashSet<String> = HashSet::new();
        assert!(!not_placeholder_credential("xxxxxsecret", &set));
    }

    #[test]
    fn test_credential_repeated_chars() {
        let set: HashSet<String> = HashSet::new();
        assert!(!not_placeholder_credential("aaaaaaaaa", &set));
    }

    #[test]
    fn test_credential_template_prefix() {
        let set: HashSet<String> = HashSet::new();
        assert!(!not_placeholder_credential("your_secret_key", &set));
    }

    #[test]
    fn test_credential_real() {
        let set: HashSet<String> = HashSet::new();
        assert!(not_placeholder_credential("sk-proj-abc123", &set));
    }

    #[test]
    fn test_credential_real_mixed() {
        let set: HashSet<String> = HashSet::new();
        assert!(not_placeholder_credential("ghp_1234abcDEF", &set));
    }
}
