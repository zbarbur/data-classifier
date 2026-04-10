# Patterns

The library ships with **59 content patterns** for detecting sensitive data in sample values.

Each pattern uses RE2-compatible regex (linear-time, no backtracking).

## PII

| Pattern | Entity Type | Sensitivity | Confidence | Validator | Description |
|---|---|---|---|---|---|
| `canadian_sin` | CANADIAN_SIN | HIGH | 0.85 | luhn_strip | Canadian Social Insurance Number |
| `date_iso_format` | DATE_OF_BIRTH | HIGH | 0.50 | -- | Date in YYYY-MM-DD or YYYY/MM/DD format (ISO-like) |
| `date_of_birth_format` | DATE_OF_BIRTH | HIGH | 0.60 | -- | Date in MM/DD/YYYY or MM-DD-YYYY format (could be any date, not necessarily DOB) |
| `dob_european` | DATE_OF_BIRTH | HIGH | 0.60 | -- | Date of birth European format (DD/MM/YYYY) |
| `dob_long_format` | DATE_OF_BIRTH | HIGH | 0.65 | -- | Date of birth long format (Month DD, YYYY) |
| `email_address` | EMAIL | HIGH | 0.95 | -- | Email address (user@domain.tld) |
| `international_phone` | PHONE | HIGH | 0.70 | -- | International phone number with country code |
| `ipv4_address` | IP_ADDRESS | MEDIUM | 0.90 | ipv4_not_reserved | IPv4 address with octet range validation |
| `ipv6_address` | IP_ADDRESS | MEDIUM | 0.90 | -- | IPv6 address (full form) |
| `mac_address` | DEVICE_ID | MEDIUM | 0.90 | -- | MAC address (XX:XX:XX:XX:XX:XX or XX-XX-XX-XX-XX-XX) |
| `uk_nino` | NATIONAL_ID | HIGH | 0.90 | -- | UK National Insurance Number (2 letters + 6 digits + 1 letter) |
| `url` | URL | LOW | 0.90 | -- | HTTP/HTTPS URL. Classified as PII when it may contain tracking parameters or user-specific paths. |
| `us_drivers_license` | NATIONAL_ID | HIGH | 0.35 | -- | US driver's license (varies by state, letter + 7-12 digits). Very low confidence alone. |
| `us_itin` | NATIONAL_ID | CRITICAL | 0.90 | -- | US Individual Taxpayer Identification Number (9XX-[7-9]X-XXXX) |
| `us_passport` | NATIONAL_ID | HIGH | 0.50 | -- | US passport number (1 letter + 8 digits). Low confidence — many false positives. |
| `us_phone_formatted` | PHONE | HIGH | 0.80 | -- | US phone number in common formats |
| `us_ssn_formatted` | SSN | CRITICAL | 0.95 | ssn_zeros | US Social Security Number in XXX-XX-XXXX format |
| `us_ssn_no_dashes` | SSN | CRITICAL | 0.40 | ssn_zeros | 9-digit number that could be an SSN without dashes. Low confidence — many false positives. |
| `vin` | VIN | MEDIUM | 0.85 | vin_checkdigit | Vehicle Identification Number |

## Financial

| Pattern | Entity Type | Sensitivity | Confidence | Validator | Description |
|---|---|---|---|---|---|
| `aba_routing` | ABA_ROUTING | HIGH | 0.75 | aba_checksum | ABA routing transit number |
| `bitcoin_address` | BITCOIN_ADDRESS | HIGH | 0.90 | -- | Bitcoin address (P2PKH/P2SH/Bech32) |
| `credit_card_amex` | CREDIT_CARD | CRITICAL | 0.90 | luhn | American Express card (starts with 34 or 37, 15 digits) |
| `credit_card_discover` | CREDIT_CARD | CRITICAL | 0.90 | luhn | Discover card number (starts with 6011 or 65, 16 digits) |
| `credit_card_formatted` | CREDIT_CARD | CRITICAL | 0.85 | luhn_strip | Credit card with separators (XXXX-XXXX-XXXX-XXXX) |
| `credit_card_mastercard` | CREDIT_CARD | CRITICAL | 0.90 | luhn | Mastercard number (starts with 51-55, 16 digits) |
| `credit_card_visa` | CREDIT_CARD | CRITICAL | 0.90 | luhn | Visa card number (starts with 4, 13 or 16 digits) |
| `ethereum_address` | ETHEREUM_ADDRESS | HIGH | 0.90 | -- | Ethereum/EVM address |
| `iban` | BANK_ACCOUNT | HIGH | 0.80 | iban_checksum | International Bank Account Number (IBAN) |
| `swift_bic` | SWIFT_BIC | MEDIUM | 0.90 | -- | SWIFT/BIC bank code |
| `us_ein` | EIN | MEDIUM | 0.70 | ein_prefix | US Employer Identification Number |

## Credential

| Pattern | Entity Type | Sensitivity | Confidence | Validator | Description |
|---|---|---|---|---|---|
| `aws_access_key` | CREDENTIAL | CRITICAL | 0.95 | -- | AWS Access Key ID (AKIA prefix + 16 alphanumeric) |
| `aws_secret_key` | CREDENTIAL | CRITICAL | 0.50 | -- | Potential AWS Secret Key (40 chars base64). Low confidence alone — usually paired with access key context. |
| `connection_string` | CREDENTIAL | CRITICAL | 0.90 | -- | Database connection string with protocol prefix |
| `databricks_token` | CREDENTIAL | CRITICAL | 0.95 | -- | Databricks personal access token (dapi prefix + 32 hex-like chars) |
| `discord_bot_token` | CREDENTIAL | CRITICAL | 0.95 | -- | Discord bot token |
| `generic_api_key` | CREDENTIAL | CRITICAL | 0.80 | -- | Generic API key assignment pattern (api_key=... or api-key: ...) |
| `github_token` | CREDENTIAL | CRITICAL | 0.99 | -- | GitHub personal access token or OAuth token |
| `gitlab_pat` | CREDENTIAL | CRITICAL | 0.99 | -- | GitLab personal access token (glpat- prefix) |
| `google_api_key` | CREDENTIAL | CRITICAL | 0.99 | -- | Google API key (AIza prefix + 35 chars) |
| `hashicorp_vault_token` | CREDENTIAL | CRITICAL | 0.95 | -- | HashiCorp Vault token |
| `jwt_token` | CREDENTIAL | CRITICAL | 0.95 | -- | JSON Web Token (three base64url segments starting with eyJ) |
| `mailgun_api_key` | CREDENTIAL | CRITICAL | 0.95 | -- | Mailgun API key (key- prefix + 32 hex chars) |
| `npm_token` | CREDENTIAL | CRITICAL | 0.95 | -- | npm access token |
| `openai_api_key` | CREDENTIAL | CRITICAL | 0.99 | -- | OpenAI project API key (sk-proj- prefix, 80+ chars) |
| `private_key_pem` | CREDENTIAL | CRITICAL | 0.99 | -- | PEM-encoded private key header |
| `pulumi_access_token` | CREDENTIAL | CRITICAL | 0.95 | -- | Pulumi access token |
| `sendgrid_api_key` | CREDENTIAL | CRITICAL | 0.99 | -- | SendGrid API key (SG. prefix with two base64 segments) |
| `shopify_access_token` | CREDENTIAL | CRITICAL | 0.99 | -- | Shopify access token (shpat_, shpca_, shppa_, shpss_ prefix + 32 hex) |
| `slack_bot_token` | CREDENTIAL | CRITICAL | 0.99 | -- | Slack bot token (xoxb- prefix) |
| `slack_user_token` | CREDENTIAL | CRITICAL | 0.99 | -- | Slack user token (xoxp- prefix) |
| `slack_webhook_url` | CREDENTIAL | HIGH | 0.99 | -- | Slack incoming webhook URL |
| `stripe_publishable_key` | CREDENTIAL | HIGH | 0.95 | -- | Stripe publishable key (less sensitive than secret, but still a credential) |
| `stripe_secret_key` | CREDENTIAL | CRITICAL | 0.99 | -- | Stripe secret or restricted key (sk_live_*, rk_live_*, sk_test_*) |
| `twilio_api_key` | CREDENTIAL | CRITICAL | 0.95 | -- | Twilio API key (SK prefix + 32 hex chars) |

## Health

| Pattern | Entity Type | Sensitivity | Confidence | Validator | Description |
|---|---|---|---|---|---|
| `icd10_code` | HEALTH | HIGH | 0.45 | -- | ICD-10 diagnosis code (letter + 2 digits + optional decimal). Low confidence alone — needs context. |
| `us_dea` | DEA_NUMBER | HIGH | 0.85 | dea_checkdigit | US DEA registration number |
| `us_mbi` | MBI | HIGH | 0.90 | -- | US Medicare Beneficiary Identifier |
| `us_medical_record_number` | HEALTH | HIGH | 0.85 | -- | Medical Record Number with contextual prefix |
| `us_npi` | NPI | HIGH | 0.80 | npi_luhn | US National Provider Identifier (10 digits, Luhn validated) |
