# Classification Library — API Reference

## Base URL

```
Standalone:  http://localhost:8000
Sidecar:     http://localhost:8000
Embedded:    (Python import, no HTTP)
```

---

## Classification Endpoints

### POST /classify/column

Classify a structured database column using metadata and sample values.

**Request:**

```json
{
  "column_name": "customer_ssn",
  "table_name": "users",
  "dataset": "production",
  "data_type": "STRING",
  "description": "Customer social security number",
  "sample_values": ["123-45-6789", "987-65-4321", "456-78-9012"],
  "stats": {
    "null_pct": 0.02,
    "distinct_count": 48000,
    "total_count": 50000,
    "min_length": 11,
    "max_length": 11,
    "avg_length": 11.0
  },
  "profile": "standard",
  "budget_ms": null,
  "run_id": "run_abc123",
  "config": {}
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `column_name` | string | **yes** | Column name — highest-signal input |
| `table_name` | string | no | Table name for context |
| `dataset` | string | no | Dataset/schema name |
| `data_type` | string | no | SQL data type (STRING, INTEGER, TIMESTAMP, etc.) |
| `description` | string | no | Column description/comment |
| `sample_values` | string[] | no | 10-100 sampled non-null values |
| `stats` | object | no | Column statistics (see below) |
| `profile` | string | no | `free`, `standard`, `advanced`, `maximum`. Default: instance config |
| `budget_ms` | float | no | Latency budget in ms. `null` = no budget, full cascade |
| `run_id` | string | no | Associate with a run for event tagging |
| `config` | object | no | Per-request config overrides (see Config Injection) |

**Stats object:**

| Field | Type | Description |
|-------|------|-------------|
| `null_pct` | float | Percentage of null values (0.0-1.0) |
| `distinct_count` | int | Number of distinct values |
| `total_count` | int | Total row count |
| `min_length` | int | Minimum string length |
| `max_length` | int | Maximum string length |
| `avg_length` | float | Average string length |

**Response:**

```json
{
  "classified": true,
  "results": [
    {
      "data_category": "PII",
      "data_type": "ssn",
      "sensitivity": "restricted",
      "confidence": 0.99,
      "tier": "regex",
      "evidence": "Pattern: US SSN matched 3/3 samples"
    }
  ],
  "tiers_executed": ["column_name", "regex"],
  "tiers_skipped": [],
  "tiers_timed_out": [],
  "budget_ms": null,
  "actual_ms": 1.8,
  "budget_exhausted": false
}
```

---

### POST /classify/table

Classify all columns in a table in a single call.

**Request:**

```json
{
  "table_name": "users",
  "dataset": "production",
  "columns": [
    {
      "column_name": "customer_ssn",
      "data_type": "STRING",
      "sample_values": ["123-45-6789", "987-65-4321"],
      "stats": {"distinct_count": 48000, "total_count": 50000}
    },
    {
      "column_name": "created_at",
      "data_type": "TIMESTAMP",
      "sample_values": ["2024-01-15T10:30:00Z"],
      "stats": {"distinct_count": 50000, "total_count": 50000}
    }
  ],
  "profile": "standard",
  "run_id": "run_abc123",
  "config": {}
}
```

**Response:**

```json
{
  "table_name": "users",
  "results": [
    {
      "column_name": "customer_ssn",
      "classified": true,
      "results": [
        {"data_category": "PII", "data_type": "ssn", "sensitivity": "restricted", "confidence": 0.99, "tier": "regex"}
      ]
    },
    {
      "column_name": "created_at",
      "classified": false,
      "results": []
    }
  ],
  "actual_ms": 45
}
```

---

### POST /classify/text

Classify unstructured text. Returns detected entities with optional character-level spans and redacted text.

**Request:**

```json
{
  "text": "Patient John Smith, DOB 03/15/1982, diagnosed with Type 2 diabetes",
  "budget_ms": 100,
  "options": {
    "return_spans": true,
    "return_redacted": true
  },
  "profile": "standard",
  "run_id": null,
  "config": {}
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `text` | string | **yes** | Text to classify (recommended: 1-5KB chunks) |
| `budget_ms` | float | no | Latency budget. `null` = full cascade |
| `options.return_spans` | bool | no | Include character offsets per entity |
| `options.return_redacted` | bool | no | Return text with entities replaced by placeholders |
| `profile` | string | no | Default: instance config |
| `run_id` | string | no | Associate with a run |
| `config` | object | no | Per-request config overrides |

**Response:**

```json
{
  "classified": true,
  "results": [
    {
      "data_category": "PII",
      "data_type": "person_name",
      "sensitivity": "confidential",
      "confidence": 0.92,
      "tier": "gliner2",
      "span": {"start": 8, "end": 18, "text": "John Smith"},
      "evidence": "GLiNER2 entity: person name"
    },
    {
      "data_category": "PII",
      "data_type": "date_of_birth",
      "sensitivity": "confidential",
      "confidence": 0.88,
      "tier": "gliner2",
      "span": {"start": 24, "end": 34, "text": "03/15/1982"},
      "evidence": "GLiNER2 entity: date of birth"
    },
    {
      "data_category": "PHI",
      "data_type": "medical_condition",
      "sensitivity": "restricted",
      "confidence": 0.85,
      "tier": "gliner2",
      "span": {"start": 51, "end": 67, "text": "Type 2 diabetes"},
      "evidence": "GLiNER2 entity: medical condition"
    }
  ],
  "redacted_text": "Patient [PERSON_NAME], DOB [DATE_OF_BIRTH], diagnosed with [MEDICAL_CONDITION]",
  "tiers_executed": ["regex", "gliner"],
  "tiers_skipped": ["cloud_dlp", "slm"],
  "tiers_timed_out": [],
  "budget_ms": 100,
  "actual_ms": 38.4,
  "budget_exhausted": false
}
```

---

## Config Injection

Any classification request can include consumer-owned configuration. This overrides instance defaults for that request only.

```json
"config": {
  "dictionaries": [
    {
      "name": "drug_names",
      "values": ["Lipitor", "Metformin", "Ozempic"],
      "category": "PHI",
      "sensitivity": "restricted",
      "match_mode": "case_insensitive"
    }
  ],
  "custom_patterns": [
    {
      "name": "employee_id",
      "pattern": "EMP-\\d{6}",
      "category": "PII",
      "sensitivity": "confidential"
    }
  ],
  "custom_labels": ["internal project name", "vendor code"],
  "model_overrides": {
    "slm_model_path": "/models/customer_123/gemma-finetuned",
    "gliner_model": "custom/fine-tuned-gliner"
  },
  "confidence_overrides": {
    "gliner": 0.5,
    "embeddings": 0.8
  }
}
```

---

## Run Management

### POST /runs/start

Start a classification run. All subsequent classifications with this `run_id` are grouped for analysis.

```json
{
  "environment": "production",
  "consumer": "scanner-bq",
  "profile": "standard",
  "metadata": {"customer_id": "cust_123", "scan_target": "dataset.users"}
}
```

**Response:**
```json
{"run_id": "run_abc123"}
```

### POST /runs/{run_id}/complete

Mark a run as complete. Emits a `RunEvent(action="complete")`.

**Response:**
```json
{"run_id": "run_abc123", "status": "complete"}
```

---

## Feedback

### POST /feedback

Submit feedback on a classification result. Library validates and emits a `FeedbackEvent`. Returns a formatted training example for the consumer to persist.

```json
{
  "request_id": "req_xyz",
  "run_id": "run_abc123",
  "tier": "gliner2",
  "correct": false,
  "original_data_type": "phone_number",
  "corrected_data_type": "employee_id",
  "corrected_sensitivity": "confidential"
}
```

**Response:**
```json
{
  "training_example": {
    "input": {"text": "EMP-001234", "mode": "column", "column_name": "emp_code"},
    "label": {"data_category": "PII", "data_type": "employee_id", "sensitivity": "confidential"},
    "original_tier": "gliner",
    "timestamp": "2026-04-07T12:00:00Z"
  }
}
```

---

## Prompt Analysis Endpoints

### POST /analyze/prompt

Analyze a prompt for sensitive data leakage risk. Performs zone segmentation, content detection, intent classification, and risk cross-correlation.

**Request:**

```json
{
  "text": "Rewrite this report:\nEmployee John Smith, SSN 123-45-6789, salary $185K",
  "budget_ms": 100,
  "profile": "standard",
  "behavioral_signals": {
    "prompt_volume_anomaly": 0.0,
    "after_hours": false,
    "paste_size_bytes": 1200,
    "session_entity_count": 0
  },
  "config": {}
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `text` | string | **yes** | Prompt text to analyze |
| `budget_ms` | float | no | Latency budget. `null` = full cascade |
| `profile` | string | no | Profile for content detection tiers |
| `behavioral_signals` | object | no | Consumer-provided behavioral context |
| `config` | object | no | Custom intents, dictionaries, patterns |

**Response:**

```json
{
  "zones": [
    {"type": "instruction", "start": 0, "end": 21, "text": "Rewrite this report:", "confidence": 0.95, "method": "heuristic"},
    {"type": "pasted_content", "start": 22, "end": 74, "text": "Employee John Smith...", "confidence": 0.90, "method": "heuristic"}
  ],
  "content": {
    "classified": true,
    "results": [
      {"data_type": "person_name", "sensitivity": "confidential", "confidence": 0.92, "tier": "gliner2",
       "span": {"start": 31, "end": 41, "text": "John Smith"}, "zone": "pasted_content"},
      {"data_type": "ssn", "sensitivity": "restricted", "confidence": 0.99, "tier": "regex",
       "span": {"start": 47, "end": 58, "text": "123-45-6789"}, "zone": "pasted_content"},
      {"data_type": "salary", "sensitivity": "confidential", "confidence": 0.87, "tier": "gliner2",
       "span": {"start": 67, "end": 72, "text": "$185K"}, "zone": "pasted_content"}
    ]
  },
  "intent": {
    "primary": "document_rewrite",
    "confidence": 0.94,
    "method": "gliner2",
    "all_intents": [
      {"label": "document_rewrite", "confidence": 0.94},
      {"label": "formatting", "confidence": 0.12}
    ]
  },
  "risk": {
    "score": 0.92,
    "level": "block",
    "factors": [
      "restricted_entities_in_pasted_content",
      "high_risk_intent: document_rewrite",
      "multiple_pii_types: 3"
    ],
    "recommended_action": "block",
    "alternative_action": "redact"
  },
  "redacted_text": "Rewrite this report:\nEmployee [PERSON_NAME], SSN [SSN], salary [SALARY]",
  "tiers_executed": {
    "content": ["regex", "gliner2"],
    "intent": ["heuristic", "gliner2"],
    "zones": ["heuristic"]
  },
  "budget_ms": 100,
  "actual_ms": 38
}
```

---

## Utility Endpoints

### GET /profiles

List available profiles with their tier configurations.

```json
{
  "profiles": {
    "free": {"tiers": ["column_name", "regex", "heuristic_stats", "dictionaries"], "cost": "none", "memory_mb": 256},
    "standard": {"tiers": ["column_name", "regex", "heuristic_stats", "cloud_dlp", "dictionaries", "gliner"], "cost": "low", "memory_mb": 1024},
    "advanced": {"tiers": ["..."], "cost": "medium", "memory_mb": 4096},
    "maximum": {"tiers": ["..."], "cost": "higher", "memory_mb": 4096}
  }
}
```

### GET /labels

List all shipped detection capabilities: regex patterns, GLiNER2 entity labels, embedding taxonomy categories.

```json
{
  "regex_patterns": ["us_ssn", "credit_card_luhn", "email", "jwt_token", "aws_access_key", "..."],
  "gliner_labels": {
    "pii": ["person name", "email address", "phone number", "physical address", "..."],
    "phi": ["medical record number", "medical condition", "medication name", "..."],
    "pci": ["credit card number", "bank account number", "routing number"],
    "credentials": ["api key", "password", "secret token", "access key"]
  },
  "embedding_taxonomy_categories": 82,
  "column_name_variants": 412
}
```

### GET /stats

Live operational stats from in-memory latency tracker.

```json
{
  "uptime_seconds": 3600,
  "latency_tracker": {
    "regex": {"p50_ms": 0.5, "p95_ms": 1.2, "p99_ms": 2.1, "samples": 100},
    "gliner": {"p50_ms": 28, "p95_ms": 42, "p99_ms": 55, "samples": 100},
    "cloud_dlp": {"p50_ms": 85, "p95_ms": 140, "p99_ms": 210, "samples": 87},
    "embeddings": {"p50_ms": 12, "p95_ms": 18, "p99_ms": 25, "samples": 62}
  },
  "active_runs": ["run_123", "run_456"],
  "loaded_models": ["gliner-pii-base-v1.0", "embeddinggemma-300m", "gemma-3-4b-it"],
  "memory_mb": 1842
}
```

### GET /health

Service health check.

```json
{"status": "ok", "version": "1.0.0"}
```

---

## Response Fields Reference

### ClassificationResult

| Field | Type | Description |
|-------|------|-------------|
| `data_category` | string | `PII`, `PHI`, `PCI`, `credentials`, `IP` |
| `data_type` | string | Specific type: `ssn`, `person_name`, `credit_card`, etc. |
| `sensitivity` | string | `public`, `internal`, `confidential`, `restricted` |
| `confidence` | float | 0.0-1.0 |
| `tier` | string | Which tier produced this result |
| `evidence` | string | Pattern name, model output, or explanation |
| `span` | object | Character offsets (text mode only, when `return_spans: true`) |
| `span.start` | int | Start character index |
| `span.end` | int | End character index |
| `span.text` | string | Matched text |

### ClassificationResponse (envelope)

| Field | Type | Description |
|-------|------|-------------|
| `classified` | bool | Whether any sensitive data was found |
| `results` | array | List of `ClassificationResult` |
| `redacted_text` | string | Text with entities replaced (when `return_redacted: true`) |
| `tiers_executed` | string[] | Tiers that ran |
| `tiers_skipped` | string[] | Tiers skipped due to budget |
| `tiers_timed_out` | string[] | Tiers that started but exceeded budget |
| `budget_ms` | float | Requested budget (`null` if none) |
| `actual_ms` | float | Total execution time |
| `budget_exhausted` | bool | Whether budget was fully consumed |

---

## Error Responses

```json
{"error": "invalid_profile", "message": "Profile 'ultra' not found. Available: free, standard, advanced, maximum"}
{"error": "tier_unavailable", "message": "GLiNER model not loaded. Check /health for loaded models."}
{"error": "config_invalid", "message": "Custom pattern 'employee_id' has invalid regex: unbalanced parenthesis"}
```

HTTP status codes: `200` success, `400` bad request, `422` validation error, `503` service unavailable (models loading).
