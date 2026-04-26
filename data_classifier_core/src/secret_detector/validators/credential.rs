/// AWS secret key validator.
///
/// AWS secret access keys are base64-encoded (mixed case + digits + /+=).
/// Pure-hex strings of matching length are git SHAs, checksums, etc. — not AWS keys.
/// Also rejects strings without both uppercase and lowercase letters.
pub fn aws_secret_not_hex(value: &str) -> bool {
    let clean = value.trim();
    // Pure hex (0-9, a-f, A-F) → not an AWS key (likely git SHA or checksum)
    if clean.chars().all(|c| c.is_ascii_hexdigit()) {
        return false;
    }
    let has_upper = clean.chars().any(|c| c.is_uppercase());
    let has_lower = clean.chars().any(|c| c.is_lowercase());
    has_upper && has_lower
}

/// OpenAI legacy key validator (sk-<48 chars>).
///
/// Real keys are base62 (a-z, A-Z, 0-9) with high entropy.
/// Rejects values that use fewer than 2 character classes from {upper, lower, digit}.
pub fn openai_legacy_key_check(value: &str) -> bool {
    let suffix = if value.starts_with("sk-") {
        &value[3..]
    } else {
        value
    };
    let has_upper = suffix.chars().any(|c| c.is_uppercase());
    let has_lower = suffix.chars().any(|c| c.is_lowercase());
    let has_digit = suffix.chars().any(|c| c.is_ascii_digit());
    let count = [has_upper, has_lower, has_digit].iter().filter(|&&b| b).count();
    count >= 2
}

/// HuggingFace token validator.
///
/// Real HuggingFace tokens are random alphanumeric (hf_ + ~34 chars).
/// Rejects camelCase identifiers (Objective-C/Swift method names) that happen
/// to be prefixed with hf_: those have camelCase transitions but no digits,
/// and are either long (>40 chars) or contain non-alphanumeric characters.
pub fn huggingface_token_check(value: &str) -> bool {
    let suffix = if value.starts_with("hf_") {
        &value[3..]
    } else {
        value
    };
    let has_camel = has_camel_transition(suffix);
    let has_digit = suffix.chars().any(|c| c.is_ascii_digit());
    // camelCase + no digits + (long OR non-purely-alphanumeric) → code identifier
    if has_camel && !has_digit && (suffix.len() > 40 || !suffix.chars().all(|c| c.is_alphanumeric())) {
        return false;
    }
    true
}

/// Check if a string contains a camelCase transition ([a-z][A-Z]).
fn has_camel_transition(s: &str) -> bool {
    let chars: Vec<char> = s.chars().collect();
    for i in 0..chars.len().saturating_sub(1) {
        if chars[i].is_lowercase() && chars[i + 1].is_uppercase() {
            return true;
        }
    }
    false
}

/// ISO 3166-1 alpha-2 country codes (full 251-entry set including SWIFT pseudo-codes).
///
/// Used for SWIFT/BIC country code validation (positions 5-6 of the BIC).
/// Includes XK (Kosovo) and EU (European Union institutions) as used by SWIFT.
static ISO_3166_ALPHA2: &[&str] = &[
    "AD", "AE", "AF", "AG", "AI", "AL", "AM", "AO", "AQ", "AR", "AS", "AT", "AU", "AW", "AX",
    "AZ", "BA", "BB", "BD", "BE", "BF", "BG", "BH", "BI", "BJ", "BL", "BM", "BN", "BO", "BQ",
    "BR", "BS", "BT", "BV", "BW", "BY", "BZ", "CA", "CC", "CD", "CF", "CG", "CH", "CI", "CK",
    "CL", "CM", "CN", "CO", "CR", "CU", "CV", "CW", "CX", "CY", "CZ", "DE", "DJ", "DK", "DM",
    "DO", "DZ", "EC", "EE", "EG", "EH", "ER", "ES", "ET", "FI", "FJ", "FK", "FM", "FO", "FR",
    "GA", "GB", "GD", "GE", "GF", "GG", "GH", "GI", "GL", "GM", "GN", "GP", "GQ", "GR", "GS",
    "GT", "GU", "GW", "GY", "HK", "HM", "HN", "HR", "HT", "HU", "ID", "IE", "IL", "IM", "IN",
    "IO", "IQ", "IR", "IS", "IT", "JE", "JM", "JO", "JP", "KE", "KG", "KH", "KI", "KM", "KN",
    "KP", "KR", "KW", "KY", "KZ", "LA", "LB", "LC", "LI", "LK", "LR", "LS", "LT", "LU", "LV",
    "LY", "MA", "MC", "MD", "ME", "MF", "MG", "MH", "MK", "ML", "MM", "MN", "MO", "MP", "MQ",
    "MR", "MS", "MT", "MU", "MV", "MW", "MX", "MY", "MZ", "NA", "NC", "NE", "NF", "NG", "NI",
    "NL", "NO", "NP", "NR", "NU", "NZ", "OM", "PA", "PE", "PF", "PG", "PH", "PK", "PL", "PM",
    "PN", "PR", "PS", "PT", "PW", "PY", "QA", "RE", "RO", "RS", "RU", "RW", "SA", "SB", "SC",
    "SD", "SE", "SG", "SH", "SI", "SJ", "SK", "SL", "SM", "SN", "SO", "SR", "SS", "ST", "SV",
    "SX", "SY", "SZ", "TC", "TD", "TF", "TG", "TH", "TJ", "TK", "TL", "TM", "TN", "TO", "TR",
    "TT", "TV", "TW", "TZ", "UA", "UG", "UM", "US", "UY", "UZ", "VA", "VC", "VE", "VG", "VI",
    "VN", "VU", "WF", "WS", "YE", "YT", "ZA", "ZM", "ZW",
    // SWIFT-specific pseudo-codes
    "XK", "EU",
];

/// SWIFT/BIC country code validator.
///
/// SWIFT/BIC format: BBBBCCLL[NNN] where CC (positions 5-6) is the ISO 3166-1 alpha-2 country code.
/// Two-layer validation:
///   1. Country code at positions 5-6 must be a valid ISO 3166-1 alpha-2.
///   2. All-alpha 8-char values are rejected — real BIC codes nearly always contain digits.
///      8-char all-alpha matches are overwhelmingly English words/surnames.
pub fn swift_bic_country_code_check(value: &str) -> bool {
    let clean = value.trim().to_uppercase();
    if clean.len() != 8 && clean.len() != 11 {
        return false;
    }
    let country = &clean[4..6];
    if !ISO_3166_ALPHA2.contains(&country) {
        return false;
    }
    // All-alpha 8-char matches are overwhelmingly false positives (surnames, words)
    if clean.chars().all(|c| c.is_alphabetic()) {
        return false;
    }
    true
}

/// Random password validator.
///
/// Accepts only mixed-class short random strings:
/// - Length must be in [4, 64]
/// - Must contain at least one symbol (non-alphanumeric, non-whitespace)
/// - Must use at least 3 of {lowercase, uppercase, digit, symbol}
pub fn random_password_check(value: &str) -> bool {
    let len = value.len();
    if !(4..=64).contains(&len) {
        return false;
    }
    let has_lower = value.chars().any(|c| c.is_lowercase());
    let has_upper = value.chars().any(|c| c.is_uppercase());
    let has_digit = value.chars().any(|c| c.is_ascii_digit());
    let has_symbol = value.chars().any(|c| !c.is_alphanumeric() && !c.is_whitespace());

    if !has_symbol {
        return false;
    }

    let classes = [has_lower, has_upper, has_digit, has_symbol]
        .iter()
        .filter(|&&b| b)
        .count();
    classes >= 3
}

#[cfg(test)]
mod tests {
    use super::*;

    // AWS
    #[test]
    fn test_aws_valid() {
        assert!(aws_secret_not_hex("wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"));
    }
    #[test]
    fn test_aws_pure_hex() {
        assert!(!aws_secret_not_hex("0123456789abcdef0123456789abcdef01234567"));
    }
    #[test]
    fn test_aws_no_upper() {
        assert!(!aws_secret_not_hex("abcdefghijklmnopqrst"));
    }

    // OpenAI
    #[test]
    fn test_openai_valid() {
        assert!(openai_legacy_key_check("sk-abcDEF123"));
    }
    #[test]
    fn test_openai_single_class() {
        assert!(!openai_legacy_key_check("sk-abcdef"));
    }

    // HuggingFace
    #[test]
    fn test_hf_valid() {
        assert!(huggingface_token_check("hf_abcdef123"));
    }
    #[test]
    fn test_hf_objc_method() {
        assert!(!huggingface_token_check(
            "hf_someVeryLongObjectiveCMethodNameThatIsClearlyNotAToken"
        ));
    }
    #[test]
    fn test_hf_short_alnum() {
        assert!(huggingface_token_check("hf_aBcDeFgH"));
    }

    // SWIFT BIC
    #[test]
    fn test_swift_valid_11() {
        assert!(swift_bic_country_code_check("DEUTDEFF500")); // 11 chars, DE=Germany
    }
    #[test]
    fn test_swift_all_alpha_8() {
        assert!(!swift_bic_country_code_check("ABCDUSXX")); // 8 chars, all alpha
    }
    #[test]
    fn test_swift_invalid_country() {
        assert!(!swift_bic_country_code_check("ABCDXX00")); // XX not ISO
    }
    #[test]
    fn test_swift_wrong_length() {
        assert!(!swift_bic_country_code_check("ABCD")); // wrong length
    }

    // Random password
    #[test]
    fn test_password_valid() {
        assert!(random_password_check("P@ssw0rd"));
    }
    #[test]
    fn test_password_no_symbol() {
        assert!(!random_password_check("Password1"));
    }
    #[test]
    fn test_password_too_short() {
        assert!(!random_password_check("P@1"));
    }
    #[test]
    fn test_password_too_long() {
        assert!(!random_password_check(&"a".repeat(65)));
    }
}
