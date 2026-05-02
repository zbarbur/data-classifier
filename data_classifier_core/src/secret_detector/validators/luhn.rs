/// Standard Luhn algorithm (credit card validation).
///
/// Extracts all digit characters, then validates using the Luhn checksum.
/// Returns false if there are no digits.
pub fn luhn_check(value: &str) -> bool {
    let digits: Vec<u32> = value.chars().filter_map(|c| c.to_digit(10)).collect();
    if digits.is_empty() {
        return false;
    }
    let sum: u32 = digits
        .iter()
        .rev()
        .enumerate()
        .map(|(i, &d)| {
            if i % 2 == 1 {
                let doubled = d * 2;
                if doubled > 9 { doubled - 9 } else { doubled }
            } else {
                d
            }
        })
        .sum();
    sum % 10 == 0
}

/// Strip dashes and spaces, then run luhn_check.
pub fn luhn_strip_check(value: &str) -> bool {
    let stripped: String = value.chars().filter(|&c| c != '-' && c != ' ').collect();
    luhn_check(&stripped)
}

/// NPI (National Provider Identifier) Luhn check.
///
/// Extracts digits, requires exactly 10, prepends "80840", then runs luhn_check
/// on the resulting 15-digit string.
pub fn npi_luhn_check(value: &str) -> bool {
    let digits: String = value.chars().filter(|c| c.is_ascii_digit()).collect();
    if digits.len() != 10 {
        return false;
    }
    let prefixed = format!("80840{}", digits);
    luhn_check(&prefixed)
}

/// Canadian Social Insurance Number (SIN) Luhn check.
///
/// Extracts digits, requires exactly 9, then runs standard luhn_check.
pub fn sin_luhn_check(value: &str) -> bool {
    let digits: String = value.chars().filter(|c| c.is_ascii_digit()).collect();
    if digits.len() != 9 {
        return false;
    }
    luhn_check(&digits)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_luhn_valid_visa() {
        assert!(luhn_check("4111111111111111"));
    }

    #[test]
    fn test_luhn_invalid() {
        assert!(!luhn_check("4111111111111112"));
    }

    #[test]
    fn test_luhn_empty() {
        assert!(!luhn_check(""));
    }

    #[test]
    fn test_luhn_non_digits() {
        assert!(!luhn_check("abcdef"));
    }

    #[test]
    fn test_luhn_strip_dashes() {
        assert!(luhn_strip_check("4111-1111-1111-1111"));
    }

    #[test]
    fn test_luhn_strip_spaces() {
        assert!(luhn_strip_check("4111 1111 1111 1111"));
    }

    #[test]
    fn test_npi_valid() {
        assert!(npi_luhn_check("1234567893"));
    }

    #[test]
    fn test_npi_wrong_length() {
        assert!(!npi_luhn_check("12345"));
    }

    #[test]
    fn test_sin_valid() {
        assert!(sin_luhn_check("046454286"));
    }

    #[test]
    fn test_sin_wrong_length() {
        assert!(!sin_luhn_check("1234"));
    }
}
