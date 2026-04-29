//! Decode optionally-encoded placeholder/credential strings.
//!
//! Mirrors `data_classifier/patterns/_decoder.py`. Entries in pattern JSONs
//! that closely resemble real credentials carry an opt-in encoding prefix
//! so they survive shipping through GitHub push protection without being
//! flagged as live secrets. Two prefixes are supported:
//!
//!   `xor:<b64>` — XOR each byte with 0x5A, then base64
//!   `b64:<b64>` — plain base64
//!
//! Bare strings are returned unchanged. Decode failures fall back to the
//! original string so a malformed entry never crashes detector startup.

use base64::engine::general_purpose::STANDARD;
use base64::Engine;

const XOR_KEY: u8 = 0x5A;

/// Decode a single optionally-prefixed string. See module docs.
pub fn decode_encoded_string(value: &str) -> String {
    if let Some(rest) = value.strip_prefix("xor:") {
        if let Ok(bytes) = STANDARD.decode(rest) {
            let xored: Vec<u8> = bytes.iter().map(|b| b ^ XOR_KEY).collect();
            if let Ok(s) = String::from_utf8(xored) {
                return s;
            }
        }
    } else if let Some(rest) = value.strip_prefix("b64:") {
        if let Ok(bytes) = STANDARD.decode(rest) {
            if let Ok(s) = String::from_utf8(bytes) {
                return s;
            }
        }
    }
    value.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn passes_through_bare_strings() {
        assert_eq!(decode_encoded_string("changeme"), "changeme");
        assert_eq!(decode_encoded_string("your_api_key_here"), "your_api_key_here");
    }

    #[test]
    fn decodes_xor_prefix() {
        // Use neutral round-trip strings here — keeping Stripe/HF/etc. -shaped
        // expected values out of the test source so push protection doesn't
        // re-flag this file. The encoder is byte-symmetric; structural
        // confidence in the decoder is unrelated to what the plaintext looks
        // like, so a non-credential-shaped pair is sufficient.
        assert_eq!(decode_encoded_string("xor:Mj82NjV6LTUoNj4="), "hello world");
        assert_eq!(
            decode_encoded_string("xor:KjY7OT8yNTY+Pyh3KT85KD8udyw7Ni8/"),
            "placeholder-secret-value",
        );
    }

    #[test]
    fn decodes_b64_prefix() {
        // base64("hello") = "aGVsbG8="
        assert_eq!(decode_encoded_string("b64:aGVsbG8="), "hello");
    }

    #[test]
    fn falls_back_on_decode_error() {
        // Malformed base64 → return original string
        assert_eq!(decode_encoded_string("xor:!!not-base64!!"), "xor:!!not-base64!!");
    }
}
