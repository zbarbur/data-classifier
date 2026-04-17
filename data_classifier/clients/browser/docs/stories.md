# Real-World Detection Stories

12 curated examples from the WildChat corpus (11,000 prompts).
Each shows a real prompt that users submitted to ChatGPT containing
credentials the scanner detected.

To see the actual prompts, use the tester page (`npm run serve`, then
open `http://localhost:4173/tester/` and select a story from the
dropdown). Prompts are XOR-encoded in `tester/corpus/stories.jsonl`
and decoded client-side — they are never stored in plaintext in git.

---

## Story 1: Azure Computer Vision SDK with hardcoded client_secret

**ID:** `story_01_azure_client_secret` | **Fingerprint:** `747c7ba7865681e6`

- **Entity type:** `API_KEY`
- **Engine:** `secret_scanner`
- **Confidence:** 0.9025
- **Prompt length:** 8,065 characters
- **Language:** Python / English

> Python script importing Azure SDK with a real client_secret in the
> initialization. The secret_scanner fires on the client_secret KV pair
> (definitive tier). The user was building a Flask app integrating
> Azure Computer Vision and pasted the entire script including credentials.

**Why it triggers:** The key name `client_secret` matches a definitive-tier
pattern (score 0.95). At definitive tier, only the "obviously not secret"
checks need to pass — no entropy gate. The value is a real Azure credential,
not a placeholder.

---

## Story 2: Instagram Graph API with embedded access token (Japanese)

**ID:** `story_02_instagram_access_token` | **Fingerprint:** `5911e6c07d4af94e`

- **Entity type:** `API_KEY`
- **Engine:** `secret_scanner`
- **Confidence:** 0.9025
- **Prompt length:** 4,141 characters
- **Language:** Japanese

> Japanese-language prompt requesting Instagram analytics code. Contains a
> hardcoded access_token for the Graph API. Definitive tier.

**Why it triggers:** The key name `access_token` is a definitive-tier match.
The prompt is entirely in Japanese except for the code variables and the
token itself — demonstrates that the scanner works on multilingual input
because it operates on key-value structure, not natural language.

---

## Story 3: C# homework with database connection string password

**ID:** `story_03_db_password_csharp` | **Fingerprint:** `1b7112175d20d03c`

- **Entity type:** `OPAQUE_SECRET`
- **Engine:** `secret_scanner`
- **Confidence:** 0.9025
- **Prompt length:** 12,240 characters
- **Language:** C# / English

> Student sharing a C# assignment that includes a database connection with
> a plaintext password. Common pattern in homework-help prompts — students
> paste entire projects including credentials.

**Why it triggers:** The key name `password` is definitive-tier (score 0.95).
The value is a real-looking password, not a placeholder or config value.
Entity type is `OPAQUE_SECRET` because `password` maps to the opaque-secret
subtype (it's not a structured token like an API key).

---

## Story 4: Telegram bot with hardcoded bot_token (Russian)

**ID:** `story_04_telegram_bot_token` | **Fingerprint:** `818ab6dacbb67586`

- **Entity type:** `OPAQUE_SECRET`
- **Engine:** `secret_scanner`
- **Confidence:** 0.6014
- **Prompt length:** 10,766 characters
- **Language:** Python / Russian

> Russian-language prompt debugging a Telegram bot. The bot_token is
> hardcoded in source. Strong tier, requires entropy confirmation.

**Why it triggers:** The key name `bot_token` is a strong-tier match
(score 0.85, not definitive). At strong tier, the value must pass either
the relative entropy gate (>= 0.5) or the char-class diversity gate (>= 3).
A Telegram bot token (`5828712341:AAG5HJ...`) has a numeric:alphanumeric
format with high diversity — it passes easily. Confidence is 0.6014
(key_score 0.85 * entropy_score).

---

## Story 5: Instagram scraper with plaintext login password

**ID:** `story_05_instagram_password` | **Fingerprint:** `9466e01f349ee88b`

- **Entity type:** `OPAQUE_SECRET`
- **Engine:** `secret_scanner`
- **Confidence:** 0.9025
- **Prompt length:** 6,726 characters
- **Language:** Python / English

> User sharing a Streamlit + Instaloader script with username and password
> in plaintext. Definitive tier on the password key.

**Why it triggers:** The `password` key is definitive-tier. The value
contains mixed case + special characters + digits — clearly not a
placeholder (passes all suppression checks). This is a classic case:
user pastes working code that includes login credentials.

---

## Story 6: Cryptography homework discussing RSA session keys

**ID:** `story_06_rsa_session_key` | **Fingerprint:** `3fcbabd03a98d39e`

- **Entity type:** `API_KEY`
- **Engine:** `secret_scanner`
- **Confidence:** 0.51
- **Prompt length:** 2,057 characters
- **Language:** English

> Assignment about RSA + AES session key file transfer. Low confidence
> (0.51). Borderline true positive.

**Why it triggers (barely):** The key name `session_key` is strong-tier
(score 0.85). The value is a technical description, not a real key, but
it has enough entropy to barely pass the 0.5 relative-entropy gate.
This is a useful edge case: the scanner flags it at low confidence,
allowing downstream consumers to threshold appropriately.

---

## Story 7: Long-lived Facebook access token in Python analytics script

**ID:** `story_07_facebook_access_token` | **Fingerprint:** `dcc0cad828e67522`

- **Entity type:** `OPAQUE_SECRET`
- **Engine:** `secret_scanner`
- **Confidence:** 0.8004
- **Prompt length:** 3,672 characters
- **Language:** Python / Japanese

> Japanese analytics script with a long Facebook Graph API access token
> (200+ characters). Strong tier on the `token` key name.

**Why it triggers:** The key `token` is strong-tier (score 0.85). The
value is a 200+ character Facebook Graph API token — extremely high
entropy and diversity. The scanner correctly identifies this as a
high-confidence credential despite the generic key name, because the
value is unambiguously random.

---

## Story 8: C# appliance rental app with capitalized Password field

**ID:** `story_08_csharp_password_capitalized` | **Fingerprint:** `35a2aa0beff0467d`

- **Entity type:** `OPAQUE_SECRET`
- **Engine:** `secret_scanner`
- **Confidence:** 0.9025
- **Prompt length:** 13,664 characters
- **Language:** C# / English

> Student building a .NET appliance rental system. The Password field
> in the login form contains a real credential.

**Why it triggers:** Case-insensitive key matching catches `Password`
(capital P) as a definitive-tier match. This demonstrates that the
scanner handles case variations in key names — important for .NET code
where PascalCase is the convention.

---

## Story 9: Selenium login automation with password (Russian)

**ID:** `story_09_selenium_login_password` | **Fingerprint:** `38500e17ed4a34aa`

- **Entity type:** `OPAQUE_SECRET`
- **Engine:** `secret_scanner`
- **Confidence:** 0.9025
- **Prompt length:** 6,812 characters
- **Language:** Python / Russian

> Russian prompt sharing a Selenium script that automates login with
> CAPTCHA solving. The password_field variable contains the actual password.

**Why it triggers:** The key name `password_field` contains `password`
as a substring — definitive-tier match via substring match_type. Even
compound key names like `password_field`, `db_password`, or
`user_password` are caught because the scorer iterates all 178 key
patterns and takes the highest match.

---

## Story 10: Solana airdrop script with SPL token address

**ID:** `story_10_solana_token_address` | **Fingerprint:** `80214d319ab6ea5c`

- **Entity type:** `OPAQUE_SECRET`
- **Engine:** `secret_scanner`
- **Confidence:** 0.5178
- **Prompt length:** 1,584 characters
- **Language:** Python / English

> Python script for Solana SPL token airdrops. Low confidence (0.52).
> Borderline: this is a token contract address, not a secret.

**Why it triggers (barely):** The key `token_address` matches strong-tier
on the `token` substring (score 0.85). The Solana address is hex-like
with just enough entropy to pass the gate. This is a **false positive** —
a blockchain address is not a secret. Useful for understanding the
scanner's limitations: it doesn't have domain knowledge about blockchain
addresses vs. authentication tokens.

---

## Story 11: Shopify PHP config with shpat_ access token

**ID:** `story_11_shopify_access_token` | **Fingerprint:** `41dad1b2a5d24f16`

- **Entity type:** `API_KEY`
- **Engine:** `regex`
- **Confidence:** 0.6435
- **Prompt length:** 903 characters
- **Language:** PHP / English

> PHP configuration array for the Shopify API. The `shpat_` prefix
> matches the Shopify PAT regex pattern.

**Why it triggers:** This is the only story triggered by the **regex
pass** (not the secret-scanner). The pattern `shopify_pat` matches the
`shpat_` prefix followed by a hex string. No key-name scoring or entropy
gating needed — the regex alone identifies the credential by its
structure. This demonstrates why both passes are needed: some credentials
have distinctive prefixes (regex catches them), others are generic
values in KV pairs (secret-scanner catches them).

---

## Story 12: Telegram bot with raw token string visible

**ID:** `story_12_telegram_raw_token` | **Fingerprint:** `024eb7f3571a3f34`

- **Entity type:** `OPAQUE_SECRET`
- **Engine:** `secret_scanner`
- **Confidence:** 0.6014
- **Prompt length:** 9,755 characters
- **Language:** Python / Russian

> Russian Telegram bot code with the raw bot token visible in the source.
> Strong tier on `bot_token`.

**Why it triggers:** Same mechanism as Story 4 (Telegram bot_token,
strong tier, entropy-confirmed). Included as a second example because
the prompt structure differs — this one has the token assigned directly
as a string literal (`bot_token = '5828...:AAG...'`), while Story 4
had it in a different code context. Both are caught by the same
key-scoring logic.

---

## Summary

| # | Entity | Engine | Confidence | Tier | Key | Interesting because |
|---|--------|--------|------------|------|-----|---------------------|
| 1 | API_KEY | secret_scanner | 0.90 | definitive | client_secret | Azure SDK credential |
| 2 | API_KEY | secret_scanner | 0.90 | definitive | access_token | Multilingual (Japanese) |
| 3 | OPAQUE_SECRET | secret_scanner | 0.90 | definitive | password | Homework DB credential |
| 4 | OPAQUE_SECRET | secret_scanner | 0.60 | strong | bot_token | Entropy-confirmed Telegram token |
| 5 | OPAQUE_SECRET | secret_scanner | 0.90 | definitive | password | Plaintext login in scraper |
| 6 | API_KEY | secret_scanner | 0.51 | strong | session_key | Borderline — barely passes gate |
| 7 | OPAQUE_SECRET | secret_scanner | 0.80 | strong | token | 200+ char Facebook token |
| 8 | OPAQUE_SECRET | secret_scanner | 0.90 | definitive | Password | PascalCase key matching |
| 9 | OPAQUE_SECRET | secret_scanner | 0.90 | definitive | password_field | Compound key substring match |
| 10 | OPAQUE_SECRET | secret_scanner | 0.52 | strong | token_address | False positive — blockchain addr |
| 11 | API_KEY | regex | 0.64 | — | — | Regex prefix match (shpat_) |
| 12 | OPAQUE_SECRET | secret_scanner | 0.60 | strong | bot_token | Second Telegram variant |
