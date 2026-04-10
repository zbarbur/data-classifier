# Entity Types

The library can detect **27 entity types** across 4 categories.

## PII

| Entity Type | Sensitivity | Regulatory | Source |
|---|---|---|---|
| `ADDRESS` | MEDIUM | PII, GDPR | profile |
| `AGE` | LOW | PII, COPPA | profile |
| `CANADIAN_SIN` | HIGH | PII, PIPEDA | profile |
| `DATE_OF_BIRTH` | HIGH | PII, HIPAA, GDPR, COPPA | profile |
| `DEMOGRAPHIC` | LOW | PII, EEOC | profile |
| `DEVICE_ID` | MEDIUM | -- | pattern |
| `EMAIL` | HIGH | PII, GDPR, CAN_SPAM | profile |
| `IP_ADDRESS` | MEDIUM | PII, GDPR | profile |
| `NATIONAL_ID` | HIGH | PII, GDPR | profile |
| `PERSON_NAME` | MEDIUM | PII, GDPR | profile |
| `PHONE` | HIGH | PII, GDPR, TCPA | profile |
| `SSN` | CRITICAL | PII, HIPAA, SOX, GDPR | profile |
| `URL` | LOW | -- | pattern |
| `VIN` | MEDIUM | PII | profile |

## Financial

| Entity Type | Sensitivity | Regulatory | Source |
|---|---|---|---|
| `ABA_ROUTING` | HIGH | PCI_DSS, PII | profile |
| `BANK_ACCOUNT` | HIGH | PCI_DSS, PII, GDPR | profile |
| `BITCOIN_ADDRESS` | HIGH | PII | profile |
| `CREDIT_CARD` | CRITICAL | PCI_DSS, PII | profile |
| `EIN` | MEDIUM | PII, SOX | profile |
| `ETHEREUM_ADDRESS` | HIGH | PII | profile |
| `FINANCIAL` | HIGH | PII, SOX, GDPR | profile |
| `SWIFT_BIC` | HIGH | PCI_DSS, PII | profile |

## Credential

| Entity Type | Sensitivity | Regulatory | Source |
|---|---|---|---|
| `CREDENTIAL` | CRITICAL | PCI_DSS, SOC2 | profile |

## Health

| Entity Type | Sensitivity | Regulatory | Source |
|---|---|---|---|
| `DEA_NUMBER` | HIGH | PII, HIPAA, DEA | profile |
| `HEALTH` | HIGH | PII, HIPAA, GDPR | profile |
| `MBI` | HIGH | PII, HIPAA, CMS | profile |
| `NPI` | HIGH | PII, HIPAA | profile |
