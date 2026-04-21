# S3G Provider Keywords — Gap Analysis

**Date:** 2026-04-16
**Session:** S3-G research (prompt-analysis branch)

---

## Summary

- **42 keyword entries** proposed (30 base providers + 12 compound/alias variants)
- **5 prefixed regex patterns** proposed
- **25 providers** are keyword-only (no distinctive prefix found or prefix already covered)
- **Source:** Provider official documentation and common industry knowledge. Providers identified via coverage-comparison exercise; all content sourced independently.

---

## 30 Base Providers Added

| Provider | Score | Tier | Notes |
|---|---|---|---|
| amplitude | 0.70 | strong | Analytics platform |
| braintree | 0.70 | strong | PayPal payment gateway |
| bugsnag | 0.70 | strong | Error monitoring |
| clickup | 0.65 | contextual | Project management |
| deepseek | 0.70 | strong | AI platform |
| elevenlabs | 0.70 | strong | AI voice platform |
| gemini | 0.70 | strong | Google AI platform |
| grok | 0.65 | contextual | word_boundary — ambiguous word |
| klaviyo | 0.70 | strong | Email/SMS marketing |
| langfuse | 0.70 | strong | LLM observability |
| langsmith | 0.70 | strong | LangChain tracing |
| mixpanel | 0.70 | strong | Product analytics |
| monday | 0.65 | contextual | word_boundary — ambiguous word |
| mongodb | 0.70 | strong | Document database |
| nexmo | 0.70 | strong | Legacy Vonage alias |
| nvidia | 0.70 | strong | AI/NGC API |
| opsgenie | 0.70 | strong | Alerting platform |
| postgresql | 0.70 | strong | Relational database |
| posthog | 0.70 | strong | Product analytics |
| razorpay | 0.70 | strong | Payment gateway (India) |
| replicate | 0.70 | strong | AI model hosting |
| ringcentral | 0.70 | strong | Communications platform |
| salesforce | 0.70 | strong | CRM platform |
| segment | 0.65 | contextual | word_boundary — ambiguous word |
| snowflake | 0.70 | strong | Data cloud platform |
| telnyx | 0.70 | strong | Communications API |
| vonage | 0.70 | strong | Communications API |
| wandb | 0.70 | strong | ML experiment tracking |
| weightsandbiases | 0.70 | strong | W&B full name slug |
| xai | 0.65 | contextual | word_boundary — short/ambiguous |

## 12 Compound / Alias Variants Added

| Pattern | Score | Rationale |
|---|---|---|
| mongo_password | 0.85 | MongoDB credential compound |
| mongo_uri | 0.80 | MongoDB URI key name |
| postgres_uri | 0.80 | PostgreSQL URI key name |
| pg_password | 0.85 | Official PostgreSQL env var prefix (libpq-envars) |
| snowflake_password | 0.85 | Snowflake credential compound |
| snowflake_account | 0.75 | Snowflake account identifier |
| sfdc | 0.70 | Standard Salesforce abbreviation (ticker symbol) |
| weights_and_biases | 0.70 | W&B underscore env var form |

---

## Prefixed Regex Patterns Added (5)

### Providers WITH distinctive prefixes — patterns added

| Provider | Prefix | Pattern Name | Source |
|---|---|---|---|
| Replicate | `r8_` | `replicate_api_key` | replicate.com/docs/reference/http#authentication |
| xAI / Grok | `xai-` | `xai_api_key` | docs.x.ai/api |
| Langfuse | `pk-lf-` | `langfuse_public_key` | langfuse.com/docs/sdk |
| Langfuse | `sk-lf-` | `langfuse_secret_key` | langfuse.com/docs/sdk |
| PostHog | `ph[cx]_` | `posthog_api_key` | posthog.com/docs/api |

---

## Providers WITHOUT distinctive prefixes — keyword-only

| Provider | Reason | Already Covered By |
|---|---|---|
| DeepSeek | Uses `sk-` prefix identical to OpenAI | `openai_legacy_key` pattern |
| MongoDB (conn string) | `mongodb://` already matched | `connection_string` pattern |
| PostgreSQL (conn string) | `postgres://`, `postgresql://` already matched | `connection_string` pattern |
| Snowflake (conn string) | Snowflake JDBC URIs use hostname structure, not simple prefix; keyword entries sufficient | keyword entries |
| Weights & Biases | Cloud tokens are opaque 40-char strings; `local-` prefix only for local installs | keyword entries |
| ElevenLabs | `sk_` prefix suspected but not confirmed stable in official docs | keyword entries |
| Segment | Opaque 40-char write keys, no prefix | keyword entries |
| Salesforce | OAuth tokens are opaque bearer tokens | keyword entries |
| LangSmith | `ls__api_` prefix not confirmed as stable across SDK versions | keyword entries |
| Mixpanel | Opaque alphanumeric, no prefix | keyword entries |
| Klaviyo | `pk_` prefix changed across API versions | keyword entries |
| NVIDIA | Opaque NGC keys, no prefix | keyword entries |
| Braintree | Opaque merchant keys, no prefix | keyword entries |
| Razorpay | `rzp_live_`/`rzp_test_` prefixes are distinctive but India-market niche; consider Sprint 13 | keyword entries |
| RingCentral | OAuth 2.0 opaque bearer tokens | keyword entries |
| OpsGenie | UUID-format keys; `uuid` pattern already exists | `uuid` pattern |
| ClickUp | `pk_` prefix not consistently documented | keyword entries |
| Amplitude | Opaque hex strings, no prefix | keyword entries |
| Bugsnag | 32-char hex, no prefix | keyword entries |
| monday.com | JWT-format tokens; JWT pattern already exists | JWT pattern |
| Telnyx | KEY prefix not consistently documented | keyword entries |
| Vonage/Nexmo | ~8-char opaque alphanumeric key+secret pair | keyword entries |

---

## Source Attribution

All entries in this session are sourced from:

1. **Provider official documentation** — for prefixed format regexes (Replicate, xAI, Langfuse, PostHog)
2. **Common industry knowledge** — for provider name keywords; provider names are factual identifiers, not copyrightable

**Coverage-comparison method:** Provider names identified through a coverage gap analysis comparing known open-source scanner coverage (trufflehog, gitleaks, secretlint) against our current `secret_key_names.json`. The gap list was used only as a checklist of provider names. All content — keyword strings and regex patterns — was sourced independently from official provider documentation. No code, regex, or test data was copied from any external scanner.

---

## Potential Sprint 13 Follow-ups

1. **Razorpay** — add `rzp_live_[A-Za-z0-9]{14}` and `rzp_test_[A-Za-z0-9]{14}` patterns after corpus validation
2. **ElevenLabs** — confirm `xi_` or `sk_[a-f0-9]{32}` format from official docs; add if stable
3. **Klaviyo** — verify stable prefix format across current API version
4. **LangSmith** — confirm `ls__api_` prefix stability across SDK versions
5. **Snowflake JDBC** — evaluate `[a-z0-9-]+\.snowflakecomputing\.com` hostname pattern if column-name detection proves insufficient
6. **PostHog phc_ confidence** — phc_ is a frontend-embeddable project key (by design); consider splitting confidence (phc_: 0.75, phx_: 0.95)
