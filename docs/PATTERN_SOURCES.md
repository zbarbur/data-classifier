# Pattern Sources & Coverage Plan

> Living document. Tracks where our patterns come from, what gaps remain, and when we plan to close them.
> Last updated: 2026-04-10

## License & IP Position

All patterns in this library are **original implementations**. We did NOT copy regex strings, code, or configuration from any source. Our process:

1. **Referenced public documentation** from each service (Stripe, Slack, AWS, etc.) for their token format specifications (prefixes, lengths, character sets). Token formats are factual, not copyrightable.
2. **Referenced open-source projects** (Presidio, gitleaks, detect-secrets) as coverage benchmarks — "what entity types exist?" — not as code sources.
3. **Wrote all regex patterns, validators, and scoring logic from scratch** based on the format specifications.

| Source | License | Our Use | IP Risk |
|---|---|---|---|
| Presidio | MIT | Coverage benchmark + validator approach | None |
| gitleaks | MIT | Coverage benchmark | None |
| trufflehog | **AGPL-3.0** | Detector list reference ONLY — no code or regex copied | None (no derived work) |
| detect-secrets | Apache 2.0 | Entropy detection concept reference | None |
| Cloud DLP | Proprietary | Public API docs reference | None |
| AWS Macie | Proprietary | Public docs reference | None |

**Rule:** When adding new patterns, always write regex from the **service's own public documentation**, never copy from AGPL-licensed sources (trufflehog). MIT-licensed sources (Presidio, gitleaks) allow copying but we prefer original implementations for consistency.

## Source Inventory

### 1. Microsoft Presidio (~60 regex recognizers)
- **Repo:** https://github.com/microsoft/presidio
- **Path:** `presidio-analyzer/presidio_analyzer/predefined_recognizers/`
- **Strength:** International government IDs with checksum validators (20+ countries), per-US-state driver's license patterns
- **Weakness:** No credential/secret detection (relies on ML for that)
- **License:** MIT

**What we took (iteration 1):**
- SSN zero-group validator pattern (from `UsSsnRecognizer`)
- Luhn checksum validator (from `CreditCardRecognizer`)
- ITIN format (from `UsItinRecognizer`)
- UK NINO format (from `NhsRecognizer` family)
- Discover card format (from `CreditCardRecognizer`)

**What remains (backlog):**
- US NPI (National Provider Identifier) — Luhn validated, 10 digits
- US MBI (Medicare Beneficiary Identifier) — alphanumeric checksum
- ABA routing number — 9 digits with checksum
- Canadian SIN — Luhn validated
- Australian ABN, ACN, TFN, Medicare — each with specific checksums
- Italian fiscal code, VAT, passport, DL, ID card
- Indian PAN, Aadhaar, GSTIN, voter ID, passport
- Spanish NIF, NIE
- UK NINO (have it), UK passport, UK postcode, UK vehicle registration
- Korean RRN, BRN, DL, passport
- German tax ID, passport, ID card, SSN, health insurance
- Polish, Finnish, Swedish, Thai, Nigerian, Singaporean IDs

### 2. gitleaks (~100 rules)
- **Repo:** https://github.com/gitleaks/gitleaks
- **Path:** `config/gitleaks.toml` (all rules in one TOML file)
- **Strength:** Best-curated service-specific API key patterns. Fixed prefixes = very low false positive.
- **Weakness:** Secret detection only — no PII patterns
- **License:** MIT

**What we took (iteration 1):**
- Stripe secret key (`sk_live_`, `sk_test_`, `rk_*`)
- Stripe publishable key (`pk_live_`, `pk_test_`)
- Slack bot token (`xoxb-`)
- Slack user token (`xoxp-`)
- Slack webhook URL (`hooks.slack.com/services/`)
- SendGrid API key (`SG.`)
- Twilio API key (`SK` + 32 hex)
- Mailgun API key (`key-` + 32 hex)
- Google API key (`AIza` + 35 chars)
- OpenAI API key (`sk-proj-`)
- GitLab PAT (`glpat-`)
- Shopify access token (`shpat_`, `shpca_`, `shppa_`, `shpss_`)
- Databricks token (`dapi`)

**What remains (backlog — high value, low effort):**
- Discord bot token
- Heroku API key (context-dependent: `HEROKU_API_KEY=`)
- Cloudflare API key (context: `CF_API_KEY=`)
- npm token (`npm_` + 36 chars)
- DigitalOcean PAT (`dop_v1_` + 64 hex)
- Grafana API key (`eyJr` prefix — needs context to distinguish from JWT)
- Azure storage key (context: `AccountKey=`)
- Facebook access token (long numeric, needs context)
- Twitter bearer token (base64, needs context)
- LinkedIn client secret (no fixed prefix, needs keyword)
- Hashicorp Vault token (`hvs.`)
- Pulumi access token (`pul-`)
- Confluent API key (`CCLOUD_API_KEY=`)
- GCP service account key (`"type": "service_account"`)

### 3. trufflehog (800+ detectors)
- **Repo:** https://github.com/trufflesecurity/trufflehog
- **Path:** `pkg/detectors/` (one Go file per detector)
- **Strength:** Broadest coverage. Many detectors include live verification (actually call the service to check if key is valid).
- **Weakness:** Go-only, not directly portable. Many detectors rely on multi-line context.
- **License:** AGPL-3.0 (cannot copy code, but can reference patterns)

**What we reference (not copied — license restriction):**
- Detector list as coverage benchmark
- Pattern formats for services not in gitleaks
- Verification approach inspiration (for future: validate detected keys against APIs)

**Specific gaps trufflehog covers that we don't:**
- Alibaba Cloud keys
- Atlassian API tokens
- Bitbucket tokens
- CircleCI tokens
- Coinbase keys
- Datadog API keys
- Dropbox tokens
- Elastic Cloud keys
- Fastly API keys
- Firebase tokens
- Fly.io tokens
- Hugging Face tokens
- LaunchDarkly keys
- Linear API keys
- Netlify tokens
- New Relic keys
- PagerDuty keys
- Planetscale tokens
- Railway tokens
- Sentry auth tokens
- Supabase keys
- Terraform Cloud tokens
- Vercel tokens

### 4. detect-secrets (~15 plugins)
- **Repo:** https://github.com/Yelp/detect-secrets
- **Strength:** Entropy-based detection (Shannon entropy on hex/base64 strings). Keyword scanning. Low false positive approach.
- **Weakness:** Fewer patterns, more heuristic
- **License:** Apache 2.0

**What we reference:**
- High-entropy string detection approach (for our structured secret scanner, iteration 2)
- Keyword + entropy combination scoring (informed our confidence model)
- Artificial example patterns for their plugins

### 5. Google Cloud DLP (150+ InfoTypes)
- **Reference:** https://cloud.google.com/sensitive-data-protection/docs/infotypes-reference
- **Strength:** Broadest PII coverage, 150+ InfoTypes, context-aware. Global coverage.
- **Weakness:** Cloud API only, not local patterns. Cost per API call.

**What we reference:**
- InfoType taxonomy as our entity type naming reference
- Coverage benchmark — what should we eventually detect?
- Country-specific PII coverage targets

### 6. AWS Macie (managed data identifiers)
- **Reference:** https://docs.aws.amazon.com/macie/latest/user/mdis-reference-quick.html
- **Strength:** Cloud-specific credential detection (AWS, Azure, GCP keys). Financial data.
- **Weakness:** AWS ecosystem only. Not open source.

**What we reference:**
- Cloud credential format specifications
- Financial data patterns (bank routing numbers, SWIFT codes)

## Current Coverage: 43 Content Patterns + 15 Profile Rules

| Category | Content Patterns | Profile Rules | Total |
|---|---|---|---|
| PII | 15 | 12 | 27 |
| Financial | 6 | 3 | 9 |
| Credential | 20 | 1 | 21 |
| Health | 2 | 1 | 3 |
| **Total** | **43** | **15** (overlap) | **58 rules** |

## Gap Closure Plan

### Iteration 2 — Pattern Expansion + Quality Enhancements (target: 60+ patterns)

#### New PII Patterns

| Gap | Source | Effort | Validator | FP Risk |
|---|---|---|---|---|
| US NPI (National Provider Identifier) | Presidio/CMS spec | Small | Luhn (modified, prefix 80840) | Low |
| US DEA Number | DEA spec | Small | Check digit (weighted formula) | Low |
| US MBI (Medicare Beneficiary Identifier) | CMS spec | Small | Positional format (no S,L,O,I,B,Z) | Low |
| VIN (Vehicle Identification Number) | ISO 3779 | Small | Check digit (mod 11, position 9) | Low |
| US EIN (Employer ID Number) | IRS spec | Small | Prefix validation (campus codes) | Medium |
| Additional DOB formats | Original | Small | None | Medium |

#### New Financial Patterns

| Gap | Source | Effort | Validator | FP Risk |
|---|---|---|---|---|
| SWIFT/BIC code | ISO 9362 | Small | Structure self-validates (4+2+2+3) | Low |
| Bitcoin address (P2PKH/P2SH/Bech32) | Bitcoin wiki | Small | Prefix (1/3/bc1) + Base58 | Low |
| Ethereum address | EIP-55 | Small | 0x prefix + 40 hex | Low |
| ABA routing number + checksum | ABA spec | Small | Weighted mod-10 (3-7-1) | Medium (needs context) |
| IBAN mod-97 validator | ISO 13616 | Small | Complete existing stub | Low |

#### New Credential Patterns (small batch — bulk via secret scanner)

| Gap | Source | Effort | FP Risk |
|---|---|---|---|
| Discord bot token | gitleaks | Small | Low (fixed format) |
| npm token | gitleaks | Small | Low (`npm_` prefix) |
| Hashicorp Vault token | gitleaks | Small | Low (`hvs.` prefix) |
| Pulumi access token | gitleaks | Small | Low (`pul-` prefix) |

#### Other Patterns

| Gap | Source | Effort | Validator | FP Risk |
|---|---|---|---|---|
| Canadian SIN + Luhn | CRA spec | Small | Luhn | Low |

#### Regex Engine Quality Enhancements

| Enhancement | Inspired By | Effort | Impact |
|---|---|---|---|
| Context window confidence boosting | Presidio LemmaContextAwareEnhancer, Cloud DLP HotwordRules | Medium | Biggest FP reducer for ambiguous patterns (ABA, EIN, dates) |
| Stopword / anti-indicator suppression | gitleaks stopwords | Small | Eliminates placeholder/example FPs ("changeme", test card numbers) |
| Allowlist / FP suppression mechanism | gitleaks allowlists | Small | Per-pattern regex allowlists (value/match/line scope) |
| Phone number library integration | Presidio PhoneRecognizer (`phonenumbers`) | Medium | 170+ countries, format normalization, range validation |

### Iteration 3 — Country-Specific Phase 1 + Financial (target: 80+ patterns)

| Region/Type | Source | Patterns | Validators |
|---|---|---|---|
| UK (NHS, passport, postcode) | Presidio | 3-4 patterns | NHS mod-11 checksum |
| Germany (tax ID, passport, ID card) | Presidio | 4-5 patterns | Tax ID checksum |
| Australia (ABN, ACN, TFN, Medicare) | Presidio | 4 patterns | ABN mod-89, TFN mod-11 |
| India (PAN, Aadhaar) | Presidio | 2 patterns | Aadhaar Verhoeff checksum |
| CUSIP | Cloud DLP ref | 1 pattern | Mod-10 check digit (needs context) |
| ISIN | ISO 6166 | 1 pattern | Luhn check digit |
| EU VAT (per-country formats) | Cloud DLP ref | 5+ patterns | Country-specific check digits |

### Iteration 4+ — Broad International (target: 100+ patterns)

| Region/Type | Source | Patterns |
|---|---|---|
| Italy, Spain, Korea, Poland, Finland, Sweden, etc. | Presidio | 30+ patterns |
| Additional cloud services (50+ from trufflehog list) | gitleaks + original | 20+ patterns |
| GPS coordinates, US NDC drug codes, CPT/HCPCS | Cloud DLP/Macie | 5+ patterns (strong context required) |
| US driver's license (per-state formats) | Macie | 10+ patterns |
| Credit card track 2 data | PCI spec | 1 pattern |

## Testing & Corpus Strategy

### Iteration 2 — Build Foundation

| Deliverable | Source | License | Notes |
|---|---|---|---|
| Synthetic corpus generator (Faker) | Own | N/A | Labeled columns per entity type, adversarial near-misses |
| Accuracy benchmark harness | Own | N/A | Precision/recall/F1 per entity type, separate from CI |
| FP test corpus | Own + Nightfall | Free eval | Negative lookalikes (order#→SSN, random→API key) |
| Property-based testing (Hypothesis) | Own | N/A | Edge case generation for patterns |
| Performance benchmarks | Own | N/A | Latency regression baseline |

### Iteration 3 — External Corpus Integration

| Deliverable | Source | License | Size | Notes |
|---|---|---|---|---|
| Nemotron-PII ETL | NVIDIA | CC BY 4.0 | 100K records, 55+ types | Extract entity values from structured records |
| SecretBench + FPSecretBench | Academic | MIT + data agreement | 97K labeled + FP corpus | Gold standard for credential accuracy |
| Ai4Privacy pii-masking-300k | Ai4Privacy | **Custom non-OSI — PENDING REMOVAL Sprint 9** | 225K rows, 27+ types | License prohibits commercial use and redistribution. See `docs/process/LICENSE_AUDIT.md`. Being replaced by Gretel-EN (Apache 2.0). |
| Gretel-PII-masking-EN-v1 | gretelai (HuggingFace) | Apache 2.0 | 60K rows, 47 domains, 43+ entity types | Sprint 9 ingest (2026-04-13, data_classifier ≥ v0.9.0). Mixed-label corpus (credentials + PII + financial + health co-occur in single documents) to break credential-pure-corpus bias in the meta-classifier. `entities` field is a Python repr (single quotes) — parse via `ast.literal_eval`, never `json.loads`. Path-(d) type map covers 16 raw labels → 12 data_classifier classes at ~71% sample coverage; dropped labels deferred to Sprint 10 taxonomy expansion. Source: https://huggingface.co/datasets/gretelai/gretel-pii-masking-en-v1 |
| StarPII | BigCode | Gated access | 20K secrets in code | Credential testing in code context |
| Nightfall expanded | Nightfall AI | Free eval | Small curated | CSV samples + negative lookalikes |
| Presidio cross-validation | Microsoft | MIT | Generated | Run same inputs through Presidio + us, compare |

## Pattern Quality Standards

Every pattern added to `default_patterns.json` must have:

1. **RE2 compatibility verified** — no lookahead, lookbehind, or backreferences
2. **Validator** where applicable (Luhn, checksum, format check)
3. **examples_match** — at least 2 positive examples (XOR-encoded for credentials)
4. **examples_no_match** — at least 2 negative examples (common false positives)
5. **Confidence calibrated** — based on false positive risk:
   - 0.95-0.99: Fixed prefix, unique format (e.g., `AKIA`, `ghp_`, `SG.`)
   - 0.80-0.95: Well-defined format with some FP risk (e.g., SSN, IBAN)
   - 0.50-0.80: Ambiguous format, needs context (e.g., 9-digit number, dates)
   - <0.50: High FP risk, context-dependent (e.g., passport numbers)
6. **Sourced and documented** — which reference source the pattern came from

## Competitive Position

| Capability | Presidio | Cloud DLP | gitleaks | trufflehog | **Us (iter 1)** | **Us (iter 2 target)** |
|---|---|---|---|---|---|---|
| PII regex patterns | ~20 | 150+ | 0 | 0 | **15** | **21** (+NPI, DEA, MBI, VIN, EIN, DOB) |
| Financial patterns | 3 | 20+ | 0 | 0 | **6** | **11** (+SWIFT, BTC, ETH, ABA, IBAN done) |
| Credential patterns | 0 | 50+ | ~100 | 800+ | **20** | **24** (+Discord, npm, Vault, Pulumi) |
| Health patterns | 3 | 10+ | 0 | 0 | **2** | **5** (+NPI, DEA, MBI) |
| Country IDs | ~40 | 30+ | 0 | 0 | **2** (ITIN, NINO) | **3** (+Canadian SIN) |
| Checksum validators | ~15 | built-in | 0 | ~50 | **4** | **10** (+DEA, VIN, ABA, EIN, IBAN, NPI) |
| Context window boosting | Yes (Lemma) | Yes (Hotword) | No | No | **No** | **Yes** |
| Entropy gating | No | No | Yes | Yes | **No** | **Yes** (secret scanner) |
| Stopword suppression | No | No | Yes | No | **No** | **Yes** |
| Allowlist/FP suppression | No | Exclusion rules | Yes | No | **No** | **Yes** |
| Phone library (phonenumbers) | Yes | N/A | N/A | N/A | **No** | **Yes** |
| RE2 set matching | No (Python re) | N/A | N/A | N/A | **Yes** | **Yes** |
| Sample-based confidence | No | N/A | N/A | N/A | **Yes** | **Yes** |
| Category filtering | No | InfoType groups | No | Detector types | **Yes** | **Yes** |
| Accuracy benchmarks | Presidio-research | N/A | N/A | N/A | **No** | **Yes** (Faker + FP corpus) |

Our differentiators: RE2 two-phase matching, sample-based confidence + prevalence, category dimension, connector-agnostic design, structured secret scanner (key-name + entropy), context boosting + FP suppression suite. Our gap: country-specific ID coverage (Presidio leads), total credential breadth (trufflehog leads).
