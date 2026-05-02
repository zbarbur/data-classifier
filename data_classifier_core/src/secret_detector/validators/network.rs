/// IPv4 address validator — rejects loopback, unspecified, multicast, reserved, and link-local.
///
/// Private ranges (10.x.x.x, 172.16-31.x.x, 192.168.x.x) are kept as valid IPs.
///
/// Port of Python validators.py:86-120.
pub fn ipv4_not_reserved_check(value: &str) -> bool {
    let parts: Vec<&str> = value.trim().split('.').collect();
    if parts.len() != 4 {
        return false;
    }
    let octets: Vec<u8> = match parts.iter().map(|p| p.parse::<u8>()).collect::<Result<Vec<_>, _>>() {
        Ok(v) => v,
        Err(_) => return false,
    };
    let (a, b, _c, _d) = (octets[0], octets[1], octets[2], octets[3]);

    // 0.0.0.0 — unspecified
    if a == 0 && octets[1] == 0 && octets[2] == 0 && octets[3] == 0 {
        return false;
    }
    // 127.x.x.x — loopback
    if a == 127 {
        return false;
    }
    // 169.254.x.x — link-local
    if a == 169 && b == 254 {
        return false;
    }
    // 224-239.x.x.x — multicast
    if (224..=239).contains(&a) {
        return false;
    }
    // 240-255.x.x.x — reserved / future / broadcast
    if a >= 240 {
        return false;
    }
    true
}

/// Phone number structural validator.
///
/// Simplified port of Python's phonenumbers-based check:
/// - Strips common extension markers (x, ext, #)
/// - Extracts digits only
/// - Requires 7–15 digits (ITU-T E.164 range)
/// - Rejects all-same-digit strings ("1111111111")
/// - Rejects sequential ascending runs ("1234567890")
pub fn phone_number_check(value: &str) -> bool {
    // Strip extension: drop everything at/after 'x', "ext", or '#'
    let lower = value.to_lowercase();
    let stripped = if let Some(pos) = lower.find("ext") {
        &value[..pos]
    } else if let Some(pos) = lower.find('x') {
        &value[..pos]
    } else if let Some(pos) = lower.find('#') {
        &value[..pos]
    } else {
        value
    };

    let digits: Vec<u8> = stripped
        .chars()
        .filter(|c| c.is_ascii_digit())
        .map(|c| c as u8 - b'0')
        .collect();

    let len = digits.len();

    // Must be 7–15 digits (E.164)
    if !(7..=15).contains(&len) {
        return false;
    }

    // Reject all-same digits
    if digits.iter().all(|&d| d == digits[0]) {
        return false;
    }

    // Reject sequential ascending: every digit equals (previous + 1) % 10
    // This catches both "1234567" and "1234567890" (wraps 9→0).
    let is_sequential = digits.windows(2).all(|w| w[1] == (w[0] + 1) % 10);
    if is_sequential {
        return false;
    }

    true
}

#[cfg(test)]
mod tests {
    use super::*;

    // --- ipv4_not_reserved_check ---

    #[test]
    fn test_ipv4_public() {
        assert!(ipv4_not_reserved_check("8.8.8.8"));
    }

    #[test]
    fn test_ipv4_private_10() {
        assert!(ipv4_not_reserved_check("10.0.0.1"));
    }

    #[test]
    fn test_ipv4_private_172() {
        assert!(ipv4_not_reserved_check("172.16.0.1"));
    }

    #[test]
    fn test_ipv4_private_192() {
        assert!(ipv4_not_reserved_check("192.168.1.1"));
    }

    #[test]
    fn test_ipv4_loopback() {
        assert!(!ipv4_not_reserved_check("127.0.0.1"));
    }

    #[test]
    fn test_ipv4_loopback_other() {
        assert!(!ipv4_not_reserved_check("127.255.255.254"));
    }

    #[test]
    fn test_ipv4_unspecified() {
        assert!(!ipv4_not_reserved_check("0.0.0.0"));
    }

    #[test]
    fn test_ipv4_multicast() {
        assert!(!ipv4_not_reserved_check("224.0.0.1"));
    }

    #[test]
    fn test_ipv4_multicast_high() {
        assert!(!ipv4_not_reserved_check("239.255.255.250"));
    }

    #[test]
    fn test_ipv4_link_local() {
        assert!(!ipv4_not_reserved_check("169.254.1.1"));
    }

    #[test]
    fn test_ipv4_link_local_boundary() {
        assert!(!ipv4_not_reserved_check("169.254.0.0"));
    }

    #[test]
    fn test_ipv4_reserved() {
        assert!(!ipv4_not_reserved_check("240.0.0.1"));
    }

    #[test]
    fn test_ipv4_broadcast() {
        assert!(!ipv4_not_reserved_check("255.255.255.255"));
    }

    #[test]
    fn test_ipv4_invalid_text() {
        assert!(!ipv4_not_reserved_check("not.an.ip"));
    }

    #[test]
    fn test_ipv4_invalid_octet() {
        assert!(!ipv4_not_reserved_check("256.0.0.1"));
    }

    #[test]
    fn test_ipv4_too_few_parts() {
        assert!(!ipv4_not_reserved_check("192.168.1"));
    }

    #[test]
    fn test_ipv4_too_many_parts() {
        assert!(!ipv4_not_reserved_check("1.2.3.4.5"));
    }

    // --- phone_number_check ---

    #[test]
    fn test_phone_valid() {
        assert!(phone_number_check("2125551234"));
    }

    #[test]
    fn test_phone_valid_with_formatting() {
        assert!(phone_number_check("+1 (212) 555-1234"));
    }

    #[test]
    fn test_phone_valid_international() {
        assert!(phone_number_check("+447700900123"));
    }

    #[test]
    fn test_phone_too_short() {
        assert!(!phone_number_check("12345"));
    }

    #[test]
    fn test_phone_too_long() {
        assert!(!phone_number_check("12345678901234567"));
    }

    #[test]
    fn test_phone_all_same() {
        assert!(!phone_number_check("1111111111"));
    }

    #[test]
    fn test_phone_all_same_zeros() {
        assert!(!phone_number_check("0000000"));
    }

    #[test]
    fn test_phone_sequential() {
        assert!(!phone_number_check("1234567890"));
    }

    #[test]
    fn test_phone_with_ext() {
        // "2125551234 ext 789" → digits before "ext" = 10 → valid
        assert!(phone_number_check("2125551234 ext 789"));
    }

    #[test]
    fn test_phone_with_x_extension() {
        // "2125551234x789" → strips at 'x' → 2125551234 (10 digits) → valid
        assert!(phone_number_check("2125551234x789"));
    }
}
