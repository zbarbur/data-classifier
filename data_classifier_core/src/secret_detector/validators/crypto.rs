use sha2::{Digest, Sha256};

/// Base58 alphabet (no 0, O, I, l).
const BASE58_ALPHABET: &[u8] = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";

/// Decode a Base58-encoded string to bytes.
/// Returns None if any character is not in the Base58 alphabet.
fn base58_decode(input: &str) -> Option<Vec<u8>> {
    // Build lookup table
    let mut table = [0xFFu8; 128];
    for (i, &ch) in BASE58_ALPHABET.iter().enumerate() {
        table[ch as usize] = i as u8;
    }

    // Count leading '1's (each maps to a zero byte)
    let leading_zeros = input.bytes().take_while(|&b| b == b'1').count();

    // Accumulate big integer as Vec<u8> (big-endian bytes)
    let mut result: Vec<u8> = vec![0];
    for byte in input.bytes() {
        if byte >= 128 {
            return None;
        }
        let idx = table[byte as usize];
        if idx == 0xFF {
            return None;
        }
        // Multiply result by 58 and add idx
        let mut carry = idx as u16;
        for b in result.iter_mut().rev() {
            let val = (*b as u16) * 58 + carry;
            *b = (val & 0xFF) as u8;
            carry = val >> 8;
        }
        while carry > 0 {
            result.insert(0, (carry & 0xFF) as u8);
            carry >>= 8;
        }
    }

    // Strip leading zero bytes from the big-integer result
    let start = result.iter().position(|&b| b != 0).unwrap_or(result.len());

    // Prepend the counted leading zeros, then append the big-integer bytes
    let mut output = vec![0u8; leading_zeros];
    output.extend_from_slice(&result[start..]);
    Some(output)
}

/// Verify a Base58Check-encoded value (used by P2PKH/P2SH Bitcoin addresses).
/// Decoded must be at least 5 bytes. Last 4 bytes are the checksum.
/// SHA256(SHA256(payload)) first 4 bytes must match the checksum.
fn base58check_verify(value: &str) -> bool {
    let decoded = match base58_decode(value) {
        Some(d) => d,
        None => return false,
    };
    if decoded.len() < 5 {
        return false;
    }
    let split = decoded.len() - 4;
    let payload = &decoded[..split];
    let checksum = &decoded[split..];

    let hash1 = Sha256::digest(payload);
    let hash2 = Sha256::digest(&hash1);

    hash2[..4] == *checksum
}

/// Bech32 charset for value decoding.
const BECH32_CHARSET: &str = "qpzry9x8gf2tvdw0s3jn54khce6mua7l";

/// Compute the bech32 polymod over a slice of u8 values.
fn bech32_polymod(values: &[u8]) -> u32 {
    let generators: [u32; 5] = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3];
    let mut checksum: u32 = 1;
    for &v in values {
        let b = checksum >> 25;
        checksum = ((checksum & 0x1ffffff) << 5) ^ (v as u32);
        for (i, &gen) in generators.iter().enumerate() {
            if (b >> i) & 1 != 0 {
                checksum ^= gen;
            }
        }
    }
    checksum
}

/// Expand the HRP for bech32 polymod computation.
/// Returns: [c >> 5 for c in hrp] ++ [0] ++ [c & 31 for c in hrp]
fn bech32_hrp_expand(hrp: &str) -> Vec<u8> {
    let mut result = Vec::with_capacity(hrp.len() * 2 + 1);
    for c in hrp.bytes() {
        result.push(c >> 5);
    }
    result.push(0);
    for c in hrp.bytes() {
        result.push(c & 31);
    }
    result
}

/// Verify a Bech32/Bech32m encoded address.
fn bech32_verify(value: &str) -> bool {
    // Reject mixed case
    let has_lower = value.chars().any(|c| c.is_ascii_lowercase());
    let has_upper = value.chars().any(|c| c.is_ascii_uppercase());
    if has_lower && has_upper {
        return false;
    }

    let lowered = value.to_ascii_lowercase();

    // Find last '1' separator
    let sep_pos = match lowered.rfind('1') {
        Some(pos) => pos,
        None => return false,
    };

    let hrp = &lowered[..sep_pos];
    let data_part = &lowered[sep_pos + 1..];

    // HRP must be "bc" for Bitcoin mainnet
    if hrp != "bc" {
        return false;
    }

    // Data part must have at least 6 chars (checksum)
    if data_part.len() < 6 {
        return false;
    }

    // Convert data chars to 5-bit values using bech32 charset
    let mut data_values: Vec<u8> = Vec::with_capacity(data_part.len());
    for ch in data_part.chars() {
        match BECH32_CHARSET.find(ch) {
            Some(idx) => data_values.push(idx as u8),
            None => return false,
        }
    }

    // Compute polymod over HRP expansion + data values
    let mut combined = bech32_hrp_expand(hrp);
    combined.extend_from_slice(&data_values);

    let polymod = bech32_polymod(&combined);

    // Valid if polymod == 1 (bech32) or polymod == 0x2bc830a3 (bech32m)
    polymod == 1 || polymod == 0x2bc830a3
}

/// Validate a Bitcoin address.
///
/// Supports:
/// - P2PKH (starts with '1') and P2SH (starts with '3'): Base58Check encoded
/// - Bech32/Bech32m (starts with 'bc1'): Bech32 encoded with polynomial checksum
pub fn bitcoin_address_check(value: &str) -> bool {
    if value.is_empty() {
        return false;
    }
    let first = value.as_bytes()[0];
    let lower = value.to_ascii_lowercase();
    if lower.starts_with("bc1") {
        bech32_verify(value)
    } else if first == b'1' || first == b'3' {
        base58check_verify(value)
    } else {
        false
    }
}

/// Validate an Ethereum address.
///
/// Must start with "0x", be exactly 42 chars, all hex after prefix.
/// Rejects known fake addresses (all zeros, all f's, deadbeef pattern).
pub fn ethereum_address_check(value: &str) -> bool {
    if !value.starts_with("0x") {
        return false;
    }
    if value.len() != 42 {
        return false;
    }
    let hex_part = &value[2..];
    if !hex_part.chars().all(|c| c.is_ascii_hexdigit()) {
        return false;
    }

    // Reject known fakes (case-insensitive)
    let lower = hex_part.to_ascii_lowercase();
    if lower == "0000000000000000000000000000000000000000" {
        return false;
    }
    if lower == "ffffffffffffffffffffffffffffffffffffffff" {
        return false;
    }
    if lower == "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef" {
        return false;
    }

    true
}

#[cfg(test)]
mod tests {
    use super::*;

    // Bitcoin P2PKH
    #[test]
    fn test_bitcoin_p2pkh_genesis() {
        assert!(bitcoin_address_check(
            "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
        ));
    }
    #[test]
    fn test_bitcoin_p2pkh_invalid_checksum() {
        assert!(!bitcoin_address_check(
            "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb"
        ));
    }

    // Bitcoin Bech32
    #[test]
    fn test_bitcoin_bech32_valid() {
        assert!(bitcoin_address_check(
            "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
        ));
    }
    #[test]
    fn test_bitcoin_bech32_wrong_hrp() {
        assert!(!bitcoin_address_check(
            "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx"
        )); // testnet
    }

    // Bitcoin invalid
    #[test]
    fn test_bitcoin_empty() {
        assert!(!bitcoin_address_check(""));
    }
    #[test]
    fn test_bitcoin_random() {
        assert!(!bitcoin_address_check("not-a-bitcoin-address"));
    }

    // Ethereum
    #[test]
    fn test_ethereum_valid() {
        assert!(ethereum_address_check(
            "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD28"
        ));
    }
    #[test]
    fn test_ethereum_all_zeros() {
        assert!(!ethereum_address_check(
            "0x0000000000000000000000000000000000000000"
        ));
    }
    #[test]
    fn test_ethereum_all_f() {
        assert!(!ethereum_address_check(
            "0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF"
        ));
    }
    #[test]
    fn test_ethereum_deadbeef() {
        assert!(!ethereum_address_check(
            "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
        ));
    }
    #[test]
    fn test_ethereum_wrong_length() {
        assert!(!ethereum_address_check("0x742d35Cc"));
    }
    #[test]
    fn test_ethereum_no_prefix() {
        assert!(!ethereum_address_check(
            "742d35Cc6634C0532925a3b844Bc9e7595f2bD28"
        ));
    }
}
