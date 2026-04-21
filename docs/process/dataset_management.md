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

## CI considerations

- **Unit tests** use fixtures (`tests/fixtures/`), NOT DVC datasets. CI does not
  need `dvc pull`.
- **Family accuracy benchmark** (`tests/benchmarks/`) uses fixture corpora
  (samples bundled in the repo). No DVC dependency.
- **Research scripts** (`scripts/s0_*.py`, `scripts/s2_*.py`) DO need DVC data.
  These run locally, not in CI.
- If a future CI job needs dataset access: add `dvc pull data/<name>.dvc` to the
  CI workflow with GCS credentials via secret.

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
