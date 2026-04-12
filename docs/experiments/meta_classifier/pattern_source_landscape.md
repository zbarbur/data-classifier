# Credential Pattern Source Landscape Survey

> **Produced by:** research agent dispatched 2026-04-13
> **Purpose:** Reference document for Sprint 8 Item B (bulk import of
> credential patterns). Enumerates license-compatible sources for
> the data_classifier pattern library.
> **Source of truth:** This file is authoritative for "what
> pattern libraries exist and can we use them?" Do not re-survey
> — update this file instead.

## Executive summary

**The single highest-value addition beyond gitleaks is MongoDB
Kingfisher** (Apache 2.0, 800+ YAML rules, released 2025). It
covers the SaaS / observability / ITSM / developer-tool ecosystem
that gitleaks misses, and it is license-compatible with our MIT
library for direct port with attribution.

Expected total yield for Sprint 8 Item B, using all license-compatible
sources with deduplication:

| Source | License | Raw patterns | Expected net-new after dedup |
|---|---|---|---|
| MongoDB Kingfisher | Apache 2.0 | ~800 | **400-500** |
| gitleaks | MIT | ~100 | **80-90** |
| Praetorian Nosey Parker | Apache 2.0 | 188 | **20-30** |
| detect-secrets | Apache 2.0 | ~30 | **10-15** |
| LeakTK patterns | MIT | ~100 | **10-15** |
| ripsecrets | MIT | ~40 | **5-10** |
| **Total projected** | | | **525-660** |

This is substantially larger than the original Sprint 8 Item B
estimate (100-200 patterns) and justifies bumping the complexity
from M (1-2 days) to **L (3-5 days)**.

## Tier 1 — Direct-port eligible sources (primary harvest)

### 1. MongoDB Kingfisher (PRIMARY)

- **URL:** https://github.com/mongodb/kingfisher
- **License:** Apache 2.0 (verified via LICENSE file)
- **Release:** 2025 (actively maintained)
- **Stars:** ~894
- **Format:** YAML rule files
- **Pattern count:** 800+
- **Port approach:** Direct copy + attribution in pattern metadata

**Unique coverage relative to gitleaks** (services that gitleaks
does NOT have dedicated rules for):

- **Observability:** Datadog, New Relic, Sentry, Dynatrace,
  Honeycomb, Sumo Logic, Grafana Cloud, Lightstep
- **ITSM / alerting:** PagerDuty, OpsGenie, Zendesk, Intercom,
  Jira, Confluence, Asana, Linear, Monday, ServiceNow
- **SaaS / productivity:** 1Password, LaunchDarkly, SonarCloud,
  JFrog, Salesforce, HubSpot, Shopify
- **Auth / identity:** Auth0, Okta, Clerk
- **Developer tooling:** Doppler, Vercel, Twitch, Mapbox
- **Edge / CDN:** Cloudflare

**Why it's the primary source:** modern curation, active
maintenance (2025 commits), covers the gaps our existing stack
has, Apache 2.0 is fully compatible with MIT for direct port
with attribution.

**Attribution requirements (Apache 2.0):**
- Include Apache 2.0 license text in distribution
- Include NOTICE file if present
- Preserve copyright notices
- Document modifications

**Sprint 8 Item B action:** Set Kingfisher as source 1 in the
ingestion script. Parse YAML format, convert to our pattern
JSON schema, attribute each pattern to Kingfisher in its metadata.

### 2. gitleaks (ALREADY KNOWN)

- **URL:** https://github.com/gitleaks/gitleaks/blob/master/config/gitleaks.toml
- **License:** MIT
- **Pattern count:** ~100
- **Format:** TOML
- **Port approach:** Direct copy + attribution

**Overlap with Kingfisher:** moderate. Kingfisher likely includes
gitleaks-style patterns for the major services (AWS, GitHub, Slack,
Stripe, OpenAI). Expected ~20-30% overlap. The Sprint 8 ingestion
script must deduplicate — when two sources provide a pattern for
the same service, pick the one with:
1. Tighter regex (less false positive surface)
2. More specific prefix anchoring
3. Better attribution traceability

**Why keep it:** gitleaks is the incumbent reference in the secret
scanning community. Some of its rules are battle-tested against
production false positive reports for years. Use it as a validation
baseline.

### 3. Praetorian Nosey Parker (PRECISION CURATION)

- **URL:** https://github.com/praetorian-inc/noseyparker
- **License:** Apache 2.0 (verified)
- **Pattern count:** 188
- **Format:** YAML
- **Port approach:** Direct copy + attribution

**Why it matters:** Nosey Parker is the "curated for low false
positive" alternative. Its rule set is smaller than Kingfisher or
gitleaks but each rule has been selected by security engineers
specifically to minimize FPR in production use. Use it as a
**second-opinion filter**: if a pattern exists in Kingfisher AND
Nosey Parker, confidence is higher. If a pattern exists only in
Kingfisher, flag it for manual review before import.

### 4. detect-secrets (ALREADY KNOWN)

- **URL:** https://github.com/Yelp/detect-secrets/tree/master/detect_secrets/plugins
- **License:** Apache 2.0
- **Pattern count:** ~30
- **Format:** Python code with embedded regex
- **Port approach:** Extract regex from Python source, attribute

**Overlap with Kingfisher:** expected high (both cover major
services). Net-new yield after Kingfisher + gitleaks probably
10-15 patterns.

### 5. LeakTK patterns (Red Hat)

- **URL:** https://github.com/leaktk/patterns
- **License:** MIT (verified)
- **Pattern count:** ~100 across multiple tool-version folders
- **Format:** TOML (gitleaks format)
- **Port approach:** Direct copy + attribution
- **Maintenance:** Active, 602 commits

**Why consider it:** Red Hat's modern curation on top of
gitleaks 7.6 and 8.27 baselines. Some original detections
beyond the gitleaks upstream. Low net-new yield (10-15) but
Red Hat-quality curation is a strong reliability signal.

### 6. ripsecrets (SANITY BASELINE)

- **URL:** https://github.com/sirwart/ripsecrets
- **License:** MIT (verified)
- **Pattern count:** ~40
- **Format:** Rust code with regex
- **Port approach:** Extract regex, attribute

**Why consider it:** Very small, near-zero false positive
curation. Use as a sanity baseline — every pattern ripsecrets
has should also be in our library. If ripsecrets catches
something we miss, that's a high-confidence gap.

## Tier 2 — Inspiration-only sources (re-derive from public docs)

These sources have licenses that prevent direct copy but provide
signal about which services have well-defined token formats.

### GitHub Secret Scanning Partner List (HIGHEST SIGNAL)

- **URL:** https://docs.github.com/en/code-security/secret-scanning/introduction/supported-secret-scanning-patterns
- **License:** CC-BY-4.0 (for docs)
- **Coverage:** 200+ partner services with published token formats
- **Recent activity:** 24 new types added November 2025
- **How to use:** Each partner entry links to that partner's own
  security documentation page. Re-derive the regex from the
  vendor's own docs (which are typically public and unlicensed
  or under the vendor's own terms). Attribution goes to the
  vendor, not to GitHub.

**Why it's the canonical reference:** This is the single
authoritative list of "services that have regex-detectable token
formats." GitHub updates it as partners onboard. Even services
that exist in Kingfisher or gitleaks can benefit from
cross-checking against the vendor's own published format in
their GitHub partner docs.

**Sprint 8 Item B action:** Before calling the harvest complete,
cross-check the imported pattern list against the GitHub partner
list. Flag services the partner list has but our imports don't.
Those are the highest-priority targets for custom re-derivation.

### trufflehog (AGPL — LIST ONLY)

- **URL:** https://github.com/trufflesecurity/trufflehog
- **License:** **AGPL-3.0 — source code CANNOT be copied**
- **Coverage:** 800+ detectors (name-wise, ~800 services)
- **Usage:** Use the DETECTOR LIST (file names in `pkg/detectors/`)
  as a gap-identification tool. For each detector trufflehog has
  that our harvest doesn't cover, find the corresponding
  vendor's public documentation and re-derive the pattern there.
- **Do NOT:** read trufflehog's detector source code, copy their
  regex, or port their verification logic. Any pattern we ship
  must be derivable from a non-AGPL source.

### Semgrep secrets rules (LICENSE RISK)

- **URL:** https://github.com/semgrep/semgrep-rules
- **License:** Semgrep Rules License v1.0 (non-OSI, restrictive)
- **Usage:** Legal review required before any copy. Treat as
  inspiration only.

### Atlassian SAST ruleset (LGPL)

- **URL:** https://github.com/atlassian-labs/atlassian-sast-ruleset
- **License:** LGPL-2.1 — incompatible for static copy into MIT
- **Usage:** Re-derive Atlassian / Jira / Confluence / Bitbucket
  token formats from Atlassian's own dev docs. Atlassian's docs
  are under their own terms, not LGPL. Attribution goes to
  Atlassian, not to the SAST ruleset repo.

## Tier 3 — Cloud vendor and SIEM catalogs (NONE WORTH PURSUING)

- **AWS, GCP, Azure** do NOT publish centralized regex catalogs.
  Token formats are embedded in per-service documentation pages
  only. Re-derivation is possible but page-by-page — no bulk
  catalog exists.
- **Datadog** publishes its Sensitive Data Scanner rules inside
  the product UI. Not downloadable, not open source.
- **Splunk, New Relic, Sumo Logic** do NOT publish public
  credential regex libraries. New Relic's Rusty-Hog exists but
  derives from trufflehog and is dormant.

**Conclusion:** No cloud vendor or SIEM offers a usable source.
Cloud-vendor patterns for AWS/GCP/Azure credentials are already in
Kingfisher and gitleaks.

## Tier 4 — Dead / unmaintained (AVOID)

- **shhgit** — MIT but author-declared unmaintained (archived notice)
- **Rusty-Hog** (New Relic) — trufflehog-derived, no updates since 2022

## Tier 5 — Risky / needs filtering (DEFER)

### mazen160/secrets-patterns-db

- **URL:** https://github.com/mazen160/secrets-patterns-db
- **License:** CC-BY-4.0 for main content, **AGPL for
  trufflehog-derived subset**
- **Pattern count:** 1,600+
- **Risk:** The repository mixes CC-BY-4.0 original content with
  AGPL-derived trufflehog rules. Using it requires per-rule
  provenance filtering to exclude the AGPL subset. The repository
  does not clearly label which rules come from which source.
- **Last meaningful commit:** October 2023 — borderline maintenance

**Sprint 8 decision:** **Skip for now.** Kingfisher covers most
of what this repo would add, without the license-mixing risk.
Reconsider only if Sprint 8's Kingfisher harvest leaves specific
unmet needs AND if someone volunteers to write a provenance
filter.

## Notable gaps in the landscape

Even after harvesting all Tier 1 sources, these credential
categories remain under-covered across the entire ecosystem:

1. **Financial / payments APIs** — Plaid, Alpaca, Coinbase Pro
   signing keys, Wise API tokens, Revolut business API keys,
   Modern Treasury tokens. Sparse in every source.

2. **Infrastructure tokens** — HashiCorp Vault (partial),
   Consul ACL tokens, Nomad tokens, etcd bootstrap tokens.
   Kingfisher has Vault but the rest are thin.

3. **Regional cloud providers** — Alibaba Cloud, Tencent Cloud,
   Yandex Cloud, OVH, Scaleway, Hetzner. Gitleaks has some
   Alibaba coverage; everything else is shallow.

4. **LLM / AI provider keys beyond OpenAI** — Anthropic, Cohere,
   Mistral, Together, Groq, Replicate, HuggingFace tokens.
   Kingfisher leads here but coverage is still incomplete, and
   this category is exploding in 2025-2026. **This will be a
   bigger gap in 6 months than it is today.**

5. **Observability stack** — Grafana Cloud, Honeycomb, Lightstep,
   Chronosphere. Kingfisher covers some, others have nothing.

6. **Enterprise SSO beyond Okta/Auth0** — Ping, OneLogin,
   JumpCloud, ForgeRock. No source has good coverage.

7. **Academic / NIST / OWASP catalogs** — **These do not exist.**
   OWASP Cheat Sheets describe secret-management practices but
   not pattern libraries. NIST publishes guidance but no regex
   catalogs.

## Sprint 9+ follow-up recommendation

After Sprint 8 Item B ships (bulk import from Tier 1 sources),
the natural next step is a **Sprint 9 "custom credential patterns
for gap coverage"** item that writes patterns for the gap
categories above. Each gap category could be its own mini-sprint
item:

- Sprint 9a: Financial/payments credentials (~10 services)
- Sprint 9b: LLM/AI provider keys (~10 services)
- Sprint 9c: Infrastructure tokens (~8 services)
- Sprint 9d: Regional cloud providers (~6 regional clouds)
- Sprint 9e: Enterprise SSO (~5 services)

Each sub-item follows the same pattern: identify services in
the gap, read each vendor's token format documentation, write
regex + positive/negative fixtures + attribution, ship.

**These are genuinely custom work** because no public pattern
catalog covers them. They cannot be mechanized via ingestion
script. But they are BQ-relevant — a real production BQ schema
could contain any of these token columns.

## Report metadata

- **Agent:** general-purpose research subagent
- **Completed:** 2026-04-13
- **Sources verified:** all Tier 1 licenses confirmed via
  LICENSE file fetch, not README claims
- **Token usage:** ~48,400 total tokens for the survey
- **Methodology:** Web search for secret/credential pattern
  libraries, fetch each repository's LICENSE file and main
  README, cross-reference coverage claims with actual rule
  files where accessible, filter out dead/unmaintained
  projects, note license incompatibilities.
