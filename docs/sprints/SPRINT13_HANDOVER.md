# Sprint 13 Handover — data_classifier

> **Theme:** Column-shape router + per-value GLiNER union + S0 precision
> **Dates:** 2026-04-16 → 2026-04-17
> **Branch:** `sprint13/main`
> **Test count:** 1532 → **1711** (+179 net-new, passing)

---

## Sprint theme in one paragraph

Sprint 13 delivered the 3-branch column-shape router (Item A), per-value GLiNER aggregation on heterogeneous columns with a union design (Item B), an entropy-based opaque-token handler (Item C), three S0-driven precision fixes from the prompt-analysis research track (SWIFT_BIC validator, IPv4 reserved-range rewrite, OpenAI/Anthropic patterns, secret-key compound stoplist), and 4 experimental GLiNER labels (AGE, HEALTH, FINANCIAL, DEMOGRAPHIC). The sprint also diagnosed and fixed a benchmark regression where Item C's entropy handler fired on Bitcoin addresses, and identified 273 NEGATIVE FPs as a structural precision gap that led to filing a research item for a binary PII gate.

---

## Completed items (6)

### Item A — Column-Shape Router (P1)

Heuristic gate routes each column to one of three branches based on post-merge content signals: `structured_single` (77%), `free_text_heterogeneous` (11%), `opaque_tokens` (12%). v5 shadow suppressed on non-structured branches.

- Safety audit Q3: 6/6 `router_deflected` (was 6/6 RED in Sprint 12)
- `shadow.cross_family_rate_emitted`: 0.0001 (was 0.0044 in Sprint 12)
- 68 tests added

### Item B — Per-Value GLiNER Aggregation (P1)

On heterogeneous columns, runs GLiNER per-value on N=60 subsample, aggregates spans, unions with cascade output. Spec revised 2026-04-17 from "replace cascade" to "augment cascade" — regex floor preserved, GLiNER adds coverage (PERSON_NAME, ADDRESS).

- Union checks: 0/6 regressions, 2/6 GLiNER lift, 0/6 hallucinations
- Per-value latency: median 2.3s, p90 2.9s per heterogeneous column
- 29 tests added

### Item C — Opaque-Token Handler (P2)

Entropy-based classifier for JWT/base64/hex-hash/session-ID columns. Two paths: high-entropy (≥4.2 bits/char, <5% spaces) and hex-hash (all hex, ≥32 chars). Only fires when cascade found nothing (guard added after Bitcoin regression).

- JWT: OPAQUE_SECRET @ 0.95, hex hashes: 0.75, session IDs: 0.88
- 15 tests added

### S0-1 — SWIFT_BIC + IPv4 Precision (P1)

- `swift_bic_country_code_check`: ISO 3166 alpha-2 at positions 5-6 (~50% English-word FP reduction)
- `ipv4_not_reserved_check`: stdlib ipaddress rewrite (full loopback/multicast/reserved/link-local/0.0.0.0-8)
- 27 tests added

### S0-2 — OpenAI/Anthropic Key Patterns (P2)

- `openai_legacy_key`: `sk-[a-zA-Z0-9]{48}` with mixed-case validator
- `anthropic_api_key`: `sk-ant-(api|admin)NN-[93+ chars]`
- 9 tests added

### S0-3 — Secret-Key Compound Stoplist (P2)

- `_is_compound_non_secret`: suffix-based rejection for `_address`, `_field`, `_id`, `_name`, `_input`, `_label`, `_placeholder`, `_url`, `_endpoint`
- Allowlist: `session_id`, `auth_id`, `client_id` (kept as sensitive)
- 21 tests added

---

## Additional deliverables

### Experimental GLiNER labels

4 labels added to `EXPERIMENTAL_LABEL_DESCRIPTIONS`: AGE (fires cleanly on HR data), HEALTH (fires on medical notes), FINANCIAL (fires on salary data), DEMOGRAPHIC (silent — model doesn't respond to current description). No tests — manually validated, promotion decision deferred.

### Benchmark regression investigation

Item C entropy handler fired OPAQUE_SECRET on Bitcoin address columns (150 FPs). Fixed by `not result` guard — entropy handler only fires when cascade is empty. CRYPTO F1 restored to 1.000.

273 NEGATIVE FPs on secretbench adversarial fixtures identified as structural cascade precision gap. Filed research item: `backlog/research-binary-pii-gate-model-evaluation.yaml` — binary "is this real PII?" gate using LR/XGBoost/MLP on existing 49 features. User observed none of the FPs have entropy/character distribution of real secrets.

---

## Key decisions

1. **Union over replacement** (2026-04-17): GLiNER per-value findings are merged with cascade, not substituted. Regex floor preserved.
2. **"Measure, do not gate"** (2026-04-16 scoping Q2): per-value latency measured but no timeout imposed. Sprint 14 revisits with production telemetry.
3. **Entropy handler guard** (2026-04-17): only fires when cascade found nothing. Prevents OPAQUE_SECRET on columns already identified (Bitcoin, Ethereum).
4. **Binary PII gate → research track** (2026-04-17): user directed model evaluation to research/meta-classifier rather than production implementation.

---

## Final benchmark numbers

| Metric | Sprint 12 | Sprint 13 |
|---|---|---|
| `shadow.cross_family_rate_emitted` | 0.0044 | **0.0004** |
| `shadow.family_macro_f1_emitted` | 0.9945 | **0.9998** |
| `live.cross_family_rate` | 0.1627 | **0.1624** |
| `live.family_macro_f1` | 0.8329 | **0.8300** |
| `router_suppression_rate` | N/A | 0.2307 |
| Tests | 1532 | **1711** (+179) |
| nemotron named F1 | 1.000 | 1.000 |
| nemotron blind F1 | 0.833 | 0.833 |

---

## Follow-ups for Sprint 14

1. **Binary PII gate research** — model evaluation on research/meta-classifier branch
2. **ai4privacy openpii-1m corpus ingest** — deferred from Sprint 12, tagged sprint14
3. **DOB_EU v6 retrain** — deferred from Sprint 13
4. **GLiNER label decisions** — promote AGE/HEALTH/FINANCIAL, fix or drop DEMOGRAPHIC
5. **ADDRESS Q3 fixture** — would close GLiNER lift gap (2/6 → likely 3/6)
6. **Browser PoC sync** — needs Sprint 13 patterns (OpenAI/Anthropic)
7. **Per-value latency gate decision** — pending 1 week of ColumnShapeEvent prod telemetry
8. **Broader LLM provider pattern mine** (S3) — Gemini, Mistral, Cohere, etc.
