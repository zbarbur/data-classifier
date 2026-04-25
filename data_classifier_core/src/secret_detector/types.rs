use serde::{Deserialize, Serialize};

/// Supported entity types for secret/credential detection.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum EntityType {
    ApiKey,
    OpaqueSecret,
    PrivateKey,
    PasswordHash,
    Ssn,
    CreditCard,
    Email,
    Phone,
    IpAddress,
    MacAddress,
    Iban,
    SwiftBic,
    AbaRouting,
    BitcoinAddress,
    EthereumAddress,
    Url,
    CanadianSin,
    NationalId,
    Health,
    DeaNumber,
    Ein,
    Mbi,
    Npi,
    Vin,
    Date,
}

impl EntityType {
    /// Parse a canonical string label into an EntityType.
    pub fn from_str(s: &str) -> Self {
        match s {
            "API_KEY" => EntityType::ApiKey,
            "OPAQUE_SECRET" => EntityType::OpaqueSecret,
            "PRIVATE_KEY" => EntityType::PrivateKey,
            "PASSWORD_HASH" => EntityType::PasswordHash,
            "SSN" => EntityType::Ssn,
            "CREDIT_CARD" => EntityType::CreditCard,
            "EMAIL" => EntityType::Email,
            "PHONE" => EntityType::Phone,
            "IP_ADDRESS" => EntityType::IpAddress,
            "MAC_ADDRESS" => EntityType::MacAddress,
            "IBAN" => EntityType::Iban,
            "SWIFT_BIC" => EntityType::SwiftBic,
            "ABA_ROUTING" => EntityType::AbaRouting,
            "BITCOIN_ADDRESS" => EntityType::BitcoinAddress,
            "ETHEREUM_ADDRESS" => EntityType::EthereumAddress,
            "URL" => EntityType::Url,
            "CANADIAN_SIN" => EntityType::CanadianSin,
            "NATIONAL_ID" => EntityType::NationalId,
            "HEALTH" => EntityType::Health,
            "DEA_NUMBER" => EntityType::DeaNumber,
            "EIN" => EntityType::Ein,
            "MBI" => EntityType::Mbi,
            "NPI" => EntityType::Npi,
            "VIN" => EntityType::Vin,
            "DATE" => EntityType::Date,
            _ => EntityType::OpaqueSecret,
        }
    }

    /// Return the canonical string label for this entity type.
    pub fn as_str(&self) -> &'static str {
        match self {
            EntityType::ApiKey => "API_KEY",
            EntityType::OpaqueSecret => "OPAQUE_SECRET",
            EntityType::PrivateKey => "PRIVATE_KEY",
            EntityType::PasswordHash => "PASSWORD_HASH",
            EntityType::Ssn => "SSN",
            EntityType::CreditCard => "CREDIT_CARD",
            EntityType::Email => "EMAIL",
            EntityType::Phone => "PHONE",
            EntityType::IpAddress => "IP_ADDRESS",
            EntityType::MacAddress => "MAC_ADDRESS",
            EntityType::Iban => "IBAN",
            EntityType::SwiftBic => "SWIFT_BIC",
            EntityType::AbaRouting => "ABA_ROUTING",
            EntityType::BitcoinAddress => "BITCOIN_ADDRESS",
            EntityType::EthereumAddress => "ETHEREUM_ADDRESS",
            EntityType::Url => "URL",
            EntityType::CanadianSin => "CANADIAN_SIN",
            EntityType::NationalId => "NATIONAL_ID",
            EntityType::Health => "HEALTH",
            EntityType::DeaNumber => "DEA_NUMBER",
            EntityType::Ein => "EIN",
            EntityType::Mbi => "MBI",
            EntityType::Npi => "NPI",
            EntityType::Vin => "VIN",
            EntityType::Date => "DATE",
        }
    }
}

/// A matched span within the input text.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Match {
    pub value_masked: String,
    pub start: usize,
    pub end: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub value_raw: Option<String>,
}

/// Key-value context for findings extracted from key=value pairs.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KVContext {
    pub key: String,
    pub tier: String,
}

/// A single detection finding.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Finding {
    pub entity_type: String,
    pub category: String,
    pub sensitivity: String,
    pub confidence: f64,
    pub engine: String,
    pub evidence: String,
    #[serde(rename = "match")]
    pub match_span: Match,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub detection_type: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub display_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub kv: Option<KVContext>,
}

/// Result of running detection on a text input.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DetectionResult {
    pub findings: Vec<Finding>,
    pub redacted_text: String,
    pub scanned_ms: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub zones: Option<serde_json::Value>,
}

/// Mask a raw value for safe display.
///
/// Values of 4 characters or fewer are fully masked with asterisks.
/// Longer values keep the first and last character with asterisks in between.
pub fn mask_value(value: &str, _entity_type: &str) -> String {
    let len = value.len();
    if len <= 4 {
        "*".repeat(len)
    } else {
        let first = &value[..1];
        let last = &value[len - 1..];
        format!("{}{}{}", first, "*".repeat(len - 2), last)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_mask_value_short() {
        assert_eq!(mask_value("abc", "API_KEY"), "***");
        assert_eq!(mask_value("abcd", "API_KEY"), "****");
    }

    #[test]
    fn test_mask_value_long() {
        assert_eq!(mask_value("sk-12345678", "API_KEY"), "s*********8");
        assert_eq!(mask_value("hello", "EMAIL"), "h***o");
    }

    #[test]
    fn test_mask_value_empty() {
        assert_eq!(mask_value("", "API_KEY"), "");
    }

    #[test]
    fn test_entity_type_roundtrip() {
        let cases = vec![
            "API_KEY",
            "OPAQUE_SECRET",
            "PRIVATE_KEY",
            "PASSWORD_HASH",
            "SSN",
            "CREDIT_CARD",
            "EMAIL",
            "PHONE",
            "IP_ADDRESS",
            "MAC_ADDRESS",
            "IBAN",
            "SWIFT_BIC",
            "ABA_ROUTING",
            "BITCOIN_ADDRESS",
            "ETHEREUM_ADDRESS",
            "URL",
            "CANADIAN_SIN",
            "NATIONAL_ID",
            "HEALTH",
            "DEA_NUMBER",
            "EIN",
            "MBI",
            "NPI",
            "VIN",
            "DATE",
        ];
        for label in cases {
            let et = EntityType::from_str(label);
            assert_eq!(et.as_str(), label, "roundtrip failed for {}", label);
        }
    }

    #[test]
    fn test_entity_type_unknown_falls_back() {
        let et = EntityType::from_str("UNKNOWN_TYPE");
        assert_eq!(et, EntityType::OpaqueSecret);
    }

    #[test]
    fn test_finding_serialization_skips_none() {
        let finding = Finding {
            entity_type: "API_KEY".to_string(),
            category: "credential".to_string(),
            sensitivity: "high".to_string(),
            confidence: 0.95,
            engine: "secret_scanner".to_string(),
            evidence: "prefix match".to_string(),
            match_span: Match {
                value_masked: "s*********8".to_string(),
                start: 0,
                end: 11,
                value_raw: None,
            },
            detection_type: None,
            display_name: None,
            kv: None,
        };
        let json = serde_json::to_string(&finding).unwrap();
        assert!(!json.contains("detection_type"));
        assert!(!json.contains("display_name"));
        assert!(!json.contains("\"kv\""));
        assert!(json.contains("\"match\""));
    }
}
