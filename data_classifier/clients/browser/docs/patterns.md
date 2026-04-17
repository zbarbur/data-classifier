# Pattern Reference

All 77 patterns shipped with `@data-classifier/browser`.
Generated from the Python `data_classifier` library.

**Categories:** Credential, Financial, Health, PII

> Patterns with `requires_column_hint = true` are excluded from browser
> scanning (no column context). They are listed here for completeness.

## Credential (41 patterns)

| Name | Entity type | Confidence | Validator | Column hint? | Description |
|------|-------------|------------|-----------|-------------|-------------|
| `argon2_hash` | PASSWORD_HASH | 0.99 | not_placeholder_credential |  | Argon2 password hash ($argon2id$, $argon2i$, $argon2d$ prefix + version/params/s |
| `aws_access_key` | API_KEY | 0.95 | not_placeholder_credential |  | AWS Access Key ID (AKIA prefix + 16 alphanumeric) |
| `aws_secret_key` | API_KEY | 0.5 | aws_secret_not_hex |  | Potential AWS Secret Key (40 chars base64). Low confidence alone — usually paire |
| `azure_storage_account_key` | API_KEY | 0.95 | not_placeholder_credential |  | Azure Storage Account key (AccountKey= connection string fragment) |
| `bcrypt_hash` | PASSWORD_HASH | 0.99 | not_placeholder_credential |  | bcrypt password hash ($2a$/$2b$/$2y$ prefix, cost + 22-char salt + 31-char hash) |
| `cloudflare_api_token` | API_KEY | 0.95 | not_placeholder_credential |  | Cloudflare API token |
| `connection_string` | API_KEY | 0.9 | not_placeholder_credential |  | Database connection string with protocol prefix |
| `databricks_token` | API_KEY | 0.95 | not_placeholder_credential |  | Databricks personal access token (dapi prefix + 32 hex-like chars) |
| `digitalocean_oauth_token` | API_KEY | 0.95 | not_placeholder_credential |  | DigitalOcean OAuth access token |
| `digitalocean_pat` | API_KEY | 0.95 | not_placeholder_credential |  | DigitalOcean Personal Access Token |
| `discord_bot_token` | API_KEY | 0.95 | not_placeholder_credential |  | Discord bot token |
| `flyio_api_token` | API_KEY | 0.95 | not_placeholder_credential |  | Fly.io API token |
| `generic_api_key` | API_KEY | 0.8 | not_placeholder_credential |  | Generic API key assignment pattern (api_key=... or api-key: ...) |
| `github_token` | API_KEY | 0.99 | not_placeholder_credential |  | GitHub personal access token or OAuth token |
| `gitlab_pat` | API_KEY | 0.99 | not_placeholder_credential |  | GitLab personal access token (glpat- prefix) |
| `google_api_key` | API_KEY | 0.99 | not_placeholder_credential |  | Google API key (AIza prefix + 35 chars) |
| `hashicorp_vault_token` | API_KEY | 0.95 | not_placeholder_credential |  | HashiCorp Vault token |
| `huggingface_token` | API_KEY | 0.95 | not_placeholder_credential |  | Hugging Face API token |
| `jwt_token` | API_KEY | 0.95 | not_placeholder_credential |  | JSON Web Token (three base64url segments starting with eyJ) |
| `linear_api_key` | API_KEY | 0.95 | not_placeholder_credential |  | Linear API key |
| `mailgun_api_key` | API_KEY | 0.95 | not_placeholder_credential |  | Mailgun API key (key- prefix + 32 hex chars) |
| `netlify_pat` | API_KEY | 0.95 | not_placeholder_credential |  | Netlify Personal Access Token |
| `npm_token` | API_KEY | 0.95 | not_placeholder_credential |  | npm access token |
| `openai_api_key` | API_KEY | 0.99 | not_placeholder_credential |  | OpenAI project API key (sk-proj- prefix, 80+ chars) |
| `private_key_pem` | PRIVATE_KEY | 0.99 | not_placeholder_credential |  | PEM-encoded private key header |
| `pulumi_access_token` | API_KEY | 0.95 | not_placeholder_credential |  | Pulumi access token |
| `random_password` | OPAQUE_SECRET | 0.6 | random_password | Yes | Column-name-gated random password: short mixed-class string in a password/secret |
| `scrypt_hash` | PASSWORD_HASH | 0.99 | not_placeholder_credential |  | scrypt password hash ($scrypt$ prefix with optional params + salt + hash). |
| `sendgrid_api_key` | API_KEY | 0.99 | not_placeholder_credential |  | SendGrid API key (SG. prefix with two base64 segments) |
| `sentry_auth_token` | API_KEY | 0.95 | not_placeholder_credential |  | Sentry auth token |
| `shacrypt_hash` | PASSWORD_HASH | 0.99 | not_placeholder_credential |  | SHA-256 ($5$) or SHA-512 ($6$) crypt password hash (glibc/Linux shadow format). |
| `shopify_access_token` | API_KEY | 0.99 | not_placeholder_credential |  | Shopify access token (shpat_, shpca_, shppa_, shpss_ prefix + 32 hex) |
| `slack_bot_token` | API_KEY | 0.99 | not_placeholder_credential |  | Slack bot token (xoxb- prefix) |
| `slack_user_token` | API_KEY | 0.99 | not_placeholder_credential |  | Slack user token (xoxp- prefix) |
| `slack_webhook_url` | API_KEY | 0.99 | not_placeholder_credential |  | Slack incoming webhook URL |
| `stripe_publishable_key` | API_KEY | 0.95 | not_placeholder_credential |  | Stripe publishable key (less sensitive than secret, but still a credential) |
| `stripe_secret_key` | API_KEY | 0.99 | not_placeholder_credential |  | Stripe secret or restricted key (sk_live_*, rk_live_*, sk_test_*) |
| `supabase_service_key` | API_KEY | 0.95 | not_placeholder_credential |  | Supabase service role / personal access token |
| `terraform_cloud_token` | API_KEY | 0.95 | not_placeholder_credential |  | Terraform Cloud / HCP Terraform API token |
| `twilio_api_key` | API_KEY | 0.95 | not_placeholder_credential |  | Twilio API key (SK prefix + 32 hex chars) |
| `vercel_api_token` | API_KEY | 0.95 | not_placeholder_credential |  | Vercel API token |

## PII (20 patterns)

| Name | Entity type | Confidence | Validator | Column hint? | Description |
|------|-------------|------------|-----------|-------------|-------------|
| `canadian_sin` | CANADIAN_SIN | 0.85 | sin_luhn |  | Canadian Social Insurance Number |
| `date_iso_format` | DATE_OF_BIRTH | 0.5 | - |  | Date in YYYY-MM-DD or YYYY/MM/DD format (ISO-like) |
| `date_of_birth_format` | DATE_OF_BIRTH | 0.6 | - |  | Date in MM/DD/YYYY or MM-DD-YYYY format (could be any date, not necessarily DOB) |
| `dob_european` | DATE_OF_BIRTH | 0.6 | - |  | Date of birth European format DD/MM/YYYY or DD.MM.YYYY. Sprint 12 retired the se |
| `dob_long_format` | DATE_OF_BIRTH | 0.65 | - |  | Date of birth long format (Month DD, YYYY) |
| `email_address` | EMAIL | 0.95 | - |  | Email address (user@domain.tld) |
| `international_phone` | PHONE | 0.7 | phone_number |  | International phone number with country code, supporting multi-segment mixed-sep |
| `international_phone_local` | PHONE | 0.6 | phone_number |  | Non-plus-prefixed international/local phone — trunk-0 or international-access-00 |
| `ipv4_address` | IP_ADDRESS | 0.9 | ipv4_not_reserved |  | IPv4 address with octet range validation |
| `ipv6_address` | IP_ADDRESS | 0.9 | - |  | IPv6 address (full form) |
| `mac_address` | MAC_ADDRESS | 0.9 | - |  | MAC address (XX:XX:XX:XX:XX:XX or XX-XX-XX-XX-XX-XX) |
| `uk_nino` | NATIONAL_ID | 0.9 | - |  | UK National Insurance Number (2 letters + 6 digits + 1 letter) |
| `url` | URL | 0.9 | - |  | HTTP/HTTPS URL. Classified as PII when it may contain tracking parameters or use |
| `us_drivers_license` | NATIONAL_ID | 0.35 | - |  | US driver's license (varies by state, letter + 7-12 digits). Very low confidence |
| `us_itin` | NATIONAL_ID | 0.9 | - |  | US Individual Taxpayer Identification Number (9XX-[7-9]X-XXXX) |
| `us_passport` | NATIONAL_ID | 0.5 | - |  | US passport number (1 letter + 8 digits). Low confidence — many false positives. |
| `us_phone_formatted` | PHONE | 0.8 | phone_number |  | US phone number in common formats |
| `us_ssn_formatted` | SSN | 0.95 | ssn_zeros |  | US Social Security Number in XXX-XX-XXXX format |
| `us_ssn_no_dashes` | SSN | 0.4 | ssn_zeros |  | 9-digit number that could be an SSN without dashes. Low confidence — many false  |
| `vin` | VIN | 0.85 | vin_checkdigit |  | Vehicle Identification Number |

## Financial (11 patterns)

| Name | Entity type | Confidence | Validator | Column hint? | Description |
|------|-------------|------------|-----------|-------------|-------------|
| `aba_routing` | ABA_ROUTING | 0.75 | aba_checksum |  | ABA routing transit number |
| `bitcoin_address` | BITCOIN_ADDRESS | 0.9 | bitcoin_address |  | Bitcoin address (P2PKH/P2SH/Bech32, checksum-verified) |
| `credit_card_amex` | CREDIT_CARD | 0.9 | luhn |  | American Express card (starts with 34 or 37, 15 digits) |
| `credit_card_discover` | CREDIT_CARD | 0.9 | luhn |  | Discover card number (starts with 6011 or 65, 16 digits) |
| `credit_card_formatted` | CREDIT_CARD | 0.85 | luhn_strip |  | Credit card with separators (XXXX-XXXX-XXXX-XXXX) |
| `credit_card_mastercard` | CREDIT_CARD | 0.9 | luhn |  | Mastercard number (starts with 51-55, 16 digits) |
| `credit_card_visa` | CREDIT_CARD | 0.9 | luhn |  | Visa card number (starts with 4, 13 or 16 digits) |
| `ethereum_address` | ETHEREUM_ADDRESS | 0.9 | ethereum_address |  | Ethereum/EVM address |
| `iban` | IBAN | 0.8 | iban_checksum |  | International Bank Account Number (IBAN) |
| `swift_bic` | SWIFT_BIC | 0.9 | - |  | SWIFT/BIC bank code |
| `us_ein` | EIN | 0.7 | ein_prefix |  | US Employer Identification Number |

## Health (5 patterns)

| Name | Entity type | Confidence | Validator | Column hint? | Description |
|------|-------------|------------|-----------|-------------|-------------|
| `icd10_code` | HEALTH | 0.3 | - |  | ICD-10 diagnosis code (letter + 2 digits + decimal + 1-4 digits). Requires decim |
| `us_dea` | DEA_NUMBER | 0.85 | dea_checkdigit |  | US DEA registration number |
| `us_mbi` | MBI | 0.9 | - |  | US Medicare Beneficiary Identifier |
| `us_medical_record_number` | HEALTH | 0.85 | - |  | Medical Record Number with contextual prefix |
| `us_npi` | NPI | 0.8 | npi_luhn |  | US National Provider Identifier (10 digits, Luhn validated) |

