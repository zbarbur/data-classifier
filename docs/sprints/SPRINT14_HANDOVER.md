# Sprint 14 Handover — data_classifier

> **Theme:** Directive flip + multi-label scoring + browser PoC + detection quality
> **Dates:** 2026-04-17 → 2026-04-21
> **Branch:** `sprint14/main`
> **Test count:** 1711 → **2257** (+546 net-new, passing)

---

## Sprint theme in one paragraph

Sprint 14 delivered the meta-classifier directive flip (shadow → live), multi-label ground truth scoring, the browser PoC release pipeline, and a major detection quality lift. The family accuracy benchmark improved from F1 0.8300 (S13) to **0.9509** — a +0.1209 jump — driven by corpus data quality fixes (Nemotron checksum filtering, NEGATIVE relabeling, CREDENTIAL subtype GT), checksum-wins collision resolution, per-pattern findings throughout the orchestrator, and the `scan_text` public API. The browser client shipped with full Python–JS parity CI gating, a release zip command, and 15 annotated WildChat stories in the tester.

---

## Completed items

### Directive Flip — Meta-Classifier Live (P1)

The meta-classifier v5 (shadow since Sprint 12) is now the live directive on `structured_single` columns. The column-shape router gates execution: shadow suppressed on `free_text_heterogeneous` and `opaque_tokens` branches (unchanged from Sprint 13).

- `live.family_macro_f1`: 0.8300 → **0.9509** (+0.1209)
- `live.cross_family_rate`: 0.1624 → **0.0915** (−0.0709)
- 14 entity types at perfect F1 (CRYPTO, DATE, NETWORK, PAYMENT_CARD, VEHICLE + 9 more)

### Multi-Label Ground Truth & Scoring (P1)

Benchmark scoring upgraded from single-label to multi-label via structural presence scanning. Each shard's GT is determined by `scan_text` on the actual corpus values, not corpus metadata alone. CREDENTIAL split into API_KEY / PRIVATE_KEY / OPAQUE_SECRET subtypes in GT.

- `_relabel_negative_by_regex()`: scans NEGATIVE pools, moves format-valid credentials to correct subtype
- `_passes_checksum()`: shared Luhn / ABA / VIN validation for corpus filtering
- `_classify_credential_value_shape()` with `_API_KEY_PREFIX_RE` for known prefix recognition

### Browser PoC Release Pipeline (P1)

Full browser client packaging: `npm run release` produces a self-contained zip with tester, dist, docs, and corpus.

- `scripts/package.js`: assembles dist-package/ with `--zip` flag
- Tester: 15 WildChat stories with annotation, detection_type, display_name
- Stories renamed `.jsonl` → `.json` (MIME type compatibility)
- `tester/dist/` symlink for dev, real copy in release zip
- `package.json` scripts/devDependencies stripped from distribution

### Python–JS Parity CI Gate (P1)

Browser parity check added to CI: `bash scripts/ci_browser_parity.sh` runs PYTHON_LOGIC_VERSION SHA comparison + differential E2E test.

- `CLAUDE.md` and `.claude/sprint-config.yaml` updated with browser parity in CI command
- `scripts/generate_browser_patterns.py`: `huggingface_token` added to PORTED_VALIDATORS
- Differential test: Playwright runs JS scanner against Python scanner output per seed case

### Checksum-Wins Collision Resolution (P2)

New collision resolution strategy: when exactly one side of a collision pair has a mathematical checksum validator (Luhn, ABA, VIN) and it passes at ≥50%, it wins regardless of confidence score. Only fires when exactly one side has a checksum (prevents SSN ↔ CANADIAN_SIN false wins where both pass Luhn).

- `_CHECKSUM_ENTITY_TYPES` frozenset: ABA_ROUTING, CANADIAN_SIN, CREDIT_CARD, NPI, IBAN, DEA_NUMBER, VIN
- `_best_validation_ratio()`: returns validated/matched ratio for checksum entity types only
- ABA_ROUTING → SSN regressions: 171 → 0
- Confidence guard: `other_conf < 0.90` prevents over-aggressive wins

### Per-Pattern Findings (P2)

Findings keyed by `detection_type` (pattern name) instead of `entity_type` throughout orchestrator, engines, and scanner. Enables fine-grained display_name and detection metadata per finding.

- `ClassificationFinding.detection_type` and `.display_name` fields
- Orchestrator collision resolution updated for per-pattern keying
- Browser JS `finding.js` updated with display_name support

### `scan_text` Public API (P2)

New `scan_text()` function for scanning raw text (not columnar data). Used internally by benchmark relabeling and externally as a convenience API.

- `data_classifier/scan_text.py`: standalone module
- Exposed via `data_classifier.__init__.py`
- `docs/CLIENT_INTEGRATION_GUIDE.md` updated

### Detection Quality Fixes

- **HuggingFace token FP**: New `huggingface_token` validator rejects camelCase + no-digits (Objective-C method names like `hf_requiredCharacteristicTypes`)
- **JS OLE DB FP**: `_CODE_CALL_RE = /[({].*[=;]/` in scanner-core.js
- **JS CJK/Cyrillic/Arabic FP**: Unicode range check prevents false matches in non-Latin prose
- **JS `not_placeholder_credential`**: Full port of Python validator (repeated-X, repeated-char, template-prefix checks)
- **Checksum suppression fix**: Denominator changed from `samples_scanned` to `samples_matched`, threshold from 0.10 to 0.25
- **min_confidence architecture**: Engines receive `min_confidence=0.0`; filter applied at orchestrator end after meta-classifier directive
- **Meta-classifier cascade trust**: Added `top.confidence >= prediction.confidence` guard to `_apply_meta_directive`

### Corpus Data Quality Fixes

- **Nemotron/Gretel CC/ABA/VIN**: Checksum validators filter LLM-generated invalid values from corpus
- **NEGATIVE relabeling**: `_relabel_negative_by_regex()` moves format-valid credentials out of NEGATIVE pools
- **DATE_OF_BIRTH → DATE**: All corpus loaders and shard builders updated; taxonomy mapping added
- **CREDENTIAL subtype GT**: Gitleaks source_type mapping, API key prefix recognition
- **OPAQUE_SECRET shard cap**: `max_credential_subtype_shards = shards_per_type * 2` prevents class imbalance
- **Meta-classifier v6 retrained**: On cleaned corpus with correct GT labels

---

## Key decisions

1. **Directive flip** (2026-04-19): meta-classifier promoted from shadow to live on structured_single columns. Justified by 13.3× cross_family reduction in Sprint 12 shadow.
2. **Checksum-wins only when one side has checksum** (2026-04-20): prevents SSN ↔ CANADIAN_SIN false wins. Both pass Luhn so mutual exclusivity required confidence guard.
3. **min_confidence=0.0 to engines** (2026-04-20): "one path for testing and production" — engines see all signals, meta-classifier makes decisions, final filter at orchestrator end.
4. **NEGATIVE single-label scoring** (2026-04-20): when no findings on NEGATIVE GT shard, predicted="NEGATIVE" (not None). Fixes 0% NEGATIVE recall.
5. **Browser PoC: stories.json over .jsonl** (2026-04-20): MIME type compatibility — some static servers block `.jsonl`.

---

## Final benchmark numbers

| Metric | Sprint 13 | Sprint 14 |
|---|---|---|
| `live.family_macro_f1` | 0.8300 | **0.9509** (+0.1209) |
| `live.cross_family_rate` | 0.1624 | **0.0915** (−0.0709) |
| `shadow.cross_family_rate_emitted` | 0.0004 | N/A (promoted) |
| Tests | 1711 | **2257** (+546) |
| Perfect families (F1=1.0) | N/A | **5** (CRYPTO, DATE, NETWORK, PAYMENT_CARD, VEHICLE) |

### Per-family results

| Family | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| CONTACT | 0.957 | 0.708 | 0.814 | 2040 |
| CREDENTIAL | 0.967 | 0.834 | 0.895 | 1500 |
| CRYPTO | 1.000 | 1.000 | 1.000 | 600 |
| DATE | 1.000 | 1.000 | 1.000 | 510 |
| FINANCIAL | 0.999 | 0.949 | 0.973 | 1470 |
| GOVERNMENT_ID | 0.995 | 1.000 | 0.997 | 1110 |
| HEALTHCARE | 0.940 | 1.000 | 0.969 | 1050 |
| NEGATIVE | 1.000 | 0.916 | 0.956 | 450 |
| NETWORK | 1.000 | 1.000 | 1.000 | 720 |
| PAYMENT_CARD | 1.000 | 1.000 | 1.000 | 510 |
| URL | 0.675 | 1.000 | 0.806 | 210 |
| VEHICLE | 1.000 | 1.000 | 1.000 | 300 |

---

## Follow-ups for Sprint 15

1. **CONTACT recall gap** (F1 0.814) — 29% missed, mainly PHONE/EMAIL in mixed-format columns
2. **CREDENTIAL recall gap** (F1 0.895) — 17% missed, OPAQUE_SECRET ↔ API_KEY corpus ambiguity remains
3. **URL precision** (0.675) — FPs from non-secret URL-shaped strings
4. **HEALTHCARE precision** (0.940) — 67 FPs, investigate source
5. **NEGATIVE recall** (0.916) — 38 FPs on adversarial fixtures, binary PII gate research item still open
6. **HEALTH entity 0% recall at production threshold** — backlog item filed, needs meta-classifier confidence recalibration
7. **Binary PII gate research** — model evaluation on research/meta-classifier branch
8. **Per-value latency gate decision** — pending production telemetry
9. **Browser PoC: additional WildChat stories** — expand from 15 to 25+ stories
10. **Broader LLM provider pattern mine** — Gemini, Mistral, Cohere, etc.
