# Pattern Source Registry

> **Purpose:** single authoritative inventory of every external source reviewed
> for credential detection patterns. Covers regex patterns (`default_patterns.json`)
> AND key-name entries (`secret_key_names.json`).
>
> **Last updated:** 2026-04-17 (S3 pattern expansion mine, research/prompt-analysis)

---

## Reviewed sources

### Mined (patterns extracted)

| # | Source | License | First mined | Last audited | Regex extracted | Keywords extracted | Provenance file |
|---|---|---|---|---|---|---|---|
| 1 | [gitleaks](https://github.com/gitleaks/gitleaks) | MIT | Sprint 10 | S3-E (2026-04-17) | 74 covered + 49 new (S3-E) | 56 new (S3-E) | `CREDENTIAL_PATTERN_SOURCES.md` + `s3e_gitleaks_completeness/` |
| 2 | [MongoDB Kingfisher](https://github.com/mongodb/kingfisher) | Apache 2.0 | Sprint 10 | S3-D (2026-04-17) | ~30 key-names | 0 new | `CREDENTIAL_PATTERN_SOURCES.md` |
| 3 | [Praetorian Nosey Parker](https://github.com/praetorian-inc/noseyparker) | Apache 2.0 | Sprint 10 | S3-D (2026-04-17) | ~10 key-names | 0 new | `CREDENTIAL_PATTERN_SOURCES.md` |
| 4 | [secretlint](https://github.com/secretlint/secretlint) | MIT | S3-A (2026-04-17) | S3-A | 9 new + 5 upgrades | 0 | `s3a_secretlint/` |
| 5 | [detect-secrets](https://github.com/Yelp/detect-secrets) | Apache 2.0 | S3-B (2026-04-17) | S3-B | 5 new + 1 upgrade | 0 | `s3b_detect_secrets/` |
| 6 | Provider documentation | N/A (factual) | S3-C (2026-04-17) | S3-C | 5 new | 0 | `s3c_provider_docs/` |
| 7 | [trivy](https://github.com/aquasecurity/trivy) | Apache 2.0 | S3-F (2026-04-17) | S3-F | 6 new | 0 | `s3f_remaining_sources/` |
| 8 | [credential-digger](https://github.com/SAP/credential-digger) | Apache 2.0 | S3-F (2026-04-17) | S3-F | 2 new | 0 | `s3f_remaining_sources/` |

### Reviewed — nothing new

| # | Source | License | Reviewed | Finding |
|---|---|---|---|---|
| 9 | [git-secrets](https://github.com/awslabs/git-secrets) | Apache 2.0 | S3-F (2026-04-17) | All AWS patterns, already covered |
| 10 | [talisman](https://github.com/thoughtworks/talisman) | MIT | S3-F (2026-04-17) | Generic keyword patterns + filename detection (out of scope for regex engine) |
| 11 | [whispers](https://github.com/Skyscanner/whispers) | Apache 2.0 | S3-F (2026-04-17) | HubSpot webhook URL only; provider keyword already in S3-E |

### Excluded (license-incompatible)

| # | Source | License | Reason | Consulted for gap identification? |
|---|---|---|---|---|
| 12 | [trufflehog](https://github.com/trufflesecurity/trufflehog) | AGPL-3.0 | Copyleft forces consumer relicense | No — per project rule, never mine patterns |
| 13 | [Semgrep Rules](https://github.com/returntocorp/semgrep-rules) | SRL v1.0 | Non-OSI, restricts redistribution | No |
| 14 | [Atlassian SAST](https://bitbucket.org/atlassian/adf-sast) | LGPL-2.1 | Copyleft linking clauses | No |

---

## Coverage totals (after S3 proposals are merged)

| Category | Before S3 | S3 proposals | After S3 |
|---|---|---|---|
| Regex patterns (`default_patterns.json`) | 79 | +76 new + 6 upgrades | ~155 |
| Key-name entries (`secret_key_names.json`) | 178 | +56 new | ~234 |
| Sources reviewed | 3 (Sprint 10) | +8 (S3) | 11 |
| Sources excluded | 3 | 0 | 3 |

## S3 proposal breakdown by stream

| Stream | Source | New regex | New keywords | Upgrades |
|---|---|---|---|---|
| S3-A | secretlint | 9 | 0 | 5 |
| S3-B | detect-secrets | 5 | 0 | 1 |
| S3-C | Provider docs | 5 | 0 | 0 |
| S3-D | Refresh (gitleaks/Kingfisher/NP) | 0 | 0 | 0 |
| S3-E | gitleaks completeness | 49 | 56 | 0 |
| S3-F | trivy + credential-digger | 8 | 0 | 0 |
| **Total** | | **76** | **56** | **6** |

## Corpus validation summary

| Stream | Corpus | Total hits | Notable |
|---|---|---|---|
| S3-A | S2 11K WildChat | 0 | — |
| S3-B | S2 11K WildChat | 3 | Telegram bot tokens (true positive) |
| S3-C | S2 11K WildChat | 0 | — |
| S3-E | S2 11K WildChat | 0 | — |
| S3-F | S2 11K WildChat | 13 | Facebook Graph tokens (true positive) |

---

## How to update this registry

When adding a new source:

1. Review the source's license — must be permissive (MIT, Apache 2.0, BSD, CC0)
2. Extract patterns, compare against current inventory
3. Write provenance file in `s3_pattern_mine/s3X_<source>/`
4. Add a row to "Reviewed sources" or "Reviewed — nothing new" in this file
5. Update coverage totals

When refreshing an existing source:

1. Compare HEAD SHA against pinned SHA in provenance file
2. Diff for new rules
3. Update "Last audited" column
