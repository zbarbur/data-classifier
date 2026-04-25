# data_classifier — Client Integration Guide

> **Audience:** Connector teams (BigQuery, Snowflake, Postgres, etc.)
> **Version:** 0.12.0 (Sprints 9 / 10 / 11 / 12 bundled — shadow meta-classifier, family taxonomy, expanded patterns, v0.8.0-compatible live path)
> **Date:** 2026-04-16
> **Status:** READY — forward-only versioning continues from `v0.8.0`; see `CHANGELOG.md` for the full per-sprint change log

---

## 1. What Is This Library?

`data_classifier` is a standalone, stateless Python library for detecting and classifying sensitive data in structured database columns. It replaces the `classifier/engine.py` module currently embedded in the BigQuery connector.

**Key properties:**

- **Stateless** — never connects to a database, never writes to disk
- **Connector-agnostic** — knows nothing about BigQuery, Snowflake, or Postgres
- **The connector's job:** collect column metadata + sample values → pass to library → receive findings → persist results
- **The library's job:** run classification engines → return typed findings with confidence and evidence

---

## 1a. Installation Tiers

Choose the tier that fits your deployment:

| Tier | Install | Size | What you get | Latency |
|------|---------|------|--------------|---------|
| **Light** | `pip install data_classifier` | ~5MB | Regex + column name + heuristic + secret scanner engines | ~15ms/col |
| **Standard (recommended)** | `pip install "data_classifier[ml]"` | ~70MB (+ ~200MB ONNX model fetched separately — see below) | + GLiNER2 NER engine for PERSON_NAME, ADDRESS, ORGANIZATION detection | ~80ms/col |
| **Developer / export** | `pip install "data_classifier[ml-full]"` | ~2.5GB | + PyTorch / transformers / onnx — required for `python -m data_classifier.export_onnx` and model fine-tuning; **not** required at runtime | N/A (build-time only) |

> **Changed in v0.8.0 (Sprint 8):** the `[ml-api]` extra was removed. It
> declared a package name that did not match what `gliner_engine.py`
> imports, and no consumer used it. Standard tier with a locally-bundled
> ONNX model is the correct production path. See `CHANGELOG.md`.

> **What's new in v0.12.0 (Sprints 9 / 10 / 11 / 12):**
>
> **No behavior change on the live path.** `classify_columns()` returns
> the same `list[ClassificationFinding]` shape as `v0.8.0` on
> structured single-entity columns (Sprint 8's test distribution).
> The 7-pass merge remains the source of truth for the orchestrator's
> return values. You do not need to change any existing consumer code
> to adopt `v0.12.0`.
>
> **What's additive:**
>
> - **`ClassificationFinding.family`** — new non-breaking field on every
>   finding. 13-family taxonomy around downstream DLP handling
>   (CONTACT, CREDENTIAL, FINANCIAL, GOVERNMENT_ID, HEALTHCARE, ...).
>   Auto-populated; consumers that ignore it continue to work. See §3
>   "Output Models" for the full list.
> - **Shadow meta-classifier v5** — accessible via
>   `ClassificationEvent.meta_classification` on every event when the
>   `[meta]` extra is installed. Observability-only; does not modify
>   `classify_columns()` return values. Useful for DLP policy telemetry
>   and pre-promotion evaluation.
> - **Expanded pattern coverage** — secret-key-name dictionary
>   88 → 178 entries, new structural validators
>   (Bitcoin base58check / bech32, Ethereum EIP-55 checksum,
>   placeholder-credential rejection), tighter secret-scanner
>   `id_token` / `token_secret` matching.
> - **GLiNER2 data_type pre-filter** — the ML engine now skips columns
>   whose `ColumnInput.data_type` is non-textual (INTEGER, DATE, etc.),
>   eliminating numeric-column false positives.
>
> **What's deprecated:**
>
> - `DATE_OF_BIRTH_EU` subtype emission. Columns that would have
>   emitted `DATE_OF_BIRTH_EU` now emit `DATE_OF_BIRTH` — both are in
>   the `DATE` family, so family-level routing is unchanged. See
>   `CHANGELOG.md` for the rationale.
>
> **What did NOT ship (and why):**
>
> - The meta-classifier's directive promotion was evaluated in Sprint
>   12 and **deferred to Sprint 13** after the Phase 5b safety audit
>   returned RED on heterogeneous columns. See
>   `docs/research/meta_classifier/sprint12_safety_audit.md`. The
>   shadow meta-classifier is observability-only on this release.

**What Light tier misses:** `PERSON_NAME`, `ADDRESS`, and `ORGANIZATION` detection from sample values. These entity types require NER (ML). If your columns have meaningful names (e.g., `full_name`, `street_address`), the column name engine still detects them without ML. ML is only needed when column names are generic or missing.

### 1b. Install recipes

> **Quick reference — pick the recipe that matches your deployment shape.** All recipes pin to `v0.12.0`.

**(A) Google Artifact Registry — recommended for GCP consumers** (including the BigQuery connector):

```bash
pip install \
  --extra-index-url https://us-central1-python.pkg.dev/dag-bigquery-dev/data-classifier/simple/ \
  "data_classifier[ml]==0.12.0"
```

The `data-classifier` Python repository lives in the `dag-bigquery-dev` GCP project under `us-central1`. Auth is handled transparently by the `keyrings.google-artifactregistry-auth` plugin — install it alongside pip:

```bash
pip install keyring keyrings.google-artifactregistry-auth
```

...and either run as a service account with `artifactregistry.reader` on `dag-bigquery-dev`, or authenticate via `gcloud auth application-default login` on developer machines. Inside Cloud Build, the default Cloud Build service account already has credentials — no extra setup.

**(B) Vendored wheel — monorepo / air-gapped / pre-sprint-8 compatibility**

```bash
# Once (on a machine with write access to a shared location or repo):
python -m build --wheel
cp dist/data_classifier-0.12.0-py3-none-any.whl <vendor-location>/

# In the consumer's pyproject.toml:
"data_classifier[ml] @ file:vendor/data_classifier-0.12.0-py3-none-any.whl"
```

**(C) Git SSH — for CI systems with a deploy key**

```bash
pip install "data_classifier[ml] @ git+ssh://git@github.com/zbarbur/data-classifier.git@v0.12.0"
```

**(D) Local editable — for development on a workspace with both repos checked out**

```bash
pip install -e "../data_classifier[ml]"
```

**Version pinning:** Always pin to a released tag (`==0.12.0` or `@v0.12.0`), never track a branch in production. The release tag is authoritative; sprint branches and `main` are moving targets.

### 1c. The GLiNER2 ONNX model (Standard tier only)

GLiNER2 needs an ONNX model file at runtime. The `[ml]` extra installs the Python bindings but **not** the model weights — those are ~200MB and distributed separately.

**For container deployments (Cloud Run, etc.):** bake the model into the image at build time so runtime has no network dependency on HuggingFace:

```dockerfile
# Dockerfile snippet for BQ connector / any container deployment
RUN pip install \
    --extra-index-url https://us-central1-python.pkg.dev/dag-bigquery-dev/data-classifier/simple/ \
    "data_classifier[ml]==0.8.0" && \
    python -m data_classifier.download_models
```

`python -m data_classifier.download_models` is a lean CLI (stdlib-only — uses `urllib.request`, `hashlib`, `tarfile`, and `subprocess`; **no `torch`, `transformers`, `onnx`, or `requests`** in the import graph) that fetches the pre-exported GLiNER ONNX tarball from the `data-classifier-models` Google Artifact Registry Generic repo in `dag-bigquery-dev`, verifies its SHA-256 against a companion `.sha256` file, and unpacks it into `~/.cache/data_classifier/models/gliner_onnx/`. The `GLiNER2Engine` auto-discovers model files at that path via `_find_bundled_onnx_model()`, so no engine config is needed.

**Model versioning is decoupled from `data_classifier` versioning.** The ONNX tarball is a separate build-time artifact derived from the upstream `urchade/gliner_multi_pii-v1` HuggingFace checkpoint. It does *not* rev when we ship a new `data_classifier` release — the same base model is used across many sprints, and re-exporting it on every library release would be pure waste (~10 min of `pip install [ml-full]` + re-running the same HF→ONNX conversion on unchanged upstream weights). When the upstream base model changes (rarely — at most once every few quarters), a human bumps `DEFAULT_MODEL_VERSION` in `data_classifier/download_models.py` and uploads a new tarball.

**CLI flags:**

| Flag | Default | Purpose |
|---|---|---|
| `--to PATH` | `~/.cache/data_classifier/models/gliner_onnx/` | Override the install location |
| `--version VERSION` | `urchade-gliner_multi_pii-v1` (the pinned GLiNER model version — **not** the data_classifier version) | Fetch a different model release |
| `--url URL` | AR Generic REST endpoint derived from `--version` | Override the full tarball URL (mirrors, testing) |
| `--checksum-url URL` | Derived from `--url` | Override the checksum URL independently |
| `--access-token TOKEN` | Auto-discovered via metadata service or `gcloud` | Explicit GCP access token for AR authentication |
| `--force` | off | Overwrite an existing target directory |
| `--quiet` | off | Suppress progress output |

**Auth token discovery order** (first hit wins):

1. `--access-token` CLI flag (explicit)
2. `GCP_ACCESS_TOKEN` environment variable
3. GCP metadata service (`metadata.google.internal` — the BQ Cloud Build path; zero setup)
4. `gcloud auth print-access-token` (dev-machine fallback, only tried if `gcloud` is on `PATH`)

The metadata service path means **BQ's Dockerfile needs no extra setup** — Cloud Build automatically exposes the build SA's token to steps running on the builder VM. If none of the four paths yield a token, the download proceeds without authentication (useful for public mirrors via `--url`).

**Safety guarantees:**
- SHA-256 mismatch aborts before touching the target directory — any existing model stays intact
- Tarball extraction uses a resolved-path containment check plus `tarfile.data_filter` (on Python 3.12+) to block path-traversal attacks
- No raw tracebacks: every handled failure exits with a single-line error on stderr and a non-zero exit code

**Required IAM on the BQ Cloud Build service account:** `roles/artifactregistry.reader` on the `data-classifier-models` AR Generic repo (or project-wide). Writer permission is NOT needed — the Docker build is a consumer, not a publisher.

**For dev / one-off export:** if you want to regenerate the ONNX model from a HuggingFace checkpoint (e.g. to experiment with a different base model), install the developer extra and run the exporter:

```bash
pip install "data_classifier[ml-full]"
python -m data_classifier.export_onnx --user  # writes to ~/.cache/data_classifier/models/gliner_onnx/
```

This is a one-time step and is **not** part of the production container image.

### 1d. Environment variables

| Variable | Effect |
|---|---|
| `DATA_CLASSIFIER_DISABLE_ML` | If set to any truthy value, skip GLiNER2 engine entirely. Useful for regex-only benchmarking, CI jobs that do not want HuggingFace network dependencies, or emergency fallback when the model is unavailable. |
| `GLINER_ONNX_PATH` | Override the ONNX model search path. If set, takes precedence over `_find_bundled_onnx_model()`'s auto-discovery. |
| `GLINER_API_KEY` | If local model loading fails and this is set, falls back to the GLiNER hosted API (`gliner.pioneer.ai`). Not recommended for production — network round-trip latency is high. |

### 1e. Observability and live telemetry

`data_classifier` ships two observability surfaces: **Python logging** (zero-setup, always-on) and a **pluggable event emitter** (opt-in, for metrics/tracing integration). Use both in production — they answer different questions.

#### Python logging

Every engine logs via `logging.getLogger("data_classifier.*")` at these levels:

| Level | Examples |
|---|---|
| `INFO` | Engine startup: `RegexEngine: compiled 58 content patterns into RE2 Set`, `GLiNER2Engine: registered 'gliner2-ner' (..., mode=onnx)`, `Model 'gliner2-ner' loaded successfully.` |
| `WARNING` | Fallback paths: `Local model load failed, falling back to API mode` |
| `EXCEPTION` (ERROR + traceback) | Per-engine inference failures inside `Orchestrator`: `Engine gliner2 failed on column <id>` with the underlying exception |

**Recommended consumer setup:**

```python
import logging

# Capture data_classifier logs at INFO+ and route to your log aggregator.
logging.getLogger("data_classifier").setLevel(logging.INFO)

# Optional: raise ML engine logs to WARNING to cut noise once the system
# is stable. Leave at INFO during the first week of a deployment so
# startup messages are visible in the log stream.
logging.getLogger("data_classifier.engines.gliner_engine").setLevel(logging.INFO)
```

If you do not configure logging at all, Python's default root logger will still print `WARNING` and above to `stderr`, so fallback paths and engine exceptions are never fully silent — but `INFO`-level startup messages will be dropped and you will lose "which engines loaded" visibility.

#### Event emitter — per-column, per-engine metrics

`classify_columns()` accepts an optional `event_emitter` parameter. When set, the orchestrator emits two event types:

- **`TierEvent`** — one per engine invocation per column. Fields: `tier` (engine name), `latency_ms`, `outcome` (`"hit"` or `"miss"`), `findings_count`, `column_id`, `run_id`, `timestamp`.
- **`ClassificationEvent`** — one per column, after all engines have run. Fields: `column_id`, `total_findings`, `total_ms`, **`engines_executed: list[str]`**, **`engines_skipped: list[str]`**, `run_id`, `timestamp`.

`engines_executed` and `engines_skipped` are the authoritative answer to *"which engines actually ran on this column?"* — more reliable than parsing log lines, and cheap enough to emit on every call.

Four built-in handler types ship with the library:

```python
from data_classifier.events.emitter import (
    EventEmitter,
    NullHandler,     # default — discards all events
    StdoutHandler,   # JSON lines to stdout, one line per event
    LogHandler,      # forward events via Python logging
    CallbackHandler, # call a user-supplied function per event
)
```

**Example — wiring into Prometheus / Cloud Monitoring / Datadog:**

```python
from data_classifier import classify_columns
from data_classifier.events.emitter import EventEmitter, CallbackHandler
from data_classifier.events.types import TierEvent, ClassificationEvent

def on_event(ev):
    if isinstance(ev, TierEvent):
        metrics.histogram(
            "data_classifier.engine.latency_ms",
            ev.latency_ms,
            tags={"engine": ev.tier, "outcome": ev.outcome},
        )
        metrics.counter(
            "data_classifier.engine.findings_total",
            ev.findings_count,
            tags={"engine": ev.tier},
        )
    elif isinstance(ev, ClassificationEvent):
        metrics.histogram("data_classifier.column.total_ms", ev.total_ms)
        metrics.gauge(
            "data_classifier.column.engines_executed",
            len(ev.engines_executed),
        )
        # Alert on unexpected engine absence in production:
        if "gliner2" not in ev.engines_executed and ev.engines_skipped:
            logger.warning(
                "GLiNER2 not running in production; engines_skipped=%s",
                ev.engines_skipped,
            )

emitter = EventEmitter()
emitter.add_handler(CallbackHandler(on_event))

findings = classify_columns(
    columns,
    profile,
    event_emitter=emitter,
    run_id="scan-2026-04-13-001",  # carried through to every event
)
```

The `run_id` you pass to `classify_columns()` is echoed on every event, so multi-column scans can be grouped and aggregated in dashboards.

#### Engine introspection — `get_active_engines()`

```python
from data_classifier import get_active_engines

for entry in get_active_engines():
    print(entry)
# {'name': 'column_name',      'order': 1, 'class': 'ColumnNameEngine'}
# {'name': 'regex',            'order': 2, 'class': 'RegexEngine'}
# {'name': 'heuristic_stats',  'order': 3, 'class': 'HeuristicEngine'}
# {'name': 'secret_scanner',   'order': 4, 'class': 'SecretScannerEngine'}
# {'name': 'gliner2',          'order': 5, 'class': 'GLiNER2Engine'}
```

Returns the list of engines currently loaded into the default cascade, in execution order. Use this at startup to assert the expected engine set before taking traffic — in particular, `gliner2` will be absent when the `[ml]` extras are not installed or when `DATA_CLASSIFIER_DISABLE_ML=1` is set, and you want to fail loud instead of silently running regex-only.

Note that when GLiNER2 fails to import, the library also logs a `WARNING` via the `data_classifier` logger (`GLiNER2 engine disabled — install [ml] extras to enable: …`). Wire that logger into your aggregator per the "Python logging" section above and you will see the degradation in real time.

#### Startup health probe — `health_check()`

```python
from data_classifier import health_check

result = health_check()
# {
#     "healthy": True,
#     "engines_executed": ["column_name", "regex", "heuristic_stats",
#                          "secret_scanner", "gliner2"],
#     "engines_skipped": [],
#     "latency_ms": 42.7,
#     "findings": [{"entity_type": "EMAIL", "category": "PII",
#                   "sensitivity": "HIGH", "confidence": 1.0}],
#     "error": None,
# }
```

`health_check()` runs a canned one-column probe (`column_name="email_address"`, `sample_values=["alice@example.com"]`) through the standard profile and returns a structured result dict. It is the canonical "is `data_classifier` alive?" check — wire it directly into your `/health` endpoint or service startup code.

Key properties:

- **Never raises.** Any exception inside the probe is caught; the returned dict has `healthy=False` and `error` populated with the exception text. Safe to call from a liveness probe without guard `try/except`.
- **`engines_executed`** is the authoritative answer to "which engines actually ran on the probe". If it omits `gliner2` in a deployment that expects ML, treat it as a deployment error — the wheel was installed without `[ml]` extras, or `DATA_CLASSIFIER_DISABLE_ML` was set, or the ONNX model failed to load.
- **`findings`** confirms the cascade actually produced a result on the canned email — if this list is empty the engine wiring is broken even though nothing raised.
- **Accepts an explicit profile** via `health_check(profile=my_profile)` if you want to probe against a non-standard rule set.

Recommended integration pattern:

```python
from data_classifier import health_check

def readiness() -> tuple[int, dict]:
    result = health_check()
    if not result["healthy"]:
        return 503, result
    if "gliner2" not in result["engines_executed"]:
        # Optional: treat missing ML engine as a hard failure in prod.
        result["warning"] = "gliner2 engine absent — check [ml] extras install"
    return 200, result
```

---

## 1c. Baking the ONNX model into a container image

Production container deployments (Cloud Run, GKE, ECS, etc.) should
**never** download the GLiNER model from HuggingFace at runtime — we
observed HTTP 429 rate-limit failures on Cloud Run cold starts, and
the first-request latency spike is unacceptable for a classification
service. Instead, bake the pre-exported ONNX tarball into the image at
build time using the `data-classifier-download-models` CLI.

This CLI is **stdlib-only** — it does not import `torch`,
`transformers`, `onnx`, or `requests`, so it is safe to run in a lean
`[ml]`-extras container. It downloads a versioned tarball from our
Google Artifact Registry Generic repo, verifies its SHA-256 checksum,
and unpacks it into `~/.cache/data_classifier/models/gliner_onnx/`,
which is one of the three paths that `GLiNER2Engine` auto-discovers at
startup.

**Dockerfile recipe:**

```dockerfile
FROM python:3.11-slim

# Install the library with ML runtime extras only (onnxruntime + gliner,
# no torch, no transformers).
RUN pip install --no-cache-dir "data_classifier[ml]==0.5.0"

# Bake the ONNX model into the image at build time. The CLI defaults to
# ~/.cache/data_classifier/models/gliner_onnx/ which is where
# GLiNER2Engine auto-discovers it at startup — no env vars needed.
RUN data-classifier-download-models

# ...your application setup...
CMD ["python", "-m", "your_app"]
```

**CLI flags:**

| Flag | Default | Purpose |
|---|---|---|
| `--to PATH` | `~/.cache/data_classifier/models/gliner_onnx/` | Destination directory. Parent dirs are created automatically. |
| `--version VERSION` | Installed `data_classifier` version | Model version to fetch (tied to library version). |
| `--url URL` | Artifact Registry URL derived from `--version` | Override the full download URL (internal mirrors, testing). |
| `--checksum-url URL` | `<url>.sha256` | Override the SHA-256 checksum URL. |
| `--force` | off | Re-download even if the target path already exists. |
| `--quiet` | off | Suppress progress output on stdout. |

**Behavior guarantees:**

- Exits 0 on success, non-zero on any failure (no raw tracebacks — you
  get a one-line `error: ...` message on stderr).
- Downloads are SHA-256 verified before extraction. A checksum
  mismatch aborts the download **without touching the target
  directory**, so a corrupt retry cannot leave the container in a
  half-installed state.
- The CLI is idempotent: running it twice is a no-op the second time
  unless you pass `--force`.
- Tar extraction is path-traversal safe (CVE-2007-4559 mitigations).

**Alternatives for air-gapped / internal networks:** use `--url` to
point at an internal mirror of the tarball, or provide a
`--checksum-url` that references your internal checksum file. The CLI
makes no assumptions about DNS or the default Artifact Registry
hostname beyond what you tell it.

---

## 2. What Changes for Connectors

### Before (current BigQuery connector)

```python
# connector.py — current
from classifier.engine import classify_columns, compute_rollups, rollup_from_rollups
from classifier.runner import findings_to_dicts, load_profile, write_rollups

cls_profile = load_profile(classification_profile_name)
all_columns = [col for cols in context.columns.values() for col in cols]
#              ↑ list[dict] with keys: id, name, type, mode, description, policy_tag, table
findings = classify_columns(all_columns, cls_profile)
```

### After (with data_classifier)

```python
# connector.py — after migration
from data_classifier import (
    ColumnInput,
    ClassificationFinding,
    ClassificationProfile,
    RollupResult,
    classify_columns,
    compute_rollups,
    rollup_from_rollups,
    load_profile_from_yaml,
    load_profile_from_dict,
    SENSITIVITY_ORDER,
)

# 1. Load profile (connector still owns DB-first fallback if desired)
cls_profile = load_profile_from_yaml("standard", yaml_path)

# 2. Convert connector's internal column dicts → library's ColumnInput
inputs = [
    ColumnInput(
        column_name=col["name"],
        column_id=col["id"],
        table_name=col.get("table", ""),
        dataset=col.get("dataset", ""),
        schema_name=col.get("schema", ""),
        data_type=col.get("type", ""),
        description=col.get("description", ""),
        # NEW: pass sample values if collected (see Section 4)
        sample_values=col.get("sample_values", []),
    )
    for col in all_columns
]

# 3. Classify
findings = classify_columns(inputs, cls_profile)

# 4. Rollups — same API as before
table_rollups = compute_rollups(findings, col_to_table)
dataset_rollups = rollup_from_rollups(table_rollups, table_to_dataset)
```

**What stays in the connector** (not in the library):
- `load_profile()` with DB-first fallback — connector owns persistence
- `findings_to_dicts()` — connector owns DB schema mapping
- `write_rollups()` — connector owns DB writes
- Sample value collection — connector owns data access

---

## 3. Python API Reference (Frozen)

### Input Models

```python
from dataclasses import dataclass, field


@dataclass
class ColumnInput:
    """Everything the library needs to classify a single column.

    Only column_name is required. All other fields are optional and
    improve accuracy when provided. Engines use what they can,
    ignore what they don't need.
    """

    # ── Required ──────────────────────────────────────────
    column_name: str
    # The column name. Highest-signal input for classification.
    # Examples: "customer_ssn", "email_address", "data_field"

    # ── Identity (optional) ───────────────────────────────
    column_id: str = ""
    # Caller-defined unique identifier. Opaque to the library —
    # echoed back in ClassificationFinding.column_id.
    # BQ example:  "resource:table:proj.ds.tbl:col_name"
    # PG example:  "public.users.email"
    # Snowflake:   "DB.SCHEMA.TABLE.COL"

    # ── Context (optional metadata) ───────────────────────
    table_name: str = ""
    # Parent table name. Provides context for ambiguous column names.

    dataset: str = ""
    # Dataset, schema, or database name.

    schema_name: str = ""
    # Schema name within a dataset or database (e.g. "public", "dbo").
    # Passed through for connector reference; not currently used for classification.

    data_type: str = ""
    # SQL data type as string: "STRING", "INTEGER", "TIMESTAMP", etc.
    # Not tied to any specific database's type system.

    description: str = ""
    # Column description/comment from the catalog.

    # ── Content (optional sample data) ────────────────────
    sample_values: list[str] = field(default_factory=list)
    # 10-100 sampled non-null values, coerced to strings by the connector.
    # Enables content-based engines (regex on values, NER, heuristics).
    # If empty, only metadata-based engines run (column name, data type).
    #
    # The library scans ALL provided values. Connector controls volume
    # via its own sampling strategy and the budget_ms parameter.

    # ── Statistics (optional) ─────────────────────────────
    stats: "ColumnStats | None" = None
    # Pre-computed column statistics. Connector computes these from the
    # source database; library uses them for heuristic classification.


@dataclass
class ColumnStats:
    """Column-level statistics computed by the connector."""
    null_pct: float = 0.0         # Null ratio 0.0-1.0
    distinct_count: int = 0       # Number of distinct non-null values
    total_count: int = 0          # Total row count
    min_length: int = 0           # Minimum string length (non-null values)
    max_length: int = 0           # Maximum string length
    avg_length: float = 0.0       # Average string length
```

### Output Models

```python
@dataclass
class SampleAnalysis:
    """How sample values contributed to a finding."""
    samples_scanned: int
    # Total values scanned for this column.

    samples_matched: int
    # How many matched this entity_type's pattern.

    samples_validated: int
    # How many passed secondary validation (Luhn checksum, format checks).

    match_ratio: float
    # matched / scanned. This is PREVALENCE — what fraction of the column
    # contains this entity type. NOT the same as confidence.
    # Use this to decide handling strategy:
    #   ratio ~1.0 → column IS this type (apply policy tag)
    #   ratio 0.01-0.3 → column CONTAINS some instances (flag for redaction)

    sample_matches: list[str] = field(default_factory=list)
    # First N matching values as evidence for audit.
    # Controlled by max_evidence_samples parameter.
    # When mask_samples=True, values are partially redacted:
    #   SSN:         "1**-**-6789"
    #   Credit card: "****-****-****-4321"
    #   Email:       "j***@acme.com"


@dataclass
class ClassificationFinding:
    """Result of classifying a single column."""

    # ── Identity ──────────────────────────────────────────
    column_id: str
    # Echoed from ColumnInput.column_id — opaque to the library.

    # ── Classification ────────────────────────────────────
    entity_type: str
    # Detected entity type: "SSN", "EMAIL", "CREDENTIAL", "CREDIT_CARD",
    # "PHONE", "DATE_OF_BIRTH", "PERSON_NAME", "ADDRESS", etc.

    category: str
    # Data category grouping: "PII", "Financial", "Credential", "Health"
    # Groups entity types by kind of sensitive data:
    #   PII        → SSN, EMAIL, PHONE, PERSON_NAME, ADDRESS, DATE_OF_BIRTH, etc.
    #   Financial  → CREDIT_CARD, BANK_ACCOUNT, FINANCIAL
    #   Credential → CREDENTIAL
    #   Health     → HEALTH

    sensitivity: str
    # Sensitivity level: "CRITICAL", "HIGH", "MEDIUM", "LOW"

    confidence: float
    # 0.0-1.0. Match quality: how certain is this specific match?
    # A validated credit card number has confidence 0.95+ regardless
    # of how many rows contain credit cards.
    # NOT prevalence — use sample_analysis.match_ratio for that.
    #
    # Rules:
    # - Validated match (Luhn, checksum, etc.) on high-base pattern → floor 0.95
    # - Unvalidated match → pattern base confidence (regex specificity)
    # - No count multiplier — match count is a prevalence signal

    regulatory: list[str]
    # Applicable regulatory frameworks: ["PII", "HIPAA", "GDPR", "PCI_DSS", ...]

    # ── Provenance ────────────────────────────────────────
    engine: str
    # Which engine produced this finding: "regex", "column_name", "gliner2", etc.

    evidence: str = ""
    # Human-readable explanation:
    #   "Regex: US SSN format matched 87/100 samples (87%)"
    #   "Column name 'customer_ssn' matches SSN pattern"

    # ── Sample detail ─────────────────────────────────────
    sample_analysis: "SampleAnalysis | None" = None
    # Populated when finding was derived from sample value analysis.
    # None when finding was derived from column name/metadata only.

    # ── Detection granularity ─────────────────────────────
    detection_type: str = ""
    # Specific detection pattern identifier, more granular than
    # ``entity_type``. Multiple detection_types may share the same
    # entity_type. Examples:
    #   entity_type="API_KEY", detection_type="aws_access_key"
    #   entity_type="API_KEY", detection_type="github_token"
    #   entity_type="SSN",     detection_type="us_ssn"
    #
    # Clients that need per-pattern detail inspect ``detection_type``;
    # clients that only need the broad label use ``entity_type`` or
    # ``family``.

    display_name: str = ""
    # Human-friendly label for ``detection_type``.
    # Examples: "AWS Access Key", "GitHub Token", "US SSN".
    # Suitable for UI display and reporting.

    # ── Family (Sprint 11) ────────────────────────────────
    family: str = ""
    # Structural handling family: a coarser grouping than
    # ``entity_type`` (26 labels) but finer than ``category`` (4
    # labels). 13 family values covering distinct downstream
    # handling needs. Auto-populated from entity_type at finding
    # construction — callers never need to set it explicitly.
    #
    # The distinction between ``category`` and ``family``:
    #   - ``category`` = regulatory grouping (GDPR scope, HIPAA
    #     scope, etc.). Use for compliance reporting.
    #   - ``family``  = DLP-policy grouping (which policy template
    #     applies?). Use for downstream handling logic.
    #
    # Family values: CONTACT, CREDENTIAL, CRYPTO, DATE, DEMOGRAPHIC,
    # FINANCIAL, GOVERNMENT_ID, HEALTHCARE, NEGATIVE, NETWORK,
    # PAYMENT_CARD, URL, VEHICLE.
    #
    # PCI-distinct split: CREDIT_CARD is in PAYMENT_CARD family
    # (PCI-DSS scope) while IBAN / BANK_ACCOUNT / ABA_ROUTING are
    # in FINANCIAL family (GLBA scope). Connectors that apply
    # different DLP policy to PCI vs non-PCI data can branch on
    # ``family`` cleanly.
    #
    # See ``data_classifier.core.taxonomy`` for the full mapping
    # and ``tests/benchmarks/README.md`` for the rationale.


@dataclass
class ClassificationProfile:
    """A named set of classification rules."""
    name: str
    description: str
    rules: list["ClassificationRule"]


@dataclass
class ClassificationRule:
    """A single classification rule within a profile."""
    entity_type: str              # "SSN", "EMAIL", etc.
    category: str                 # "PII", "Financial", "Credential", "Health"
    sensitivity: str              # "CRITICAL", "HIGH", "MEDIUM", "LOW"
    regulatory: list[str]         # ["PII", "HIPAA"]
    confidence: float             # Base confidence for this rule (0.0-1.0)
    patterns: list[str]           # Regex patterns


@dataclass
class RollupResult:
    """Aggregated classification summary for a parent node."""
    sensitivity: str              # Highest sensitivity from children
    classifications: list[str]    # Sorted unique entity types
    frameworks: list[str]         # Sorted unique regulatory frameworks
    findings_count: int           # Total findings count


SENSITIVITY_ORDER: dict[str, int] = {
    "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4,
}
```

### Functions

```python
def classify_columns(
    columns: list[ColumnInput],
    profile: ClassificationProfile,
    *,
    min_confidence: float = 0.5,
    # Findings below this threshold are not returned.
    # Default 0.5 filters noise while keeping moderate signals.
    # Lower (0.1) for maximum recall; raise (0.8) for precision.

    budget_ms: float | None = None,
    # Latency budget in milliseconds. None = no budget, full engine cascade.
    # When set, faster engines run first; slower engines skipped if budget
    # would be exceeded. Iteration 1: accepted but not enforced (single engine).

    run_id: str | None = None,
    # Associates findings with a run for telemetry event tagging.

    config: dict | None = None,
    # Per-request overrides: custom patterns, dictionaries, confidence thresholds.
    # Iteration 1: accepted but not used.

    mask_samples: bool = False,
    # When True, sample_matches in SampleAnalysis are partially redacted.
    # SSN "123-45-6789" → "1**-**-6789". Useful when findings are logged
    # or stored where PII should not appear in cleartext.

    max_evidence_samples: int = 5,
    # Maximum number of matching sample values to include in
    # SampleAnalysis.sample_matches.
) -> list[ClassificationFinding]:
    """Classify columns using the engine cascade.

    Returns one or more ClassificationFinding per column that has
    detectable sensitive data. Columns with no matches are omitted.
    A single column may have multiple findings (e.g., a "notes" column
    with both emails and phone numbers in its sample values).
    """
    ...


def load_profile_from_yaml(
    profile_name: str,
    yaml_path: str | Path,
) -> ClassificationProfile:
    """Load a named profile from a YAML file.

    Raises ValueError if profile_name not found in the YAML.
    Raises FileNotFoundError if yaml_path doesn't exist.
    """
    ...


def load_profile_from_dict(
    profile_name: str,
    data: dict,
) -> ClassificationProfile:
    """Load a named profile from an already-parsed dict.

    Raises ValueError if profile_name not found.
    """
    ...


def load_profile(
    profile_name: str = "standard",
) -> ClassificationProfile:
    """Load a profile from the library's bundled profiles.

    The library ships with a 'standard' profile. This function loads
    it from the package's bundled YAML — no file path needed.

    Connectors that store profiles in a database should implement their
    own load_profile() that tries DB first, then falls back to this.
    """
    ...


def compute_rollups(
    findings: list[ClassificationFinding],
    parent_map: dict[str, str],
) -> dict[str, RollupResult]:
    """Aggregate findings into parent-level rollups.

    Args:
        findings: Classification findings to aggregate.
        parent_map: Maps column_id → parent_id (e.g., column → table).
    """
    ...


def rollup_from_rollups(
    child_rollups: dict[str, RollupResult],
    parent_map: dict[str, str],
) -> dict[str, RollupResult]:
    """Aggregate child rollups into grandparent rollups (table → dataset)."""
    ...


def get_active_engines() -> list[dict]:
    """Return the engines currently loaded into the default cascade.

    Each entry is a dict with keys ``name``, ``order``, ``class``.
    Use this at startup to assert which engines are live — in particular
    to catch the case where the ``[ml]`` extras are missing and the
    GLiNER2 engine has silently dropped out of the cascade.
    """
    ...


def health_check(
    profile: ClassificationProfile | None = None,
) -> dict:
    """Run a canned single-column classification probe and report status.

    Returns a dict with keys:

        healthy          — bool
        engines_executed — list[str]
        engines_skipped  — list[str]
        latency_ms       — float
        findings         — list[dict] (subset of ClassificationFinding)
        error            — str | None (populated on failure)

    Never raises. Safe to call from /health endpoints and startup hooks.
    """
    ...
```

---

## 4. Connector Responsibilities

The library is connector-agnostic. Each connector is responsible for:

### 4a. Column Metadata Collection

Collect column schema from the source and map to `ColumnInput`:

| Connector field | ColumnInput field | Notes |
|---|---|---|
| Column name | `column_name` | **Required.** |
| Unique identifier | `column_id` | Connector-defined format. Library echoes it back. |
| Table name | `table_name` | For context. |
| Schema/dataset | `dataset` | For context. |
| SQL data type | `data_type` | Normalize to generic types: "STRING", "INTEGER", "TIMESTAMP", etc. |
| Column comment | `description` | Catalog description if available. |

### 4b. Sample Value Collection (NEW — connector must implement)

The library now accepts `sample_values` for content-based classification. **This is where the major accuracy improvement comes from** — column name matching alone misses generically-named columns.

**What the connector must do:**
1. For each table being classified, sample N rows (recommended: 50-100)
2. For each column, collect the non-null values as strings
3. Pass them in `ColumnInput.sample_values`

**Sampling strategies by platform:**

| Platform | Recommended approach |
|---|---|
| **BigQuery** | `SELECT * FROM table TABLESAMPLE SYSTEM (N ROWS)` or `LIMIT N` with `ORDER BY RAND()` |
| **Snowflake** | `SELECT * FROM table SAMPLE (N ROWS)` |
| **Postgres** | `SELECT * FROM table TABLESAMPLE BERNOULLI (pct)` or `ORDER BY random() LIMIT N` |

**Important constraints:**
- Coerce all values to strings before passing: `str(value)` — the library doesn't parse SQL types
- Exclude nulls from the sample — the library wants non-null values only
- The library scans ALL provided values (no internal cap). Control volume through your sampling query. Budget_ms also provides a timing escape hatch
- If sampling is not available or too expensive for a scan, omit `sample_values`. The library still classifies using column name and metadata — just with lower coverage

### 4c. Statistics Collection (optional, future)

If available, compute `ColumnStats` from the source:

| Platform | How to compute |
|---|---|
| **BigQuery** | `INFORMATION_SCHEMA.COLUMN_FIELD_PATHS` + `APPROX_COUNT_DISTINCT()` |
| **Snowflake** | `SHOW COLUMNS` + `APPROX_COUNT_DISTINCT()` |
| **Postgres** | `pg_stats` view (already has null_frac, n_distinct, avg_width) |

### 4d. Profile Loading

The library ships a bundled `standard` profile accessible via `load_profile("standard")`.

**If your connector stores profiles in a database**, implement your own wrapper:

```python
# In your connector (NOT in the library):
from data_classifier import load_profile_from_dict, load_profile as load_bundled_profile

def load_profile(profile_name: str) -> ClassificationProfile:
    """DB-first, bundled fallback."""
    db_profile = _try_load_from_db(profile_name)  # your DB logic
    if db_profile is not None:
        return db_profile
    return load_bundled_profile(profile_name)
```

### 4e. Result Persistence

The library returns `ClassificationFinding` objects. The connector maps them to its own DB schema:

```python
# In your connector (NOT in the library):
def findings_to_db_rows(findings: list[ClassificationFinding]) -> list[dict]:
    return [
        {
            "column_node_id": f.column_id,
            "entity_type": f.entity_type,
            "category": f.category,
            "confidence": f.confidence,
            "engine": f.engine,
            "sensitivity": f.sensitivity,
            "regulatory": f.regulatory,
            "evidence": f.evidence,
            "match_ratio": f.sample_analysis.match_ratio if f.sample_analysis else None,
            "sample_value": None,  # or masked sample if desired
        }
        for f in findings
    ]
```

---

## 5. ML Engine Setup (Standard Tier)

If using the Standard or Full tier, the GLiNER NER engine needs a one-time model setup.

### Option A: Zero-Config Auto-Discovery (recommended)

The library auto-discovers the ONNX model from standard locations — **no
environment variables, no paths, no code changes**. Export once at build
time, the engine finds it automatically at runtime.

```bash
# One-time build step (needs ml-full for export):
pip install "data_classifier[ml-full]"
python -m data_classifier.export_onnx
# Writes to {package_dir}/models/gliner_onnx/ (~350MB)
# This location is auto-discovered by the library at startup.
```

```python
# Runtime code — same as Light tier, no GLiNER config needed
from data_classifier import classify_columns, load_profile

findings = classify_columns(inputs, load_profile("standard"))
# GLiNER2 engine auto-discovers the bundled ONNX model on first inference
```

The library searches these locations in order:
1. `{package_dir}/models/gliner_onnx/` — bundled with the library (default)
2. `~/.cache/data_classifier/models/gliner_onnx/` — user cache
3. `/var/cache/data_classifier/models/gliner_onnx/` — system cache
4. `$GLINER_ONNX_PATH` env var — explicit override

### Option A2: Environment Variable Override

For containers where the model lives outside the package directory:

```bash
export GLINER_ONNX_PATH=/app/models/gliner_onnx
```

No code changes required — the library's default engine builder reads
this env var automatically.

### Option B: API Mode (testing / light workloads)

```bash
export GLINER_API_KEY=your-api-key
```

```python
from data_classifier import classify_columns, load_profile
findings = classify_columns(inputs, load_profile("standard"))
# GLiNER2 engine uses hosted API when GLINER_API_KEY is set and no ONNX path
```

### Option C: Explicit Engine Injection (advanced)

For full control over engine configuration, build your own engine list and
use `ClassificationOrchestrator` directly:

```python
from data_classifier.engines.column_name_engine import ColumnNameEngine
from data_classifier.engines.regex_engine import RegexEngine
from data_classifier.engines.heuristic_engine import HeuristicEngine
from data_classifier.engines.secret_scanner import SecretScannerEngine
from data_classifier.engines.gliner_engine import GLiNER2Engine
from data_classifier.orchestrator.orchestrator import ClassificationOrchestrator

engines = [
    ColumnNameEngine(),
    RegexEngine(),
    HeuristicEngine(),
    SecretScannerEngine(),
    GLiNER2Engine(onnx_path="/app/models/gliner_onnx", gliner_threshold=0.5),
]
orchestrator = ClassificationOrchestrator(engines=engines)
findings = orchestrator.classify_columns(inputs, load_profile("standard"))
```

### Option D: Skip ML entirely (Light tier)

```bash
# Either don't install [ml], or disable at runtime:
export DATA_CLASSIFIER_DISABLE_ML=1
```

The library auto-skips the GLiNER engine when the gliner package is not
available or when `DATA_CLASSIFIER_DISABLE_ML` is set. You get regex +
column name + heuristic engines only.

### Environment Variables Summary

| Variable | Effect |
|----------|--------|
| `GLINER_ONNX_PATH` | Path to pre-exported ONNX model directory |
| `GLINER_API_KEY` | API key for GLiNER hosted API fallback |
| `DATA_CLASSIFIER_DISABLE_ML` | If set, skip GLiNER2 engine entirely |

### What the ML engine detects

| Entity type | Without ML | With ML |
|-------------|-----------|---------|
| PERSON_NAME | Column name only | Column name + sample value NER |
| ADDRESS | Column name only | Column name + sample value NER |
| ORGANIZATION | Column name only | Column name + sample value NER |
| EMAIL | Regex (strong) | Regex + NER reinforcement |
| PHONE | Regex (US formats) | Regex + NER (international formats) |
| SSN | Regex (US format) | Regex + NER (international IDs) |
| All others | Regex + heuristic | Same (ML adds no value on structured patterns) |

### New classify_columns Parameters (v0.5.0)

```python
findings = classify_columns(
    inputs,
    profile,
    max_findings=1,                # Return only top-1 prediction per column
    confidence_gap_threshold=0.30, # Suppress secondary findings below gap
    # ... existing parameters unchanged
)
```

---

## 5A. Engines Reference

> **Audience:** Anyone who needs to predict or debug classification behavior without reading `data_classifier/engines/*.py`. Every statement in this section is cross-referenced against code paths on `main` — if you find a drift, file a docs bug.
>
> **Last verified:** Sprint 11 (2026-04-14). Source files: `data_classifier/engines/column_name_engine.py`, `regex_engine.py`, `heuristic_engine.py`, `secret_scanner.py`, `gliner_engine.py`, `data_classifier/orchestrator/orchestrator.py`, `data_classifier/engines/interface.py`.

The library ships **5 classification engines**. Each one reads `ColumnInput` (and optionally a `ClassificationProfile`), emits zero or more `ClassificationFinding`s, and returns. Engines never talk to each other directly; all merging, dedup, and conflict resolution lives in the orchestrator (see §5A.6 below).

### Engine contract — what they share

Every engine is a subclass of `ClassificationEngine` (`data_classifier/engines/interface.py`) and declares four class-level attributes the orchestrator uses at dispatch time:

| Attribute | Purpose | Default | Affects |
|---|---|---|---|
| `name` | Stable engine identifier string | — (required) | Finding provenance, telemetry |
| `order` | Execution sequence in the cascade | `0` | Runtime order (lower runs first) |
| `authority` | Trust weight for conflict resolution | `1` | Cross-engine dedup (§5A.6) |
| `min_confidence` | Floor at which engine emits a finding | `0.0` | Per-engine filter before orchestrator sees results |
| `supported_modes` | Which orchestrator modes the engine participates in | `frozenset()` | `{structured, unstructured, prompt}` — orchestrator filters at init |

Every engine also implements `classify_column(column, *, profile, min_confidence, mask_samples, max_evidence_samples) -> list[ClassificationFinding]`. Returning `[]` means "I had nothing to say"; raising is caught and logged by the orchestrator (the failing engine is treated as empty for that column — see the per-engine `try/except` in `Orchestrator.classify_column`).

The orchestrator filters engines by mode at construction time and sorts them by `order`. **Runtime order is fixed; authority is only consulted at merge time.** Column-name happens to be both order 1 **and** authority 10 — that is not coincidence: we want the cheapest, most-signal engine to run first and also to win ties.

### Engines at a glance

| `order` | Engine | `name` | `authority` | `supported_modes` | Primary signal |
|---|---|---|---|---|---|
| 1 | Column Name | `column_name` | **10** | `{structured}` | Column name string |
| 2 | Regex | `regex` | **5** | `{structured, unstructured, prompt}` | Sample value patterns |
| 3 | Heuristic Stats | `heuristic_stats` | 1 | `{structured}` | Cardinality, length, char-class, entropy |
| 4 | Secret Scanner | `secret_scanner` | 1 | `{structured, unstructured}` | Structured key-value parsing + entropy |
| 5 | GLiNER2 NER | `gliner2` | 1 | `{structured}` | Zero-shot transformer NER |

If the `[ml]` extra is not installed, GLiNER2 is silently skipped at import time and a WARNING is emitted by the `data_classifier` logger (see `get_active_engines()` / `health_check()` in §1e — connectors should assert the expected engine set at startup).

---

### 5A.1. `column_name` — fuzzy column name semantics

**Source:** `data_classifier/engines/column_name_engine.py`
**Order:** 1 · **Authority:** 10 (highest) · **Modes:** `structured`

**Purpose.** Classify a column by its *name* alone, using a ~700-variant dictionary (`data_classifier/patterns/column_names.json`) covering 35 entity types. This is the cheapest and most-signal engine in the cascade: if a column is named `ssn` or `credit_card_num`, no amount of sample-value analysis is going to change the answer.

**When it fires.** Always, in `structured` mode — it runs first and never reads sample values, so it's effectively free. The engine does **not** participate in `unstructured` or `prompt` modes (no column name, nothing to match).

**Input requirements.**
- `ColumnInput.column_name` — required (empty string means no finding)
- `ColumnInput.table_name` — optional; when present, triggers a small context boost (`_TABLE_CONTEXT_BOOST = 0.05`) if the table's domain matches the entity's category. See `_TABLE_CONTEXT` + `_get_table_context_boost` in `column_name_engine.py` — e.g., `employee_data` table + `ssn` column → +0.05 boost.

Sample values, `data_type`, and `description` are ignored by this engine.

**Matching strategy** (in priority order, highest confidence wins):

1. **Direct lookup.** Normalize column name (lowercase, underscore-join, strip separators) → exact lookup in the variants dict. Full base confidence from the JSON (typically 0.90–0.99).
2. **Abbreviation expansion.** Expand short forms (`ssn → social_security_number`, `dob → date_of_birth`, `addr → address`, 30+ entries in `_ABBREVIATIONS` in `column_name_engine.py`) then re-lookup. Confidence scaled by **0.95**.
3. **Multi-token subsequence.** Split camelCase / snake_case into tokens, check every contiguous subsequence against the variants dict. Confidence scaled by **0.85**.

**Output format.** A `ClassificationFinding` per matched entity type with `engine="column_name"`, confidence in **[0.76, 0.99]** (base × scaling factor), and evidence string `"Column name match: <variant>"` or `"Column name match (abbreviation): <variant>"`. Typically 0–2 findings per column — the engine returns at most one finding per entity type.

**Why authority 10.** Column names are a source-of-truth signal. When the connector tells us "this column is named `ssn`," lower-authority engines (regex, heuristic, gliner) are not allowed to override it with a conflicting entity type. See §5A.6 on engine weighting for the exact suppression rule.

---

### 5A.2. `regex` — RE2 two-phase pattern matching

**Source:** `data_classifier/engines/regex_engine.py`, `data_classifier/patterns/default_patterns.json` (159 content patterns as of Sprint 14), `data_classifier/engines/validators.py` (14 validators)
**Order:** 2 · **Authority:** 5 · **Modes:** `structured`, `unstructured`, `prompt`

**Purpose.** Detect structured entity types (SSN, email, phone, credit card, JWT, PEM keys, ABA routing, NPI, DEA, IBAN, VIN, …) from sample values using Google RE2 for linear-time regex matching. This is the library's workhorse — the pattern bundle covers almost every well-formatted PII and credential type that has a reliable lexical fingerprint.

**Architecture — the "Set then extract" trick.** Naively running every pattern against every sample value would be O(patterns × values). RE2 exposes a `Set` primitive that screens all patterns in a single C++ pass, releasing the GIL. The engine uses a two-phase strategy:

1. **Phase 1 (screening).** All content patterns are compiled into one `re2.Set`. For each sample value, one `Set.match(value)` call returns the indices of patterns that matched. This is O(value length), not O(patterns × value length).
2. **Phase 2 (extraction).** Only the patterns that screened positive are re-run individually against the value to extract match positions, values, and apply secondary validators.

This means `regex_engine.classify_column` stays fast even as the pattern library grows. The screening cost is why "add 10 more patterns" is nearly free.

**Two classification paths.** The engine classifies by *both* column name (profile rules matched against `column.column_name`) **and** sample values (content patterns matched against each `sample_value`). This is orthogonal to the `column_name` engine — the regex engine's column-name path uses the profile's regex rules, while `column_name_engine` uses the variant dictionary.

**When it fires.** Always, in any mode where sample values or column names are available. In `unstructured` and `prompt` modes, the column-name path is a no-op (no column name is passed) and only the content-pattern path runs.

**Input requirements.**
- `ColumnInput.sample_values` — required for the content-pattern path
- `ColumnInput.column_name` — optional, drives the profile-rule path
- `ClassificationProfile` — required for the column-name path (provides the regex rules)

**Signals and adjustments.** The engine layers several mechanisms on top of raw pattern matching:

- **Context boosting / suppression** (`_CONTEXT_BOOST = 0.30` in `regex_engine.py`) — per-pattern "boost words" and "suppress words" scanned in a 10-token window around the match adjust confidence by up to ±0.30. Used to distinguish e.g. "customer number 123-45-6789" (boosted SSN) from "invoice line 123-45-6789" (suppressed).
- **Stopword suppression** — both global (`patterns/stopwords.json`) and per-pattern known-placeholder lists produce hard-zero on match (e.g. `000-00-0000`, `xxx-xx-xxxx`, `4111-1111-1111-1111`).
- **Allowlists** — per-pattern allowlisted exact values that are *always* kept regardless of other suppressors.
- **Secondary validators** (`validators.py`) — 14 validators run on matched values: Luhn (credit card, SIN), SSN area/group/serial rules, NPI check digit, DEA check, VIN check digit, EIN format, ABA routing check digit, IBAN MOD-97, phonenumbers lib validation, IPv4 octet range, `random_password` entropy shape, AWS-key "not hex" check. Failing validation reduces confidence proportionally (see confidence formula below).
- **Column-gated patterns** (Sprint 7) — patterns can declare `requires_column_hint: true` and a list of `column_hint_keywords`. The pattern only fires when the column name contains one of the hints, cutting cross-column false positives on ambiguous shapes (e.g., `random_password` only fires on columns named like `password`, `passwd`, `secret`, …).

**Confidence formula** (`_compute_sample_confidence` in `regex_engine.py`):

```
if matches == 0:          0.0
if matches == 1:          base * 0.65    # single match could be noise
if 2 <= matches <= 4:     base * 0.85    # probably real
if 5 <= matches <= 20:    base           # solid evidence
if matches > 20:          min(base * 1.05, 1.0)

if validation_rate < 1.0:
    multiply by validation_rate          # e.g., 50% validated → halve
```

**Output format.** One `ClassificationFinding` **per matched pattern** per column (not per entity type), with `engine="regex"`, confidence in **[0.0, 1.0]**, and rich evidence (pattern name, match count, validation rate, context boost deltas). Each finding carries a `detection_type` identifying the specific pattern (e.g. `"aws_access_key"`, `"github_token"`) and a `display_name` with a human-friendly label. Multiple findings may share the same `entity_type` — clients that need a single row per entity type can group by `entity_type` or `family`. `sample_analysis.sample_matches` contains the raw (or masked, when `mask_samples=True`) matched values for downstream triage.

**Masking.** When `mask_samples=True`, matched values are partially redacted before being stored in `sample_analysis` (`_mask_value` in `regex_engine.py`). Redaction is entity-type-aware: SSN/credit-card preserve the last 4, email preserves the local-part first char and the entire domain, phone preserves the last 4, generic entity types preserve first+last char.

---

### 5A.3. `heuristic_stats` — cardinality, length, entropy, char-class

**Source:** `data_classifier/engines/heuristic_engine.py`, `data_classifier/config/engine_defaults.yaml` (`heuristic_engine.*` keys)
**Order:** 3 · **Authority:** 1 (default) · **Modes:** `structured`

**Purpose.** Classify columns using *distributional* signals when pattern matching is ambiguous. The canonical use case is **SSN vs. ABA routing disambiguation**: both are 9-digit all-numeric strings, but SSN has high cardinality (every row unique) while ABA routing has low cardinality (same handful of routing numbers reused across thousands of rows). A pattern-only engine can't tell them apart; a heuristic engine that looks at `distinct_count / total_count` can.

The engine's second responsibility is the **OPAQUE_SECRET catch-all** (Sprint 4+): high-entropy, column-gated values that didn't match any regex pattern and look like credentials. This is deliberately conservative — it fires only when a strict 5-signal conjunction holds (column name hint + entropy + length + char-class diversity + non-placeholder).

**When it fires.** In `structured` mode only, when `len(sample_values) >= min_samples` (default 5, see `engine_defaults.yaml`). Columns with fewer samples return `[]` immediately.

**Input requirements.**
- `ColumnInput.sample_values` — required, minimum sample count gate (default 5)
- `ColumnInput.stats` — optional; if the connector pre-computed `distinct_count` / `total_count`, the engine uses those for cardinality instead of `len(set(values)) / len(values)` on the sample (better precision on large columns with small samples)
- `ColumnInput.column_name` — used by the OPAQUE_SECRET column gate

**Rules shipped on main.** The engine currently emits findings for:

| Rule | Entity type | Trigger | Confidence formula |
|---|---|---|---|
| High-card 9-digit all-numeric | `SSN` | `cardinality ≥ high_threshold` AND `digit_ratio ≥ digit_purity` AND `uniform length == 9` | `min(0.70 + 0.15 * cardinality, 0.95)` → **0.82–0.95** |
| Low-card 9-digit all-numeric | `ABA_ROUTING` | `cardinality ≤ low_threshold` AND `digit_ratio ≥ digit_purity` AND `uniform length == 9` | `min(0.75 + 0.10 * (1 - cardinality), 0.90)` → **0.82–0.90** |
| Column-gated opaque credential | `OPAQUE_SECRET` | `opaque_secret_detection()` passes all 5 guards | Fixed **0.75** |

All thresholds live in `config/engine_defaults.yaml` under `heuristic_engine.signals` — no hardcoded fallbacks. Connector teams can tune without touching engine code.

**Signal functions.** The engine exposes pure computation functions other engines can import (`secret_scanner` uses `compute_shannon_entropy` and `compute_char_class_diversity` directly): `compute_cardinality_ratio`, `compute_shannon_entropy`, `compute_avg_entropy`, `compute_length_stats`, `compute_char_class_ratios`, `compute_char_class_diversity`, `compute_avg_char_class_diversity`. See `heuristic_engine.py` for the full list.

**Output format.** Zero to three `ClassificationFinding`s per column, `engine="heuristic_stats"`. Evidence includes the numerical signals that triggered the finding (e.g. `"Heuristic: cardinality=0.97 (high), uniform length=9, digit_ratio=1.00"`).

**Authority 1 and the orchestrator.** Because the engine has default authority, its findings are freely overridden by the column-name engine and compete on confidence with the regex engine. The orchestrator's "generic CREDENTIAL suppression" rule (§5A.6) also targets the heuristic engine's OPAQUE_SECRET finding when a more-specific credential subtype (API_KEY, PRIVATE_KEY, PASSWORD_HASH) has been found.

---

### 5A.4. `secret_scanner` — structured secret detection

**Source:** `data_classifier/engines/secret_scanner.py`, `data_classifier/engines/parsers.py` (JSON/YAML/env/code parsers), `data_classifier/patterns/secret_key_names.json` (271-entry tiered dictionary)
**Order:** 4 · **Authority:** 1 (default) · **Modes:** `structured`, `unstructured`

**Purpose.** Detect credentials embedded in structured text — JSON blobs, YAML configs, `.env` files, code literals like `password = "SuperSecret123!"`. This engine catches secrets that regex patterns *can't*: values that have no known prefix or format, identified only by the **key name** they're bound to plus high relative entropy.

Example detections:
- `{"db_password": "kJ#9xMp$2wLq!"}` — JSON key `db_password` at `definitive` tier + high entropy on value
- `export API_TOKEN=a8f3b2c1d4e5` — env var name `API_TOKEN` at `strong` tier + entropy
- `password = "SuperSecret123!"` — Python/JS code literal assignment

This is the primary detection layer for the four credential subtypes (`API_KEY`, `PRIVATE_KEY`, `PASSWORD_HASH`, `OPAQUE_SECRET`) that were split out of the legacy `CREDENTIAL` type in Sprint 8. Each dictionary entry declares its `subtype`, so the scanner emits the correct narrow type instead of a generic CREDENTIAL label.

**When it fires.** In `structured` and `unstructured` modes, whenever `ColumnInput.sample_values` contains at least one value that the key-value parsers can parse. Columns whose sample values are all plain strings (no `key=value` shape) are a no-op.

**Input requirements.**
- `ColumnInput.sample_values` — required
- The four parsers (`parsers.py`) run in sequence on each value: JSON → YAML → shell-style `KEY=VALUE` → Python/JS code literal. First parser that produces a non-empty key-value list wins.

**Tiered scoring.** Every entry in `secret_key_names.json` has a `tier` (`definitive` / `strong` / `contextual`), a `match_type` (`substring` / `word_boundary` / `suffix`), a `score` (base confidence), and a `subtype` (the final entity_type to emit). The scanner's composite scoring rule (`_compute_tiered_score` in `secret_scanner.py`):

| Tier | Semantics | Evidence requirement | Composite score |
|---|---|---|---|
| `definitive` | Key name alone is diagnostic (e.g. `aws_secret_access_key`, `stripe_secret_key`) | Value must not be a known placeholder (checked against `known_placeholder_values.json`) | `key_score * definitive_multiplier` (default 0.95) |
| `strong` | Key name is strong but needs corroboration (e.g. `api_key`, `auth_token`) | Value entropy ≥ strong threshold OR value length ≥ length threshold | `key_score * strong_multiplier` |
| `contextual` | Key name only suggests a secret (e.g. `token`, `key`) | Value must independently score high on entropy + length + char diversity | Conjunction of all three signals × `contextual_multiplier` |

All multipliers and thresholds live in `config/engine_defaults.yaml` under `secret_scanner.scoring`.

**Match types** (Sprint 11 item #4 tightened `id_token` and `token_secret` from `substring` to `word_boundary` to cut FPs on columns named `rapid_token`, `bigtoken_secret`, etc.):

- `substring` — case-insensitive substring anywhere in the key
- `word_boundary` — substring delimited by `_ - . \s` on both sides (regex `(^|[_\-\s.])PATTERN($|[_\-\s.])`)
- `suffix` — substring at the end of the key only

**Relative entropy.** Rather than raw Shannon entropy (which penalizes hex-only or base64-only values), the scanner computes entropy *relative* to the theoretical max for the detected charset (`_CHARSET_MAX_ENTROPY` in `secret_scanner.py`). A 32-char hex string at entropy 4.0 scores 1.0 (perfect) instead of ~61% of the full-printable-ASCII max. This is what lets the scanner correctly flag high-quality hex secrets without flagging low-quality full-printable gibberish.

**Output format.** One `ClassificationFinding` per matched key-value pair, with `engine="secret_scanner"`, `entity_type` set to the dictionary entry's `subtype` (one of `API_KEY`, `PRIVATE_KEY`, `PASSWORD_HASH`, `OPAQUE_SECRET`), and evidence like `"Secret scanner: key 'db_password' (score=0.95, tier=definitive, subtype=OPAQUE_SECRET) + value entropy 0.87"`. Findings are emitted *per match*, but the orchestrator dedups by `entity_type` so the final result is at most one finding per subtype per column.

**Sprint 10 dictionary expansion.** The dictionary grew from 88 → 178 → 271 entries via `scripts/ingest_credential_patterns.py`, which harvests key-name lists from Kingfisher (Apache-2.0), gitleaks (MIT), and Nosey Parker (Apache-2.0) with pinned upstream SHAs. Per-entry attribution lives in `docs/process/CREDENTIAL_PATTERN_SOURCES.md` — every new entry is traceable to its upstream.

---

### 5A.5. `gliner2` — zero-shot NER (ML engine)

**Source:** `data_classifier/engines/gliner_engine.py`
**Order:** 5 · **Authority:** 1 (default) · **Modes:** `structured`
**Tier:** requires `pip install "data_classifier[ml]"` + bundled ONNX model

**Purpose.** Run zero-shot Named Entity Recognition on sample values using the GLiNER model (`urchade/gliner_multi_pii-v1`, threshold 0.50, descriptions enabled), with description-enhanced inference for higher accuracy. This is the engine that detects `PERSON_NAME`, `ADDRESS`, and `ORGANIZATION` when column names are generic or missing — the three entity types that have no reliable lexical fingerprint and therefore can't be caught by the regex engine.

The engine also produces reinforcement signals for `EMAIL`, `PHONE`, `SSN`, `DATE_OF_BIRTH`, and `IP_ADDRESS` — these types are already well-covered by regex, but a matching GLiNER finding acts as independent corroboration and triggers the orchestrator's +0.05 agreement boost (§5A.6).

**When it fires.** In `structured` mode only, when:

1. The `gliner` package is importable (otherwise the engine is not registered at startup — see `get_active_engines()` + `health_check()` at §1e).
2. `ColumnInput.data_type` is **NOT** one of the non-text SQL types (`INTEGER`, `INT64`, `FLOAT`, `FLOAT64`, `NUMERIC`, `BIGNUMERIC`, `BOOLEAN`, `BOOL`, `TIMESTAMP`, `DATE`, `DATETIME`, `TIME`, `BYTES`). Non-text columns return `[]` immediately — no inference, no latency, no FPs. Empty `data_type` (legacy connectors) falls through to the model. See `_NON_TEXT_DATA_TYPES` in `gliner_engine.py`. **This is the Sprint 10 data_type pre-filter.**
3. `ColumnInput.sample_values` has at least one non-empty value.

**Input requirements.**
- `ColumnInput.sample_values` — required
- `ColumnInput.data_type` — **used as a skip-filter** (upper-case convention; comparison is case-insensitive)
- `ColumnInput.column_name`, `ColumnInput.table_name`, `ColumnInput.description` — used by the Sprint 10 S1 NL-prompt wrapper (see below)

**Sprint 10 S1 NL-prompt wrapping** (`_build_ner_prompt` in `gliner_engine.py`). GLiNER is a context-attention model trained on natural-language sentences. Feeding it raw `"value ; value ; value"` strings is out-of-distribution and causes ORGANIZATION/PERSON_NAME/PHONE false-fires on numeric columns. The S1 wrapper reshapes the input:

```
Column '<column_name>' from table '<table_name>'. Description: <desc>. Sample values: <v1>, <v2>, <v3>, ...
```

Metadata-free columns fall back to the pre-Sprint-10 raw `" ; ".join(chunk)` shape, so the change is strictly additive — connectors that populate `column_name`/`table_name`/`description` see the uplift; connectors that don't see the original behavior. Description is truncated first if the assembled prompt would exceed the 2000-char budget; sample values are never sacrificed.

**Entity types and descriptions** (`ENTITY_LABEL_DESCRIPTIONS` in `gliner_engine.py`). The model is asked to find 8 entity types: `PERSON_NAME`, `ADDRESS`, `ORGANIZATION`, `DATE_OF_BIRTH`, `PHONE`, `SSN`, `EMAIL`, `IP_ADDRESS`. Each one ships with a short natural-language description that GLiNER's schema-based extraction uses as grounding — e.g., `PHONE → ("phone number", "Telephone numbers in any international format with country codes, dashes, dots, or spaces")`. These descriptions are part of the API contract; changing them requires a re-benchmark.

**Inference modes** (tried in order at engine init):

1. **ONNX local** — if `onnx_path` is set (or auto-discovered via `_find_bundled_onnx_model()` in `gliner_engine.py`, searching package `models/`, `~/.cache/data_classifier/models/gliner_onnx/`, and `/var/cache/data_classifier/models/gliner_onnx/`). Fastest load (~3s vs 14s for HuggingFace download), no network dependency, production-ready. **This is what container deployments should use.**
2. **Local model** — loads from HuggingFace or user's HF cache.
3. **API fallback** — if `api_key` is set and local loading fails, uses the GLiNER hosted API. Intended for testing, not production.

**Threshold and chunking.** Default threshold `_DEFAULT_GLINER_THRESHOLD = 0.5`; predictions below this are discarded. Sample values are chunked at `_SAMPLE_CHUNK_SIZE = 50` per NER call to stay within the model's 384-token context window.

**Output format.** One `ClassificationFinding` per detected entity type, `engine="gliner2"`, with metadata from `_ENTITY_METADATA` (category, sensitivity, regulatory tags). Confidence is the raw GLiNER score (0.5–1.0 range in practice). Evidence is a count of how many chunks fired for the type.

**Why authority 1.** GLiNER is powerful but noisy on out-of-distribution inputs (Sprint 10 fastino promotion attempt confirmed this). It's deliberately treated as a contributing signal, not a source of truth — authority 1 means any column-name or regex finding can override it on a conflict.

---

### 5A.6. Orchestrator — cascade, dedup, and conflict resolution

**Source:** `data_classifier/orchestrator/orchestrator.py`

The orchestrator is **one class, one cascade, three modes** (`structured`, `unstructured`, `prompt`). It:

1. Filters engines by mode at construction time.
2. Sorts them by `order`.
3. On each call to `classify_column`, walks the engine list, dispatches, collects findings, merges them via authority + confidence, and applies five post-processing passes.

The post-processing passes are the interesting part — below is the pass list in the exact order they run, with the code location and the "why" behind each.

#### Pass 1 — Merge by `entity_type` with authority + confidence tiebreak

For each finding emitted by each engine, compare against the existing finding for the same `entity_type`:

- **No existing finding:** insert.
- **Higher-authority engine:** replace (higher authority wins unconditionally).
- **Equal authority, higher confidence:** replace (confidence tiebreak).
- **Equal or lower authority AND equal or lower confidence:** drop.

This means `column_name` (authority 10) always wins on matching entity types against `regex` (5) and the rest (1). Within the three authority-1 engines (heuristic, secret_scanner, gliner2), whichever found the higher confidence for the same entity type wins.

#### Pass 2 — Engine priority weighting

`_apply_engine_weighting` in `orchestrator.py`. The orchestrator looks at the highest-authority engine that produced *any* finding on this column. If that authority is ≥ `_AUTHORITY_THRESHOLD` (8) — in practice, that's only `column_name` at 10 — two things happen:

1. **Suppression.** Lower-authority engines' findings for *different* entity types (types the authoritative engine didn't also identify) are dropped, but only when the authority gap is ≥ `_AUTHORITY_GAP_MIN` (3). Example: column named `ssn`, column_name engine fires `SSN`. Regex also fires `ABA_ROUTING` on the same 9-digit values. Authority gap = 10 − 5 = 5 ≥ 3, so `ABA_ROUTING` is suppressed in favor of `SSN`.
2. **Agreement boost.** When a lower-authority engine *also* identifies the same entity type, the authoritative finding's confidence is boosted by `_AGREEMENT_BOOST` (0.05, capped at 1.0), and an evidence tag is appended: `" [+0.05 agreement with regex]"`.

This is how "column name + regex agreement" becomes a stronger signal than either alone, without requiring engines to be aware of each other.

#### Pass 3 — Suppress ML-only types when non-ML is strong

`_suppress_ml_when_strong_match` in `orchestrator.py`. If any *non-ML* engine produced a finding with confidence ≥ 0.85, any ML-engine-only finding for a *different* entity type is dropped. This prevents GLiNER from adding `PERSON_NAME` noise on a column where regex already confidently identified `EMAIL` or `IP_ADDRESS`. ML findings that *agree* with the strong non-ML finding are kept (they reinforce via pass 2). ML findings on columns with no non-ML signal are kept (that's the ML engine filling a detection gap — the reason it exists).

#### Pass 4 — Resolve known collision pairs

`_resolve_collisions` in `orchestrator.py`. Five entity-type pairs have regex shapes that structurally overlap:

```python
_COLLISION_PAIRS = [
    ("SSN", "ABA_ROUTING"),
    ("SSN", "CANADIAN_SIN"),
    ("ABA_ROUTING", "CANADIAN_SIN"),
    ("NPI", "PHONE"),
    ("DEA_NUMBER", "IBAN"),
]
```

When both members of a pair co-occur on the same column, the lower-confidence finding is dropped **only if** the gap exceeds `_COLLISION_GAP_THRESHOLD` (0.15). Smaller gaps mean the column is genuinely ambiguous and both findings are kept for the connector to triage. This is the final line of defense after the heuristic engine's cardinality-based disambiguation.

#### Pass 5 — Suppress generic CREDENTIAL

`_suppress_generic_credential` in `orchestrator.py`. The legacy `CREDENTIAL` label is dropped when any *more-specific* finding exists with equal or higher confidence. Historically this targeted the heuristic engine's high-entropy catch-all. Post-Sprint-8 (which split CREDENTIAL into `API_KEY`/`PRIVATE_KEY`/`PASSWORD_HASH`/`OPAQUE_SECRET`), the pass mainly handles the residual case where a legacy loader or downstream consumer emits the flat `CREDENTIAL` label alongside a subtype — the subtype wins.

#### Pass 6 — Suppress URL-embedded IP addresses

`_suppress_url_embedded_ips` in `orchestrator.py`. The `ipv4_address` regex matches inside URL strings like `http://192.168.1.1/api`. RE2 has no variable-width lookbehind, so the regex alone can't avoid this. Worse, the `url` regex requires a letter-only TLD and therefore doesn't match bare-IP URLs — so there's no co-finding to trigger a suppression. The pass inspects the `IP_ADDRESS` finding's `sample_analysis.sample_matches`: if *every* matched value starts with `http://` or `https://`, the finding is dropped. A mixed column (some bare IPs, some URL-embedded) keeps the finding.

#### Pass 7 — Sibling-context adjustment (batch only)

`classify_columns` in `orchestrator.py` runs two passes over a *list* of columns. Pass 1 classifies each column independently. Pass 2 builds a `TableProfile` from the high-confidence Pass 1 findings across the whole list, then re-adjusts ambiguous columns using the sibling context — if 8 of the 10 columns look like a payroll table, the remaining 2 ambiguous columns get a financial-domain prior that shifts confidence toward financial entity types.

This pass only fires when `classify_columns` is called with more than one column; `classify_column` (singular) skips it entirely.

#### Meta-classifier shadow path

After the 7 passes complete and a final list of findings is ready, an optional `MetaClassifier` runs in **shadow mode**: it predicts an entity type from the live engine findings, emits a `MetaClassifierEvent` for telemetry, and then is discarded. **The shadow path never mutates `result` and never raises** — it's belt-and-suspenders wrapped in a broad `try/except`. Disabled entirely via `DATA_CLASSIFIER_DISABLE_META=1`. See `docs/learning/sprint9-cv-shortcut-and-gated-architecture.md` for the honest CV numbers and why shadow-only is the current posture.

---

### 5A.7. Debugging the cascade

When a finding shows up that you don't expect (or a finding you *do* expect is missing), the debugging path is:

1. **Check which engines ran.** Set logging to DEBUG on the `data_classifier` logger and look for `TierEvent` emissions — each engine emits one per column with its `latency_ms`, `findings_count`, and `outcome`. If an engine is missing, it was filtered by `supported_modes` at orchestrator init (or skipped by the GLiNER `data_type` pre-filter).
2. **Check what each engine produced, pre-merge.** The orchestrator logs DEBUG messages for every suppression and every boost in passes 2–6 — search for `"Engine weighting"`, `"Collision resolution"`, `"Suppressing generic CREDENTIAL"`, `"Suppressed ML-only"`, `"Suppressing IP_ADDRESS"`.
3. **Use `get_active_engines()` + `health_check()`** (§1e) to assert the expected engine set at application startup. These are the Sprint 9 observability primitives; they're the fastest way to catch "wait, GLiNER isn't even loaded" before spending time debugging an empty finding list.
4. **Consult `ClassificationFinding.evidence`.** Every finding carries a human-readable evidence string that records which rule fired, which pattern matched, which signal triggered, and which boosts/suppressors applied. Evidence is the paper trail.

---

### What confidence means

`confidence` answers: **"How sure are we that this entity type EXISTS in this column?"**

It does NOT answer "what percentage of the column contains this type" — that's `sample_analysis.match_ratio` (prevalence).

| Signal | confidence | prevalence |
|---|---|---|
| Column named `ssn`, 95/100 samples match | 0.99 | 0.95 |
| Column named `data`, 3/100 samples are SSNs | 0.81 | 0.03 |
| Column named `notes`, 1/100 samples is SSN | 0.59 | 0.01 |
| Column named `order_num`, 40/100 match SSN format but fail validation | 0.0 | N/A (discarded) |

### How confidence is computed

**Column name match:**
Uses the base confidence from the profile rule (e.g., SSN rule = 0.95).

**Sample value match:**
Base confidence adjusted by match count (not ratio):

| Matches | Adjustment | Rationale |
|---|---|---|
| 0 | 0.0 (no finding) | Nothing to report |
| 1 | base * 0.65 | Single match could be noise |
| 2-4 | base * 0.85 | Probably real |
| 5-20 | base * 1.0 | Solid evidence |
| 20+ | min(base * 1.05, 1.0) | Abundant evidence |

Validation failures reduce confidence: if only 50% of matches pass secondary validation (Luhn, format check), confidence is halved.

### Minimum threshold

`classify_columns()` accepts `min_confidence` (default: 0.5). Findings below this are not returned. Connectors can adjust:
- `min_confidence=0.3` — high recall, more noise (audit/discovery mode)
- `min_confidence=0.7` — high precision, fewer findings (production tagging)

### How to use prevalence

`sample_analysis.match_ratio` tells the connector how to **act** on a finding:

| Prevalence | Interpretation | Suggested action |
|---|---|---|
| > 0.8 | Column IS this type | Apply policy tag / column-level protection |
| 0.3 - 0.8 | Mixed content, significant PII presence | Flag for review, consider row-level scanning |
| 0.01 - 0.3 | Scattered PII (e.g., notes/comments column) | Content-level redaction, DLP scanning |
| < 0.01 | Rare occurrences | Log for awareness, likely no column-level action |

---

## 7. Migration Plan for BigQuery Connector

### Scope

This replaces `classifier/engine.py` with the `data_classifier` package. `classifier/runner.py` stays in the BQ connector — it handles DB-specific concerns.

### Step-by-step

**1. Add dependency (shared workspace)**
```toml
# pyproject.toml — since we share a workspace:
dependencies = [
    "data_classifier[ml] @ file:///${PROJECT_ROOT}/../data_classifier",
    # ... existing deps
]
```

Or for the BQ connector (sibling folder):
```bash
# From the BigQuery-connector directory:
pip install -e "../data_classifier[ml]"
```

**2. Update runner.py imports**
```python
# BEFORE
from classifier.engine import (
    SENSITIVITY_ORDER,
    ClassificationFinding,
    ClassificationProfile,
    ClassificationRule,
    RollupResult,
    classify_columns,
    compute_rollups,
    load_profile_from_dict,
    load_profile_from_yaml,
    rollup_from_rollups,
)

# AFTER
from data_classifier import (
    SENSITIVITY_ORDER,
    ClassificationFinding,
    ClassificationProfile,
    ClassificationRule,
    ColumnInput,           # NEW
    RollupResult,
    classify_columns,
    compute_rollups,
    load_profile_from_dict,
    load_profile_from_yaml,
    rollup_from_rollups,
)
```

**3. Update connector.py classification call**
```python
# BEFORE
from classifier.engine import classify_columns, compute_rollups, rollup_from_rollups
from classifier.runner import findings_to_dicts, load_profile, write_rollups

all_columns = [col for cols in context.columns.values() for col in cols]
findings = classify_columns(all_columns, cls_profile)

# AFTER
from data_classifier import classify_columns, compute_rollups, rollup_from_rollups, ColumnInput
from classifier.runner import findings_to_dicts, load_profile, write_rollups

all_columns = [col for cols in context.columns.values() for col in cols]
inputs = [
    ColumnInput(
        column_name=col["name"],
        column_id=col["id"],
        data_type=col.get("type", ""),
        description=col.get("description", ""),
        sample_values=col.get("sample_values", []),  # when sampling is implemented
    )
    for col in all_columns
]
findings = classify_columns(inputs, cls_profile)
```

**4. Update test imports**
```python
# tests/test_classification_runner.py, test_connector_classification.py
# BEFORE: from classifier.engine import ...
# AFTER:  from data_classifier import ...
```

**5. Delete classifier/engine.py**
The engine logic now lives in `data_classifier`. Keep `classifier/runner.py` — it's the DB integration layer.

**6. (Optional) Add sample collection**
Implement `TABLESAMPLE` in the BQ collector to populate `sample_values` on column dicts. This is independent of the library migration and can be done before or after.

### What does NOT change
- `classifier/runner.py` — stays, still owns DB profile loading + persistence
- `findings_to_dicts()` — stays, maps findings to BQ connector's DB schema
- `write_rollups()` — stays, writes to `classification_rollups` table
- Rollup logic (`compute_rollups`, `rollup_from_rollups`) — same API, just imported from new package
- Profile YAML format — backward compatible (new `category` field added to each rule)

---

## 8. Testing Contract

The library ships with fixture-based tests ported from the BigQuery connector's test suite. These fixtures are the behavioral contract:

- Every test input (columns + profile) from `test_classification_runner.py` is a fixture
- Every expected output (findings, rollups) is a golden-set fixture
- If the library passes these tests, the migration cannot regress

**After migration, the BQ connector should also run:**
```python
# Verify that data_classifier produces identical results
from data_classifier import classify_columns, ColumnInput, load_profile

profile = load_profile("standard")
inputs = [ColumnInput(column_name="email", column_id="t:email")]
findings = classify_columns(inputs, profile)
assert findings[0].entity_type == "EMAIL"
assert findings[0].sensitivity == "HIGH"
```

---

## 9. Timeline

| Milestone | Owner | Status |
|---|---|---|
| Library v0.5.0 — regex + column name + heuristic + GLiNER ML + ONNX | data_classifier team | Done |
| BQ connector sampling implementation | BQ connector team | In progress |
| BQ connector migration to data_classifier | BQ connector team | Current sprint |
| Library v0.6.0 — meta-classifier, GLiNER2 descriptions, scan depth config | data_classifier team | Next sprint |

---

## 10. Questions / Open Items

1. **Sampling configuration in BQ connector** — what sample size? Configurable per-profile or global? Suggested default: 100 rows per table.

2. **Profile YAML storage** — does the BQ connector want to continue storing profiles in the config DB table, or switch to bundled YAML from the library? The library supports both patterns.

3. **New DB columns** — the `classification_findings` table will need new columns: `category` (TEXT), `evidence` (TEXT), and `match_ratio` (FLOAT). Plan the migration.

4. **Confidence threshold** — the library defaults to `min_confidence=0.5`. Does the BQ connector want to use a different default, or make it configurable via `enrichment_config`?

---

## Appendix A: Full Public API Surface (v0.5.0)

Everything exported from `data_classifier.__init__`:

```python
# Types
ColumnInput
ColumnStats
ClassificationFinding
SampleAnalysis
ClassificationProfile
ClassificationRule
RollupResult

# Functions
classify_columns(
    columns, profile, *,
    min_confidence=0.5,
    budget_ms=None,
    run_id=None,
    config=None,
    mask_samples=False,
    max_evidence_samples=5,
    max_findings=None,                # NEW v0.5.0 — limit findings per column
    confidence_gap_threshold=0.30,    # NEW v0.5.0 — suppress weak secondary findings
)
load_profile(profile_name)
load_profile_from_yaml(profile_name, yaml_path)
load_profile_from_dict(profile_name, data)
compute_rollups(findings, parent_map)
rollup_from_rollups(child_rollups, parent_map)

# Introspection / observability
get_supported_categories()
get_supported_entity_types()
get_supported_sensitivity_levels()
get_pattern_library()
get_active_engines()               # NEW Sprint 9 — engine cascade introspection
health_check(profile=None)         # NEW Sprint 9 — canonical /health probe

# Constants
SENSITIVITY_ORDER
```

## Appendix B: Engine Cascade (v0.5.0)

> **See §5A "Engines Reference"** for the canonical, per-engine documentation added in Sprint 11. The table below is a quick-reference summary; the numbered subsections 5A.1–5A.7 are the source of truth for engine behavior, configuration, and the orchestrator's merge/suppression passes.

| Order | Engine | Authority | What it detects | Requires |
|-------|--------|-----------|----------------|----------|
| 1 | `column_name` | **10** | All types from column name matching (§5A.1) | Nothing beyond `column_name` |
| 2 | `regex` | **5** | Structured patterns — 159 patterns, 14 validators (§5A.2) | `sample_values` |
| 3 | `heuristic_stats` | 1 | SSN/ABA disambiguation, opaque-secret catch-all (§5A.3) | `sample_values` ≥ min_samples |
| 4 | `secret_scanner` | 1 | API keys, private keys, password hashes, opaque secrets (§5A.4) | `sample_values` parseable as KV |
| 5 | `gliner2` | 1 | PERSON_NAME, ADDRESS, ORGANIZATION + reinforcement (§5A.5) | `[ml]` install + ONNX model + text `data_type` |

When the `[ml]` extra is not installed, `gliner2` is silently skipped and the `data_classifier` logger emits a WARNING at import time. Use `get_active_engines()` or `health_check()` (§1e) to assert the expected engine set at startup. The orchestrator's 7-pass merge, dedup, and conflict-resolution pipeline is documented in §5A.6.

## Appendix C: Version History

| Version | Sprint | Key additions |
|---------|--------|--------------|
| v0.1.0 | 1 | RE2 regex engine, 43 patterns, 234 tests |
| v0.2.0 | 2 | Column name engine, 59 patterns, 398 tests |
| v0.3.0 | 3 | Heuristic engine, secret scanner, 603 tests |
| v0.4.0 | 4 | Collision resolution, model registry, real corpora, 681 tests |
| v0.5.0 | 5 | GLiNER ML engine, ONNX deployment, engine weighting, calibration, 777 tests |
