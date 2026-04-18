# S3-A — Secretlint Pattern Mine: Gap Analysis

**Date**: 2026-04-16
**Source**: secretlint (MIT), commit `3e58badf8f8b` (2026-04-14)
**Branch**: `research/prompt-analysis`

---

## Summary

- Secretlint has 27 rule packages covering roughly 40 credential types
- 16 services already covered by our 79 patterns on `main` (including Sprint 13's `openai_legacy_key` + `anthropic_api_key`)
- **9 net-new patterns proposed** — see `s3a_proposed_patterns.json`
- **5 quality upgrades proposed** — see `s3a_proposed_upgrades.json`
- **Corpus validation**: 0 total hits on 11K WildChat prompts (2.7s elapsed) — expected; these are niche credential formats not present in general-purpose chat logs
- **Provenance**: all 14 entries recorded in `s3a_provenance.json`

---

## Net-new patterns (9)

### 1. grafana_cloud_api_token

Grafana Cloud API tokens carry a `glc_` prefix followed by a base64-encoded JWT body (32–400 chars, optional `=` padding). The token embeds the org ID, stack name, and region in its body. Regex: `\bglc_[A-Za-z0-9+/]{32,400}={0,2}`. RE2 translation: secretlint used `(?<!\p{L})` Unicode lookbehind — replaced with `\b`. Named captures dropped. Confidence 0.95 — prefix is globally unique and the length floor eliminates incidental matches. Corpus hits: 0.

### 2. grafana_service_account_token

Grafana service account tokens use `glsa_` prefix with a 32-char alphanumeric body followed by `_` and an 8-hex-char checksum: `glsa_{32alnum}_{8hex}`. The checksum segment is the strongest specificity signal — it constrains total token length to exactly 41 chars after the prefix. Regex: `\bglsa_[A-Za-z0-9]{32}_[A-Fa-f0-9]{8}\b`. Confidence 0.95. Corpus hits: 0.

### 3. docker_hub_pat

Docker Hub personal access tokens use a `dckr_pat_` prefix with exactly 27 alphanumeric-plus-hyphen-underscore characters (fixed length). The fixed-length body makes this a very low FP risk. Regex: `\bdckr_pat_[a-zA-Z0-9_-]{27}\b`. Confidence 0.95. Source: `@secretlint/secretlint-rule-docker`. Corpus hits: 0.

### 4. linear_api_token

Linear project management API tokens carry a `lin_api_` prefix followed by 32–128 alphanumeric characters. The `lin_api_` prefix (7 chars) is specific enough to eliminate false positives. Regex: `\blin_api_[a-zA-Z0-9_]{32,128}\b`. Confidence 0.95. No overlap with any existing pattern. Corpus hits: 0.

### 5. groq_api_key

Groq LLM API keys use a `gsk_` prefix with exactly 52 alphanumeric characters (fixed length, total token 56 chars). The fixed length is a meaningful signal — loose `gsk_` strings short of 52 chars do not match. Regex: `\bgsk_[a-zA-Z0-9]{52}\b`. Confidence 0.95. Corpus hits: 0.

### 6. onepassword_service_token

1Password service account tokens use `ops_` prefix with a base64 JSON body beginning with `ey` (JWT-style). Total length is 104–1284 chars. The `ops_ey` anchor is specific; the very long minimum length (100 base64 chars = ~75 decoded bytes) eliminates accidental matches. No `\b` on the right end — base64 bodies may end in `=` or alnum and word-boundary semantics are unreliable at variable terminations. Regex: `\bops_ey[A-Za-z0-9+/=]{100,1280}`. Confidence 0.90 (slightly lower: no right-anchor `\b`). Corpus hits: 0.

### 7. notion_integration_token

Notion integration tokens follow a rigid structure: `ntn_` prefix, exactly 11 decimal digits, then exactly 35 alphanumeric characters (total 50 chars after prefix). The digit run at position 4–14 is the most distinctive signal — it separates this from generic API keys. Regex: `\bntn_[0-9]{11}[A-Za-z0-9]{35}\b`. Confidence 0.95. Corpus hits: 0.

### 8. figma_pat

Figma personal access tokens use a `figd_` prefix with 40–200 chars of URL-safe base64 characters (alnum, hyphen, underscore). The lower bound of 40 prevents collision with short identifiers. Regex: `\bfigd_[A-Za-z0-9_-]{40,200}\b`. Confidence 0.95. Corpus hits: 0.

### 9. basicauth_url

HTTP Basic Auth credentials embedded in URLs (`scheme://user:pass@host`) are a generic credential format rather than a service-specific token, but they are included in secretlint's recommended preset and represent a real exposure vector in connection strings, DSN fields, and log data. Regex: `https?://[a-zA-Z0-9_-]{2,256}:[a-zA-Z0-9_-]{4,256}@[a-zA-Z0-9%._+~#=-]{1,256}\.[a-zA-Z0-9()]{1,6}`. Sensitivity: HIGH (not CRITICAL — the credential value may be weak). Confidence 0.80 — lowest of the batch due to placeholder risk (e.g., `user:password@example.com` in docs). Guards applied: `validator: not_placeholder_credential`, `stopwords: [password, YOUR_PASSWORD, changeme, xxx]`, `allowlist_patterns: [\$\{, \{\{, <%=]`. Corpus hits: 0 — the no-hit result combined with no samples means we cannot calibrate the validator threshold on WildChat; production FP rate remains unvalidated and is the main risk item before merging.

---

## Quality upgrades (5)

### 1. github_token — add fine-grained PATs

**Current regex** (`main`): `\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36}\b`

GitHub introduced fine-grained PATs in 2022 with a new format: `github_pat_` prefix followed by exactly 82 alphanumeric/underscore characters. This format is not matched by any of the five `gh{x}_` prefixes on main.

**Proposed**: `\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36}\b|\bgithub_pat_[A-Za-z0-9_]{82}\b`

Classic tokens (ghp/gho/ghu/ghs/ghr) unchanged. The fine-grained variant is an alternation on the same pattern entry. No entity type change — still `API_KEY`. Source: `@secretlint/secretlint-rule-github`.

### 2. slack_bot_token — unify all Slack token prefixes

**Current state on `main`**: two separate patterns — `slack_bot_token` (`\bxoxb-...`) and `slack_user_token` (`\bxoxp-...`). The `xapp` (app-level), `xoxa` (OAuth app), `xoxo` (internal), and `xoxr` (refresh) prefixes are not covered by either.

**Proposed**: `\b(?:xoxb|xoxp|xapp|xoxa|xoxo|xoxr)-(?:[0-9]+-)?[a-zA-Z0-9]{1,40}(?:-[a-zA-Z0-9]{1,40})*\b`

This collapses all six Slack token families into one pattern and extends coverage to app tokens and OAuth refresh tokens. The implementation decision — whether to rename the existing `slack_bot_token` entry or retire `slack_user_token` as a duplicate — is a main-PR concern. Source: `@secretlint/secretlint-rule-slack`.

### 3. openai_api_key — svcacct/admin prefixes + T3BlbkFJ tightening

**Current regex** (`main`): `\bsk-proj-[a-zA-Z0-9\-_]{80,}\b`

OpenAI's new key formats include `sk-svcacct-` (service account) and `sk-admin-` (admin) prefixes alongside `sk-proj-`. All new-format keys embed the magic bytes `T3BlbkFJ` (base64 of `OpenAI`) in a fixed position within the body.

**Proposed**: `\bsk-(?:proj|svcacct|admin)-[A-Za-z0-9_-]{58,80}T3BlbkFJ[A-Za-z0-9_-]{58,80}\b`

**Verification required before merging**: if Sprint 13's `sk-proj` regex already accepts svcacct/admin keys because the prefix structure is identical past the first segment, only the `T3BlbkFJ` tightening is needed. `new_examples_match` is empty in the proposals file pending verification. Source: `@secretlint/secretlint-rule-openai`.

### 4. hashicorp_vault_token — add hvb and hvr prefixes

**Current regex** (`main`): `\bhvs\.[A-Za-z0-9_-]{24,}\b`

HashiCorp Vault issues three token classes with distinct prefixes: `hvs.` (service tokens, covered), `hvb.` (batch tokens, 138–300 chars, not covered), and `hvr.` (recovery tokens, 90–120 chars, not covered). All share the same body character set.

**Proposed**: `\b(?:hvs|hvb|hvr)\.[A-Za-z0-9_-]{24,}\b`

Minimal change — adds two prefix alternatives, does not change the body constraint. Source: `@secretlint/secretlint-rule-hashicorp-vault`.

### 5. huggingface_token — tighten to alpha-only 34 chars

**Current regex** (`main`): `\bhf_[A-Za-z0-9]{20,}\b`

Secretlint's rule asserts HuggingFace user access tokens are exactly 34 alpha characters (no digits, no underscore). If true, the tighter regex `\bhf_[a-zA-Z]{34}\b` would reduce false positives from short or numeric-containing lookalikes.

**Proposed**: `\bhf_[a-zA-Z]{34}\b`

**Verification required before merging**: the alpha-only, fixed-length claim must be validated against real HuggingFace tokens before this upgrade is adopted. If real tokens include digits, the correct fix is to keep alphanumeric and add the `{34}` fixed-length constraint (`\bhf_[A-Za-z0-9]{34}\b`). Source: `@secretlint/secretlint-rule-huggingface`.

---

## Patterns NOT proposed (with rationale)

**GCP service account JSON key**: Detection requires parsing the full JSON structure (`"type": "service_account"`, `"private_key"`, `"client_email"` co-presence). No single regex over a text stream can reliably match this without structural context. Out of scope for the regex engine. Secretlint's GCP rule similarly depends on JSON key detection, not a token prefix.

**secp256k1 / Ethereum private key**: A 64-hex-char string beginning with `0x` is not reliably a private key without cryptographic validation (checking whether the value is a valid field element). Secretlint excludes secp256k1 from its recommended preset for the same reason. Regex-only detection yields unacceptable FP rates on any system emitting 64-char hex strings (UUIDs, SHA-256 hashes, etc.).

**Kubernetes Secret manifests**: Detection depends on YAML structural context (`kind: Secret`, `data:` block, base64-encoded value). A flat text regex cannot distinguish Kubernetes Secret YAML from other base64 content. Out of scope for the regex engine; would require a structural parser.

**Azure tenant_id / client_id (GUID format)**: GUIDs (`xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`) are identifiers, not secrets. Azure `client_secret` values are secrets but are context-keyed — they appear alongside `client_id` or `client_secret =` assignment patterns. The existing `secret_scanner` key+entropy heuristic already catches `client_secret = "..."` style exposures without a dedicated pattern. A bare GUID regex would produce extreme FP rates.

---

## Corpus validation summary

All 9 proposed patterns returned 0 hits on 11,000 WildChat prompts (S2 corpus, 2.7s elapsed).

This is consistent with S0's finding that credential prevalence in WildChat is 0.12% overall, dominated by a small number of common credential types (Shopify, Instagram, Telegram, OpenAI). Niche developer credentials (Grafana, Docker Hub PAT, Linear, Groq, Notion, Figma, 1Password) are rare to absent in general-purpose chat logs.

The 0-hit result on `basicauth_url` means the `not_placeholder_credential` validator and stopword list are unvalidated for this corpus. The FP risk on production data (connection-string columns, log columns) should be evaluated using targeted BQ column samples before the pattern is promoted to main.

---

## Verification items for main PR

- [ ] Verify HuggingFace alpha-only claim: check 5+ real `hf_` tokens from HuggingFace API docs or token dumps; if any contain digits, adopt `\bhf_[A-Za-z0-9]{34}\b` instead of alpha-only
- [ ] Verify OpenAI svcacct/admin prefix format: confirm whether `sk-svcacct-` and `sk-admin-` share the same 58–80 char body + `T3BlbkFJ` magic as `sk-proj-`; if so, add `new_examples_match` entries before merge
- [ ] Validate basicauth_url FP rate on a real production column sample (connection_string or url columns in BQ); the 0-hit corpus result provides no calibration signal
- [ ] Decide: merge `slack_bot_token` + `slack_user_token` into a single unified `slack_token` pattern entry, or keep as one broadened `slack_bot_token` and retire `slack_user_token`?

---

## RE2 translation notes

Secretlint TypeScript patterns use features not supported in RE2:

| secretlint construct | RE2 translation used |
|---|---|
| `(?<!\p{L})` Unicode lookbehind | `\b` word boundary |
| `(?<name>...)` named capture | `(?:...)` non-capturing group |
| `/pattern/u` flag | `u` flag dropped (RE2 is Unicode by default) |
| Lookaheads `(?=...)` | Replaced with `\b` or explicit length constraints |

The `basicauth_url` pattern avoids `\b` on the right end because URLs may be terminated by non-word characters (`,`, `)`, whitespace) that make word-boundary anchoring unreliable. Length constraints on each segment serve as the FP guard instead.

---

## Next: S3-B (detect-secrets)

detect-secrets (Apache 2.0, Yelp) operates as a plugin-based secret scanner with a fundamentally different pattern philosophy than secretlint: rather than prefix-anchored token patterns, it emphasizes entropy scoring, high-entropy string heuristics, and private key PEM block detection. Coverage areas where detect-secrets is likely to add value beyond S3-A:

- **High-entropy string detection**: configurable Shannon entropy threshold for generic API keys with no known prefix — catches credentials from services that do not use structured token formats (e.g., random 40-char hex API keys)
- **PEM private key blocks**: `-----BEGIN RSA PRIVATE KEY-----` and variants (RSA, EC, OPENSSH) as multiline structural patterns
- **AWS credential detection**: `AKIA` / `ASIA` prefixed keys already covered on main, but detect-secrets includes session token detection (`AWS_SESSION_TOKEN`) which may be a gap
- **Basic auth in non-URL contexts**: detect-secrets includes a base64-decoded basic auth heuristic that catches `Authorization: Basic <b64>` headers in log data — complementary to `basicauth_url`
- **Generic secret assignment**: `SECRET_KEY = "..."` style patterns with entropy scoring — useful for catching secrets in configuration files without service-specific prefixes

S3-B should run detect-secrets in `--list-all-plugins` mode to enumerate its full detector set, then diff against our 79+9 patterns to find remaining gaps.
