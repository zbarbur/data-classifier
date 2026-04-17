# S3 — Pattern Expansion Mine (SPEC)

**Stage**: S3 from `docs/experiments/prompt_analysis/queue.md` §"Secret detection track"
**Date**: 2026-04-17
**Branch**: `research/prompt-analysis`
**Status**: spec — pending implementation
**Effort**: ~5-7 days total (across 4 source streams)
**Driver**: Expand credential pattern coverage for both consumers
(BQ-connector + browser extension). S0 showed 9/10 real credentials were
caught by secret_scanner heuristic, not regex patterns — the pattern set
has gaps.

---

## Goal

Mine 4 open-source/public sources for credential detection patterns we
don't have, validate against real-world corpus data, and produce a single
PR to `main` with all net-new patterns + quality upgrades.

**Two PRs to main (separate, independent):**

1. **DVC infrastructure PR** (ready now, independent of S3):
   - `.dvc/config`, `.dvcignore`, `data/wildchat_1m.dvc`
   - `data_classifier/datasets.py` (load_local_or_remote helper)
   - `docs/process/dataset_management.md` (runbook)

2. **S3 pattern expansion PR** (after all 4 streams complete):
   - New patterns in `default_patterns.json`
   - Upgraded existing patterns
   - `CREDENTIAL_PATTERN_SOURCES.md` updates with provenance
   - Tests for all new/upgraded patterns
   - Family benchmark run

---

## Source streams

| Stream | Source | License | Type | Est. effort |
|---|---|---|---|---|
| **S3-A** | secretlint | MIT | New mine | 1 day |
| **S3-B** | detect-secrets | Apache 2.0 | New mine | 1 day |
| **S3-C** | Provider docs + RFCs | N/A (factual) | Manual research | 1-2 days |
| **S3-D** | gitleaks / Kingfisher / Nosey Parker refresh | MIT / Apache 2.0 | Diff vs Sprint 10 | 1 day |

Streams are independent and can be done across sessions. Each produces
a per-source gap analysis memo + proposed patterns. The final PR batches
all proposals.

**Excluded sources** (per project rule):
- trufflehog (AGPL-3.0) — forces consumer relicense
- Semgrep Rules (SRL v1.0) — restrictive
- Atlassian SAST (LGPL-2.1) — copyleft

---

## S3-A: Secretlint mine (this session)

### Source

- **Repo**: github.com/secretlint/secretlint (MIT)
- **Structure**: TypeScript monorepo, rules at `packages/@secretlint/secretlint-rule-<name>/src/index.ts`
- **Rule count**: 27 rule packages (15 in recommended preset + 12 opt-in)

### Already covered by us (16 services)

AWS, GitHub, GitLab, Slack, SendGrid, Shopify, OpenAI, Private key PEM,
JWT, Connection string, Discord bot, NPM, HashiCorp Vault, Databricks,
HuggingFace, Vercel.

### Sprint 13 already shipped

- OpenAI legacy `sk-*` pattern (S0 gap)
- Anthropic `sk-ant-api0\d-` pattern (S0 gap)

These are excluded from S3-A proposals.

### Net-new patterns to propose (9 services)

| # | Service | Prefix/Format | Priority | Rationale |
|---|---|---|---|---|
| 1 | Grafana | `glc_`, `glsa_` | High | Popular observability platform |
| 2 | Azure AD | client_secret (context-keyed) | High | Major cloud provider |
| 3 | Basic auth in URLs | `http://user:pass@host` | High | Generic, common pattern |
| 4 | Docker Hub PAT | `dckr_pat_` | Medium | Container ecosystem |
| 5 | Linear API | `lin_api_` | Medium | Dev tool, growing |
| 6 | Groq API | `gsk_` | Medium | LLM provider, growing |
| 7 | 1Password service | `ops_ey...` | Medium | Password manager |
| 8 | Notion integration | `ntn_` | Low | Productivity tool |
| 9 | Figma PAT | `figd_` | Low | Design tool |

### Quality upgrades to existing patterns (5 candidates)

| # | Pattern | Gap | Secretlint reference |
|---|---|---|---|
| 1 | `github_token` | Missing fine-grained PATs (`github_pat_` 82-char) | secretlint-rule-github |
| 2 | `slack_bot_token` / `slack_user_token` | Missing `xapp`, `xoxa`, `xoxr` prefixes | secretlint-rule-slack |
| 3 | `openai_api_key` | Verify Sprint 13 covers new format with `T3BlbkFJ` magic | secretlint-rule-openai |
| 4 | `hashicorp_vault_token` | Secretlint has 3 subtypes (hvs/hvb/hvr) — verify coverage | secretlint-rule-hashicorp-vault |
| 5 | `huggingface_token` | Secretlint says alpha-only, 34 chars — verify our regex | secretlint-rule-huggingface |

### RE2 translation notes

Secretlint uses JS-native patterns with features that need translation
for our RE2-compatible regex set:

| Secretlint feature | RE2 translation |
|---|---|
| `(?<!\p{L})` (Unicode lookbehind) | `\b` or `(?:^\|[^a-zA-Z])` |
| `(?![A-Za-z0-9])` (lookahead) | RE2 does NOT support lookahead — use length/boundary constraints or post-match validator |
| `/u` flag (Unicode) | Drop — RE2 handles Unicode natively |
| Named capture groups `(?<name>...)` | Convert to non-capturing `(?:...)` |
| Post-match validation (length, Base64, JSON) | Map to our validator framework |

### Per-pattern process

For each proposed pattern:

1. **Extract** secretlint's regex from TypeScript source
2. **Translate** to RE2-compatible syntax
3. **Determine entity_type** — map to our taxonomy (API_KEY, OPAQUE_SECRET, etc.)
4. **Set confidence** — based on pattern specificity (prefixed tokens = 0.95, context-keyed = 0.80)
5. **Identify validator** — map secretlint's post-match checks to our validator framework, or note "needs new validator"
6. **Write test examples** — match + no-match, from secretlint's test suite
7. **Record provenance** — secretlint rule name, commit SHA, MIT license, date pulled
8. **Corpus validation** — run against S2 11K corpus, count hits, estimate FP rate

### Output artifacts (in `s3_pattern_mine/s3a_secretlint/`)

| File | Purpose |
|---|---|
| `s3a_gap_analysis.md` | Per-pattern analysis memo with decisions |
| `s3a_proposed_patterns.json` | New patterns in `default_patterns.json` schema |
| `s3a_proposed_upgrades.json` | Diffs to existing patterns |
| `s3a_provenance.json` | Per-pattern provenance records |
| `s3a_corpus_validation.json` | Hits against S2 corpus (FP estimate) |

---

## S3-B, S3-C, S3-D (future sessions)

Same per-source structure. Each produces its own sub-directory and
artifacts. Spec details written when each stream starts.

### S3-B: detect-secrets (Apache 2.0)

- **Repo**: github.com/Yelp/detect-secrets
- **Structure**: Python, plugins at `detect_secrets/plugins/`
- **Focus**: patterns not covered by secretlint or our existing set

### S3-C: Provider documentation + RFCs

- **Sources**: official key-format docs from AWS, GCP, Azure, OpenAI,
  Anthropic, Stripe, Twilio, etc. + JWT RFC 7519, OAuth RFC 6749
- **Focus**: format specs that are factual (no license concern), especially
  providers where our regex is loose/imprecise
- **No code mining** — pure documentation research

### S3-D: Refresh existing mines

- **Sources**: gitleaks, Kingfisher, Nosey Parker at HEAD
- **Sprint 10 pins**: gitleaks `8863af47`, Kingfisher `be0ce3ba`, Nosey Parker `2e6e7f36`
- **Focus**: net-new rules added since Sprint 10 (diff SHA pins vs HEAD)

---

## Final PR structure

After all 4 streams complete, one PR to `main`:

```
sprint14/s3-pattern-expansion
├── data_classifier/patterns/default_patterns.json    (modified)
├── docs/process/CREDENTIAL_PATTERN_SOURCES.md        (modified — new provenance rows)
├── tests/test_new_credential_patterns.py             (new — per-pattern test fixtures)
└── family benchmark run attached to PR description
```

### PR acceptance criteria

- [ ] All new patterns compile in RE2 (`ruff check` passes)
- [ ] All new patterns have match + no-match test examples
- [ ] All new patterns have provenance in CREDENTIAL_PATTERN_SOURCES.md
- [ ] Family benchmark does not regress (cross_family_rate ≤ Sprint 13 baseline)
- [ ] Corpus validation shows <5% estimated FP rate per pattern
- [ ] Lint + format clean, full test suite green

---

## Decisions made during brainstorm (2026-04-17)

| Decision | Choice | Rationale |
|---|---|---|
| Scope | Net-new patterns + quality upgrades (option b) | Maximizes coverage in one pass |
| Output format | Research analysis + ready-to-merge JSON (option a) | Sprint team can review per-pattern |
| Promotion path | Single PR to main after all sources (option a) | One review, one benchmark |
| DVC infrastructure | Separate PR (independent, ready now) | Don't hold infra hostage to pattern mine |
| Excluded sources | trufflehog (AGPL), Semgrep (SRL), Atlassian (LGPL) | License incompatibility |
| Session scope | S3-A (secretlint) first | Highest net-new yield, MIT, JS-native |
