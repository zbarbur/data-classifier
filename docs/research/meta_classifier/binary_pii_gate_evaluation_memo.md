# Credential FP investigation — binary gate evaluation + heuristic gate + SecretBench relabel

> **Supersedes** the auto-generated YELLOW-verdict memo from the same path earlier on 2026-04-17. That run's `promotion_decision()` averaged LOCO F1 over all corpora including single-class ones (nemotron, gretel_en), which inflated the score. Full raw training output preserved at `docs/experiments/meta_classifier/runs/20260417-binary-pii-gate/`.

**Run date:** 2026-04-17
**Branch:** `research/meta-classifier`
**Backlog item:** `backlog/research-binary-pii-gate-model-evaluation.yaml`
**Scope expansion:** During investigation the research question expanded from "does an ML gate suppress the 273 CREDENTIAL FPs?" to "what are the 273 FPs actually made of?" — answered in three parts below.

---

## TL;DR

- **Binary ML gate: RED.** In-distribution test metrics look good (100% FP suppression, 99% recall), but LOCO reveals the model cannot generalize because the three NEGATIVE-containing corpora encode three fundamentally different concepts of "not a secret". No single structural signal exists for it to learn. Mean LOCO F1 = 0.529.
- **Heuristic gate (F2): GREEN on two of three corpora.** Two simple shard-level rules (config-literal pattern + placeholder pattern) eliminate **100% of detect_secrets FPs** and **71% of gitleaks FPs** at **0.3% TP cost**. Covers 132 of the 267 measured FPs cleanly. Promote to Sprint 14 production item.
- **SecretBench label semantics are being misused.** The corpus was designed for tool-alignment evaluation (*"did a scanner match the right file coordinates of a real leak?"*), not value classification (*"is this string a secret?"*). On our `secretbench_sample.json` fixture, **178 of 516 `is_secret=True` entries (34.5%) are structurally not secrets** — they are prose sentences, empty XML tags, bare `${VAR}` references, or path fragments. Those false TPs were inflating the Sprint 13 "273 FP" count and anchoring the ML gate toward an unlearnable boundary.
- **Relabeled v2 fixture produced.** `tests/fixtures/corpora/secretbench_sample_v2.json` — 178 `True → False` flips, per-row audit trail. Does not contradict upstream semantics; derives a different label for our question.

---

## Background — the Sprint 13 problem

Sprint 13's canonical family benchmark reported 273 CREDENTIAL false positives on 450 NEGATIVE shards (precision 0.7214 on CREDENTIAL family). User observation: *"none of these FPs have the high-entropy / character-distribution signature of real secrets."* The existing v5 meta-classifier feature vector already carries entropy, dictionary_word_ratio, and has_secret_indicators; the signal is there, just not applied for NEGATIVE suppression.

The Sprint 13 handover filed a research item asking whether a binary "is this real PII?" gate on the same 49 features could suppress those FPs without regressing recall on true positives.

## Data

| | |
|---|---|
| Training data | `tests/benchmarks/meta_classifier/training_data_binary_gate.jsonl` — 9,870 rows, 49 features (schema v5) |
| Positive class | any row where ground_truth ≠ NEGATIVE (9,420 rows) |
| Negative class | ground_truth = NEGATIVE (450 rows, 4.6%, from secretbench/gitleaks/detect_secrets) |
| Imbalance | ~20:1 |
| Train/test | 80/20 StratifiedGroupKFold by base shard ID |
| CV | 5-fold StratifiedGroupKFold grouped by corpus |
| LOCO | leave-one-corpus-out on each of the 3 NEGATIVE-containing corpora |

## Finding 1 — binary ML gate: RED

Four arms evaluated. Full results in auto-memo + `docs/experiments/meta_classifier/runs/20260417-binary-pii-gate/`.

### Arm comparison

| Arm | CV F1 | Test F1 | LOCO mean F1 | Test FP supp @ R≥0.99 |
|---|--:|--:|--:|--:|
| G0_LR | 0.880 ± 0.118 | 0.988 | 0.526 | 0.389 |
| **G1_LR_interactions** | **0.894 ± 0.121** | **0.991** | **0.529** | **1.000** |
| G2_XGBoost | 0.896 ± 0.119 | 0.990 | 0.528 | 0.998 |
| G3_MLP | 0.881 ± 0.117 | 0.986 | 0.510 | 0.955 |

**Winner: G1_LR_interactions** on standard metrics. **But LOCO tells a different story.**

### LOCO — three collapse modes, not one

| Holdout corpus | F1 | Precision | Recall | FP supp |
|---|--:|--:|--:|--:|
| secretbench | 0.242 | 0.688 | 0.147 | 0.933 |
| gitleaks | 0.679 | 0.514 | 1.000 | 0.053 |
| detect_secrets | 0.667 | 0.500 | 1.000 | 0.000 |

Three different failure modes:
- **secretbench holdout** → model predicts NEGATIVE by default (93% suppression, 15% recall)
- **gitleaks holdout** → model predicts POSITIVE by default (0% suppression, 100% recall)
- **detect_secrets holdout** → same pattern, 0% suppression

No corpus generalizes to the others. That is the hallmark of three unrelated concepts wearing the same label.

### Why it collapses — raw NEGATIVE inspection

Examining the actual values each corpus labels NEGATIVE makes the non-generalization obvious:

| Corpus | Character of "NEGATIVE" | Example |
|---|---|---|
| **secretbench** (552 NEGs) | Credential-shaped KV with human-readable values | `PSWRD="anothersecRet4ME!"` |
| **gitleaks** (141 NEGs) | Redactions, placeholders, foreign prose | `SUMO_ACCESS_KEY=xxxxxxxxxxxxxxxx` |
| **detect_secrets** (5 raw NEGs, resampled 30× to 150 shards) | Config literals | `PORT=8080`, `DEBUG=true` |

These share no common structural signal. The ML gate is being asked to learn a union of disjoint concepts and a 4.6% class on 49 features (≈9 samples/feature). Even the top learned feature — `heuristic_dictionary_word_ratio × has_secret_indicators` with coefficient −3.3 — is secretbench-specific and doesn't transfer.

### Verdict

**RED.** The binary PII gate architecture is the wrong primitive for this problem. NEGATIVE is not a single concept.

## Finding 2 — heuristic gate (F2): GREEN on 2 of 3 corpora

If each corpus has its own NEGATIVE pattern, treat them separately. Two rules cover two of three corpora cleanly.

### Rules

- **R2 — config literal:** if ≥30% of values match `KEY = (numeric|boolean|level|short-quoted-string)` at EOL, suppress.
  Example matches: `PORT=8080`, `DEBUG=true`, `LOG_LEVEL=INFO`, `token_expiry = "3600"`.

- **R3 — placeholder noise:** if ≥15% of values contain `[xX*]{4,}`, `#{4,}`, `~{4,}`, bracketed placeholders (`[PASSWORD]`, `[REDACTED]`, `<ANGLE_PLACEHOLDER>`), suppress.
  Example matches: `SUMO_ACCESS_KEY=xxxxxxxxxxxxxx`, `A3-xXXXXX-XXXXX`, `[PASSWORD]`, `<REDACTED>`.

Applied only to columns where the cascade predicts `OPAQUE_SECRET`, `API_KEY`, or `PRIVATE_KEY`.

### Threshold sweep

| R3 threshold | FP supp | TP loss | FP % | TP % |
|--:|--:|--:|--:|--:|
| 0.20 | 103 / 267 | 0 / 707 | 38.6% | 0.0% |
| **0.15** ⬅ recommended | **132 / 267** | **2 / 707** | **49.4%** | **0.3%** |
| 0.10 | 167 / 267 | 16 / 707 | 62.5% | 2.3% |
| 0.05 | 229 / 267 | 83 / 707 | 85.8% | 11.7% |

R2 stays at 0.30 throughout (no TP loss at any threshold tested). The cost curve is sharp — below R3=0.10 TP loss blows up, above R3=0.20 FP capture degrades fast.

### Per-corpus suppression @ R3=0.15

| Corpus | FP supp | TP loss |
|---|--:|--:|
| detect_secrets | **75 / 75 (100%)** | 0 / 147 |
| gitleaks | **54 / 76 (71%)** | 0 / 143 |
| secretbench | 3 / 116 (3%) | 2 / 135 |

detect_secrets and gitleaks are cleanly solved. secretbench is not solvable by structural rules — see Finding 3.

### Verdict

**GREEN for R2+R3 on detect_secrets and gitleaks.** Promote to Sprint 14 production item. Implementation surface: ~100 lines in a new `orchestrator/credential_gate.py`, two regex-backed helpers, gate applied post-cascade when primary_entity ∈ {OPAQUE_SECRET, API_KEY, PRIVATE_KEY}. Tests against the 267-FP corpus + regression on the 707 CREDENTIAL TPs.

## Finding 3 — SecretBench is not what we thought it was

### What SecretBench actually is

- **Source:** Basak & Neil et al., MSR 2023 — [arxiv:2303.06729](https://arxiv.org/abs/2303.06729) — repo at [setu1421/SecretBench](https://github.com/setu1421/SecretBench).
- **Size:** 97,479 candidate secrets from 818 public GitHub repos. 15,084 labeled True. Distributed via Google BigQuery / Cloud Storage under a data-protection agreement.
- **Schema:** each row has a `secret` field (the scanner's capture, bracketed), `label` (True/False), `file_path`, `start_line`, `start_column`, `end_line`, `end_column`, and structural feature columns (`is_template`, `has_words`, `entropy`, `is_multiline`).
- **Labeling methodology** (per the paper): *"researchers determined whether each candidate secret was actual or not after inspecting the secret and the source code context."*

### The semantic gap

SecretBench answers: *"Given this file at these coordinates, did a secret-detection tool's match correspond to a real leak?"* — a tool-alignment/evaluation question.

data_classifier asks: *"Is this column value a secret?"* — a value-classification question.

These are different. A row like `"Have you heard of the passwd application that was being started by froderick?"` carries `is_secret=True` in SecretBench because the file it came from leaked a real secret *somewhere* and the scanner's regex fired on this line due to the keyword "passwd". That does not make the prose sentence itself a secret.

### Seven canonical mislabel shapes

Found in the `is_secret=True` side of our 1,068-row fixture:

| Shape | Count | Example |
|---|--:|---|
| Bare variable reference | 88 | `PSWRD="${env.PSWRD}"` |
| Prose sentence | 38 + 4 (reviewed) | `Have you heard of the passwd application...` |
| Empty credential value | 12 | `my_password =` |
| Value equals key name | 11 + 1 (reviewed) | `password = "password"` |
| PEM header only | 5 | `-----BEGIN RSA PRIVATE KEY-----` (no body) |
| Placeholder literal | 3 | `AKIAI44QH8DHBEXAMPLE` |
| Empty XML tag | 3 + 1 (reviewed) | `<Password></Password>` |
| Trivially-short value | 3 + 1 (reviewed) | `"password": "a"` |
| XML tag fragment | 2 | bare `<Password>` |
| Code syntax reference | 1 | `case "Password":` |
| Function-call getter | 1 | `password=credentials.getPassword();` |
| Misc user-reviewed | 5 | JSON-snippet + keyboard-mash prose, shell `$1` args, template `{password}` |

Side-by-side comparison of secretbench NEGATIVE vs POSITIVE shards confirms they are structurally indistinguishable at every feature tested (entropy distribution, length, dict-word ratio, distinct ratio, max-len). The literal string `thisIsMyP@$$w0rd1-Ha-Ha!` appears in both POS-labeled and NEG-labeled shards — the distinction is provenance, not appearance.

### Quantification

| Side | Count | Mislabel rate (our semantics) |
|---|--:|--:|
| `is_secret=True` | 516 | **178 / 516 = 34.5%** (167 auto + 11 user-reviewed) |
| `is_secret=False` | 552 | ≈ 5% (28 potential hits on provider-shape patterns, most with `EXAMPLE`/sequence-placeholder context) — **direction left untouched** because upstream's label is plausible under its own semantics |

### Implication

The Sprint 13 benchmark's "CREDENTIAL precision 0.7214 / 273 FPs" metric had a structural label-noise floor. Some fraction of the 273 "FPs" are cascade-correct calls that secretbench-v1 happens to disagree with at the file-context level; some fraction of the 707 "TPs" are upstream-positive on values that aren't secrets.

## Finding 4 — v2 fixture

Script: `scripts/relabel_secretbench.py`. Output at `tests/fixtures/corpora/secretbench_sample_v2.json` plus per-rule audit trail under `docs/experiments/meta_classifier/runs/20260417-secretbench-relabel/`.

### Before / after

| | is_secret=True | is_secret=False |
|---|--:|--:|
| upstream (v1) | 516 | 552 |
| v2 | 338 | 730 |

### Provenance

- 167 flips from 11 conservative structural rules (auto)
- 11 flips from edge-case human review (user-confirmed 2026-04-17, all confirmed *not* a secret)
- 0 flips in the `False → True` direction (out of scope for this pass)
- Every flipped row carries `relabel_rule`, `relabel_notes`, and `upstream_is_secret` fields for audit

### Scope limits

- Only our 1,068-row fixture sample. The full SecretBench (97,479 rows) is not relabeled here — would require BigQuery access + DPA sign-off.
- Production code under `data_classifier/` still reads `secretbench_sample.json` (v1). Benchmark adoption of v2 is a Sprint 14 decision, not an artifact of this research.

## Sprint 14 recommendations

### Ship

1. **F2 gate (R2+R3)** as `orchestrator/credential_gate.py`. Apply when primary_entity ∈ {OPAQUE_SECRET, API_KEY, PRIVATE_KEY}. Thresholds R2=0.30, R3=0.15. Tests: regression on 707 CREDENTIAL TPs (≤2 losses), suppression on 267 FPs (≥130). File as `backlog/credential-gate-heuristic-shipping.yaml` P1.
2. **Adopt `secretbench_sample_v2.json` in family benchmark** as the primary CREDENTIAL ground truth. Keep v1 available under `docs/experiments/.../v1_upstream.json` for reproducibility of historical numbers.

### File as research follow-ups

3. **Full SecretBench native evaluation harness.** Pull the BigQuery table, download the 818 source files, score the cascade at line/span granularity — SecretBench's intended evaluation mode. Gives us tool-alignment precision separate from value-classification precision.
4. **Full-corpus value-level relabel.** If value-level labels are useful on the full 97,479 rows, extend `relabel_secretbench.py` and run over the BigQuery export. Effort: a day once the data is in hand.
5. **Corpus diversification for future gates.** If we ever revisit a learned suppression gate, we need ≥5 structurally-distinct NEGATIVE sources (not 3), each with ≥100 distinct values. The 5-distinct-values-resampled-30× pattern in detect_secrets is the main reason LOCO collapsed.

### Retire

6. **Binary PII gate as a production architecture.** The RED verdict is well-supported. Revisit only if the class definition changes (e.g., we adopt a new NEGATIVE corpus that does share a structural signal).

## Reproducibility

| Step | Command |
|---|---|
| Regenerate training data | `.venv/bin/python -m tests.benchmarks.meta_classifier.build_training_data --output tests/benchmarks/meta_classifier/training_data_binary_gate.jsonl` |
| Retrain binary gate | `.venv/bin/python scripts/train_binary_pii_gate.py --input tests/benchmarks/meta_classifier/training_data_binary_gate.jsonl --out-dir docs/experiments/meta_classifier/runs/20260417-binary-pii-gate --arms G0_LR G1_LR_interactions G2_XGBoost G3_MLP --loco-subset secretbench gitleaks detect_secrets` |
| Rerun F2 heuristic evaluation | see `/tmp/f2_fps_with_values.jsonl` generation inline in this memo's source session; will be formalized into `scripts/evaluate_credential_gate.py` when promoted to Sprint 14 |
| Rerun relabel | `.venv/bin/python scripts/relabel_secretbench.py --input tests/fixtures/corpora/secretbench_sample.json --out-dir docs/experiments/meta_classifier/runs/20260417-secretbench-relabel` |

## Sources

- Basak, Neil, et al. "SecretBench: A Dataset of Software Secrets." MSR 2023. [arxiv:2303.06729](https://arxiv.org/abs/2303.06729) · [GitHub: setu1421/SecretBench](https://github.com/setu1421/SecretBench) · [NSF PAR PDF](https://par.nsf.gov/servlets/purl/10505638)
- Our Sprint 13 handover: `docs/sprints/SPRINT13_HANDOVER.md`
- Sprint 13 family benchmark: `docs/research/meta_classifier/sprint13_final_family_benchmark.json`
- Backlog item: `backlog/research-binary-pii-gate-model-evaluation.yaml`
