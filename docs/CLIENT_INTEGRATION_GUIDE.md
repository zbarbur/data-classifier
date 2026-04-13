# data_classifier — Client Integration Guide

> **Audience:** Connector teams (BigQuery, Snowflake, Postgres, etc.)
> **Version:** 0.8.0 (Sprint 8 — wheel versioning, AR release pipeline, model distribution)
> **Date:** 2026-04-13
> **Status:** READY — forward-only versioning begins at `v0.8.0`; see `CHANGELOG.md` for the history of the earlier `0.1.0` vendored-wheel era

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

**What Light tier misses:** `PERSON_NAME`, `ADDRESS`, and `ORGANIZATION` detection from sample values. These entity types require NER (ML). If your columns have meaningful names (e.g., `full_name`, `street_address`), the column name engine still detects them without ML. ML is only needed when column names are generic or missing.

### 1b. Install recipes

> **Quick reference — pick the recipe that matches your deployment shape.** All recipes pin to `v0.8.0`.

**(A) Google Artifact Registry — recommended for GCP consumers** (including the BigQuery connector):

```bash
pip install \
  --extra-index-url https://us-central1-python.pkg.dev/dag-bigquery-dev/data-classifier/simple/ \
  "data_classifier[ml]==0.8.0"
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
cp dist/data_classifier-0.8.0-py3-none-any.whl <vendor-location>/

# In the consumer's pyproject.toml:
"data_classifier[ml] @ file:vendor/data_classifier-0.8.0-py3-none-any.whl"
```

**(C) Git SSH — for CI systems with a deploy key**

```bash
pip install "data_classifier[ml] @ git+ssh://git@github.com/zbarbur/data-classifier.git@v0.8.0"
```

**(D) Local editable — for development on a workspace with both repos checked out**

```bash
pip install -e "../data_classifier[ml]"
```

**Version pinning:** Always pin to a released tag (`==0.8.0` or `@v0.8.0`), never track a branch in production. The release tag is authoritative; `sprint8/main` and `main` are moving targets.

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

`python -m data_classifier.download_models` is a lean CLI (stdlib-only — no torch, no transformers) that fetches a pre-exported ONNX tarball from the `data-classifier-models` AR Generic repo, verifies its SHA-256, and unpacks to `~/.cache/data_classifier/models/gliner_onnx/`. The `GLiNER2Engine` auto-discovers model files at that path via `_find_bundled_onnx_model()`, so no engine config is needed.

> **Sprint 8 Item 5 status:** `data_classifier.download_models` lands
> within Sprint 8. Until it ships, consumers on Standard tier can either
> (a) pre-populate the cache directory manually from a dev machine where
> the model was first downloaded, or (b) disable ML via
> `DATA_CLASSIFIER_DISABLE_ML=1` and run in regex-only mode (equivalent
> to Light tier's entity coverage).

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

#### Startup health probe (recommended pattern)

The library does not ship a built-in `health_check()` function yet — that's on the Sprint 9 roadmap. For now, consumers should run a one-column smoke test at service startup to verify the cascade is live:

```python
from data_classifier import ColumnInput, classify_columns, load_profile
from data_classifier.events.emitter import EventEmitter, CallbackHandler
from data_classifier.events.types import ClassificationEvent

def startup_health_check() -> dict[str, list[str]]:
    """Runs a canned classification and returns which engines executed.

    Call this from your health endpoint or service startup code to verify
    the cascade is functioning BEFORE taking traffic. Raises RuntimeError
    if no engines executed (e.g. broken install).
    """
    engines_seen: list[str] = []

    def capture(ev):
        if isinstance(ev, ClassificationEvent):
            engines_seen.extend(ev.engines_executed)

    emitter = EventEmitter()
    emitter.add_handler(CallbackHandler(capture))

    probe = ColumnInput(
        column_name="email_address",
        column_id="healthcheck:probe",
        sample_values=["alice@example.com"],
    )
    classify_columns([probe], load_profile("standard"), event_emitter=emitter)

    if not engines_seen:
        raise RuntimeError("data_classifier: no engines executed on probe")

    return {"engines_executed": engines_seen}
```

#### Known gaps (Sprint 9 backlog)

As of v0.8.0 there are three observability gaps you may hit in production:

1. **Silent `[ml]` missing fallback.** `_build_default_engines()` (in `data_classifier/__init__.py`) catches `ImportError` and silently skips the GLiNER2 engine when the `gliner` package is not installed. If your container accidentally ships without `[ml]` extras, there is **no warning log** at startup — classification silently degrades to regex-only. Mitigation: run the startup health check above, which will report `gliner2` absent from `engines_executed`.
2. **No `get_active_engines()` helper.** There is no public introspection function that returns "which engines are loaded and ready". The workaround is the event-emitter probe shown above.
3. **No built-in `health_check()` function.** Each consumer implements its own probe (as shown above). A canonical helper will ship in a future sprint so consumers can drop their own implementation.

These are tracked under the Sprint 9 backlog item `observability-gaps-get-active-engines-health-check-loud-import-error`.

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
    # 0.0-1.0. Represents "how sure are we this entity type EXISTS
    # in this column?" — NOT scaled by prevalence.
    # 3 valid SSNs in 100 samples → high confidence (those are real SSNs).
    # See Section 5 for confidence model details.

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

## 6. Confidence Model (updated v0.5.0)

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

# Constants
SENSITIVITY_ORDER
```

## Appendix B: Engine Cascade (v0.5.0)

The library runs up to 5 engines in order. Each engine adds findings; the orchestrator merges, calibrates, and deduplicates.

| Order | Engine | What it detects | Requires |
|-------|--------|----------------|----------|
| 1 | Column Name | All types from column name matching | Nothing (always runs) |
| 2 | Regex | Structured patterns (SSN, email, phone, credit card, ...) | `sample_values` |
| 3 | Heuristic | Statistical signals (cardinality, format distribution) | `sample_values` |
| 4 | Secret Scanner | Credentials, API keys, secrets in structured text | `sample_values` |
| 5 | GLiNER NER | PERSON_NAME, ADDRESS, ORGANIZATION + reinforcement | `[ml]` install + ONNX model |

When the `[ml]` extra is not installed, the GLiNER engine is silently skipped.

## Appendix C: Version History

| Version | Sprint | Key additions |
|---------|--------|--------------|
| v0.1.0 | 1 | RE2 regex engine, 43 patterns, 234 tests |
| v0.2.0 | 2 | Column name engine, 59 patterns, 398 tests |
| v0.3.0 | 3 | Heuristic engine, secret scanner, 603 tests |
| v0.4.0 | 4 | Collision resolution, model registry, real corpora, 681 tests |
| v0.5.0 | 5 | GLiNER ML engine, ONNX deployment, engine weighting, calibration, 777 tests |
