# Real-World Detection Stories

Annotated examples from the WildChat corpus (11,000 prompts).
Each shows a real prompt that users submitted to ChatGPT containing
credentials the scanner detected. The tester page includes all 17
stories; the 9 documented below are the most instructive.

To see the actual prompts, use the tester page (`npm run serve`, then
open `http://localhost:4173/tester/` and select a story from the
dropdown). Prompts are XOR-encoded in `tester/corpus/stories.jsonl`
and decoded client-side — they are never stored in plaintext in git.

---

## Azure Computer Vision SDK with hardcoded client_secret

**ID:** `story_01_azure_client_secret` | **Fingerprint:** `747c7ba7865681e6`

- **Entity type:** `API_KEY`
- **Engine:** `secret_scanner`
- **Confidence:** 0.9025
- **Prompt length:** 8,065 characters

> Python script importing Azure SDK with a real client_secret in the initialization. The secret_scanner fires on the client_secret KV pair (definitive tier).

---

## Instagram Graph API with embedded access token (Japanese)

**ID:** `story_02_instagram_access_token` | **Fingerprint:** `5911e6c07d4af94e`

- **Entity type:** `API_KEY`
- **Engine:** `secret_scanner`
- **Confidence:** 0.9025
- **Prompt length:** 4,141 characters

> Japanese-language prompt requesting Instagram analytics code. Contains a hardcoded access_token for the Graph API. Definitive tier.

---

## C# homework with database connection string password

**ID:** `story_03_db_password_csharp` | **Fingerprint:** `1b7112175d20d03c`

- **Entity type:** `OPAQUE_SECRET`
- **Engine:** `secret_scanner`
- **Confidence:** 0.9025
- **Prompt length:** 12,240 characters

> Student sharing a C# assignment that includes a database connection with a plaintext password. Common pattern in homework-help prompts.

---

## Telegram bot with hardcoded bot_token (Russian)

**ID:** `story_04_telegram_bot_token` | **Fingerprint:** `818ab6dacbb67586`

- **Entity type:** `OPAQUE_SECRET`
- **Engine:** `secret_scanner`
- **Confidence:** 0.6014
- **Prompt length:** 10,766 characters

> Russian-language prompt debugging a Telegram bot. The bot_token is hardcoded in source. Strong tier, requires entropy confirmation since bot_token is not definitive.

---

## Instagram scraper with plaintext login password

**ID:** `story_05_instagram_password` | **Fingerprint:** `9466e01f349ee88b`

- **Entity type:** `OPAQUE_SECRET`
- **Engine:** `secret_scanner`
- **Confidence:** 0.9025
- **Prompt length:** 6,726 characters

> User sharing a Streamlit + Instaloader script with username and password in plaintext. Definitive tier on the password key.

---

## Cryptography homework discussing RSA session keys

**ID:** `story_06_rsa_session_key` | **Fingerprint:** `3fcbabd03a98d39e`

- **Entity type:** `API_KEY`
- **Engine:** `secret_scanner`
- **Confidence:** 0.51
- **Prompt length:** 2,057 characters

> Assignment about RSA + AES session key file transfer. Low confidence (0.51). The key name session_key is strong tier and the value barely passes the entropy gate. Borderline true positive.

---

## Long-lived Facebook access token in Python analytics script

**ID:** `story_07_facebook_access_token` | **Fingerprint:** `dcc0cad828e67522`

- **Entity type:** `OPAQUE_SECRET`
- **Engine:** `secret_scanner`
- **Confidence:** 0.8004
- **Prompt length:** 3,672 characters

> Japanese analytics script with a long Facebook Graph API access token. Strong tier. The token key name needs entropy confirmation, which the 200+ character token easily passes.

---

## Shopify PHP config with shpat_ access token

**ID:** `story_08_shopify_access_token` | **Fingerprint:** `41dad1b2a5d24f16`

- **Entity type:** `API_KEY`
- **Engine:** `regex`
- **Confidence:** 0.6435
- **Prompt length:** 903 characters

> PHP configuration array for the Shopify API. The shpat_ prefix matches the Shopify PAT regex pattern directly (regex engine, not secret_scanner). The only story triggered by the regex pass.

---

## Telegram bot with raw token string visible

**ID:** `story_09_telegram_raw_token` | **Fingerprint:** `024eb7f3571a3f34`

- **Entity type:** `OPAQUE_SECRET`
- **Engine:** `secret_scanner`
- **Confidence:** 0.6014
- **Prompt length:** 9,755 characters

> Russian Telegram bot code with the raw bot token visible in the source. Strong tier on bot_token. The colon-separated numeric:alphanumeric format has high entropy and diversity.

---

## Summary

| # | Entity | Engine | Confidence | Key | Interesting because |
|---|--------|--------|------------|-----|---------------------|
| 1 | API_KEY | secret_scanner | 0.9025 | client_secret | Azure Computer Vision SDK with hardcoded |
| 2 | API_KEY | secret_scanner | 0.9025 | access_token | Instagram Graph API with embedded access |
| 3 | OPAQUE_SECRET | secret_scanner | 0.9025 | password | C# homework with database connection str |
| 4 | OPAQUE_SECRET | secret_scanner | 0.6014 | bot_token | Telegram bot with hardcoded bot_token (R |
| 5 | OPAQUE_SECRET | secret_scanner | 0.9025 | password | Instagram scraper with plaintext login p |
| 6 | API_KEY | secret_scanner | 0.51 | session_key | Cryptography homework discussing RSA ses |
| 7 | OPAQUE_SECRET | secret_scanner | 0.8004 | token | Long-lived Facebook access token in Pyth |
| 8 | API_KEY | regex | 0.6435 | (regex prefix) | Shopify PHP config with shpat_ access to |
| 9 | OPAQUE_SECRET | secret_scanner | 0.6014 | bot_token | Telegram bot with raw token string visib |

