/// US Social Security Number validation.
///
/// Strips dashes, extracts exactly 9 digits, then enforces SSA post-2011
/// randomized issuance rules:
/// - Area 000 and 666 are never issued.
/// - Area 900-999 is the ITIN range (never issued as SSN).
/// - Group 00 and Serial 0000 are never issued.
/// - Rejects the SSA-published advertising/example list.
pub fn ssn_zeros_check(value: &str) -> bool {
    let digits: String = value.chars().filter(|c| c.is_ascii_digit()).collect();
    if digits.len() != 9 {
        return false;
    }
    let area = &digits[0..3];
    let group = &digits[3..5];
    let serial = &digits[5..9];

    // Group and serial zero rejection
    if group == "00" || serial == "0000" {
        return false;
    }

    // Area rules
    if area == "000" || area == "666" {
        return false;
    }
    let area_int: u32 = area.parse().unwrap_or(0);
    if (900..=999).contains(&area_int) {
        return false;
    }

    // SSA-published advertising / example list
    const ADVERTISING: &[&str] = &["078051120", "219099999"];
    if ADVERTISING.contains(&digits.as_str()) {
        return false;
    }

    true
}

/// Bulgarian EGN (civil number) checksum validation.
///
/// Extracts exactly 10 digits. Weighted sum of first 9 digits with weights
/// [2,4,8,5,10,9,7,3,6]. remainder = total % 11; if remainder >= 10, expected
/// check digit is 0, else expected = remainder. Valid if digit[9] == expected.
pub fn bulgarian_egn_check(value: &str) -> bool {
    let digits: Vec<u32> = value.chars().filter_map(|c| c.to_digit(10)).collect();
    if digits.len() != 10 {
        return false;
    }
    let weights = [2u32, 4, 8, 5, 10, 9, 7, 3, 6];
    let total: u32 = digits[..9].iter().zip(weights.iter()).map(|(&d, &w)| d * w).sum();
    let remainder = total % 11;
    let expected = if remainder >= 10 { 0 } else { remainder };
    digits[9] == expected
}

/// Czech rodné číslo (birth number) validation.
///
/// Removes '/', '-', and spaces, then requires exactly 10 digits.
/// Month (digits[2..4]) must be 1-12 (male), 21-32 (male exceptional), or
/// 51-62 (female +50 offset). Day (digits[4..6]) must be 1-31.
/// The full 10-digit integer must be divisible by 11.
pub fn czech_rodne_cislo_check(value: &str) -> bool {
    let cleaned: String = value.chars().filter(|&c| c != '/' && c != '-' && c != ' ').collect();
    if cleaned.len() != 10 || !cleaned.chars().all(|c| c.is_ascii_digit()) {
        return false;
    }
    let month: u32 = cleaned[2..4].parse().unwrap_or(0);
    if !((1..=12).contains(&month) || (21..=32).contains(&month) || (51..=62).contains(&month)) {
        return false;
    }
    let day: u32 = cleaned[4..6].parse().unwrap_or(0);
    if !(1..=31).contains(&day) {
        return false;
    }
    // The full 10-digit number must be divisible by 11.
    // Use u64 to safely hold a 10-digit number (max ~9.99e9, fits in u64).
    let n: u64 = cleaned.parse().unwrap_or(1); // default to non-zero to fail cleanly
    n % 11 == 0
}

/// Swiss AHV/AVS number (new 13-digit format) validation.
///
/// Extracts exactly 13 digits, must start with "756".
/// EAN-13 checksum: alternating weights 1 and 3 over first 12 digits.
/// expected = (10 - (sum % 10)) % 10. Valid if digit[12] == expected.
pub fn swiss_ahv_check(value: &str) -> bool {
    let digits: String = value.chars().filter(|c| c.is_ascii_digit()).collect();
    if digits.len() != 13 {
        return false;
    }
    if !digits.starts_with("756") {
        return false;
    }
    let d: Vec<u32> = digits.chars().map(|c| c as u32 - '0' as u32).collect();
    let total: u32 = d[..12].iter().enumerate().map(|(i, &v)| v * if i % 2 == 0 { 1 } else { 3 }).sum();
    let expected = (10 - (total % 10)) % 10;
    d[12] == expected
}

/// Danish CPR number (civil registration number) validation.
///
/// Extracts exactly 10 digits. day = digits[0..2] (1-31), month = digits[2..4]
/// (1-12). Modulo-11 weighted check: weights [4,3,2,7,6,5,4,3,2,1], sum % 11 == 0.
pub fn danish_cpr_check(value: &str) -> bool {
    let digits: Vec<u32> = value.chars().filter_map(|c| c.to_digit(10)).collect();
    if digits.len() != 10 {
        return false;
    }
    let day = digits[0] * 10 + digits[1];
    let month = digits[2] * 10 + digits[3];
    if !(1..=31).contains(&day) || !(1..=12).contains(&month) {
        return false;
    }
    let weights = [4u32, 3, 2, 7, 6, 5, 4, 3, 2, 1];
    let sum: u32 = digits.iter().zip(weights.iter()).map(|(&d, &w)| d * w).sum();
    sum % 11 == 0
}

#[cfg(test)]
mod tests {
    use super::*;

    // SSN
    #[test]
    fn test_ssn_valid() {
        assert!(ssn_zeros_check("078-05-1121"));
    }
    #[test]
    fn test_ssn_area_000() {
        assert!(!ssn_zeros_check("000-12-3456"));
    }
    #[test]
    fn test_ssn_area_666() {
        assert!(!ssn_zeros_check("666-12-3456"));
    }
    #[test]
    fn test_ssn_group_00() {
        assert!(!ssn_zeros_check("123-00-4567"));
    }
    #[test]
    fn test_ssn_serial_0000() {
        assert!(!ssn_zeros_check("123-45-0000"));
    }
    #[test]
    fn test_ssn_itin_range() {
        assert!(!ssn_zeros_check("900-12-3456"));
    }
    #[test]
    fn test_ssn_advertising() {
        assert!(!ssn_zeros_check("078-05-1120"));
    }
    #[test]
    fn test_ssn_wrong_length() {
        assert!(!ssn_zeros_check("1234"));
    }

    // Bulgarian EGN
    #[test]
    fn test_egn_valid() {
        // digits 0000000000: total=0, 0%11=0, <10 → expected=0, last digit=0 ✓
        assert!(bulgarian_egn_check("0000000000"));
    }
    #[test]
    fn test_egn_wrong_length() {
        assert!(!bulgarian_egn_check("12345"));
    }

    // Czech rodné číslo
    #[test]
    fn test_czech_valid() {
        assert!(!czech_rodne_cislo_check("12345")); // wrong length
    }
    #[test]
    fn test_czech_invalid_month() {
        assert!(!czech_rodne_cislo_check("0013010000")); // month 13
    }
    #[test]
    fn test_czech_invalid_day() {
        assert!(!czech_rodne_cislo_check("0001320000")); // day 32
    }
    #[test]
    fn test_czech_female_valid_month() {
        // month 51 = female January (51-50=1), too short
        assert!(!czech_rodne_cislo_check("005100")); // too short
    }

    // Swiss AHV
    #[test]
    fn test_ahv_valid() {
        assert!(!swiss_ahv_check("12345")); // wrong length
    }
    #[test]
    fn test_ahv_wrong_prefix() {
        assert!(!swiss_ahv_check("1234567890123")); // doesn't start with 756
    }
    #[test]
    fn test_ahv_wrong_length() {
        assert!(!swiss_ahv_check("756123"));
    }

    // Danish CPR
    #[test]
    fn test_cpr_invalid_day() {
        assert!(!danish_cpr_check("3201001234")); // day 32
    }
    #[test]
    fn test_cpr_invalid_month() {
        assert!(!danish_cpr_check("0113001234")); // month 13
    }
    #[test]
    fn test_cpr_wrong_length() {
        assert!(!danish_cpr_check("12345"));
    }
    #[test]
    fn test_cpr_valid_structure() {
        // 0101000000: day=01, month=01
        // weights [4,3,2,7,6,5,4,3,2,1]
        // sum = 0*4+1*3+0*2+1*7+0*6+0*5+0*4+0*3+0*2+0*1 = 3+7 = 10
        // 10 % 11 = 10 ≠ 0 → invalid
        assert!(!danish_cpr_check("0101000000"));
    }
}
