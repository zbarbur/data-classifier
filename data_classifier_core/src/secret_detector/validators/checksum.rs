/// ABA routing number checksum validation.
///
/// Extracts all digit characters (must be exactly 9), then applies the weighted
/// checksum: weights [3,7,1,3,7,1,3,7,1]. Valid if sum % 10 == 0.
pub fn aba_checksum_check(value: &str) -> bool {
    let digits: Vec<u32> = value.chars().filter_map(|c| c.to_digit(10)).collect();
    if digits.len() != 9 {
        return false;
    }
    let weights = [3u32, 7, 1, 3, 7, 1, 3, 7, 1];
    let sum: u32 = digits.iter().zip(weights.iter()).map(|(&d, &w)| d * w).sum();
    sum % 10 == 0
}

/// IBAN checksum validation (ISO 13616).
///
/// Cleans the value (remove spaces/dashes, uppercase), rearranges (first 4 chars
/// to end), converts letters to digits (A=10..Z=35), then verifies modulo-97 == 1.
pub fn iban_checksum_check(value: &str) -> bool {
    let clean: String = value
        .chars()
        .filter(|&c| c != ' ' && c != '-')
        .map(|c| c.to_ascii_uppercase())
        .collect();
    if clean.len() < 5 {
        return false;
    }
    // Rearrange: move first 4 chars to end
    let rearranged = format!("{}{}", &clean[4..], &clean[..4]);
    // Convert to numeric string and compute mod 97 incrementally
    let mut remainder: u64 = 0;
    for ch in rearranged.chars() {
        if let Some(d) = ch.to_digit(10) {
            remainder = (remainder * 10 + d as u64) % 97;
        } else if ch.is_ascii_alphabetic() {
            let val = (ch as u64) - ('A' as u64) + 10; // A=10..Z=35
            // val is always 10..35, so two digits; process tens then units
            remainder = (remainder * 10 + val / 10) % 97;
            remainder = (remainder * 10 + val % 10) % 97;
        } else {
            return false;
        }
    }
    remainder == 1
}

/// DEA number check-digit validation.
///
/// Must be exactly 9 chars. Positions 2..8 (0-indexed) must be digits.
/// checksum = (d0+d2+d4) + 2*(d1+d3+d5). Valid if checksum % 10 == d6.
pub fn dea_checkdigit_check(value: &str) -> bool {
    if value.len() != 9 {
        return false;
    }
    let chars: Vec<char> = value.chars().collect();
    // Positions 2..8 (indices 2,3,4,5,6,7,8) must be digits — 7 total
    let digits: Vec<u32> = match chars[2..9].iter().map(|c| c.to_digit(10)).collect::<Option<Vec<_>>>() {
        Some(d) => d,
        None => return false,
    };
    let checksum = (digits[0] + digits[2] + digits[4]) + 2 * (digits[1] + digits[3] + digits[5]);
    checksum % 10 == digits[6]
}

/// VIN (Vehicle Identification Number) check-digit validation.
///
/// Uppercases value, requires exactly 17 chars. Transliterates letters to values,
/// applies position weights, remainder = total % 11. Check digit at position 8:
/// remainder 10 → 'X', else the digit character.
pub fn vin_checkdigit_check(value: &str) -> bool {
    let value = value.to_ascii_uppercase();
    if value.len() != 17 {
        return false;
    }
    let transliterate = |c: char| -> Option<u32> {
        match c {
            '0'..='9' => Some(c as u32 - '0' as u32),
            'A' => Some(1), 'B' => Some(2), 'C' => Some(3), 'D' => Some(4),
            'E' => Some(5), 'F' => Some(6), 'G' => Some(7), 'H' => Some(8),
            'J' => Some(1), 'K' => Some(2), 'L' => Some(3), 'M' => Some(4),
            'N' => Some(5), 'P' => Some(7), 'R' => Some(9),
            'S' => Some(2), 'T' => Some(3), 'U' => Some(4), 'V' => Some(5),
            'W' => Some(6), 'X' => Some(7), 'Y' => Some(8), 'Z' => Some(9),
            _ => None, // I, O, Q and any other char are invalid
        }
    };
    let weights = [8u32, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2];
    let chars: Vec<char> = value.chars().collect();
    let mut total: u32 = 0;
    for (i, &ch) in chars.iter().enumerate() {
        match transliterate(ch) {
            Some(v) => total += v * weights[i],
            None => return false,
        }
    }
    let remainder = total % 11;
    let expected = if remainder == 10 { 'X' } else { char::from_digit(remainder, 10).unwrap() };
    chars[8] == expected
}

/// EIN (Employer Identification Number) campus-prefix validation.
///
/// Strips dashes, extracts digits (must be exactly 9), checks that the first
/// two digits form a valid IRS campus prefix.
pub fn ein_prefix_check(value: &str) -> bool {
    let digits: String = value.chars().filter(|c| c.is_ascii_digit()).collect();
    if digits.len() != 9 {
        return false;
    }
    let prefix: u32 = digits[..2].parse().unwrap_or(0);
    matches!(
        prefix,
        10..=16 | 20..=27 | 30..=39 | 40..=48 | 50..=59 | 60..=68 | 71..=77 | 80..=88 | 90..=99
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    // ABA
    #[test]
    fn test_aba_valid() {
        assert!(aba_checksum_check("011000015")); // Federal Reserve Bank of Boston
    }
    #[test]
    fn test_aba_invalid() {
        assert!(!aba_checksum_check("011000016"));
    }
    #[test]
    fn test_aba_wrong_length() {
        assert!(!aba_checksum_check("12345"));
    }

    // IBAN
    #[test]
    fn test_iban_valid_gb() {
        assert!(iban_checksum_check("GB29NWBK60161331926819"));
    }
    #[test]
    fn test_iban_valid_de() {
        assert!(iban_checksum_check("DE89370400440532013000"));
    }
    #[test]
    fn test_iban_invalid() {
        assert!(!iban_checksum_check("GB29NWBK60161331926810"));
    }
    #[test]
    fn test_iban_with_spaces() {
        assert!(iban_checksum_check("GB29 NWBK 6016 1331 9268 19"));
    }

    // DEA
    #[test]
    fn test_dea_valid() {
        // DEA format: 2 letters + 6 digits + check digit
        // For AB1234563: (1+3+5) + 2*(2+4+6) = 9 + 24 = 33, 33%10=3 = last digit
        assert!(dea_checkdigit_check("AB1234563"));
    }
    #[test]
    fn test_dea_invalid() {
        assert!(!dea_checkdigit_check("AB1234560"));
    }
    #[test]
    fn test_dea_wrong_length() {
        assert!(!dea_checkdigit_check("AB123"));
    }

    // VIN
    #[test]
    fn test_vin_all_ones() {
        // 11111111111111111: all 1s, weight sum=8+7+6+5+4+3+2+10+0+9+8+7+6+5+4+3+2=89
        // 89%11=1, position 8 is '1'
        assert!(vin_checkdigit_check("11111111111111111"));
    }
    #[test]
    fn test_vin_wrong_length() {
        assert!(!vin_checkdigit_check("1234567890"));
    }
    #[test]
    fn test_vin_invalid_char() {
        assert!(!vin_checkdigit_check("IIIIIIIIIIIIIIIII")); // I is invalid in VIN
    }

    // EIN
    #[test]
    fn test_ein_valid() {
        assert!(ein_prefix_check("12-3456789")); // prefix 12 is valid
    }
    #[test]
    fn test_ein_invalid_prefix() {
        assert!(!ein_prefix_check("00-1234567")); // 00 not valid
    }
    #[test]
    fn test_ein_wrong_length() {
        assert!(!ein_prefix_check("123"));
    }
}
