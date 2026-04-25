# Secret Detection in data_classifier

This document explains how `data_classifier` detects credentials and secrets embedded in structured database columns.

---

## 1. Overview

Secret detection uses three active detection layers for **structured columns**
(`classify_columns`) and a dedicated **free-text scanner** (`scan_text`) for
unstructured text (prompts, logs, configs):

| Layer | Mechanism | Catches |
|---|---|---|
| **Layer 1** | Known-prefix regex | Tokens with a well-known structural prefix (AWS keys, GitHub PATs, etc.) |
| **Layer 2** | Structured secret scanner | Credentials embedded in JSON/YAML/env/code content, identified by key name and entropy |
| **Layer 3** | PEM block detection + opaque token pass | PEM private keys (`-----BEGIN/END-----`), standalone high-entropy tokens (JWTs, hex hashes, random API keys) |

### Free-text scanning (`scan_text`)

For unstructured text (LLM prompts, log files, configuration dumps), use `scan_text()`:

```python
from data_classifier import scan_text

result = scan_text("Use this key: ghp_xK9mP2nQ7rT4wY6aB8cD0eF3gH5iJ1kLmN0p")
for finding in result.findings:
    print(f"{finding.entity_type}: {finding.value_masked}")
```

`scan_text` runs three passes:
1. **Regex pass** — credential patterns with validators and FP filters
2. **KV pass** — parses key-value structures, scores key names against the dictionary
3. **Opaque token pass** — scans whitespace-delimited tokens for high-entropy secrets

All detection is **stateless**: the library never stores, logs, or transmits detected values. When `mask_samples=True` is passed to `classify_columns()`, evidence strings show `kJ***q!` rather than the raw value.

Detection is **configurable** via `data_classifier/config/engine_defaults.yaml` and pattern files under `data_classifier/patterns/` — no code changes are required to tune thresholds, add key names, or extend placeholder lists.

---

## 2. Detection Layers

### Layer 1: Known-Prefix Regex

The regex engine (`data_classifier/engines/regex_engine.py`) contains **77 credential patterns** in `data_classifier/patterns/default_patterns.json` (out of 162 total patterns). These match tokens with a known structural prefix or format that uniquely identifies the issuer.

Services covered:

| Category | Services |
|---|---|
| Cloud providers | AWS (access key + secret key), Azure Storage, Google API, Cloudflare |
| Version control | GitHub PAT, GitLab PAT, npm token, Terraform Cloud |
| Payments | Stripe (secret, publishable), Shopify |
| Messaging / collaboration | Slack (bot token, user token, webhook URL), Discord, Twilio, SendGrid, Mailgun |
| Developer tooling | Databricks, HashiCorp Vault, Pulumi, Vercel, Linear, Netlify, Fly.io |
| AI / ML | OpenAI, Hugging Face, Sentry |
| Auth primitives | JWT, PEM private keys, generic API keys, connection strings |

Each pattern is a RE2-compatible regex matched against sample values. The `aws_secret_key` pattern applies the `aws_secret_not_hex` post-match validator (see Section 4) to reject false matches on git SHAs and checksums.

Layer 1 runs first (engine order 2) and is the lowest-cost path. When a known-prefix token is present, no entropy analysis is needed.

### Layer 2: Structured Secret Scanner

The `SecretScannerEngine` (`data_classifier/engines/secret_scanner.py`, engine order 4) finds credentials where the token has **no recognizable prefix** — identified only by its context. The engine:

1. Parses each sample value into key-value pairs using format-aware parsers.
2. Scores each key name against the key-name dictionary.
3. Applies tiered scoring that combines key-name confidence with value plausibility.
4. Applies false-positive filters at each stage.

This catches patterns like:

```
# From a database column containing .env file content
DB_PASSWORD=realPr0dP@ss!

# From a column containing JSON config blobs
{"database": {"credentials": {"password": "Pr0d_S3cret!"}}}

# From a column containing YAML config
database:
  password: "myDbP@ss123"

# From a column containing Python source literals
secret_key: str = "kJ9x#Mp$2wLq"
```

None of these have a recognizable service-specific prefix — they are detected purely by key name and value character distribution.

### Layer 3: PEM Detection + Opaque Token Pass

**PEM block detection** (Sprint 15) scans for `-----BEGIN/END PRIVATE KEY-----`
blocks and emits a single `PRIVATE_KEY` finding per block. Public keys and
certificates are recognised but not flagged as secrets.

**Opaque token pass** (Sprint 15) scans whitespace-delimited tokens for
standalone high-entropy secrets — JWTs, hex hashes, random API keys that have
no recognisable prefix. Tokens must pass entropy (≥0.7 relative), char-class
diversity (≥3), and 25+ structural FP filters (file paths, code expressions,
CamelCase identifiers, UUIDs, etc.) to be flagged.

**URI connection strings** (e.g., `mongodb+srv://admin:P@ssw0rd!23@cluster.mongodb.net/mydb`)
embed credentials in a URI authority field that is not yet parsed. This remains
a known gap.

---

## 3. Scoring Model

### Key-Name Dictionary

The secret scanner uses `data_classifier/patterns/secret_key_names.json`, which contains **283 entries** across three tiers and three match types:

| Tier | Count | Meaning |
|---|---|---|
| `definitive` | 70 | Key name alone is strong evidence (`password`, `api_key`, `jwt_secret`) |
| `strong` | 14 | Key name is suggestive but needs value corroboration (`token`, `auth`, `dsn`) |
| `contextual` | 4 | Key name is weak signal, needs strong value evidence (`hash`, `salt`, `nonce`, `key` suffix) |

| Match type | Count | Rule |
|---|---|---|
| `substring` | 78 | Pattern appears anywhere in the key name |
| `word_boundary` | 9 | Pattern is surrounded by `_`, `-`, `.`, space, or string start/end |
| `suffix` | 1 | Pattern appears only at the end of the key name, after a separator |

Word-boundary and suffix matching prevent false positives from key names like `keyboard` (must not match `key`), `author` (must not match `auth`), or `bypass_flag` (must not match `pass`).

### Tiered Scoring

The composite confidence score is computed by `_compute_tiered_score()`:

**Definitive tier** (key name alone is sufficient):
- Value must pass a plausibility check — prose, dates, URLs, and config flags (`true`, `null`, `disabled`, etc.) are rejected.
- Formula: `composite = key_score × 0.95`
- Example: `{"db_password": "kJ#9xMp$2wLq!"}` → key score 0.95, composite 0.9025

**Strong tier** (needs moderate value signal):
- Requires relative entropy ≥ 0.5 OR char class diversity ≥ 3.
- Formula: `composite = key_score × max(0.6, score_relative_entropy(rel_entropy))`
- Example: `{"token": "eyJhbGciOiJSUzI1NiJ9..."}` → high-entropy base64, fires

**Contextual tier** (needs strong value signal):
- Requires relative entropy ≥ 0.7 AND char class diversity ≥ 3.
- Formula: `composite = key_score × score_relative_entropy(rel_entropy)`
- Example: `{"session_id": "aB3$kJ9x#Mp2wLq!nR5s"}` → four char classes + high entropy, fires

If the value does not meet the tier's requirements, `_compute_tiered_score()` returns 0.0 and no finding is produced.

### Relative Entropy

Raw Shannon entropy (bits per character) is hard to threshold reliably because different character sets have different theoretical maxima. The scanner normalizes to **relative entropy** — the observed entropy as a fraction of the theoretical maximum for the detected charset:

```
relative_entropy = shannon_entropy(value) / max_entropy_for_charset(value)
```

| Charset | Max entropy (bits/char) | Example |
|---|---|---|
| `hex` | 4.0 — log2(16) | `a3f8b2c1d4e5f6a7` |
| `base64` | 6.0 — log2(64) | `wJalrXUtnFEMI/K7MDENG` |
| `alphanumeric` | 5.95 — log2(62) | `aB3cD4eF5g` |
| `full` (printable) | 6.57 — log2(95) | `kJ#9xMp$2wLq!` |

This normalization means a high-entropy hex string like a git SHA (relative entropy ~0.97) is not automatically flagged — it only fires if the key name is in the `contextual` tier with a score high enough to survive the `0.7 × diversity ≥ 3` gate.

The entropy score used in the composite formula is linear: 0.0 for relative entropy below 0.5, then scales linearly to 1.0.

---

## 4. False Positive Prevention

Multiple mechanisms operate in layers, from cheapest to most expensive:

| Mechanism | Stage | What it prevents |
|---|---|---|
| **Min value length** | Parser output | Values shorter than 8 chars are skipped entirely |
| **Anti-indicators** | Post-parse, key + value | Substrings `example`, `test`, `placeholder`, `changeme` in key or value suppress the pair |
| **Known placeholder list** | Post-parse, value | 34 known dummy values suppressed (`changeme`, `password123`, `your_api_key_here`, etc.) |
| **Word-boundary matching** | Key scoring | `keyboard` does not match `key`; `author` does not match `auth` |
| **Suffix matching** | Key scoring | `key` only matches at end of key name (`public_key` yes, `keyboard` no) |
| **Value plausibility check** | Definitive tier | Rejects URLs, date-like strings, prose (> 60% alpha + spaces), and config flags (`true`, `false`, `null`, etc.) |
| **Relative entropy threshold** | Strong / contextual tiers | Low-entropy values (below 0.5 or 0.7 relative entropy) rejected even with a good key name |
| **Char class diversity** | Contextual tier | Values using fewer than 3 character classes fail |
| **`aws_secret_not_hex` validator** | Regex engine, Layer 1 | Rejects pure-hex strings that match the 40-char AWS secret key length (git SHAs, checksums) |
| **CREDENTIAL suppression** | Orchestrator, post-cascade | Generic `CREDENTIAL` is dropped when a more specific entity type is found at equal or higher confidence |

### `aws_secret_not_hex` Validator

AWS secret access keys are 40-character base64 strings with mixed case. Git SHAs and checksums are also 40 characters but are pure hex (only `[0-9a-fA-F]`). The `aws_secret_not_hex` validator in `data_classifier/engines/validators.py`:

1. Rejects the match if the value is pure hex.
2. Requires at least one uppercase AND one lowercase letter (base64 property).

This eliminates SHA-1 git commit hashes as false positives.

### CREDENTIAL Suppression in the Orchestrator

The orchestrator (`data_classifier/orchestrator/orchestrator.py`) calls `_suppress_generic_credential()` after all engines complete. If any other entity type has a finding with confidence ≥ the `CREDENTIAL` finding's confidence, the `CREDENTIAL` finding is removed. This prevents the secret scanner's broad `CREDENTIAL` signal from appearing alongside a more specific regex finding (e.g., `SSN`, `CREDIT_CARD`, `EMAIL`) on the same column.

---

## 5. Configuration

All parameters are in `data_classifier/config/engine_defaults.yaml` — no code changes needed to tune.

```yaml
secret_scanner:
  min_value_length: 8            # Values shorter than this are skipped
  anti_indicators:               # Suppress finding if found in key or value
    - example
    - test
    - placeholder
    - changeme
  scoring:
    tier_boundaries:
      definitive: 0.90           # Key score >= this → key name alone sufficient
      strong: 0.70               # Key score >= this → needs moderate value signal
    definitive_multiplier: 0.95  # Definitive: composite = key_score × this
    strong_min_entropy_score: 0.6  # Strong: minimum entropy contribution
    relative_entropy_thresholds:
      strong: 0.5                # Strong: rel entropy >= this OR diversity >= 3
      contextual: 0.7            # Contextual: rel entropy >= this AND diversity >= 3
    diversity_threshold: 3       # Min character classes (upper/lower/digit/special)
    prose_alpha_threshold: 0.6   # Value with >60% alpha + spaces = prose, not secret

collision_resolution:
  gap_threshold: 0.15            # Min confidence gap to suppress lower finding
```

### Parameter Reference

| Parameter | Default | What it controls |
|---|---|---|
| `min_value_length` | 8 | Values shorter than this are skipped before scoring |
| `anti_indicators` | 4 words | Substrings that suppress findings in key or value (case-insensitive) |
| `tier_boundaries.definitive` | 0.90 | Key score threshold for definitive tier (key alone sufficient) |
| `tier_boundaries.strong` | 0.70 | Key score threshold for strong tier (needs value signal) |
| `definitive_multiplier` | 0.95 | Score multiplier for definitive tier findings |
| `strong_min_entropy_score` | 0.60 | Minimum entropy score contribution for strong tier |
| `relative_entropy_thresholds.strong` | 0.50 | Relative entropy threshold for strong tier |
| `relative_entropy_thresholds.contextual` | 0.70 | Relative entropy threshold for contextual tier |
| `diversity_threshold` | 3 | Minimum character classes required |
| `prose_alpha_threshold` | 0.60 | Alpha ratio above which space-containing values are classified as prose |
| `collision_resolution.gap_threshold` | 0.15 | Minimum confidence gap to suppress a conflicting entity type |

Anti-indicators are checked case-insensitively against both the key name and the value. So `{"password": "test123"}` is suppressed (value contains `test`), and `{"test_password": "kJ9x#Mp$2wLq"}` is also suppressed (key contains `test`).

### Data Files (also configurable, no code changes needed)

| File | Purpose | Entries |
|---|---|---|
| `patterns/secret_key_names.json` | Key-name dictionary with scores, match types, tiers | 88 |
| `patterns/known_placeholder_values.json` | Known dummy values to suppress | 34 |
| `patterns/default_patterns.json` | Regex patterns (credential section) | 36 |

To add new entries, edit the JSON files directly. Changes take effect at next engine startup.

---

## 6. Parsers

The `parse_key_values()` function in `data_classifier/engines/parsers.py` extracts key-value pairs from raw text using four parsers, tried in order:

| Parser | Format | Assignment styles | Notes |
|---|---|---|---|
| **JSON** | JSON objects | `{"key": "value"}` | Nested dicts flattened with dots: `db.credentials.password` |
| **YAML** | YAML mappings | `key: value` | Only runs if JSON fails |
| **env** | `.env` files, shell exports | `KEY=VALUE`, `export KEY=VALUE`, `KEY="VALUE"`, `KEY='VALUE'` | Regex-based, multiline |
| **Code literals** | Source code | `key = "value"`, `key := 'value'`, `key: "value"` | Supports `=`, `:=`, `:` operators |

JSON and YAML are mutually exclusive — YAML only runs when JSON fails. The env and code literal parsers both run and results are deduplicated before scoring (env and code literal parsers can produce overlapping results for the same input).

Nested JSON/YAML dicts produce dotted key paths. For example, `{"database": {"credentials": {"password": "secret"}}}` produces the key `database.credentials.password`. Both the full path and each segment can match patterns — `password` (substring) matches in the path `database.credentials.password`.

The code literal parser applies a 500-character length limit on matched values to avoid performance issues on very large text columns.

---

## 7. Performance

The secret scanner is the most expensive engine in the pipeline because it attempts multiple parsers on every sample value. Observed costs from `tests/benchmarks/perf_benchmark.py`:

| Engine | Per-column latency (100 samples) | % of pipeline |
|---|---|---|
| `column_name` | < 0.1 ms | ~3% |
| `regex` | ~0.3 ms | ~10% |
| `heuristic_stats` | ~0.5 ms | ~15% |
| `secret_scanner` | ~2 ms | ~78% |

The dominant cost is format parsing (JSON/YAML failure-path exception handling) and regex scanning for env/code literal patterns across every sample.

A fast-path optimization is tracked in the Sprint 4 backlog: skip all parsing for sample values that contain no KV indicator characters (`=`, `:`, `{`, `"`). This would eliminate scanner overhead on digit-only, plain-text, or numeric columns — estimated 50–60% cost reduction on mixed corpora.

Cost scales linearly with sample count. Columns with 10 samples are approximately 10x faster to scan than columns with 100 samples.

---

## 8. Benchmarking

### Secret Benchmark

`tests/benchmarks/secret_benchmark.py` — run manually:

```
python3 -m tests.benchmarks.secret_benchmark [--verbose]
```

Tests individual sample values (not full columns). For each case, a single-sample `ColumnInput` is created and the full pipeline is run. The benchmark reports per-detection-layer precision, recall, and F1.

The corpus contains **102 labeled samples**:

| Positive class (expected detected) | Count |
|---|---|
| Layer 1 — known-prefix regex tokens | 15 |
| Layer 2 scanner — definitive tier | 11 |
| Layer 2 scanner — strong tier | 6 |
| Layer 2 scanner — contextual tier | 1 |
| Known limitation (URI parser needed) | 1 |
| **Total true positives** | **34** |

| Negative class (expected not detected) | Count |
|---|---|
| Adversarial near-miss keys (`password_policy`, `token_expiry`) | 15 |
| Word-boundary false positive attempts (`author`, `keyboard`) | 8 |
| Known placeholder values (`changeme`, `password123`) | 5 |
| Non-secret key-value content (`PORT=8080`, `DEBUG=true`) | 10 |
| High-entropy non-secrets (UUIDs, git SHAs, checksums) | 8 |
| Encoded non-secrets (base64 plain text, HTML) | 5 |
| Plain text / unstructured (no KV structure) | 8 |
| Edge cases (empty, very short, unicode, null values) | 6 |
| Ambiguous — deferred, needs table/sibling context | 3 |
| **Total true negatives** | **68** |

Current results:

| Layer | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| regex | 15 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| scanner_definitive | 11 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| scanner_strong | 6 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| scanner_contextual | 1 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| **OVERALL** | **33** | **0** | **1** | **1.000** | **0.971** | **0.985** |

The single false negative is the MongoDB URI (`mongodb+srv://admin:P@ssw0rd!23@cluster.mongodb.net/mydb`) — a known gap requiring Layer 3.

### Column Benchmark

`tests/benchmarks/accuracy_benchmark.py` — full-pipeline accuracy across all entity types at the column level:

| Profile | Precision | Recall | F1 |
|---|---|---|---|
| Sprint 2 baseline (synthetic golden fixtures) | 0.831 | 0.758 | **0.793** |
| Sprint 2 baseline (real-world sample) | 0.634 | 0.963 | **0.765** |

The real-world sample's lower precision reflects collision noise between similar-looking entity types (SSN vs. ABA routing, phone number overlaps) rather than credential-specific issues. `CREDENTIAL` F1 in the real-world sample was 0.000 (0 TP, 1 FP, 0 FN) — a single column where the scanner over-fired on a non-secret key.

---

## 9. Architecture — What Each Layer Handles

| Input scenario | Layer 1 (Regex) | Layer 2 (Scanner) | Layer 3 (Future) |
|---|---|---|---|
| `ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcd` — GitHub PAT | Catches | Not needed | — |
| `AKIAIOSFODNN7EXAMPLX` — AWS access key | Catches | Not needed | — |
| `5f4dcc3b5aa765d61d8327deb882cf99` — git SHA (40 hex chars) | Rejected by `aws_secret_not_hex` | Not matched (hex, contextual tier needs diversity) | — |
| `{"db_password": "Pr0d_S3cret!"}` — JSON config blob | Misses (no prefix) | Catches (definitive: `db_password`) | — |
| `export API_TOKEN=a8f3b2c1d4e5F6` — env file line | Misses | Catches (definitive: `api_token`) | — |
| `secret_key: str = "kJ9x#Mp$2wLq"` — Python source | Misses | Catches (definitive: `secret_key`) | — |
| `mongodb+srv://admin:P@ss@cluster.net` — URI | Misses | Misses (no key=value structure) | Will catch |
| `{"password": "changeme"}` — placeholder | N/A | Suppressed (placeholder list) | — |
| `{"author": "John Smith"}` — non-secret | N/A | Not matched (word boundary: `auth` ≠ `author`) | — |
| `{"checksum": "e3b0c44298fc..."}` — SHA-256 | Misses | Not matched (`checksum` not in dictionary) | — |
| `{"token_expiry": "3600"}` — near-miss key | N/A | Rejected (value plausibility: numeric) | — |
| `{"password_policy": "8 chars minimum"}` — policy field | N/A | Rejected (plausibility: prose) | — |

---

## 10. Limitations and Future Work

**URI connection strings are not detected.** The structured parsers extract key=value pairs. URI formats (`scheme://user:pass@host/db`) embed credentials in the authority component with no key name. A dedicated URI parser is the highest-priority Layer 3 item. Affected formats: PostgreSQL DSNs, MongoDB connection strings, Redis URLs, MySQL connection strings.

**No structural document parsers.** PEM certificate and private key blocks, PKCS#12 archives, SSH `authorized_keys` format, and Docker `config.json` are not parsed beyond what the existing code literal parser handles.

**Ambiguous contextual keys defer correctly.** Keys like `nonce`, `hash`, and `salt` are in the contextual tier intentionally — they are genuinely ambiguous without table context. A `nonce` column might be a cryptographic nonce (sensitive) or a web request counter (not sensitive). These require sibling column analysis or schema-level context, which is tracked in the BQ coordination backlog item.

**Entropy thresholds are empirical, not ML-optimized.** The thresholds (0.5 and 0.7 relative entropy, 0.90/0.70 key score cutoffs) were set against the benchmark corpus. A trained classifier on a larger corpus (SecretBench, StarPII) could improve contextual tier recall.

**Secret scanner is 78% of pipeline cost.** Fast-path optimization (skip parsing when no KV indicators present) is tracked but not yet implemented. Until then, scanner cost dominates for any column with structured-looking values.

---

## 11. Adding New Patterns

### Add a new known-prefix regex pattern (Layer 1)

Edit `data_classifier/patterns/default_patterns.json`. Add an entry in the CREDENTIAL section:

```json
{
  "name": "example_api_key",
  "regex": "\\bexk_[A-Za-z0-9]{32}\\b",
  "entity_type": "CREDENTIAL",
  "category": "Credential",
  "sensitivity": "CRITICAL",
  "confidence": 0.95,
  "description": "Example service API key (exk_ prefix + 32 chars)"
}
```

Optionally add `"validator": "validator_name"` referencing a function in `data_classifier/engines/validators.py` if post-match validation is needed to reject structural false positives.

### Add a new key-name entry (Layer 2)

Edit `data_classifier/patterns/secret_key_names.json`. Add an entry to the `key_names` array:

```json
{
  "pattern": "vault_token",
  "score": 0.95,
  "category": "Credential",
  "match_type": "substring",
  "tier": "definitive"
}
```

Choose `match_type` carefully:
- `"word_boundary"` — for short patterns that could appear inside unrelated words (`key`, `pass`, `auth`, `token`)
- `"suffix"` — for patterns meaningful only at the end of a key name, after a separator
- `"substring"` — for specific multi-word patterns unlikely to produce false positives (`vault_token`, `db_password`)

Choose `tier` based on how much value evidence is required:
- `"definitive"` — key name alone is strong evidence; value only needs to pass the plausibility check
- `"strong"` — key name is suggestive; value must show relative entropy ≥ 0.5 or 3+ char classes
- `"contextual"` — key name is weak; value must show relative entropy ≥ 0.7 AND 3+ char classes

### Add a new placeholder value

Edit `data_classifier/patterns/known_placeholder_values.json`. Add to the `placeholder_values` array:

```json
{
  "placeholder_values": [
    "changeme",
    "your_new_placeholder_here",
    ...
  ]
}
```

Values are matched case-insensitively after loading.

### Add a new anti-indicator

Edit `data_classifier/config/engine_defaults.yaml`:

```yaml
secret_scanner:
  anti_indicators:
    - example
    - test
    - placeholder
    - changeme
    - your_new_indicator
```

Anti-indicators are substring-matched case-insensitively against both the key name and the value.

### Add a new post-match validator

Edit `data_classifier/engines/validators.py`. Add a function and register it in the `VALIDATORS` dict at the bottom:

```python
def my_validator(value: str) -> bool:
    """Return False to reject the match, True to accept it."""
    ...

VALIDATORS: dict[str, typing.Callable] = {
    ...
    "my_validator": my_validator,
}
```

Then reference `"validator": "my_validator"` in the pattern entry in `default_patterns.json`.
