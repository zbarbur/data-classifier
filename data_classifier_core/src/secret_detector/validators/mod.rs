pub mod luhn;
// Future modules will be added here:
// pub mod checksum;
// pub mod crypto;
// pub mod identity;
// pub mod network;
// pub mod credential;
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
        assert_eq!(reg.len(), 4);
    }
}
