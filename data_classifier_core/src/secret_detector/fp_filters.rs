//! False-positive filters for secret/credential detection.
//!
//! Port of the union of:
//! - Python `data_classifier/engines/secret_scanner.py:369-604` (`_value_is_obviously_not_secret`)
//! - JS `data_classifier/clients/browser/src/scanner-core.js:237-319` (`valueIsObviouslyNotSecret`)
//!
//! Returns `true` when a value is *obviously not* a secret (i.e. should be
//! suppressed).  Categories include configuration constants, URLs, dates, IPs,
//! numeric strings, code expressions, file paths, FQCNs, HTML/XML fragments,
//! identifiers, code constructs, CLI patterns, slash-separated words, simple
//! values, natural language / non-Latin text.

use std::collections::HashSet;
use std::sync::OnceLock;

use fancy_regex::Regex as FancyRegex;
use regex::Regex;

// ---------------------------------------------------------------------------
// Static config-value set (union of Python _CONFIG_VALUES + JS configValues)
// ---------------------------------------------------------------------------
fn config_values() -> &'static HashSet<&'static str> {
    static SET: OnceLock<HashSet<&str>> = OnceLock::new();
    SET.get_or_init(|| {
        [
            "true", "false", "yes", "no", "on", "off", "enabled", "disabled",
            "none", "null", "undefined", "nan", "info", "debug", "warn",
            "error", "trace", "production", "staging", "development", "test",
            "testing", "default", "localhost", "example", "sample",
        ]
        .into_iter()
        .collect()
    })
}

// ---------------------------------------------------------------------------
// Lazy-compiled regex helpers
// ---------------------------------------------------------------------------
macro_rules! lazy_re {
    ($name:ident, $pat:expr) => {
        fn $name() -> &'static Regex {
            static RE: OnceLock<Regex> = OnceLock::new();
            RE.get_or_init(|| Regex::new($pat).expect(concat!("fp_filters: bad regex: ", $pat)))
        }
    };
}

// Patterns that require lookaround must use fancy-regex (backtracking engine).
macro_rules! lazy_fancy_re {
    ($name:ident, $pat:expr) => {
        fn $name() -> &'static FancyRegex {
            static RE: OnceLock<FancyRegex> = OnceLock::new();
            RE.get_or_init(|| FancyRegex::new($pat).expect(concat!("fp_filters: bad fancy regex: ", $pat)))
        }
    };
}

// Category 2 — URLs
lazy_re!(re_url_like, r"(?i)^https?://");
lazy_re!(re_protocol_relative, r"^//\w");
lazy_re!(re_bare_domain_url, r"^[a-z][a-z0-9\-]*(?:\.[a-z][a-z0-9\-]*){2,}/");

// Category 3 — Dates
lazy_re!(re_date_like, r"^\d{4}[-/]\d{2}[-/]\d{2}");

// Category 4 — IP addresses
lazy_re!(re_ip_like, r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$");

// Category 5 — Numeric
lazy_re!(re_numeric_only, r"^[\d\s.,+\-]+$");

// Category 6 — Code expressions
lazy_re!(re_code_dot_notation, r"^[a-zA-Z_]\w*(\.[a-zA-Z_]\w*)+[;,]?$");
lazy_re!(re_code_bracket_access, r"^[a-zA-Z_]\w*(\.[a-zA-Z_]\w*)*\[[^\]]+\][;,]?$");
lazy_re!(re_code_semicolon, r"^[a-zA-Z_]\w*;$");
lazy_re!(re_code_call, r"[({].*[=;]");
lazy_fancy_re!(re_shell_variable, r"^\$(?!2[aby]\$|[56]\$|argon2|scrypt)[\w{]");
lazy_re!(re_constant_name, r"^[A-Z][A-Z0-9]*([_\-][A-Z0-9]+)+$");
lazy_re!(re_code_punctuation, r"^[\[\](){}<>,./\\|!@#%^&*\-+=~`;:\s]+$");

// Category 7 — File paths
lazy_re!(re_file_path, r"^[/~][\w./\-:+]+$|^[A-Z]:\\[\w\\.\-:+]+$");
lazy_re!(re_win_drive, r"^[A-Za-z]:[/\\]");
lazy_re!(re_relative_path, r"^\.\.?/");

// Category 9 — HTML / XML / encoding
lazy_re!(re_html_attr, r#"(?i)^(?:href|src|integrity|action|id|class|data-\w+)\s*=\s*""#);
lazy_re!(re_sri_hash, r"^sha(?:256|384|512)-[A-Za-z0-9+/=]+$");
lazy_re!(re_ssh_fingerprint, r"^SHA(?:256|384|512):");
lazy_re!(re_xmlns_cargo, r"^(?:xmlns|cargo):");

// Category 10 — Identifiers
lazy_re!(re_camelcase_word, r"[A-Z][a-z]{3,}");
lazy_re!(re_android_bytecode, r"^L[a-z][a-z0-9]*/");
lazy_re!(re_vulkan_id, r"^VUID-");

// Category 11 — Code constructs
lazy_re!(re_dict_bracket, r"^[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*\[");
lazy_re!(re_func_call, r"^[a-zA-Z_!][\w:.]*\(");

// Category 12 — CLI / assignment patterns
lazy_re!(re_cli_flag_url, r"^--[\w\-]+=https?://");
lazy_re!(re_key_path_assign, r#"^[\w\-]+="(?:https?://|/|~/|\$|\.\.?/)"#);
lazy_re!(re_python_fstring_url, r"^f['\x22]https?://");

// Category 14 — Simple values
lazy_re!(re_single_word, r"^[a-zA-Z]+(-[a-zA-Z]+)*$");
lazy_re!(re_ethereum, r"^0x[0-9a-fA-F]{40}$");

// Category 16 — Markdown / rich text
lazy_re!(re_markdown_image_link, r"^!?\[.*\]\(");

// Category 17 — URL-encoded values (2+ percent-encoded chars = URL query/cookie)
lazy_re!(re_url_encoded, r"%[0-9A-Fa-f]{2}.*%[0-9A-Fa-f]{2}");

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

/// Returns `true` if `value` is obviously *not* a secret/credential.
///
/// This is the union of all false-positive suppression rules from both the
/// Python `secret_scanner.py` and the JS `scanner-core.js` implementations.
/// A return value of `true` means the value should be suppressed (not reported
/// as a secret).
pub fn value_is_obviously_not_secret(value: &str, prose_threshold: f64) -> bool {
    // ---- Category 1: Configuration values ----
    let v_lower = value.to_lowercase();
    let v_trimmed = v_lower.trim();
    if config_values().contains(v_trimmed) {
        return true;
    }

    // ---- Category 2: URL patterns ----
    if is_match(re_url_like(), value) {
        return true;
    }

    // ---- Category 3: Date patterns ----
    if is_match(re_date_like(), value) {
        return true;
    }

    // ---- Category 4: IP address ----
    if is_match(re_ip_like(), value) {
        return true;
    }

    // ---- Category 5: Numeric only ----
    if is_match(re_numeric_only(), value) {
        return true;
    }

    // ---- Category 6: Code expressions ----
    // Dot notation — guard: skip if any segment > 32 chars (JWT, not code)
    if is_match(re_code_dot_notation(), value) {
        let stripped = value.trim_end_matches(|c| c == ';' || c == ',');
        if stripped.split('.').all(|seg| seg.len() <= 32) {
            return true;
        }
    }
    if is_match(re_code_bracket_access(), value) || is_match(re_code_semicolon(), value) {
        return true;
    }
    // Code call — parens/braces with equals/semicolons (search, not anchored)
    if is_find(re_code_call(), value) {
        return true;
    }
    // Shell/env variable (exclude crypt hash prefixes)
    if is_match_fancy(re_shell_variable(), value) {
        return true;
    }
    // ALL_CAPS constant
    if is_match(re_constant_name(), value) {
        return true;
    }
    // Code punctuation only
    if is_match(re_code_punctuation(), value) {
        return true;
    }

    // ---- Category 7: File paths ----
    if is_match(re_file_path(), value) {
        return true;
    }
    // Quoted paths — strip leading/trailing quotes, recheck
    let stripped_q = value.trim().trim_matches(|c| c == '"' || c == '\'');
    if is_match(re_file_path(), stripped_q) {
        return true;
    }
    // Windows drive letter after quote stripping
    if is_match(re_win_drive(), stripped_q) {
        return true;
    }

    // ---- Category 8: FQCNs (Java/Python class names) ----
    // 4+ dot-separated segments, each starts with letter, each <= 50 chars
    {
        let fqcn_cleaned = value.trim_end_matches(|c| c == ';' || c == ',' || c == '(' || c == ')');
        let segments: Vec<&str> = fqcn_cleaned.split('.').collect();
        if segments.len() >= 4
            && segments
                .iter()
                .all(|s| !s.is_empty() && s.starts_with(|c: char| c.is_ascii_alphabetic()) && s.len() <= 50)
        {
            return true;
        }
    }

    // ---- Category 2 continued: URLs without protocol ----
    if is_match(re_protocol_relative(), value) {
        return true;
    }
    if is_match(re_bare_domain_url(), value) {
        return true;
    }

    // ---- Category 9: HTML / XML / encoding ----
    if is_match(re_html_attr(), value) {
        return true;
    }
    if is_match(re_sri_hash(), value) {
        return true;
    }
    if is_match(re_ssh_fingerprint(), value) {
        return true;
    }

    // ---- Category 10: Identifiers ----
    // Purely-alpha CamelCase: >90% alpha AND >=3 words with [A-Z][a-z]{3,}
    {
        let alpha_count = value.chars().filter(|c| c.is_ascii_alphabetic()).count();
        let len = value.len().max(1);
        if (alpha_count as f64 / len as f64) > 0.90 {
            if re_camelcase_word().find_iter(value).count() >= 3 {
                return true;
            }
        }
    }
    // Android/JVM bytecode
    if is_match(re_android_bytecode(), value) {
        return true;
    }

    // ---- Category 11: Code constructs ----
    // Dict/config bracket access
    if is_match(re_dict_bracket(), value) {
        return true;
    }
    // Function calls (no spaces)
    if !value.contains(' ') && is_match(re_func_call(), value) {
        return true;
    }
    // XML namespace / cargo directives
    if is_match(re_xmlns_cargo(), value) {
        return true;
    }

    // ---- Category 12: CLI / assignment patterns ----
    // key="path/url" assignments
    if is_match(re_key_path_assign(), value) {
        return true;
    }
    // file:// URI
    if value.contains("file://") {
        return true;
    }
    // Ethereum address
    if is_match(re_ethereum(), value) {
        return true;
    }
    // Relative paths
    if is_match(re_relative_path(), value) {
        return true;
    }
    // CLI flags with URL
    if is_match(re_cli_flag_url(), value) {
        return true;
    }

    // ---- Category 13: Slash-separated words ----
    {
        let slash_segs: Vec<&str> = value.split('/').filter(|s| !s.is_empty()).collect();
        if slash_segs.len() >= 4
            && slash_segs
                .iter()
                .all(|s| s.starts_with(|c: char| c.is_ascii_alphabetic()) && s.len() <= 30)
        {
            return true;
        }
    }

    // Template literals with ${...}
    if value.contains("${") {
        return true;
    }

    // Vulkan/OpenGL validation IDs
    if is_match(re_vulkan_id(), value) {
        return true;
    }

    // Values starting with open bracket/paren
    if value.starts_with('[') || value.starts_with('(') {
        return true;
    }

    // Backslash-separated paths (2+ backslashes)
    if value.chars().filter(|&c| c == '\\').count() >= 2 {
        return true;
    }

    // Python f-string URLs
    if is_match(re_python_fstring_url(), value) {
        return true;
    }

    // ---- Category 14: Simple values ----
    // Single word: letters + hyphens only, max 30 chars
    {
        let trimmed = value.trim();
        if trimmed.len() <= 30 && is_match(re_single_word(), trimmed) {
            return true;
        }
    }
    // String concatenation — starts/ends with +
    {
        let stripped = value.trim().trim_matches(|c| c == '"' || c == '\'').trim();
        if stripped.starts_with('+') || stripped.ends_with('+') {
            return true;
        }
    }

    // ---- Category 16: Alphabet/charset constants ----
    // Sorted or sequential character sets like "abcdefghijklmnop..."
    {
        let stripped = value.trim().trim_matches(|c| c == '"' || c == '\'');
        if stripped.len() >= 20 {
            // Check for sequential lowercase run of 10+
            let has_seq_lower = stripped.contains("abcdefghij");
            let has_seq_upper = stripped.contains("ABCDEFGHIJ");
            let has_seq_digit = stripped.contains("0123456789");
            if (has_seq_lower && has_seq_upper) || (has_seq_lower && has_seq_digit) || (has_seq_upper && has_seq_digit) {
                return true;
            }
        }
    }

    // ---- Category 16b: Markdown / rich text ----
    // Markdown image ![alt](url) or link [text](url)
    if is_match(re_markdown_image_link(), value) {
        return true;
    }

    // ---- Category 17: URL-encoded / cookie / query-string values ----
    // Values with 2+ percent-encoded sequences are URL query params or cookies
    if is_find(re_url_encoded(), value) {
        return true;
    }

    // ---- Category 18: Brace-delimited expressions ----
    // Python f-string / template expressions with matching braces: {expr}
    // Catches {list(...)}, {data.key}, etc. — but NOT ${...} (already caught above)
    if value.contains('{') && value.contains('}') && !value.contains("${") {
        return true;
    }

    // ---- Category 19: Comma-separated lists ----
    // HTTP headers, config lists: "DNT,X-Mx-ReqToken,Keep-Alive,..."
    {
        let comma_parts: Vec<&str> = value.split(',').collect();
        if comma_parts.len() >= 4
            && comma_parts.iter().all(|p| {
                let t = p.trim();
                !t.is_empty() && t.len() <= 40 && t.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
            })
        {
            return true;
        }
    }

    // ---- Category 15: Natural language detection ----
    // Prose: spaces + high alpha ratio
    if value.contains(' ') {
        let alpha_count = value.chars().filter(|c| c.is_alphabetic()).count();
        let len = value.len().max(1);
        if (alpha_count as f64 / len as f64) > prose_threshold {
            return true;
        }
    }

    // Non-Latin scripts: CJK, Cyrillic, Arabic, Indic, Thai, Korean
    for ch in value.chars() {
        let cp = ch as u32;
        if (0x0900..=0x0DFF).contains(&cp)    // Devanagari..Malayalam
            || (0x0E00..=0x0E7F).contains(&cp) // Thai
            || (0x3000..=0x9FFF).contains(&cp)  // CJK
            || (0xAC00..=0xD7AF).contains(&cp)  // Korean Hangul
            || (0x0400..=0x04FF).contains(&cp)   // Cyrillic
            || (0x0600..=0x06FF).contains(&cp)   // Arabic
        {
            return true;
        }
    }

    false
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// `regex::Regex::is_match` — direct call, no Result wrapping needed.
#[inline]
fn is_match(re: &Regex, text: &str) -> bool {
    re.is_match(text)
}

/// `regex::Regex::find` (search) — direct call.
#[inline]
fn is_find(re: &Regex, text: &str) -> bool {
    re.find(text).is_some()
}

/// `fancy_regex::Regex::is_match` wrapper for the few patterns that need
/// lookaround — treats errors as non-match.
#[inline]
fn is_match_fancy(re: &FancyRegex, text: &str) -> bool {
    re.is_match(text).unwrap_or(false)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;

    // ---------------------------------------------------------------
    // Should be SUPPRESSED (return true = not a secret)
    // ---------------------------------------------------------------

    // Category 1: Config values
    #[test]
    fn test_config_true() {
        assert!(value_is_obviously_not_secret("true", 0.6));
    }
    #[test]
    fn test_config_false() {
        assert!(value_is_obviously_not_secret("false", 0.6));
    }
    #[test]
    fn test_config_null() {
        assert!(value_is_obviously_not_secret("null", 0.6));
    }
    #[test]
    fn test_config_none() {
        assert!(value_is_obviously_not_secret("none", 0.6));
    }
    #[test]
    fn test_config_production() {
        assert!(value_is_obviously_not_secret("production", 0.6));
    }
    #[test]
    fn test_config_debug() {
        assert!(value_is_obviously_not_secret("debug", 0.6));
    }
    #[test]
    fn test_config_case_insensitive() {
        assert!(value_is_obviously_not_secret("TRUE", 0.6));
    }
    #[test]
    fn test_config_with_whitespace() {
        assert!(value_is_obviously_not_secret("  false  ", 0.6));
    }
    #[test]
    fn test_config_on() {
        assert!(value_is_obviously_not_secret("on", 0.6));
    }
    #[test]
    fn test_config_off() {
        assert!(value_is_obviously_not_secret("off", 0.6));
    }
    #[test]
    fn test_config_enabled() {
        assert!(value_is_obviously_not_secret("enabled", 0.6));
    }
    #[test]
    fn test_config_disabled() {
        assert!(value_is_obviously_not_secret("disabled", 0.6));
    }
    #[test]
    fn test_config_undefined() {
        assert!(value_is_obviously_not_secret("undefined", 0.6));
    }
    #[test]
    fn test_config_sample() {
        assert!(value_is_obviously_not_secret("sample", 0.6));
    }

    // Category 2: URLs
    #[test]
    fn test_url_https() {
        assert!(value_is_obviously_not_secret("https://example.com", 0.6));
    }
    #[test]
    fn test_url_http() {
        assert!(value_is_obviously_not_secret("http://localhost:8080/api", 0.6));
    }
    #[test]
    fn test_url_protocol_relative() {
        assert!(value_is_obviously_not_secret("//seller.dhgate.com/path", 0.6));
    }
    #[test]
    fn test_url_bare_domain() {
        assert!(value_is_obviously_not_secret("colab.research.google.com/drive/x", 0.6));
    }

    // Category 3: Dates
    #[test]
    fn test_date_dash() {
        assert!(value_is_obviously_not_secret("2024-01-15", 0.6));
    }
    #[test]
    fn test_date_slash() {
        assert!(value_is_obviously_not_secret("2024/01/15", 0.6));
    }
    #[test]
    fn test_date_with_time() {
        assert!(value_is_obviously_not_secret("2024-01-15T10:30:00Z", 0.6));
    }

    // Category 4: IP addresses
    #[test]
    fn test_ip_private() {
        assert!(value_is_obviously_not_secret("192.168.1.1", 0.6));
    }
    #[test]
    fn test_ip_localhost() {
        assert!(value_is_obviously_not_secret("127.0.0.1", 0.6));
    }

    // Category 5: Numeric
    #[test]
    fn test_numeric_decimal() {
        assert!(value_is_obviously_not_secret("12345.67", 0.6));
    }
    #[test]
    fn test_numeric_negative() {
        assert!(value_is_obviously_not_secret("-42", 0.6));
    }
    #[test]
    fn test_numeric_comma() {
        assert!(value_is_obviously_not_secret("1,234,567", 0.6));
    }

    // Category 6: Code expressions
    #[test]
    fn test_dot_notation() {
        assert!(value_is_obviously_not_secret("form.password.data", 0.6));
    }
    #[test]
    fn test_dot_notation_semicolon() {
        assert!(value_is_obviously_not_secret("textBox2.Text;", 0.6));
    }
    #[test]
    fn test_bracket_access() {
        assert!(value_is_obviously_not_secret("request.POST[\"key\"]", 0.6));
    }
    #[test]
    fn test_code_semicolon() {
        assert!(value_is_obviously_not_secret("tokenApp;", 0.6));
    }
    #[test]
    fn test_code_call_parens_equals() {
        assert!(value_is_obviously_not_secret("OleDbConnection(\"Provider=Microsoft.Jet\")", 0.6));
    }
    #[test]
    fn test_shell_var() {
        assert!(value_is_obviously_not_secret("$SECRET_KEY", 0.6));
    }
    #[test]
    fn test_shell_var_braces() {
        assert!(value_is_obviously_not_secret("${DB_PASS}", 0.6));
    }
    #[test]
    fn test_constant_name() {
        assert!(value_is_obviously_not_secret("API_KEY_BINANCE", 0.6));
    }
    #[test]
    fn test_constant_hyphen() {
        assert!(value_is_obviously_not_secret("MY-CONFIG-VALUE", 0.6));
    }
    #[test]
    fn test_code_punctuation() {
        assert!(value_is_obviously_not_secret("));", 0.6));
    }
    #[test]
    fn test_code_punctuation_brackets() {
        assert!(value_is_obviously_not_secret("]{}", 0.6));
    }

    // Category 7: File paths
    #[test]
    fn test_unix_path() {
        assert!(value_is_obviously_not_secret("/home/user/.config", 0.6));
    }
    #[test]
    fn test_tilde_path() {
        assert!(value_is_obviously_not_secret("~/config/secret", 0.6));
    }
    #[test]
    fn test_windows_path() {
        assert!(value_is_obviously_not_secret("C:\\Users\\test\\file", 0.6));
    }
    #[test]
    fn test_quoted_path() {
        assert!(value_is_obviously_not_secret("\"/c:/path/file\"", 0.6));
    }
    #[test]
    fn test_relative_path() {
        assert!(value_is_obviously_not_secret("../src/file.rs", 0.6));
    }
    #[test]
    fn test_relative_path_dot() {
        assert!(value_is_obviously_not_secret("./build/output", 0.6));
    }
    #[test]
    fn test_file_uri() {
        assert!(value_is_obviously_not_secret("file:///C:/Users/test", 0.6));
    }

    // Category 8: FQCNs
    #[test]
    fn test_fqcn_java() {
        assert!(value_is_obviously_not_secret("com.example.MyClass.method", 0.6));
    }
    #[test]
    fn test_fqcn_gradle() {
        assert!(value_is_obviously_not_secret(
            "org.gradle.api.internal.project.DefaultProjectStateRegistry",
            0.6
        ));
    }

    // Category 9: HTML / XML / encoding
    #[test]
    fn test_html_href() {
        assert!(value_is_obviously_not_secret("href=\"https://example.com\"", 0.6));
    }
    #[test]
    fn test_html_src() {
        assert!(value_is_obviously_not_secret("src=\"/img/logo.png\"", 0.6));
    }
    #[test]
    fn test_html_data_attr() {
        assert!(value_is_obviously_not_secret("data-token=\"abc\"", 0.6));
    }
    #[test]
    fn test_sri_hash() {
        assert!(value_is_obviously_not_secret("sha256-abc123def456+/=", 0.6));
    }
    #[test]
    fn test_sri_sha384() {
        assert!(value_is_obviously_not_secret("sha384-oqVuAfXRKap7fdgcCY5uykM6+R9GqQ8K/uxy9rx7HNQlGYl1kPzQho1wx4JwY8wC", 0.6));
    }
    #[test]
    fn test_ssh_fingerprint() {
        assert!(value_is_obviously_not_secret("SHA256:NkM/srqYj7zGKHzICaoq5963pLDX", 0.6));
    }
    #[test]
    fn test_xmlns() {
        assert!(value_is_obviously_not_secret("xmlns:xs=\"http://www.w3.org/schema\"", 0.6));
    }
    #[test]
    fn test_cargo_directive() {
        assert!(value_is_obviously_not_secret("cargo:rerun-if-env-changed=FOO", 0.6));
    }

    // Category 10: Identifiers
    #[test]
    fn test_camelcase_identifier() {
        assert!(value_is_obviously_not_secret("FeatureGateManagerService", 0.6));
    }
    #[test]
    fn test_camelcase_long() {
        assert!(value_is_obviously_not_secret("FFlagSimCSGV3CacheVerboseBSPMemory", 0.6));
    }
    #[test]
    fn test_android_bytecode() {
        assert!(value_is_obviously_not_secret("Lcom/android/server/", 0.6));
    }
    #[test]
    fn test_android_dalvik() {
        assert!(value_is_obviously_not_secret("Ldalvik/system/CloseGuard;", 0.6));
    }
    #[test]
    fn test_vulkan_id() {
        assert!(value_is_obviously_not_secret("VUID-VkFramebufferCreateInfo", 0.6));
    }

    // Category 11: Code constructs
    #[test]
    fn test_dict_bracket() {
        assert!(value_is_obviously_not_secret("app.config['SQLALCHEMY_DATABASE_URI']", 0.6));
    }
    #[test]
    fn test_function_call() {
        assert!(value_is_obviously_not_secret("Objects.requireNonNull(x)", 0.6));
    }
    #[test]
    fn test_function_call_cpp() {
        assert!(value_is_obviously_not_secret("validationLayers.push_back(\"VK_LAYER\"", 0.6));
    }
    #[test]
    fn test_template_literal() {
        assert!(value_is_obviously_not_secret("prefix${data.id}suffix", 0.6));
    }
    #[test]
    fn test_starts_with_bracket() {
        assert!(value_is_obviously_not_secret("[TransactionTypes.PURCHASE]", 0.6));
    }
    #[test]
    fn test_starts_with_paren() {
        assert!(value_is_obviously_not_secret("(async function() {", 0.6));
    }
    #[test]
    fn test_backslash_separated() {
        assert!(value_is_obviously_not_secret("227\\Logs\\Chrome\\Default\\Cookies.txt", 0.6));
    }

    // Category 12: CLI / assignment patterns
    #[test]
    fn test_cli_flag_url() {
        assert!(value_is_obviously_not_secret("--tunnel_url=https://colab.com", 0.6));
    }
    #[test]
    fn test_key_path_assign() {
        assert!(value_is_obviously_not_secret("WEAVIATE_PATH=\"/home/me/data\"", 0.6));
    }
    #[test]
    fn test_python_fstring() {
        assert!(value_is_obviously_not_secret("f'https://api.example.com/{key}'", 0.6));
    }

    // Category 13: Slash-separated words
    #[test]
    fn test_slash_words() {
        assert!(value_is_obviously_not_secret("ISE/ACS/Sourcefire/Meraki", 0.6));
    }
    #[test]
    fn test_slash_words_assets() {
        assert!(value_is_obviously_not_secret("Assets/Resources/SourceResources/Motion", 0.6));
    }

    // Category 14: Simple values
    #[test]
    fn test_single_word() {
        assert!(value_is_obviously_not_secret("development-mode", 0.6));
    }
    #[test]
    fn test_single_word_alpha() {
        assert!(value_is_obviously_not_secret("Steganography", 0.6));
    }
    #[test]
    fn test_string_concat_start() {
        assert!(value_is_obviously_not_secret("+my_token+", 0.6));
    }
    #[test]
    fn test_string_concat_end() {
        assert!(value_is_obviously_not_secret("variable+", 0.6));
    }
    #[test]
    fn test_ethereum_address() {
        assert!(value_is_obviously_not_secret(
            "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD28",
            0.6
        ));
    }

    // Category 15: Natural language
    #[test]
    fn test_prose_english() {
        assert!(value_is_obviously_not_secret("the quick brown fox jumps", 0.6));
    }
    #[test]
    fn test_prose_sentence() {
        assert!(value_is_obviously_not_secret("This is a password policy description", 0.6));
    }
    #[test]
    fn test_cjk_characters() {
        assert!(value_is_obviously_not_secret("\u{5BC6}\u{7801}\u{662F}123", 0.6));
    }
    #[test]
    fn test_cyrillic() {
        assert!(value_is_obviously_not_secret("\u{043F}\u{0430}\u{0440}\u{043E}\u{043B}\u{044C}", 0.6));
    }
    #[test]
    fn test_arabic() {
        assert!(value_is_obviously_not_secret("\u{0643}\u{0644}\u{0645}\u{0629} \u{0627}\u{0644}\u{0633}\u{0631}", 0.6));
    }
    #[test]
    fn test_thai() {
        assert!(value_is_obviously_not_secret("\u{0E23}\u{0E2B}\u{0E31}\u{0E2A}\u{0E1C}\u{0E48}\u{0E32}\u{0E19}", 0.6));
    }
    #[test]
    fn test_korean() {
        assert!(value_is_obviously_not_secret("\u{BE44}\u{BC00}\u{BC88}\u{D638}", 0.6));
    }
    #[test]
    fn test_devanagari() {
        assert!(value_is_obviously_not_secret("\u{092A}\u{093E}\u{0938}\u{0935}\u{0930}\u{094D}\u{0921}", 0.6));
    }

    // Category 16: Markdown
    #[test]
    fn test_markdown_image() {
        assert!(value_is_obviously_not_secret("![girl](https://source.unsplash.com/random/400x300", 0.6));
    }
    #[test]
    fn test_markdown_link() {
        assert!(value_is_obviously_not_secret("[click here](https://example.com/page)", 0.6));
    }

    // Category 17: URL-encoded
    #[test]
    fn test_url_encoded_cookie() {
        assert!(value_is_obviously_not_secret(
            "_fmdata=s8R408o4s3s%2FHDz7f6bGAsfUs1d58PKLnPGkiC5FMzdu8H3jPpxG%2Bifm7PPDeLBu",
            0.6
        ));
    }

    // Category 18: Brace expressions
    #[test]
    fn test_python_fstring_braces() {
        assert!(value_is_obviously_not_secret("{list(CHECKPOINT_PARAMS.keys())}.", 0.6));
    }
    #[test]
    fn test_brace_template() {
        assert!(value_is_obviously_not_secret("{data.user.name}", 0.6));
    }

    // Category 19: Comma-separated lists (HTTP headers)
    #[test]
    fn test_http_header_list() {
        assert!(value_is_obviously_not_secret(
            "DNT,X-Mx-ReqToken,Keep-Alive,User-Agent,X-Requested-With",
            0.6
        ));
    }
    #[test]
    fn test_cors_headers() {
        assert!(value_is_obviously_not_secret(
            "Content-Type,Authorization,X-Amz-Date,X-Api-Key",
            0.6
        ));
    }

    // ---------------------------------------------------------------
    // Should NOT be suppressed (return false = could be a secret)
    // ---------------------------------------------------------------
    #[test]
    fn test_real_api_key() {
        assert!(!value_is_obviously_not_secret("sk-proj-abc123def456ghi789", 0.6));
    }
    #[test]
    fn test_real_github_pat() {
        assert!(!value_is_obviously_not_secret(
            "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ012345",
            0.6
        ));
    }
    #[test]
    fn test_real_password() {
        assert!(!value_is_obviously_not_secret("MyP@ssw0rd!2024", 0.6));
    }
    #[test]
    fn test_crypt_hash_kept() {
        assert!(!value_is_obviously_not_secret("$2b$12$abcdefghijklmnop", 0.6));
    }
    #[test]
    fn test_base64_token() {
        assert!(!value_is_obviously_not_secret("dGhpcyBpcyBhIHNlY3JldA==", 0.6));
    }
    #[test]
    fn test_jwt_segment() {
        assert!(!value_is_obviously_not_secret(
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
            0.6
        ));
    }
    #[test]
    fn test_aws_secret_key() {
        assert!(!value_is_obviously_not_secret(
            "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            0.6
        ));
    }
    #[test]
    fn test_random_hex_token() {
        assert!(!value_is_obviously_not_secret(
            "a3f9c2b1d4e8f7a0b3c5d2e1f9a8b7c6",
            0.6
        ));
    }
    #[test]
    fn test_long_mixed_not_single_word() {
        // >30 chars with digits — real API key, not a CamelCase identifier
        assert!(!value_is_obviously_not_secret(
            "pkLMZITIr9OWZ3wazmrh7nzuXMDj2RhbtK",
            0.6
        ));
    }
    #[test]
    fn test_crypt_2a_not_shell_var() {
        assert!(!value_is_obviously_not_secret("$2a$10$abcdefghijklmnop", 0.6));
    }
    #[test]
    fn test_crypt_5_not_shell_var() {
        assert!(!value_is_obviously_not_secret("$5$rounds=5000$saltsalt", 0.6));
    }
    #[test]
    fn test_crypt_6_not_shell_var() {
        assert!(!value_is_obviously_not_secret("$6$rounds=5000$saltsalt", 0.6));
    }
    #[test]
    fn test_argon2_not_shell_var() {
        assert!(!value_is_obviously_not_secret("$argon2id$v=19$m=65536", 0.6));
    }
    #[test]
    fn test_scrypt_not_shell_var() {
        assert!(!value_is_obviously_not_secret("$scrypt$ln=17,r=8,p=1$salt", 0.6));
    }
    #[test]
    fn test_jwt_long_segments_not_dot_notation() {
        // JWT has segments > 32 chars — should NOT be caught by dot-notation
        assert!(!value_is_obviously_not_secret(
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0.Sfl",
            0.6
        ));
    }
}
