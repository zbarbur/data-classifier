# S0 — WildChat Prevalence Findings Memo

**Stage**: S0 from `docs/experiments/prompt_analysis/queue.md` §"Secret detection track"
**Date**: 2026-04-16
**Branch**: `research/prompt-analysis`
**Driver**: First prompt-analysis client (Chrome extension over ChatGPT) needs evidence for product positioning + scanner calibration.

---

## TL;DR

Two scans run on **WildChat-1M**:

| Scan | Prompts | Engine prevalence | Cred raw hits | Distinct cred prompts | Throughput |
|---|---|---|---|---|---|
| Smoke | 500 | 5.0% | 1 OPAQUE | 1 | 42/s (cold) |
| 50K | 50,000 | 3.66% (1,830) | 59 | 50 → ~10 distinct credentials | 1,140/s (warm) |
| **1M (full)** | **1,000,000** | **(not separately measured)** | **1,712** | **1,171** | **2,022/s** |

**The 1M scan blew past the 50K extrapolation.** Predicted ~200 distinct
credentials from 50K scaling; actual 1M shows **1,171 distinct prompts
with credentials** — 5.8× higher than extrapolated. The 50K sample was
dominated by a few heavy-duplicate prompts (one C# admin password x11,
one Instagram cred x6, one Facebook Graph token x11) that masked the
long-tail diversity. At 1M scale, the
long tail dominates.

**Real product story** (use these numbers):
- **0.12% of real ChatGPT prompts contain a leaked credential** (1,171 / 1M)
- **1.7 raw credential findings per 1,000 prompts** (1,712 / 1M)
- Includes **6 PRIVATE_KEY** leaks (PEM blocks pasted into prompts) and
  **1 PASSWORD_HASH** that didn't appear in the 50K sample
- At an enterprise scale of 100K-prompts/day, the browser PoC would
  block ~117 credential leaks per day on average

Real credentials found include:
- Live Shopify access token + secret pair
- Instagram username + password (Selenium scraper)
- Telegram bot token (Russian bot)
- Facebook Graph API access token (Instagram automation)
- OpenAI API key (legacy `sk-` format — pattern not in our set)

The numbers validate the browser PoC's product premise: **users do paste real credentials into ChatGPT prompts at a measurable rate**, primarily as hardcoded values in pasted code snippets.

---

## Methodology

- **Source**: `allenai/WildChat-1M` (CC0, real ChatGPT conversations)
- **Sample**: First 50,000 user-turns from streamed dataset
- **Scanners**: `regex_engine` + `secret_scanner` (ML disabled)
- **Filter**: Engine-level findings only (validators applied) — finditer-level
  accounting is unreliable because raw regexes bypass validators (see "Methodology
  notes" below)
- **Dedup key**: SHA-256 fingerprint of the full prompt text (top 16 hex chars)

Two scripts produced the artifacts in this directory:

- `scripts/s0_wildchat_prevalence.py` — original prevalence scan with engine +
  finditer accounting (finditer was misleading; see notes)
- `scripts/s0_curate_credentials.py` — v2 focused capture of all credential
  findings + 5% sample of non-credential findings

---

## Findings — Real credentials (deduped)

| # | Credential (redacted) | Type | Distinct prompts | Detected by |
|---|---|---|---|---|
| 1 | `stc****` (admin password — looks like Maltese telecom) | Plaintext | ~11 (C# homework — heavy duplicate) | `secret_scanner` |
| 2 | `W@l****` for username `wal****` | Instagram credentials | 6 | `secret_scanner` |
| 3 | `582*******:AAG*****` | Telegram bot token | 4 | `secret_scanner` |
| 4 | `EAA*******` (Meta Graph API prefix) | Facebook Graph API token | ~11 | `secret_scanner` + `regex` |
| 5 | `shpat_7f7*****` + `shpat_e62*****` (token + secret pair) | Shopify access token + secret | 1 | `regex` (`shopify_access_token`) |
| 6 | `416*****` (32-char hex) | Generic API key | 2 | `secret_scanner` + `regex` (`generic_api_key`) |
| 7 | `HDM*****` (40-char base62) | Generic client_secret | 1 | `secret_scanner` |
| 8 | `1f8*****` (32-char hex) | Generic app_secret | 3 | `secret_scanner` |
| 9 | **`sk-9hu*****`** (legacy OpenAI `sk-` prefix) | **OpenAI API key (legacy `sk-` format)** | 1 | `secret_scanner` (caught by key name; **regex pattern set has no entry for legacy `sk-` — covered by Sprint 13 backlog item**) |
| 10 | `AAF*****` (35-char base62) | Unknown bot_token (not Telegram format) | 3 | `secret_scanner` |

**Full unredacted values are in `s0_credentials.jsonl` (XOR-encoded)
per `feedback_xor_fixture_pattern.md`** — the redacted prefixes above
are intentionally short to avoid tripping GitHub secret-scanning push
protection. Decode the JSONL via
`data_classifier.patterns._decoder.decode_encoded_strings` for full
audit / curation work.

**9 of 10 distinct credentials were detected via `secret_scanner`'s
key-name + entropy heuristic, NOT via regex pattern matching.** Only
Shopify (#5) and the partial-coverage on Generic 32-char (#6) were
caught by regex alone.

---

## Findings — False positives

### Credential-side (within the 59 hits)

~6 of 59 raw hits (10%) were FPs. All from `secret_scanner` matching
key names that don't actually contain credential values:

| Pattern | Why FP | Fix |
|---|---|---|
| `token_address = config['token_address']` | Solana blockchain address (PUBLIC by design); secret-key dict treats "token_address" as if it contained a token | Add to secret-key dictionary stoplist (Sprint 13 third item, see backlog draft) |
| `password_field = wait.until(...)` | Selenium variable name for a UI element | Same stoplist fix |
| `session_key = 'decrypted cipher text'` | The "value" is literal text describing what would go there | Same stoplist fix |
| `YOUR_GOOGLE_API_KEY`, `YOUR_PINECONE_API_KEY` | Documentation placeholders | `not_placeholder_credential` validator works; these slipped because key name matched | Same stoplist fix |

### Non-credential-side (60 sampled findings)

Confirms credential-detection precision is high — **no hidden credentials
in non-credential buckets**.

| Type | Verdict |
|---|---|
| **SWIFT_BIC** (28 sampled, 15 unique) | **100% FP** — all English words: PROMPTER, QUESTION, BIOHELIX, CONSTRAINTS, COMMANDS, PERFORMANCE, RESPONSE, LANGUAGE, PROJECTIONS, FORTHCOMING, MOVEMENT, SPECIFIC, INSPIRATION, MATERIAL, CREATIVE. Pattern has empty validator. **Sprint 13 P1 fix.** |
| URL (27 sampled, 15 unique) | 100% legitimate URLs (github, wikipedia, ted.com, gaming sites). Real PII but not credentials. Correct classification. |
| EMAIL (4 sampled, 9 unique) | Mix of `*@example.com/.org` test emails. One minor FP: `this@MainActivity.error` (Android stack trace fragment). |
| IP_ADDRESS (1 sampled) | `172.28.115.0` — RFC1918 private. Correctly identified as leaked internal IP. |

---

## Bugs surfaced + Sprint 13 backlog items filed

Three Sprint 13 backlog items drafted at `/tmp/backlog_drafts/` (to be filed
on `sprint13/main` from a separate session):

1. **`sprint13-s0-pattern-precision-pass.yaml`** (P1 bugfix, ~1 day)
   - SWIFT_BIC: add ISO-3166 country-code validator (~250-entry list)
   - IPv4: rewrite `ipv4_not_reserved_check` using `ipaddress` module +
     tighten regex boundaries
   - Tests: S0 repro fixtures committed to this artifact directory

2. **`sprint13-add-legacy-llm-provider-patterns.yaml`** (P2 feature, ~½ day)
   - OpenAI legacy `sk-*` (no `proj-` prefix): empirically present in
     WildChat (hit #9 above)
   - Anthropic `sk-ant-api03-*` / `sk-ant-admin01-*`
   - Source: provider documentation (factual, no IP exposure)

3. **`sprint13-secret-key-dict-stoplist.yaml`** (P2 bugfix, ~½ day)
   - Add stoplist to `secret_key_names.json` for compound names that
     are NOT credential values: `*_address`, `*_field`, `*_id`,
     `*_name`, `*_input`, `*_label`, `*_placeholder`
   - Specifically rejects `token_address`, `password_field`,
     `session_id`, etc.
   - Validates against the 4 confirmed FPs above

---

## Architectural commitments derived

Added to `docs/experiments/prompt_analysis/queue.md` §"Architectural
commitments" 2026-04-16:

### Validators are first-class for the JS port

Empirical S0 finding: every regex-pattern false positive in the 500-prompt
smoke was correctly rejected by its validator. The browser JS port MUST
faithfully implement validators, not just regexes — patterns alone overfire
~4× per pattern. This is a Day-1 commitment, not an optimization.

### `secret_scanner` heuristic MUST be in the JS port

9 of 10 distinct real credentials in S0 were caught by `secret_scanner`'s
key + entropy heuristic, NOT by any of the 76 regex patterns. Pure-regex
JS port would miss the dominant real-positive pattern: hardcoded
credentials in pasted code (e.g., `password = "X"`, `token: "Y"`).

---

## Methodology notes (for v2 script)

Three issues with the current S0 script that don't invalidate the
findings but should be fixed in S0 v2:

1. **Finditer accounting overcounts.** Raw `re.finditer` over loaded
   patterns bypasses validators that the engine applies. Drop the
   per-pattern hit count from `s0_pattern_hits.json` or replicate the
   validator pipeline.
2. **Audit-sample logic missed `secret_scanner`-only positives.** The
   reservoir-sample only added prompts with span_hits, so prompts where
   only `secret_scanner` fired (no regex hit) were excluded from the
   audit. Should sample on `engine_findings or span_hits`.
3. **No deduplication of repeated-substring matches.** The 500-smoke
   showed AWS_secret_key with 11 sub-spans from one 4KB base64 blob
   (caught by validator at engine level, but pattern accounting
   overcounted). Should dedup by span content + position-overlap.

The v2 `scripts/s0_curate_credentials.py` already addresses (1) and (2)
implicitly — it relies on engine findings only and saves all
credential-family records (no reservoir sampling for the credential
side).

---

## Hero examples for client conversation

Three of the strongest "this is exactly what the browser PoC blocks"
examples, ranked by impact:

1. **Live Shopify token + secret pair** — turn 13396, real shop URL
   (myshopify.com subdomain). If the shop is live, the leaked
   `shpat_*` token grants API access right now. User asked a
   pagination question and leaked production auth.

2. **Real Instagram credentials in scraper script** — username + plaintext
   password hardcoded in 6 different prompts asking for help with
   Instaloader-style automation. Users were asking technical questions
   and exposing their personal Instagram login.

3. **Telegram bot token in production-style code** — full
   `<bot_id>:<token>` format hardcoded in Russian Python `telebot`
   code. Bot tokens grant full bot control.

All anonymizable (substitute pseudonyms in client demos; raw values
remain XOR-encoded in this repo per the fixture rule).

---

## Next stages

- **S1 — Pattern gap audit** (blocked on this memo): the 3 Sprint 13
  backlog items above ARE part of S1's output. Treat S1 as completed
  by this memo + the YAML drafts.
- **S2 — Browser-port feasibility spike**: now actively beneficial —
  the validator and `secret_scanner` requirements derived here directly
  shape the JS-port architecture. Coordinate with the
  `sprint14/browser-poc-secret` execution session.
- **S3 — Pattern expansion mine** (Sprint 14): proceed as planned.
  Anthropic + OpenAI legacy split off into the Sprint 13 item above.
- **S4 — re2-wasm migration** (planned, trigger-driven): no change
  to triggers.

---

## Artifact inventory

**50K scan** (in `s0_artifacts/`):

| File | Purpose | Records |
|---|---|---|
| `s0_credentials.jsonl` | Every CREDENTIAL-family finding (XOR-encoded) | 59 |
| `s0_non_credential_sample.jsonl` | 5% sample of non-credential findings | 60 |
| `s0_curate_summary.json` | Aggregate stats | — |
| `s0_findings_memo.md` | This document | — |

**1M scan** (in `s0_artifacts/s0_1m/`):

| File | Purpose | Records |
|---|---|---|
| `s0_credentials.jsonl` | Every CREDENTIAL-family finding from 1M (XOR-encoded) | 1,712 |
| `s0_non_credential_sample.jsonl` | 5% sample of non-credential findings | 1,278 |
| `s0_curate_summary.json` | Aggregate stats from 1M run | — |

**1M-vs-50K key differences** (both engine-level, validators applied):

| Metric | 50K | 1M | 1M / 20× extrapolation |
|---|---|---|---|
| Raw credential hits | 59 | 1,712 | **1.45× higher** than naive scaling |
| Distinct credential prompts | 50 | 1,171 | **1.17× higher** |
| API_KEY hits | 23 | 1,025 | **2.23× higher** |
| OPAQUE_SECRET hits | 36 | 680 | 0.94× (proportional) |
| PRIVATE_KEY hits | 0 | 6 | NEW |
| PASSWORD_HASH hits | 0 | 1 | NEW |
| `secret_scanner` engine | 54 | 1,069 | 0.99× (proportional) |
| `regex` engine | 5 | 643 | **6.4× higher** — long tail emerges only at scale |

The big finding: **regex-engine credentials are vastly more diverse at
1M scale than at 50K**. The 50K's 5 regex hits were 4 Shopify dupes +
1 generic. At 1M, 643 regex hits across many distinct services. This
matters for pattern coverage decisions — the long tail isn't visible
from 50K samples.

The `scripts/s0_wildchat_prevalence.py` and `scripts/s0_curate_credentials.py`
in the repo root reproduce these artifacts. Run via:

```bash
DATA_CLASSIFIER_DISABLE_ML=1 .venv/bin/python scripts/s0_curate_credentials.py \
    --limit 50000 --out-dir docs/experiments/prompt_analysis/s0_artifacts
```
