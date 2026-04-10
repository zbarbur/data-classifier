# Profiles

## standard

Standard classification profile. Covers 15 entity types across 4 categories and 4 sensitivity levels.


This profile contains **25 rules**.

| Entity Type | Category | Sensitivity | Confidence | Regulatory | Patterns |
|---|---|---|---|---|---|
| `CREDENTIAL` | Credential | CRITICAL | 0.95 | PCI_DSS, SOC2 | 1 pattern |
| `ABA_ROUTING` | Financial | HIGH | 0.90 | PCI_DSS, PII | 1 pattern |
| `BANK_ACCOUNT` | Financial | HIGH | 0.90 | PCI_DSS, PII, GDPR | 1 pattern |
| `BITCOIN_ADDRESS` | Financial | HIGH | 0.85 | PII | 1 pattern |
| `CREDIT_CARD` | Financial | CRITICAL | 0.95 | PCI_DSS, PII | 1 pattern |
| `EIN` | Financial | MEDIUM | 0.85 | PII, SOX | 1 pattern |
| `ETHEREUM_ADDRESS` | Financial | HIGH | 0.85 | PII | 1 pattern |
| `FINANCIAL` | Financial | HIGH | 0.85 | PII, SOX, GDPR | 1 pattern |
| `SWIFT_BIC` | Financial | HIGH | 0.90 | PCI_DSS, PII | 1 pattern |
| `DEA_NUMBER` | Health | HIGH | 0.90 | PII, HIPAA, DEA | 1 pattern |
| `HEALTH` | Health | HIGH | 0.90 | PII, HIPAA, GDPR | 1 pattern |
| `MBI` | Health | HIGH | 0.90 | PII, HIPAA, CMS | 1 pattern |
| `NPI` | Health | HIGH | 0.90 | PII, HIPAA | 1 pattern |
| `ADDRESS` | PII | MEDIUM | 0.80 | PII, GDPR | 1 pattern |
| `AGE` | PII | LOW | 0.75 | PII, COPPA | 1 pattern |
| `CANADIAN_SIN` | PII | HIGH | 0.90 | PII, PIPEDA | 1 pattern |
| `DATE_OF_BIRTH` | PII | HIGH | 0.90 | PII, HIPAA, GDPR, COPPA | 1 pattern |
| `DEMOGRAPHIC` | PII | LOW | 0.70 | PII, EEOC | 1 pattern |
| `EMAIL` | PII | HIGH | 0.90 | PII, GDPR, CAN_SPAM | 1 pattern |
| `IP_ADDRESS` | PII | MEDIUM | 0.85 | PII, GDPR | 1 pattern |
| `NATIONAL_ID` | PII | HIGH | 0.90 | PII, GDPR | 1 pattern |
| `PERSON_NAME` | PII | MEDIUM | 0.75 | PII, GDPR | 1 pattern |
| `PHONE` | PII | HIGH | 0.90 | PII, GDPR, TCPA | 1 pattern |
| `SSN` | PII | CRITICAL | 0.95 | PII, HIPAA, SOX, GDPR | 1 pattern |
| `VIN` | PII | MEDIUM | 0.85 | PII | 1 pattern |
