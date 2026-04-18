# S3-C Provider Documentation Gap Analysis

**Date:** 2026-04-16
**Researcher:** S3-C research session
**Branch:** research/prompt-analysis

## Summary

13 providers were researched against official documentation. 5 net-new patterns proposed.
All existing S3-A/S3-B proposals and main-branch patterns were checked to avoid duplication.

---

## Provider-by-Provider Decisions

### Proposed (5 patterns)

| Provider | Pattern Name | Prefix | Decision |
|---|---|---|---|
| Okta | `okta_api_token` | `00` + 42 chars | PROPOSED with `requires_column_hint=true` — prefix is weak but length + column context makes it viable |
| Postman | `postman_api_key` | `PMAK-` | PROPOSED — highly distinctive prefix, officially documented |
| Airtable | `airtable_pat` | `pat` + 14 chars + `.` | PROPOSED — dot separator makes it structurally unique; deprecated legacy key was random 17-char with no prefix |
| Heroku | `heroku_api_key` | `HRKU-` | PROPOSED — Heroku Dev Center explicitly documents this prefix as of April 2025; new format only |
| Render | `render_api_key` | `rnd_` | PROPOSED — confirmed across official Render API docs and blog |

### Skipped — No Distinctive Prefix

| Provider | Reason |
|---|---|
| **Twitch** | OAuth tokens are standard opaque bearer tokens with no documented prefix. Format is not publicly specified. Covered by `generic_api_key` + entropy heuristic. |
| **Atlassian (Jira/Confluence)** | Cloud API tokens are random 24-char base64 strings with no prefix. Data Center PATs use `ATATTxx` or similar but the format is not officially specified in public docs. No reliable low-FP regex possible. |
| **Datadog** | API keys are 32-char hex strings (no prefix). App keys are 40-char hex strings (no prefix). Both documented as random hex — covered by entropy-based `generic_api_key`. |
| **PagerDuty** | REST API keys are 20-char random alphanumeric strings (example: `y_NbAkKc66ryYTWUXYEu`). The `y_` seen in examples is NOT a fixed prefix — it's part of the random body. No official prefix documented. Events API keys are 32-char random strings. |
| **CircleCI** | Personal API tokens are 40-char hex strings with no documented prefix. Project tokens are also random alphanumeric. No reliable prefix-based pattern. |
| **Travis CI** | API tokens are opaque random strings with no prefix. No format documentation found. |
| **Auth0** | Management API tokens are standard JWTs (ey... prefix) — already covered by `jwt_token` on main. |

### Existing Coverage — Already Handled

| Provider | Pattern(s) Already on Main | Notes |
|---|---|---|
| **DigitalOcean** | `digitalocean_pat` (`dop_v1_[hex]{64}`) + `digitalocean_oauth_token` (`doo_v1_[hex]{64}`) | Verified: existing patterns match current DO format exactly. No gap. |
| **Linear** | `linear_api_key` (`lin_api_[alnum]{40,}`) | Also proposed in S3-A as `linear_api_token` — both are covered. The S3-A proposal is a duplicate; recommend dropping it at wrap stage. |

---

## FP Risk Notes

- **Okta `00` prefix:** Weakest prefix of the set. `requires_column_hint=true` is mandatory. Without column context this would FP on anything starting with `00` + 40 chars. The restriction to token/api_key/okta column names makes it safe.
- **Airtable `pat` prefix:** The `pat` string alone would collide with many English words (patch, patient, pattern) but the structural constraint `pat[14 alphanum].[32+ alphanum]` is highly specific due to the dot separator and exact 14-char ID segment. Low FP risk.
- **All PMAK- / HRKU- / rnd_:** These prefixes do not appear in natural language and are highly distinctive. Very low FP risk.

---

## Corpus Validation

Zero hits across all 5 patterns on the 11K WildChat S2 corpus. This is expected — the corpus is chat prompts, not leaked credential stores. The patterns' value is in structured data columns (e.g., API key fields in databases), not free-text chat.
