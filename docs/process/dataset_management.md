# Dataset Management — DVC + GCS

**Bucket**: `gs://data-classifier-datasets/dvc-cache`
**GCP project**: `dag-bigquery-dev`
**DVC remote name**: `gcs` (default)

---

## Overview

Datasets are tracked by DVC (Data Version Control). Git stores small `.dvc` pointer
files; actual data lives in GCS and is pulled on demand. This keeps large files
out of git history while providing versioned, reproducible dataset access.

```
data/                          ← gitignored by DVC, actual data
├── wildchat_1m/
│   └── train.parquet
├── ai4privacy_openpii/
│   └── train.parquet
├── nemotron_pii/
│   └── train.parquet
├── gretel_en/
│   └── *.parquet
└── gretel_finance/
    └── *.parquet

data/wildchat_1m.dvc           ← tracked in git (pointer: hash + size)
data/ai4privacy_openpii.dvc
...
```

---

## Quick reference

### Pull datasets on a new machine

```bash
# One-time GCP auth (if not already authenticated)
gcloud auth application-default login

# Pull all datasets
.venv/bin/dvc pull

# Pull only what you need
.venv/bin/dvc pull data/wildchat_1m.dvc
```

### Add a new dataset

```bash
# 1. Download to data/<name>/
mkdir -p data/my_dataset
.venv/bin/python -c "
from datasets import load_dataset
ds = load_dataset('org/dataset-name', split='train')
ds.to_parquet('data/my_dataset/train.parquet')
"

# 2. Track with DVC
.venv/bin/dvc add data/my_dataset

# 3. Commit pointer + gitignore update
git add data/my_dataset.dvc data/.gitignore
git commit -m 'data: add my_dataset via DVC'

# 4. Push data to GCS
.venv/bin/dvc push
```

### Update an existing dataset

```bash
# Re-download or modify data/my_dataset/
# ...

# DVC detects the change
.venv/bin/dvc add data/my_dataset
git add data/my_dataset.dvc
git commit -m 'data: update my_dataset'
.venv/bin/dvc push
```

### Check what's tracked

```bash
.venv/bin/dvc status          # local changes vs pointer files
.venv/bin/dvc status --cloud  # local vs what's in GCS
```

---

## Using datasets in code

### Helper: `data_classifier.datasets.load_local_or_remote`

Scripts should use the project helper instead of calling `load_dataset()` directly.
The helper checks for local DVC data first, falls back to HuggingFace streaming
if not hydrated:

```python
from data_classifier.datasets import load_local_or_remote

# Returns a HuggingFace Dataset object either way
ds = load_local_or_remote("wildchat_1m")
ds = load_local_or_remote("nemotron_pii")
```

Behavior:
- If `data/{name}/` exists locally → `load_dataset("parquet", data_files=...)`
- Otherwise → `load_dataset(HF_REGISTRY[name], streaming=True)` with a warning

This means scripts work on any machine:
- **With DVC hydrated**: instant local load, offline-capable
- **Without DVC**: falls back to HF streaming (slower, needs network)

### Dataset registry

The helper maintains a registry mapping local names to HuggingFace identifiers:

| Local name | HuggingFace ID | License | Notes |
|---|---|---|---|
| `wildchat_1m` | `allenai/WildChat-1M` | CC0 | Primary prompt corpus |
| `ai4privacy_openpii` | `ai4privacy/pii-masking-300k` | CC-BY-4.0 | PII benchmark (methodology-only, see Sprint 9 license note) |
| `nemotron_pii` | `nvidia/Nemotron-PII` | CC-BY-4.0 | PII benchmark |
| `gretel_en` | `gretelai/gretel-pii-masking-en-v1` | Apache 2.0 | Primary blind corpus |
| `gretel_finance` | `gretelai/gretel-pii-finance-multilingual` | Apache 2.0 | Finance-specific PII |

---

## Benchmark fixtures (DVC-tracked)

The family-accuracy and meta-classifier benchmarks load **pre-flattened
sample JSONs** from `tests/fixtures/corpora/`. These are not the raw
HuggingFace datasets — they are post-ETL extracts produced by
`scripts/download_corpora.py` and pinned to specific shapes the
`shard_builder` expects. The full set is required; partial fixture
loads silently undermeasure the benchmark and have caused at least
one historical measurement artifact (Sprint 17).

| File | Source corpus | Used by |
|---|---|---|
| `gretel_en_sample.json` | `gretelai/gretel-pii-masking-en-v1` | `_gretel_en_pool`, `load_gretel_en_corpus` |
| `gretel_finance_sample.json` | `gretelai/gretel-pii-finance-multilingual` | `_gretel_finance_pool`, `load_gretel_finance_corpus` |
| `nemotron_sample.json` | `nvidia/Nemotron-PII` | `_nemotron_pool`, `load_nemotron_corpus` |
| `openpii_1m_sample.json` | `ai4privacy/pii-masking-300k` (1M variant) | `_openpii_1m_pool`, `load_openpii_1m_corpus` |
| `secretbench_sample_v2.json` | SecretBench v2 export | `_credential_corpus_pool('secretbench')` |
| `gitleaks_fixtures.json` | gitleaks-tuned positives + TN | `_credential_corpus_pool('gitleaks')`, `load_gitleaks_corpus` |
| `detect_secrets_fixtures.json` | hand-curated detect_secrets positives | `_credential_corpus_pool('detect_secrets')`, `load_detect_secrets_corpus` |

The canonical regen path is `dvc pull tests/fixtures/corpora.dvc`.
Local-only alternative when GCS auth is unavailable:
`python scripts/download_corpora.py --all`.

The shard builder enforces presence at startup via
`tests.benchmarks.meta_classifier.shard_builder.verify_required_fixtures()`,
which raises a single `FileNotFoundError` listing every missing file.
The internal `_load_raw_records` helper also raises `FileNotFoundError`
on the per-call path — silent `[]` fallbacks were retired in Sprint 18.

## WildChat labeled evaluation set (DVC-tracked)

`data/wildchat_labeled_eval/labeled_set.jsonl` is the locked regression
corpus used by `tests/test_wildchat_labeled_regression.py`. It carries
the full 3,515-prompt WildChat credential corpus (XOR-encoded) joined
with **334 human-reviewed prompts** from the Sprint 14/15
`prompt_reviewer.py` web tool — 425 finding-level TP verdicts and
549 FP verdicts.

Per-row schema:

| Field | Description |
|---|---|
| `prompt_id` | Stable id matching `data/wildchat_eval/wildchat_eval_v2.jsonl` |
| `prompt_xor` | Base64-XOR-encoded prompt text (per repo policy — never commit cleartext WildChat secrets) |
| `scanner_findings` | Snapshot of `scan_text` output at build time |
| `old_findings` | Historical findings from the v2 GT build |
| `human_verdicts` | `{finding_idx: "tp"\|"fp"}` from manual review (None for unreviewed rows) |
| `label` | Row-level summary: `TP_REVIEWED` / `FP_REVIEWED` / `MIXED_REVIEWED` / `UNREVIEWED_POSITIVE` / `UNREVIEWED_NEGATIVE` |
| `reviewed` | bool |

Regenerate locally:

```bash
.venv/bin/python scripts/build_wildchat_labeled.py
dvc add data/wildchat_labeled_eval
dvc push data/wildchat_labeled_eval.dvc
git add data/wildchat_labeled_eval.dvc data/.gitignore
```

Pull on a fresh checkout / CI:

```bash
dvc pull data/wildchat_labeled_eval.dvc
```

The regression test (`tests/test_wildchat_labeled_regression.py`)
auto-skips when the labeled set is absent. CI hydrates it via the
existing `dvc pull tests/fixtures/corpora.dvc` path; this corpus
lives at the repo level (`data/`), not the test fixtures level.

---

## CI Setup

CI pulls DVC fixtures (`tests/fixtures/corpora.dvc`) using a GCS service-account
key stored as the `GCS_SA_KEY` GitHub secret. Two jobs require this auth:
`lint-and-test` (Python tests across 3 versions) and `browser-parity` (Vitest
+ Playwright). DVC pull failure is fail-loud — CI exits 1 with an actionable
error, no silent skipping.

### One-time setup

```bash
# 1. Create a read-only service account for CI
gcloud iam service-accounts create dvc-ci-reader \
  --display-name="DVC CI Reader" \
  --project=dag-bigquery-dev

# 2. Grant read access to the dataset bucket
gcloud projects add-iam-policy-binding dag-bigquery-dev \
  --member="serviceAccount:dvc-ci-reader@dag-bigquery-dev.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"

# 3. Generate a JSON key (one-shot; do not commit)
gcloud iam service-accounts keys create ~/dvc-ci-key.json \
  --iam-account=dvc-ci-reader@dag-bigquery-dev.iam.gserviceaccount.com

# 4. Upload to GitHub repo secrets
gh secret set GCS_SA_KEY < ~/dvc-ci-key.json

# 5. Delete the local key (no long-term storage on dev box)
rm ~/dvc-ci-key.json
```

### How CI uses the key

The workflow runs `google-github-actions/auth@v2` before `Install DVC`. The
auth action exports `GOOGLE_APPLICATION_CREDENTIALS` so `dvc pull`
authenticates automatically. If `dvc pull` fails — missing secret, network
issue, revoked key, bucket permission change — the job exits 1 with an error
message naming the likely cause.

### Future hardening: WIF

Workload Identity Federation removes the long-lived JSON key entirely.
Tracked as future infrastructure work; not in scope until SA keys become a
compliance pain point.

### Local development

Local development uses `gcloud auth application-default login` (not the CI
service account). Project IAM grants Storage Object Viewer to authenticated
Google accounts.

### Tests that depend on DVC fixtures

- **Family accuracy benchmark** (`tests/benchmarks/family_accuracy_benchmark.py`)
  — uses both bundled samples AND DVC-tracked corpora. Runs in `lint-and-test`.
- **Browser parity** (`scripts/ci_browser_parity.sh`) — compares JS scanner
  output against Python on DVC-tracked WildChat samples.
- **Research scripts** (`scripts/s0_*.py`, `scripts/s2_*.py`) — need DVC data
  but run locally, not in CI.
- Most unit tests in `tests/test_*.py` use bundled `tests/fixtures/` and do
  NOT need DVC. They still run on every CI invocation.

---

## Cross-branch behavior

DVC pointer files (`.dvc`) travel with git. When branch A adds a new dataset and
branch B merges from A, branch B gets the pointer file and can `dvc pull` to
hydrate.

The `data/` directory itself is gitignored — each worktree hydrates independently
via `dvc pull`. This means:

- Main worktree: `dvc pull` hydrates `data/`
- Research worktree: same `dvc pull` hydrates a separate `data/` copy
- Shared GCS cache means no redundant uploads

---

## Storage costs

GCS Standard in us-central1:
- Storage: $0.020/GB/month
- Estimated total (~5 GB): ~$0.10/month
- Download egress (same region): free
- Download egress (internet): $0.12/GB (but research is local, not cloud)

---

## Troubleshooting

**`dvc pull` fails with auth error**:
```bash
gcloud auth application-default login
```

**Dataset not found locally after `dvc pull`**:
```bash
dvc status          # check if pointer is up to date
dvc pull -f         # force pull
```

**Large download taking too long**:
Pull only what you need: `dvc pull data/wildchat_1m.dvc`

**New worktree has no data/**:
Expected. Run `dvc pull` in the new worktree to hydrate.
