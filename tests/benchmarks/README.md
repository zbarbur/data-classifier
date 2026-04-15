# Benchmarks

This directory contains the accuracy and performance benchmarks used
for sprint quality gates and historical measurement.

## The official sprint quality metric: `family_accuracy_benchmark`

**Use this for sprint closure reporting.** It runs the full orchestrator
over every labeled training shard (~10,170 columns, ~35s wall clock
with `DATA_CLASSIFIER_DISABLE_ML=1`) and produces a single summary
JSON carrying both the live-cascade and meta-classifier shadow
predictions, scored at two tiers.

### Tiered evaluation

**Tier 1 (scored, primary):** *family-level* precision, recall, and
macro F1. The family taxonomy is defined in
[`data_classifier.core.taxonomy`](../../data_classifier/core/taxonomy.py)
and exported as public API (`data_classifier.FAMILIES`,
`data_classifier.family_for`). Cross-family errors —
calling a credit card a URL, or calling a non-sensitive column a
credential — are real product quality gaps that change downstream
handling and regulatory scope. The `cross_family_error_rate` and
`family_macro_f1` numbers are the **sprint quality gate**.

**Tier 2 (informational, secondary):** *subtype-level* precision,
recall, and macro F1. Within a family, the classifier's specific
subtype choice (API_KEY vs OPAQUE_SECRET, DATE_OF_BIRTH vs
DATE_OF_BIRTH_EU) is nice-to-have metadata for downstream tools but
does not change sensitivity tier or regulatory treatment. Reported
for debugging only; not part of the sprint quality gate.

### Running it

```bash
DATA_CLASSIFIER_DISABLE_ML=1 \
    python -m tests.benchmarks.family_accuracy_benchmark \
    --out /tmp/bench.predictions.jsonl \
    --summary /tmp/bench.summary.json
```

For sprint-to-sprint deltas, pass the previous sprint's committed
summary:

```bash
python -m tests.benchmarks.family_accuracy_benchmark \
    --out /tmp/bench.predictions.jsonl \
    --summary /tmp/bench.summary.json \
    --compare-to docs/research/meta_classifier/sprint11_family_benchmark.json
```

The `--compare-to` output adds a `delta_vs_previous` section to the
summary with per-split, per-tier movement in `cross_family_rate` and
`family_macro_f1`.

### Expected output shape

```json
{
  "n_shards": 10170,
  "n_families": 12,
  "live": {
    "overall": { "family": { "cross_family_rate": 0.157, "family_macro_f1": 0.835, "per_family": {...} },
                  "subtype": { "accuracy": 0.750, "macro_f1": 0.776, "per_class": {...} } },
    "named":   { ... },
    "blind":   { ... }
  },
  "shadow": { "overall": { ... }, "named": { ... }, "blind": { ... } }
}
```

### Sprint 11 reference numbers

From `docs/research/meta_classifier/sprint11_family_benchmark.json`
(committed post-Sprint-11 batch):

| Path | cross_family_rate | family_macro_f1 |
|---|---:|---:|
| LIVE (live cascade only) | 0.1571 | 0.8351 |
| SHADOW (meta-classifier v3) | **0.0584** | **0.9286** |

**The Sprint 11 batch's headline deliverable is the shadow-path
drop from 0.4771 to 0.0584** — an 8.2× reduction in cross-family
errors. The live path is bit-for-bit unchanged (0.1571 on both
sides of the sprint), which is the expected behavior of a
shadow-first batch.

Sprint 12's stretch target is shadow `cross_family_rate < 0.030`,
reached primarily through two feature-engineering items:

1. `validator_rejected_credential` feature — targets NEGATIVE family
   recall (currently 0.478) by telling the meta-classifier when the
   live-path validator chain rejected a credential-shaped value.
2. `has_dictionary_name_match` feature — targets the remaining
   catch-all confusions landing in the CONTACT family.

## Other benchmarks in this directory

- [`accuracy_benchmark.py`](accuracy_benchmark.py) — Sprint 7 "Compare
  & Measure" harness. Aggregates samples per entity type into
  single columns (yielding only ~12 columns per run) and reports
  per-entity-type P/R. Still useful for spot-checks on specific
  real corpora; **not** the sprint gate.
- [`pattern_benchmark.py`](pattern_benchmark.py) — per-pattern
  precision/recall over the real-corpus suite.
- [`perf_benchmark.py`](perf_benchmark.py) / [`perf_quick.py`](perf_quick.py)
  — wall-clock performance measurements.
- [`secret_benchmark.py`](secret_benchmark.py) — credential-specific
  detection benchmark, uses the SecretBench + gitleaks + detect_secrets
  corpora.
- [`meta_classifier/`](meta_classifier/) — training data builder,
  per-class diagnostic, and shard builder consumed by
  `family_accuracy_benchmark`.

## Adding new subtypes

When a new entity type is added to the library, update
[`data_classifier/core/taxonomy.py`](../../data_classifier/core/taxonomy.py)
to assign it to a family. If the new type doesn't fit any existing
family cleanly, the benchmark will emit a warning and
`ClassificationFinding.family` will fall back to the subtype as a
singleton family until the mapping is updated.
