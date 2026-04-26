pub mod luhn;
pub mod checksum;
pub mod crypto;
pub mod identity;
pub mod credential;
// Future modules will be added here:
// pub mod network;
// pub mod placeholder;

use std::collections::HashMap;

pub type ValidatorFn = fn(&str) -> bool;

/// Build a map of validator name → function.
pub fn build_validator_registry() -> HashMap<&'static str, ValidatorFn> {
    let mut m: HashMap<&'static str, ValidatorFn> = HashMap::new();
    m.insert("luhn", luhn::luhn_check);
    m.insert("luhn_strip", luhn::luhn_strip_check);
    m.insert("npi_luhn", luhn::npi_luhn_check);
    m.insert("sin_luhn", luhn::sin_luhn_check);
    m.insert("aba_checksum", checksum::aba_checksum_check);
    m.insert("iban_checksum", checksum::iban_checksum_check);
    m.insert("dea_checkdigit", checksum::dea_checkdigit_check);
    m.insert("vin_checkdigit", checksum::vin_checkdigit_check);
    m.insert("ein_prefix", checksum::ein_prefix_check);
    m.insert("bitcoin_address", crypto::bitcoin_address_check);
    m.insert("ethereum_address", crypto::ethereum_address_check);
    m.insert("ssn_zeros", identity::ssn_zeros_check);
    m.insert("bulgarian_egn", identity::bulgarian_egn_check);
    m.insert("czech_rodne_cislo", identity::czech_rodne_cislo_check);
    m.insert("swiss_ahv", identity::swiss_ahv_check);
    m.insert("danish_cpr", identity::danish_cpr_check);
    m.insert("aws_secret_not_hex", credential::aws_secret_not_hex);
    m.insert("openai_legacy_key", credential::openai_legacy_key_check);
    m.insert("huggingface_token", credential::huggingface_token_check);
    m.insert("swift_bic_country_code", credential::swift_bic_country_code_check);
    m.insert("random_password", credential::random_password_check);
    m
}

/// Resolve a validator by name. Returns None if name is empty.
pub fn resolve_validator(name: &str, registry: &HashMap<&str, ValidatorFn>) -> Option<ValidatorFn> {
    if name.is_empty() {
        return None;
    }
    registry.get(name).copied()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_registry_has_luhn() {
        let reg = build_validator_registry();
        assert!(reg.contains_key("luhn"));
        assert!(reg.contains_key("luhn_strip"));
        assert!(reg.contains_key("npi_luhn"));
        assert!(reg.contains_key("sin_luhn"));
        assert_eq!(reg.len(), 21);
    }
}
