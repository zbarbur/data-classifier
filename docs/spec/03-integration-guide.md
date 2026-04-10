# Classification Library — Integration Guide

## Quick Start

### Installation

```bash
pip install classification-library
```

### Embedded Mode (Python)

```python
from classification_library import Classifier, Profile, ColumnInput

classifier = Classifier(profile=Profile.STANDARD)

# Classify a database column
result = classifier.classify_column(ColumnInput(
    column_name="customer_email",
    data_type="STRING",
    sample_values=["john@acme.com", "jane@example.org", "bob@corp.net"]
))
print(result.classified)       # True
print(result.results[0].data_type)  # "email"

# Classify free text
result = classifier.classify_text("Call John Smith at 555-123-4567")
print(result.results)          # [person_name, phone_number]
```

### Standalone Service (Docker)

```bash
docker run -p 8000:8000 classification-library:latest

curl -X POST http://localhost:8000/classify/text \
  -H "Content-Type: application/json" \
  -d '{"text": "SSN: 123-45-6789", "profile": "standard"}'
```

---

## Integration Patterns

### Pattern 1: Data Platform Scanner

The scanner samples column values from BigQuery/Snowflake, sends them to the library, and maps results to governance labels.

**Characteristics:** Batch processing, no latency pressure, column mode, full cascade.

```python
from classification_library import Classifier, Profile, ColumnInput

# Load customer config from your database
customer_config = db.load_config(customer_id)

classifier = Classifier(
    profile=Profile(customer_config["profile"]),
    dictionaries=db.load_dictionaries(customer_id),
    custom_patterns=db.load_patterns(customer_id),
    event_handler=JSONLFileHandler("/var/log/classification/events.jsonl"),
)

# Start a run
run = classifier.start_run(
    environment="production",
    consumer="scanner-bq",
    metadata={"customer_id": customer_id}
)

for table in tables_to_scan:
    columns = []
    for col in table.columns:
        # Your sampling logic
        samples = bq_client.query(
            f"SELECT DISTINCT {col.name} FROM `{table.fqn}` LIMIT 100"
        )
        stats = compute_column_stats(col)  # your implementation

        columns.append(ColumnInput(
            column_name=col.name,
            table_name=table.name,
            dataset=table.dataset,
            data_type=col.data_type,
            description=col.description,
            sample_values=[str(v) for v in samples if v is not None],
            stats=stats,
        ))

    # Classify entire table
    results = classifier.classify_table(table.name, columns)

    # Persist results in your database
    for col_input, result in zip(columns, results):
        db.save_classification(table, col_input.column_name, result)

# Complete run
classifier.complete_run(run.run_id)
```

**Recommended settings:**
- Profile: `standard` or `advanced`
- Budget: `null` (no latency pressure)
- Always send `stats` — it's cheap to compute and significantly boosts heuristic accuracy

---

### Pattern 2: Prompt Leak Detection (via Prompt Analysis Module)

Intercept prompts bound for public LLMs, analyze for sensitive data with zone-aware intent-based risk scoring, and decide whether to block, redact, or allow.

**Characteristics:** Real-time, latency-sensitive, uses `/analyze/prompt`, budget-constrained. The prompt module performs zone segmentation (identifying instruction vs pasted content), intent classification (document_rewrite, code_debug, etc.), content detection (delegated to classification library), and risk cross-correlation — all in a single call.

```python
from classification_library import Classifier, Profile
from prompt_analysis import PromptAnalyzer

classifier = Classifier(
    profile=Profile.STANDARD,
    event_handler=PubSubHandler("projects/my-project/topics/prompt-events"),
)
analyzer = PromptAnalyzer(classifier)

async def intercept_prompt(user_id: str, prompt: str, target_llm: str):
    # Full prompt analysis with 100ms budget
    result = await analyzer.analyze(
        prompt,
        budget_ms=100,
        behavioral_signals={
            "prompt_volume_anomaly": get_volume_anomaly(user_id),
            "after_hours": is_after_hours(),
            "paste_size_bytes": len(prompt.encode()),
        }
    )

    # The module returns a risk score with recommended action
    action = result.risk.recommended_action  # "block", "redact", "alert", "log"

    if action == "block":
        log_alert(user_id, result.risk.factors)
        return {"action": "block", "reason": result.risk.factors}
    elif action == "redact":
        return {"action": "redact", "redacted_prompt": result.redacted_text}
    elif action == "alert":
        log_alert(user_id, result.risk.factors)
        return {"action": "allow"}  # allow but alert security team
    else:
        return {"action": "allow"}
```

**Why the prompt module over raw `classify_text`:** The prompt module adds zone segmentation (a question about SSNs is treated differently from pasted SSNs), intent classification (document rewrite has different risk than brainstorming), and zone-weighted risk scoring. These are critical for reducing false positives — content-only detection would alert on "What format is an SSN?" which has zero actual risk.

**Recommended settings:**
- Profile: `standard` (GLiNER2 is the primary detector for text)
- Budget: `50-150ms` depending on acceptable latency
- Always provide `behavioral_signals` — volume anomalies and after-hours activity materially affect risk scores

---

### Pattern 3: Document Pipeline

Scan documents for sensitive data before storage, sharing, or ingestion into AI systems.

**Characteristics:** Batch or streaming, text mode, chunk-based.

```python
from classification_library import Classifier, Profile

classifier = Classifier(profile=Profile.ADVANCED)

def scan_document(document):
    all_results = []
    for chunk in document.chunks(max_chars=5000):
        result = classifier.classify_text(
            chunk.text,
            return_spans=True,
        )
        # Adjust span offsets to document-level
        for r in result.results:
            if r.span:
                r.span.start += chunk.offset
                r.span.end += chunk.offset
        all_results.extend(result.results)

    return {
        "document": document.name,
        "sensitive": len(all_results) > 0,
        "entities": all_results,
        "sensitivity": max((r.sensitivity.value for r in all_results), default="public"),
    }
```

---

### Pattern 4: CI/CD Gate

Block deployments that contain credentials or secrets in configuration files.

```python
import requests

def check_config_file(file_content: str) -> bool:
    response = requests.post("http://classification-service:8000/classify/text", json={
        "text": file_content,
        "profile": "free",  # regex is enough for credentials
        "budget_ms": 50,
    })
    data = response.json()
    credentials = [r for r in data["results"] if r["data_category"] == "credentials"]
    if credentials:
        print(f"BLOCKED: Found {len(credentials)} credentials in config")
        return False
    return True
```

---

## Configuration

### Instance Configuration

Set at initialization. Applies to all requests unless overridden.

```python
classifier = Classifier(
    # Profile
    profile=Profile.STANDARD,

    # Custom patterns (consumer loads from their storage)
    custom_patterns=[
        {"name": "employee_id", "pattern": r"EMP-\d{6}", "category": "PII", "sensitivity": "confidential"},
        {"name": "project_code", "pattern": r"PRJ-[A-Z]{3}-\d{4}", "category": "IP", "sensitivity": "internal"},
    ],

    # Custom dictionaries (consumer loads from their storage)
    dictionaries=[
        {"name": "drug_names", "values": ["Lipitor", "Metformin"], "category": "PHI", "sensitivity": "restricted"},
    ],

    # Custom GLiNER labels (extends shipped labels)
    custom_labels=["internal project name", "vendor code", "deal ID"],

    # Model paths (for fine-tuned models)
    slm_model_path="/models/customer_123/gemma-finetuned",

    # Observability
    event_handler=JSONLFileHandler("/var/log/classification/events.jsonl"),

    # Latency
    default_budget_ms=None,  # no budget by default
    latency_tracker_window=100,  # rolling window size
)
```

### Per-Request Configuration

Override instance config for a single request. Useful for multi-tenant API consumers.

```json
POST /classify/column
{
  "column_name": "...",
  "config": {
    "dictionaries": [{"name": "custom", "values": [...], "category": "PII"}],
    "custom_patterns": [{"name": "internal_id", "pattern": "ID-\\d+", "category": "PII"}],
    "confidence_overrides": {"gliner": 0.5}
  }
}
```

---

## Event Handling

The library emits structured events for every operation. Configure a handler to capture them.

### Built-in Handlers

```python
from classification_library.events import (
    NullHandler,        # disabled
    StdoutHandler,      # print to console (dev)
    JSONLFileHandler,   # write to .jsonl file
    CallbackHandler,    # call your function
    MultiHandler,       # fan-out to multiple handlers
)

# Development
classifier = Classifier(event_handler=StdoutHandler())

# Production: file + custom pipeline
classifier = Classifier(event_handler=MultiHandler([
    JSONLFileHandler("/var/log/events.jsonl"),
    CallbackHandler(lambda event: my_pubsub_client.publish(event)),
]))
```

### Custom Handler

```python
from classification_library.events import EventHandler

class BigQueryHandler(EventHandler):
    def __init__(self, table_id):
        self.client = bigquery.Client()
        self.table_id = table_id

    def emit(self, event):
        row = event.to_dict()
        self.client.insert_rows_json(self.table_id, [row])
```

### Event Types

| Event | Emitted When | Key Fields |
|-------|-------------|------------|
| `TierEvent` | Each tier executes | `tier`, `outcome`, `latency_ms`, `results_count` |
| `ClassificationEvent` | Each classify call completes | `mode`, `classified`, `total_ms`, `budget_exhausted` |
| `FeedbackEvent` | Consumer submits feedback | `tier`, `correct`, `corrected_data_type` |
| `RunEvent` | Run starts or completes | `run_id`, `action` |

All events include: `timestamp`, `request_id`, `run_id`, `environment`, `consumer`, `profile`.

---

## Best Practices

### Structured Data (Column Mode)

1. **Always send `column_name`** — it's the highest-signal input. A column named `ssn` is classified in microseconds without touching sample values.
2. **Include `stats`** — `distinct_count`, `total_count`, and length statistics are cheap to compute and significantly improve heuristic accuracy.
3. **Sample 50-100 distinct non-null values** — more is diminishing returns, fewer risks missing edge cases.
4. **Send `description`** when available — BigQuery and Snowflake both expose column comments through their metadata APIs.
5. **Use `classify_table`** for batch — classifies all columns in one call with shared context.

### Unstructured Data (Text Mode)

1. **Chunk text to 1-5KB** — GLiNER performs best on focused text segments, not entire documents.
2. **Request `return_spans: true`** if you need to know where entities are (redaction, highlighting).
3. **Set `budget_ms`** for real-time use cases (prompt interception, live API). Omit for batch.
4. **Adjust span offsets** when chunking documents — spans are relative to the chunk, not the document.

### Performance

1. **Start with the Free profile** — regex + heuristics catches 50%+ of common sensitive data for zero cost.
2. **Measure before upgrading profiles** — use event logs to quantify what each tier adds.
3. **Use budget mode** for latency-sensitive consumers — the library will parallelize slow tiers and skip those that won't fit.
4. **Monitor `/stats`** — live p95 latency per tier tells you exactly where time is spent.
5. **Lazy model loading** — ML models (GLiNER, Embeddings, SLM) load on first use, not at startup.

### Observability

1. **Always configure an event handler** — even `JSONLFileHandler` is better than `NullHandler`.
2. **Include `environment` and `consumer`** in runs — enables scoped analysis.
3. **Submit feedback** — without it, you have hit rate but not precision.
4. **Export events to BigQuery or similar** for trend analysis: tier effectiveness over time, coverage drift, cost ROI.
