# Layered Data Classification Library — Implementation Spec

**Version:** 3.0  
**Date:** April 2026  
**Purpose:** General-purpose, API-first classification engine. Deployable as a standalone service consumed by any client — scanner images, prompt gateways, DLP pipelines, or third-party integrations.

**Related docs:** 01-architecture, 02-api-reference, 03-integration-guide, 04-engines, 05-pipelines, 06-use-cases, 07-performance, 08-prompt-analysis-module-spec, 09-structural-detection-spec, 10-ml-architecture-exploration, 11-ssm-reference-guide, 12-ssm-learning-guide, 13-study-program, CLAUDE.md, DECISIONS.md, research-summary

---

## Architecture Overview

![System Architecture](diagrams/01_system_architecture.png)

### Deployment Modes

| Mode | Description | Use Case |
|------|------------|----------|
| **Embedded library** | Import as Python package, in-process | Scanner images, tight latency |
| **Sidecar service** | Co-deployed container, localhost API | Scanner + other local consumers |
| **Standalone service** | Independent deployment, network API | Multi-consumer, shared infra |
| **Serverless function** | Cloud Run / Lambda per-request | Burst workloads, pay-per-use |

### API Contract

Two classification modes — same library, same tiers, different entry points.

#### Column Mode (Structured Data)

```
POST /classify/column
Content-Type: application/json

{
  "column_name": "customer_ssn",
  "table_name": "users",
  "dataset": "production",
  "data_type": "STRING",
  "description": "Customer identifier",
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
  "config": {}
}

Response:
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
  "profile_used": "standard",
  "tiers_executed": ["column_name_semantics"],
  "tiers_skipped": [],
  "tiers_timed_out": [],
  "budget_ms": null,
  "actual_ms": 2.1,
  "budget_exhausted": false
}
```

**Stats are optional but strongly recommended.** Cheap for the scanner to compute during sampling and massively boost heuristic accuracy.

#### Table Batch (Structured Data — Scanner Convenience)

```
POST /classify/table
{
  "table_name": "users",
  "dataset": "production",
  "columns": [
    {
      "column_name": "customer_ssn",
      "data_type": "STRING",
      "sample_values": ["123-45-6789", ...],
      "stats": {...}
    },
    {
      "column_name": "created_at",
      "data_type": "TIMESTAMP",
      "sample_values": ["2024-01-15T10:30:00Z", ...],
      "stats": {...}
    }
  ],
  "profile": "standard",
  "config": {}
}

Response:
{
  "table_name": "users",
  "results": [
    {"column_name": "customer_ssn", "classified": true, "results": [...]},
    {"column_name": "created_at", "classified": false, "results": []}
  ],
  "actual_ms": 85
}
```

#### Text Mode (Unstructured Data)

```
POST /classify/text
{
  "text": "Patient John Smith, DOB 03/15/1982, diagnosed with Type 2 diabetes",
  "budget_ms": 100,
  "options": {
    "return_spans": true,
    "return_redacted": true
  },
  "profile": "standard",
  "config": {}
}

Response:
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
  "redacted_text": "Patient [PERSON_NAME], DOB [DOB], diagnosed with [MEDICAL_CONDITION]",
  "profile_used": "standard",
  "tiers_executed": ["regex", "cloud_dlp", "gliner2"],
  "tiers_skipped": [],
  "tiers_timed_out": [],
  "budget_ms": null,
  "actual_ms": 45.2,
  "budget_exhausted": false
}
```

#### Shared Config Injection (Both Modes)

Any request can include consumer-owned config:

```json
"config": {
  "dictionaries": [
    {"name": "drug_names", "values": ["Lipitor", "Metformin"], "category": "PHI", "sensitivity": "restricted"}
  ],
  "custom_patterns": [
    {"name": "employee_id", "pattern": "EMP-\\d{6}", "category": "PII", "sensitivity": "confidential"}
  ],
  "custom_labels": ["internal project name", "vendor code"],
  "model_overrides": {
    "slm_model_path": "/models/customer_123/gemma-finetuned"
  }
}
```

#### Feedback (Consumer Persists)

```
POST /feedback

{
  "mode": "column",
  "input": {"column_name": "emp_code", "table_name": "staff", "sample_values": ["EMP-001234"]},
  "original_result": {"data_type": "unknown", "tier": "none"},
  "correction": {"data_category": "PII", "data_type": "employee_id", "sensitivity": "confidential"}
}

Response:
{
  "training_example": {
    "input": {...},
    "label": {...},
    "timestamp": "2026-04-07T12:00:00Z"
  }
}
```

Library returns a validated, formatted training example. Consumer persists it.

#### Utility Endpoints

```
GET  /profiles              → available profiles with tier lists
GET  /labels                → shipped GLiNER2 labels, regex patterns, taxonomy categories
GET  /health                → service health + loaded models
```

### Tier Behavior Per Mode

Each tier implements one or both modes. The orchestrator calls the right method.

![Tier Cascade](diagrams/02_tier_cascade.png)

**Column mode cascade (optimized for structured data):**

```
1. Column name semantics  ← runs first, cheapest, highest signal
2. Regex on sample values
3. Cloud DLP on sample values
4. Value statistics (length, cardinality, entropy)
5. Dictionaries (exact value match)
6. Embeddings on column name + description
7. GLiNER2 on concatenated sample values (less useful but catches edge cases)
8. SLM with full column context
9. LLM fallback
```

**Text mode cascade (optimized for unstructured data):**

```
1. Regex on full text
2. Cloud DLP on full text
3. Dictionaries (token match)
4. GLiNER2 NER  ← primary tier for text mode
5. Embeddings on text chunks
6. SLM with text prompt
7. LLM fallback
```

### Consumer Integration Patterns

| Consumer | Endpoint | What It Sends | What It Uses From Response |
|----------|----------|---------------|--------------------------|
| **BigQuery scanner** | `/classify/table` or embedded `classify_column()` | Column name + samples + stats | `data_category`, `sensitivity`, `data_type` → maps to SailPoint entitlements |
| **Snowflake scanner** | `/classify/table` or embedded `classify_column()` | Same as above | Same as above |
| **Prompt leak detector** | `/classify/text` | Prompt text, `return_spans: true` | `results[].span` → redaction offsets, `sensitivity` → risk scoring |
| **Document DLP** | `/classify/text` | Document text chunks, `return_redacted: true` | `redacted_text` → sanitized document |
| **CI/CD gate** | `/classify/text` | Config files, env vars, logs | `data_type: "credential"` → block deployment |
| **Third-party SaaS** | `/classify/text` or `/classify/column` | Any payload | Full response, consumer decides action |

---

## Tier Cascade

![Tier Cascade](diagrams/02_tier_cascade.png)

**Core principle:** Each tier only processes what previous tiers didn't classify. Cheap/fast first, expensive/heavy last. Every tier returns a standardized `ClassificationResult`.

---

## Design Principle: Zero Customer Data Required

The library MUST deliver strong classification out of the box. Customer-supplied data (dictionaries, fine-tuning labels) is an enhancement, not a prerequisite.

### What Ships Out of the Box (No Customer Input)

| Tier | Out-of-Box Capability |
|------|----------------------|
| Regex | Curated library: 50+ patterns (SSN, CC, IBAN, email, phone, JWT, API keys, etc.) |
| Cloud DLP | Google's 150+ built-in InfoTypes — zero config |
| Heuristics | Column name matching (400+ sensitive field name variants), statistical signals |
| GLiNER2 | Pre-defined label sets: 60+ PII/PHI/PCI/credential entity types |
| Embeddings | Pre-computed reference taxonomy: 80+ sensitive data categories |
| SLM | General classification prompt — works without fine-tuning |
| LLM | General world knowledge — works without any setup |

**Customer dictionaries (Tier 3) is the ONLY tier that requires customer input.** It's skipped when not configured — the cascade jumps from Cloud DLP straight to Heuristics.

### What Customer Data Unlocks (Enhancement, Not Requirement)

- Custom regex patterns for proprietary formats
- Value dictionaries for domain-specific terms (drug names, project codenames)
- Custom GLiNER2 labels for industry-specific entity types
- Fine-tuned GLiNER2/SLM for higher accuracy on their specific data landscape
- Confirmation/rejection feedback that improves models over time

---

## Cost / Performance Profiles

Customers choose a profile through the dashboard. Each profile enables a different set of tiers, trading accuracy for cost and compute.

### Profile Definitions

![Tier Cascade](diagrams/02_tier_cascade.png)

### Resource Requirements per Profile

![Budget Execution](diagrams/09_budget_execution.png)

### Customer Controls (Dashboard)

- **Profile selector**: pick preset or customize which tiers are active
- **Per-tier toggle**: enable/disable individual tiers within a profile
- **Confidence thresholds**: adjust per tier (lower = more aggressive classification)
- **LLM budget cap**: max API calls per scan, max $ per month
- **SLM model selector**: choose model size (1B / 4B / 12B) based on available resources
- **Cloud DLP toggle**: skip entirely to avoid API cost (Free profile)

---

## Gemma Model Family Strategy

All local ML tiers default to Google Gemma models. Natural fit: BigQuery customers are already on GCP, Gemma is Apache 2.0 licensed, and the family covers every tier.

### Tier-to-Model Mapping

| Tier | Model | Size | Why |
|------|-------|------|-----|
| **Embeddings** | **EmbeddingGemma** | 308M | Purpose-built for embeddings, 100+ languages, <200MB quantized, runs on CPU in <22ms. Matryoshka dimensions (768→128) for speed/accuracy tradeoff. Best-in-class under 500M on MTEB. |
| **SLM (budget)** | **Gemma 3 1B** | 1B | Text-only, 32K context, minimal footprint. Good for constrained scanner images. |
| **SLM (balanced)** | **Gemma 3 4B-IT** | 4B | Multimodal, 128K context. Beats Gemma 2 27B on benchmarks. Sweet spot for classification. |
| **SLM (quality)** | **Gemma 4 E4B MoE** | 26B total / 4B active | MoE architecture: only 4B params active per inference, but draws from 26B knowledge. Apache 2.0. Best intelligence-per-compute. |
| **SLM (max local)** | **Gemma 4 31B** | 31B | For customers with GPU resources wanting maximum local accuracy before hitting LLM API. |
| **LLM fallback** | Gemini API / Claude API | - | Customer's choice of API provider. |

### Why Gemma Over Alternatives

- **Apache 2.0 license** (Gemma 4) — no usage restrictions, commercially deployable
- **Native GCP ecosystem** — your customers are already on BigQuery/GCP
- **Full size range** — 270M to 31B covers every resource constraint
- **EmbeddingGemma** — purpose-built for Tier 6, eliminates need for separate embedding model
- **QAT checkpoints** — quantization-aware training means 4-bit inference without accuracy loss
- **Fine-tuning ecosystem** — Unsloth, LoRA, QLoRA all have day-one Gemma support

### SLM Size Decision Tree (Customer Guidance)

```
Scanner runs on shared VM, no GPU?
  → Gemma 3 1B (quantized 4-bit, ~500MB RAM)

Scanner has 4GB+ RAM, CPU only?
  → Gemma 3 4B-IT (quantized, ~2GB RAM)

Scanner has GPU or dedicated instance?
  → Gemma 4 E4B MoE (best accuracy/compute, ~4GB)

Customer wants maximum local accuracy?
  → Gemma 4 31B (needs ~20GB, single GPU)
```

---

## Shared Interfaces

### Python Package (Embedded Mode)

```python
from classification_library import Classifier, Profile, ColumnInput

# --- Column mode (scanner use case) ---
classifier = Classifier(profile=Profile.STANDARD)

result = classifier.classify_column(ColumnInput(
    column_name="customer_ssn",
    table_name="users",
    data_type="STRING",
    sample_values=["123-45-6789", "987-65-4321"],
    stats={"distinct_count": 48000, "total_count": 50000, "min_length": 11, "max_length": 11}
))

# Batch: classify entire table
results = classifier.classify_table(
    table_name="users",
    columns=[col1_input, col2_input, col3_input]
)

# --- Text mode (prompt leak, DLP, documents) ---
result = classifier.classify_text(
    "Patient John Smith, DOB 03/15/1982, diagnosed with Type 2 diabetes",
    return_spans=True,
    return_redacted=True
)
print(result.redacted_text)
# "Patient [PERSON_NAME], DOB [DOB], diagnosed with [MEDICAL_CONDITION]"

# --- With consumer-owned config injection ---
classifier = Classifier(
    profile=Profile.STANDARD,
    custom_patterns=load_from_db(customer_id, "patterns"),
    dictionaries=load_from_db(customer_id, "dictionaries"),
    custom_labels=load_from_db(customer_id, "gliner_labels"),
    slm_model_path="/models/customer_123/gemma-finetuned",
)

# --- Feedback (consumer persists the returned training example) ---
training_example = classifier.feedback(result, correct=False, corrected_type="employee_id")
save_to_db(training_example)
```

### Core Data Model

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class SensitivityLevel(Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"

@dataclass
class Span:
    start: int
    end: int
    text: str

@dataclass
class ClassificationResult:
    data_category: Optional[str]        # "PII", "PHI", "PCI", "credentials"
    data_type: Optional[str]            # "ssn", "email", "credit_card", "person_name"
    sensitivity: Optional[SensitivityLevel]
    confidence: float                   # 0.0 - 1.0
    tier: str                           # which tier classified it
    evidence: Optional[str]             # pattern name, model output, etc.
    span: Optional[Span] = None         # character offsets (text mode only)

@dataclass
class ClassificationResponse:
    classified: bool
    results: list[ClassificationResult]
    redacted_text: Optional[str] = None
    profile_used: str = ""
    tiers_executed: list[str] = field(default_factory=list)
    tiers_skipped: list[str] = field(default_factory=list)
    tiers_timed_out: list[str] = field(default_factory=list)
    budget_ms: Optional[float] = None
    actual_ms: float = 0.0
    budget_exhausted: bool = False

@dataclass
class ColumnInput:
    column_name: str
    table_name: str = ""
    dataset: str = ""
    data_type: str = ""
    description: str = ""
    sample_values: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)  # null_pct, distinct_count, min/max/avg_length, etc.

class ClassificationTier:
    """Base class for all tiers. Implement one or both modes."""
    name: str
    order: int
    min_confidence: float

    def classify_column(self, column: ColumnInput) -> list[ClassificationResult]:
        """Structured data mode. Override if tier supports columns."""
        return []

    def classify_text(self, text: str) -> list[ClassificationResult]:
        """Unstructured text mode. Override if tier supports free text."""
        return []
```

---

## Tier 1: Regex

**Cost:** Zero  
**Latency:** Sub-millisecond  
**Input:** Sample cell values  
**Scope:** Platform-provided + customer-extensible

### Patterns Library

Ship a curated regex library covering common sensitive data formats:

| Category | Pattern Target | Example |
|----------|---------------|---------|
| PII | SSN (US) | `\b\d{3}-\d{2}-\d{4}\b` |
| PII | Email | RFC 5322 pattern |
| PCI | Credit card (Luhn) | `\b(?:\d[ -]*?){13,19}\b` + Luhn check |
| PCI | IBAN | Country-specific prefix + check digit |
| PHI | MRN formats | Institution-specific patterns |
| Credentials | API keys | Provider-specific prefixes (AWS `AKIA`, GCP `AIza`) |
| Credentials | JWT tokens | `eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+` |
| Network | IPv4/IPv6 | Standard patterns |
| Identity | Passport numbers | Country-specific formats |

### Implementation Notes

- **Engine: Google RE2** (`pip install google-re2`). Linear-time guarantee (no catastrophic backtracking — critical for prompt gateways accepting arbitrary input). C++ backend releases GIL for concurrent processing.
- **Two-phase matching:** All 50+ patterns compiled into a single RE2 Set. Phase 1: one pass identifies which patterns matched (C++, ~0.3ms for 10KB). Phase 2: extract positions for only the matched patterns (typically 1-3 hits, not 50 scans).
- Apply Luhn validation for credit card candidates, format checks for SSN/IP/AWS keys.
- Customer-extensible: custom regex via configuration (stored in PostgreSQL, surfaced through Next.js dashboard). Custom patterns compiled into the RE2 set at startup alongside built-in patterns.
- Confidence: 0.95+ for validated patterns (e.g., Luhn-verified CC), 0.7-0.9 for format-only matches.
- **NOT using Python `re` module:** Backtracking engine is vulnerable to ReDoS, scans text separately per pattern (50x overhead), and holds GIL during matching.

---

## Tier 2: Cloud DLP

**Cost:** Per-API-call (Google Cloud DLP / AWS Macie)  
**Latency:** 50-200ms per request  
**Input:** Sample cell values (batched)

### Integration Strategy

- Use Google Cloud DLP `inspect_content` with configurable `InfoType` detectors.
- Batch sample values per column into single API calls (max 500KB per request).
- Map DLP `InfoType` results to internal `data_type` taxonomy.
- Support both built-in InfoTypes (100+ types) and custom InfoTypes defined by customer.
- Apply `min_likelihood` threshold of `LIKELY` to reduce noise.

### State of the Art Context

Leading DSPM vendors (Varonis, Sentra, Forcepoint) combine pattern matching with cloud DLP as their foundational layers. Varonis reports 98% classification accuracy using this combination. Sentra explicitly prioritizes rule-based models wherever possible for structured data due to their deterministic nature and efficiency.

### Key Decision

- Google Cloud DLP is the natural choice given BigQuery integration — same GCP project, no cross-cloud data movement.
- For Snowflake connector: evaluate AWS Macie or run DLP on extracted samples.

---

## Tier 3: Customer-Provided Dictionaries

**Cost:** Zero (runtime)  
**Latency:** Sub-millisecond (hash lookup)  
**Input:** Sample cell values + column names  
**Scope:** Customer-provided and managed

### Design

Customers upload curated value lists through the Next.js dashboard:

- Drug names (brand + generic)
- Disease/condition codes (ICD-10, SNOMED)
- Internal project codenames
- Employee ID formats
- Country/region-specific identifiers
- Custom domain-specific terms

### Storage

![System Architecture](diagrams/01_system_architecture.png)

### Implementation

- Load dictionaries into hash sets at scan startup.
- Support exact match, case-insensitive match, and prefix match modes.
- Allow customer to assign sensitivity level + data category per dictionary.
- Dashboard UI: upload CSV/TXT, preview matches against sample data, activate/deactivate.

---

## Tier 4: Zero-Shot Heuristics

**Cost:** Zero  
**Latency:** Sub-millisecond  
**Input:** Column metadata + sample values  
**Scope:** Statistical and structural analysis

### Heuristic Signals

#### Column Name Semantics
- Fuzzy match column names against known sensitive field name patterns.
- Keyword groups: `["ssn", "social_security", "tax_id", "sin"]` → PII/government_id
- Support abbreviation expansion: `dob` → date_of_birth, `cc_num` → credit_card_number
- Weighted scoring: exact match (1.0), substring match (0.7), edit distance < 2 (0.5)

#### Data Type + Cardinality Analysis
| Signal | Interpretation | Confidence |
|--------|---------------|------------|
| High cardinality + string + name-like column | Likely PII identifier | 0.6 |
| Exactly 2 unique values + boolean-like column | Unlikely sensitive | 0.3 |
| All values same length (9 chars) + digits only | Possible SSN/ID | 0.7 |
| High entropy strings (>4.0 bits/char) | Possible tokens/keys/hashes | 0.65 |

#### Value Shape Analysis
- Length distribution: consistent lengths suggest formatted identifiers
- Character class ratios: all digits vs alphanumeric vs special chars
- Format detection: email-like (`@` + `.`), phone-like (digit groups with separators)
- Entropy calculation per column for token/key/hash detection

#### Metadata Signals
- Column description/comments (BigQuery, Snowflake both expose these)
- Table name context (e.g., column in `patients` table gets higher PHI prior)
- Schema/dataset grouping

---

## Tier 5: GLiNER2 (Unified NER + Classification + Extraction)

**Cost:** Zero (local inference)  
**Latency:** ~10-50ms per batch  
**Input:** Sample cell values (concatenated as text)  
**Scope:** Entity recognition on unstructured/semi-structured values

### Why GLiNER2

GLiNER2 is a bidirectional transformer encoder (<500M parameters) that matches text spans to entity labels in a shared latent space. Key advantages for this use case:

- **Zero-shot**: Define entity labels at runtime — no retraining needed.
- **Runs on CPU**: Critical for scanner images deployed in customer environments.
- **PII-specific models exist**: `knowledgator/gliner-pii-base-v1.0` achieves ~81% F1 on PII benchmarks with 60+ predefined entity categories.
- **Presidio integration**: GLiNER has a built-in `GLiNERRecognizer` in Microsoft Presidio, providing a validated integration path.
- **Fine-tunable**: Can be fine-tuned on customer-specific labeled data (see Fine-Tuning section).
- **GLiNER2**: Newer multi-task variant supports joint NER, text classification, and structured data extraction from a single model.

### Model Selection

| Model | Size | F1 | Deployment |
|-------|------|-----|-----------|
| `knowledgator/gliner-pii-base-v1.0` | ~500M | 80.99% | Best overall accuracy |
| `knowledgator/gliner-pii-edge-v1.0` | Smaller | ~77% | Lower latency, edge deployment |
| `urchade/gliner_multi_pii-v1` | ~500M | Good | Multi-language support |

### Pre-Defined Label Library (shipped by us)

```python
PII_LABELS = [
    "person name", "email address", "phone number", "physical address",
    "date of birth", "social security number", "driver license number",
    "passport number", "national id", "tax id"
]
PHI_LABELS = [
    "medical record number", "medical condition", "diagnosis",
    "medication name", "treatment", "health insurance id"
]
PCI_LABELS = [
    "credit card number", "bank account number", "routing number"
]
CREDENTIAL_LABELS = [
    "api key", "password", "secret token", "access key"
]
```

Customers can extend these label sets through the dashboard.

### Implementation

```python
from gliner2 import GLiNER2

model = GLiNER2.from_pretrained("knowledgator/gliner-pii-base-v1.0")

def classify_with_gliner(sample_values: list[str], labels: list[str]) -> list:
    # Concatenate samples into text blocks for batch processing
    text = " | ".join(sample_values[:50])  # limit sample size
    entities = model.predict_entities(text, labels, threshold=0.5)
    return entities
```

### Performance Considerations

- ONNX quantization (UINT8) for faster CPU inference.
- Batch processing: concatenate column samples, run inference once per column.
- Benchmark target: <100ms per column on standard server hardware.

---

## Tier 6: Zero-Shot Embeddings

**Cost:** One-time embedding generation + vector math at runtime  
**Latency:** ~5-20ms per column (after reference set pre-computed)  
**Input:** Column names + sample values  
**Scope:** Semantic similarity matching

### Approach

1. **Pre-compute reference embeddings** for a standard sensitivity taxonomy (ship with product).
2. **At scan time**: embed column name + representative sample values.
3. **Cosine similarity** against reference set.
4. **Threshold**: classify if similarity > 0.75.

### Reference Taxonomy (pre-embedded)

```python
SENSITIVITY_REFERENCE = {
    "person_name": ["full name", "first name", "last name", "employee name", "patient name"],
    "date_of_birth": ["birthday", "birth date", "DOB", "age", "born on"],
    "salary": ["compensation", "pay", "remuneration", "wage", "earnings", "annual income"],
    "address": ["street address", "home address", "mailing address", "domicile", "residence"],
    "medical_condition": ["diagnosis", "disease", "illness", "health condition", "prognosis"],
    # ... 50+ categories
}
```

### Model Selection

| Model | Params | Dimensions | Strength |
|-------|--------|-----------|----------|
| **EmbeddingGemma** (recommended) | 308M | 768 (MRL: 512/256/128) | Best-in-class <500M on MTEB, 100+ languages, <200MB quantized, <22ms on edge hardware. Same Gemma family as SLM tier. |
| `BAAI/bge-small-en-v1.5` | 33M | 384 | Even smaller, English-only alternative |
| `sentence-transformers/all-MiniLM-L6-v2` | 22M | 384 | Smallest footprint, good baseline |

**Default: EmbeddingGemma.** Use Matryoshka dimensions for profile-based tradeoff:
- **Quality**: 768 dimensions (full)
- **Balanced**: 256 dimensions
- **Speed/storage**: 128 dimensions

### Why Not Earlier in the Stack

Embeddings catch semantic synonyms that heuristics miss (e.g., `remuneration` → salary, `domicile` → address, `fecha_nacimiento` → date_of_birth). But they require model loading overhead and are less precise than pattern-based methods for known formats.

---

## Tier 7: SLM (Small Language Model)

**Cost:** Local inference (no API), moderate compute  
**Latency:** 50-200ms per column  
**Input:** Column metadata + sample values as structured prompt  
**Scope:** Context-aware classification requiring reasoning

### Why SLMs for Data Classification

- **<1B parameters**: Deployable on CPU, no GPU required in production.
- **Privacy-first**: Data never leaves customer environment.
- **Fine-tunable**: LoRA/QLoRA fine-tuning with customer-specific labeled data.
- **Competitive accuracy**: Fine-tuned SLMs outperform general-purpose LLMs on specific classification tasks.
- Symmetry Systems advocates this exact architecture: per-customer SLM instances, fine-tuned on actual customer data, running inside customer infrastructure.

### Model Candidates (Gemma-First)

| Model | Parameters | Memory (4-bit) | Context | Notes |
|-------|-----------|----------------|---------|-------|
| **Gemma 3 1B-IT** | 1B | ~500MB | 32K | Text-only, minimal footprint, Free profile |
| **Gemma 3 4B-IT** | 4B | ~2GB | 128K | Multimodal, beats Gemma 2 27B. Default choice. |
| **Gemma 4 E4B MoE** | 26B total/4B active | ~4GB | - | MoE: 4B active params, 26B knowledge. Best accuracy/compute. Apache 2.0. |
| **Gemma 4 31B** | 31B | ~20GB | - | Maximum local quality. Needs GPU. |
| Qwen 2.5 0.5B/1.5B | 0.5-1.5B | ~300MB-1GB | 32K | Alternative if Gemma unavailable |

**Default: Gemma 3 4B-IT** — strong enough for classification, runs on CPU, 128K context handles large column samples.

### Prompt Template

```
You are a data classification expert. Given a database column and sample values,
classify the sensitivity of this data.

Column: {column_name}
Table: {table_name}
Data type: {data_type}
Sample values: {sample_values}

Respond with JSON only:
{
  "sensitive": true/false,
  "data_category": "PII|PHI|PCI|credentials|IP|public",
  "data_type": "specific_type",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation"
}
```

### Fine-Tuning Strategy (Platform Capability)

This is a key product differentiator. The platform gets more accurate the longer a customer uses it.

#### Data Collection
- Customer confirms/rejects classifications through Next.js dashboard.
- Each confirmation/rejection becomes a labeled training example.
- Store in customer's environment (BigQuery dataset or GCS bucket).

#### Training Pipeline
```
Customer corrections → Labeled dataset (min 500 examples)
    → LoRA fine-tuning (rank 16, alpha 32)
    → Quantized deployment (4-bit via QLoRA)
    → A/B test against base model
    → Deploy if accuracy improves
```

#### Per-Customer vs Shared Model
| Approach | Pros | Cons |
|----------|------|------|
| Per-customer | Privacy-safe, tailored accuracy | Cold start, needs data per customer |
| Shared (anonymized patterns) | Fast cold start, broader coverage | Privacy complexity, averaging effect |

**Recommendation:** Start per-customer. Explore federated learning or pattern-only sharing (not values) as a v2 optimization for cold start.

#### Fine-Tuning GLiNER2 Too
GLiNER2 can also be fine-tuned on customer-labeled data, making Tier 5 stronger over time. This means the earlier, cheaper tier catches more, reducing load on Tier 7-8.

---

## Tier 8: LLM (Last Resort)

**Cost:** Per-token API cost  
**Latency:** 500ms-2s per request  
**Input:** Full context (column metadata + sample values + table context)  
**Scope:** Ambiguous cases requiring broad world knowledge

### When This Fires
- Column passed through all 7 previous tiers without classification.
- Typically: novel data types, domain-specific IP, complex multi-column sensitivity.

### Implementation
- Default to **Gemini Flash** (cheapest capable Google model) — same GCP ecosystem as BigQuery customers.
- Alternative: Claude Haiku, GPT-4o-mini — customer selects in dashboard.
- Batch unclassified columns per table to amortize API cost.
- Cache results: same column pattern in different tables reuses classification.
- Rate limit: cap at N LLM calls per scan to control cost.

---

## Orchestrator Design

### Latency Tracker (Adaptive)

Every tier execution is timed. The orchestrator uses live p95 latency to decide what fits in the remaining budget. Cold start (no history) → run all tiers, collect baseline. System self-tunes within the first few calls.

```python
from collections import deque
import numpy as np
import time

class TierLatencyTracker:
    """Rolling window of actual execution times per tier."""

    def __init__(self, window_size: int = 100):
        self.history: dict[str, deque] = {}

    def record(self, tier_name: str, latency_ms: float):
        if tier_name not in self.history:
            self.history[tier_name] = deque(maxlen=100)
        self.history[tier_name].append(latency_ms)

    def p95(self, tier_name: str) -> float | None:
        """p95 for budget decisions — conservative but not worst-case."""
        if tier_name not in self.history or len(self.history[tier_name]) < 5:
            return None  # not enough data, cold start
        return float(np.percentile(list(self.history[tier_name]), 95))

    def will_fit(self, tier_name: str, remaining_ms: float) -> bool:
        p95 = self.p95(tier_name)
        if p95 is None:
            return True  # cold start: optimistic, run it to collect data
        return p95 < remaining_ms

    def stats(self) -> dict:
        """Expose for /health endpoint."""
        return {
            name: {
                "p50": float(np.percentile(list(times), 50)),
                "p95": float(np.percentile(list(times), 95)),
                "p99": float(np.percentile(list(times), 99)),
                "samples": len(times),
            }
            for name, times in self.history.items()
            if len(times) >= 5
        }
```

### Budget-Aware Orchestrator

```python
import asyncio

class ClassificationOrchestrator:
    # Tiers are grouped by speed class
    FAST_TIERS = {"column_name", "regex", "heuristic_stats", "dictionaries"}
    SLOW_TIERS = {"cloud_dlp", "gliner2", "embeddings", "slm"}
    LAST_RESORT = {"llm"}

    def __init__(self, config: ClassificationConfig):
        self.tiers = [
            ColumnNameTier(),
            RegexTier(config.regex_patterns),
            HeuristicStatsTier(),
            DictionaryTier(config.customer_dicts),
            CloudDLPTier(config.dlp_settings),
            GLiNER2Tier(config.gliner_model, config.custom_labels),
            EmbeddingTier(config.embedding_model),
            SLMTier(config.slm_model),
            LLMTier(config.llm_settings),
        ]
        self.active_tiers = self._resolve_profile(config.profile, config.overrides)
        self.latency = TierLatencyTracker()

    # ─── Column mode ───

    def classify_column(self, column: ColumnInput, budget_ms: float = None) -> ClassificationResponse:
        return self._run_cascade(
            classify_fn=lambda tier: tier.classify_column(column),
            budget_ms=budget_ms,
        )

    def classify_table(self, table_name: str, columns: list[ColumnInput]) -> list[ClassificationResponse]:
        return [self.classify_column(col) for col in columns]

    # ─── Text mode ───

    def classify_text(self, text: str, budget_ms: float = None,
                      return_spans=False, return_redacted=False) -> ClassificationResponse:
        response = self._run_cascade(
            classify_fn=lambda tier: tier.classify_text(text),
            budget_ms=budget_ms,
        )
        if return_redacted and response.results:
            response.redacted_text = self._redact(text, response.results)
        return response

    # ─── Core cascade engine ───

    def _run_cascade(self, classify_fn, budget_ms: float = None) -> ClassificationResponse:
        start = time.monotonic()
        results = []
        tiers_executed = []
        tiers_skipped = []
        tiers_timed_out = []

        fast = [t for t in self.active_tiers if t.name in self.FAST_TIERS]
        slow = [t for t in self.active_tiers if t.name in self.SLOW_TIERS]
        last = [t for t in self.active_tiers if t.name in self.LAST_RESORT]

        # Phase 1: fast tiers — always run synchronously (<5ms total)
        for tier in fast:
            t0 = time.monotonic()
            tier_results = classify_fn(tier)
            elapsed = (time.monotonic() - t0) * 1000
            self.latency.record(tier.name, elapsed)
            tiers_executed.append(tier.name)
            results.extend([r for r in tier_results if r.confidence >= tier.min_confidence])

        # Short-circuit if fast tiers found high-confidence result
        if self._has_definitive_result(results):
            return self._build_response(results, start, tiers_executed, tiers_skipped, tiers_timed_out, budget_ms)

        # No budget → sequential cascade through remaining tiers
        if budget_ms is None:
            for tier in slow + last:
                t0 = time.monotonic()
                tier_results = classify_fn(tier)
                elapsed = (time.monotonic() - t0) * 1000
                self.latency.record(tier.name, elapsed)
                tiers_executed.append(tier.name)
                results.extend([r for r in tier_results if r.confidence >= tier.min_confidence])
                if self._has_definitive_result(results):
                    break
            return self._build_response(results, start, tiers_executed, tiers_skipped, tiers_timed_out, budget_ms)

        # Budget mode → adaptive scheduling based on live latency
        remaining = budget_ms - self._elapsed_ms(start)

        # Phase 2: slow tiers — run those that fit in remaining budget
        # Sort by expected value: accuracy contribution / latency cost
        eligible = []
        for tier in slow:
            if self.latency.will_fit(tier.name, remaining):
                eligible.append(tier)
            else:
                tiers_skipped.append(tier.name)

        # Run eligible slow tiers in parallel
        if eligible:
            phase2_results, phase2_executed, phase2_timed_out = asyncio.run(
                self._race_tiers(eligible, classify_fn, remaining)
            )
            results.extend(phase2_results)
            tiers_executed.extend(phase2_executed)
            tiers_timed_out.extend(phase2_timed_out)

        # Phase 3: LLM — only if budget remains AND nothing found
        remaining = budget_ms - self._elapsed_ms(start)
        if not results and last and remaining > 200:
            tier = last[0]
            if self.latency.will_fit(tier.name, remaining):
                t0 = time.monotonic()
                try:
                    tier_results = asyncio.run(
                        asyncio.wait_for(
                            tier.classify_text_async(classify_fn),
                            timeout=remaining / 1000
                        )
                    )
                    elapsed = (time.monotonic() - t0) * 1000
                    self.latency.record(tier.name, elapsed)
                    tiers_executed.append(tier.name)
                    results.extend(tier_results)
                except asyncio.TimeoutError:
                    tiers_timed_out.append(tier.name)
            else:
                tiers_skipped.append(tier.name)

        return self._build_response(results, start, tiers_executed, tiers_skipped, tiers_timed_out, budget_ms)

    async def _race_tiers(self, tiers, classify_fn, timeout_ms):
        """Run tiers in parallel, collect results until timeout."""
        async def run_tier(tier):
            t0 = time.monotonic()
            result = await asyncio.to_thread(classify_fn, tier)
            elapsed = (time.monotonic() - t0) * 1000
            self.latency.record(tier.name, elapsed)
            return tier.name, [r for r in result if r.confidence >= tier.min_confidence]

        tasks = {asyncio.create_task(run_tier(t)): t for t in tiers}
        executed = []
        timed_out = []
        results = []

        done, pending = await asyncio.wait(
            tasks.keys(), timeout=timeout_ms / 1000, return_when=asyncio.ALL_COMPLETED
        )
        for task in done:
            try:
                tier_name, tier_results = task.result()
                executed.append(tier_name)
                results.extend(tier_results)
            except Exception:
                pass
        for task in pending:
            timed_out.append(tasks[task].name)
            task.cancel()

        return results, executed, timed_out

    # ─── Helpers ───

    def _has_definitive_result(self, results: list) -> bool:
        return any(
            r.confidence >= 0.9 and r.sensitivity in (SensitivityLevel.RESTRICTED, SensitivityLevel.CONFIDENTIAL)
            for r in results
        )

    def _build_response(self, results, start, executed, skipped, timed_out, budget_ms):
        actual_ms = self._elapsed_ms(start)
        return ClassificationResponse(
            classified=len(results) > 0,
            results=results,
            tiers_executed=executed,
            tiers_skipped=skipped,
            tiers_timed_out=timed_out,
            budget_ms=budget_ms,
            actual_ms=round(actual_ms, 1),
            budget_exhausted=budget_ms is not None and actual_ms >= budget_ms,
        )

    def _elapsed_ms(self, start) -> float:
        return (time.monotonic() - start) * 1000

    def _redact(self, text: str, results: list[ClassificationResult]) -> str:
        spans = sorted([r for r in results if r.span], key=lambda r: r.span.start, reverse=True)
        redacted = text
        for r in spans:
            placeholder = f"[{r.data_type.upper()}]"
            redacted = redacted[:r.span.start] + placeholder + redacted[r.span.end:]
        return redacted

    def _resolve_profile(self, profile: str, overrides: dict) -> list:
        PROFILES = {
            "free":     ["column_name", "regex", "heuristic_stats", "dictionaries"],
            "standard": ["column_name", "regex", "heuristic_stats", "cloud_dlp", "dictionaries", "gliner2"],
            "advanced": ["column_name", "regex", "heuristic_stats", "cloud_dlp", "dictionaries", "gliner2", "embeddings", "slm"],
            "maximum":  ["column_name", "regex", "heuristic_stats", "cloud_dlp", "dictionaries", "gliner2", "embeddings", "slm", "llm"],
        }
        enabled = PROFILES.get(profile, PROFILES["standard"])
        if overrides.get("add_tiers"):
            enabled.extend(overrides["add_tiers"])
        if overrides.get("remove_tiers"):
            enabled = [t for t in enabled if t not in overrides["remove_tiers"]]
        return [t for t in self.tiers if t.name in enabled]
```

### FastAPI Service Wrapper (Standalone Mode)

```python
from fastapi import FastAPI
from classification_library import Classifier, Profile, ColumnInput

app = FastAPI(title="Classification Service")
classifier = Classifier(profile=Profile.STANDARD)

@app.post("/classify/column")
async def classify_column(request: ColumnClassifyRequest):
    column = ColumnInput(**request.dict(exclude={"profile", "config", "budget_ms"}))
    return classifier.classify_column(column, budget_ms=request.budget_ms)

@app.post("/classify/table")
async def classify_table(request: TableClassifyRequest):
    columns = [ColumnInput(**c) for c in request.columns]
    return classifier.classify_table(request.table_name, columns)

@app.post("/classify/text")
async def classify_text(request: TextClassifyRequest):
    return classifier.classify_text(
        request.text,
        budget_ms=request.budget_ms,
        return_spans=request.options.get("return_spans", False),
        return_redacted=request.options.get("return_redacted", False),
    )

@app.post("/feedback")
async def feedback(request: FeedbackRequest):
    return classifier.feedback(request)  # returns training example, consumer persists

@app.get("/profiles")
async def profiles():
    return classifier.available_profiles()

@app.get("/labels")
async def labels():
    return classifier.available_labels()

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "loaded_models": classifier.loaded_models(),
        "tier_latency": classifier.latency_stats(),  # live p50/p95/p99 per tier
        "memory_mb": classifier.memory_usage(),
    }
```

### Configuration (per consumer, injected at init or per-request)

```json
{
  "profile": "standard",
  "profile_overrides": {
    "add_tiers": [],
    "remove_tiers": []
  },
  "confidence_thresholds": {
    "regex": 0.7,
    "cloud_dlp": 0.8,
    "gliner2": 0.6,
    "embeddings": 0.75,
    "slm": 0.7,
    "llm": 0.6
  },
  "latency": {
    "default_budget_ms": null,
    "tracker_window_size": 100
  },
  "model_selection": {
    "gliner_model": "knowledgator/gliner-pii-base-v1.0",
    "embedding_model": "google/embeddinggemma-300m",
    "embedding_dimensions": 256,
    "slm_model": "google/gemma-3-4b-it",
    "slm_quantization": "4bit",
    "llm_provider": "gemini",
    "llm_model": "gemini-2.0-flash"
  },
  "cost_budget": {
    "max_dlp_calls_per_scan": 1000,
    "max_llm_calls_per_scan": 50,
    "max_llm_cost_per_month_usd": 50
  }
}
```

**Budget behavior:**
- `default_budget_ms: null` → no budget, full sequential cascade (scanner batch mode)
- `default_budget_ms: 100` → all requests use 100ms budget unless overridden per-request
- Per-request `budget_ms` always overrides default
- Consumer sets budget per use case: scanner = null, prompt interception = 100ms, API consumer = 50ms
```

---

## Consumer Integration Examples

The library is stateless. Consumers own persistence and pass everything in.

### Scanner Consumer — Column Mode

```python
# Scanner code — NOT part of classification library
from classification_library import Classifier, Profile, ColumnInput

# Load customer config from scanner's PostgreSQL
customer_config = db.load_config(customer_id)

classifier = Classifier(
    profile=Profile(customer_config["profile"]),
    dictionaries=db.load_dictionaries(customer_id),
    custom_patterns=db.load_patterns(customer_id),
)

# Sample from BigQuery and classify
for table in tables_to_scan:
    columns = []
    for col in table.columns:
        samples = bq_client.query(
            f"SELECT {col.name} FROM `{table.fqn}` TABLESAMPLE SYSTEM (1 PERCENT) LIMIT 100"
        )
        stats = bq_client.query(
            f"SELECT COUNT(DISTINCT {col.name}) as distinct_count, COUNT(*) as total, ..."
        )
        columns.append(ColumnInput(
            column_name=col.name,
            table_name=table.name,
            dataset=table.dataset,
            data_type=col.data_type,
            description=col.description,
            sample_values=[str(v) for v in samples if v is not None],
            stats=stats,
        ))

    results = classifier.classify_table(table.name, columns)
    db.save_classification_results(table, results)  # scanner persists
```

### Prompt Leak Consumer — Text Mode

```python
from classification_library import Classifier, Profile

classifier = Classifier(profile=Profile.STANDARD)

def intercept_prompt(user_id: str, prompt: str, target_llm: str):
    result = classifier.classify_text(prompt, return_spans=True, return_redacted=True)

    if any(r.sensitivity.value == "restricted" for r in result.results):
        return {"action": "block", "reason": result.results}
    elif result.classified:
        return {"action": "redact", "redacted_prompt": result.redacted_text}
    else:
        return {"action": "allow"}
```

### Document Pipeline Consumer — Text Mode

```python
for chunk in document.chunks(max_chars=5000):
    result = classifier.classify_text(chunk, return_spans=True)
    for r in result.results:
        document.add_label(r.data_category, r.sensitivity, r.span)
```

### Consumer Guidelines

**Column mode:**
- Always send `column_name` — highest-signal input for structured data
- Include `stats` (distinct_count, length distribution) — cheap to compute, big accuracy boost
- Sample 50-100 distinct non-null values
- Send `description` if available (BigQuery and Snowflake both expose column comments)

**Text mode:**
- Send chunks of 1-5KB for optimal GLiNER2 performance
- Request `return_spans: true` if you need redaction offsets
- Request `return_redacted: true` for pre-built redacted text

---

## Observability: Events & Logging

The library emits structured events for every tier execution and classification call. **No pre-aggregation, no time windows** — raw events that consumers persist and analyze however they want.

### Event Schema

```python
@dataclass
class TierEvent:
    """Emitted for every tier execution."""
    type: str = "tier"
    timestamp: datetime
    request_id: str
    run_id: str | None
    mode: str                        # "column" | "text"
    tier: str                        # "regex", "gliner2", etc.
    latency_ms: float
    outcome: str                     # "hit" | "miss" | "timeout" | "skip" | "error"
    results_count: int
    avg_confidence: float | None
    environment: str | None
    consumer: str | None
    profile: str
    budget_ms: float | None
    budget_remaining_ms: float | None

@dataclass
class ClassificationEvent:
    """Emitted per classification call. Wraps tier events."""
    type: str = "classification"
    timestamp: datetime
    request_id: str
    run_id: str | None
    mode: str                        # "column" | "text"
    classified: bool
    result_count: int
    tier_events: list[TierEvent]
    total_ms: float
    budget_ms: float | None
    budget_exhausted: bool
    environment: str | None
    consumer: str | None
    profile: str

@dataclass
class FeedbackEvent:
    """Emitted when consumer submits feedback."""
    type: str = "feedback"
    timestamp: datetime
    request_id: str
    run_id: str | None
    tier: str
    original_data_type: str
    corrected_data_type: str
    correct: bool
    environment: str | None
    consumer: str | None

@dataclass
class RunEvent:
    """Emitted on run start/complete."""
    type: str = "run"
    timestamp: datetime
    run_id: str
    action: str                     # "start" | "complete"
    environment: str | None
    consumer: str | None
    profile: str
    metadata: dict | None
```

### Pluggable Event Handler

Library emits events. Consumer decides where they go.

```python
class EventHandler:
    """Consumer implements this."""
    def emit(self, event: TierEvent | ClassificationEvent | FeedbackEvent | RunEvent):
        raise NotImplementedError

# Built-in handlers (shipped with library)
class NullHandler(EventHandler):          # disabled, zero overhead
class StdoutHandler(EventHandler):        # dev/debug
class JSONLFileHandler(EventHandler):     # file export → /var/log/classification/events.jsonl
class CallbackHandler(EventHandler):      # in-process callback function
class MultiHandler(EventHandler):         # fan-out to multiple handlers

# Consumer-provided handlers (examples)
class PubSubHandler(EventHandler):        # GCP Pub/Sub
class BigQueryStreamHandler(EventHandler): # direct to BQ streaming insert
class WebhookHandler(EventHandler):       # POST to endpoint
```

```python
# Usage
classifier = Classifier(
    profile=Profile.STANDARD,
    event_handler=JSONLFileHandler("/var/log/classification/events.jsonl")
)

# Or fan-out to multiple destinations
classifier = Classifier(
    event_handler=MultiHandler([
        JSONLFileHandler("/var/log/events.jsonl"),   # local file for debugging
        PubSubHandler("projects/my-project/topics/classification-events"),  # analytics pipeline
    ])
)
```

### JSONL Output Format

One JSON object per line. Consumers ingest with BigQuery, Pandas, ELK, Grafana, etc.

```jsonl
{"type":"tier","timestamp":"2026-04-07T14:23:01.123Z","request_id":"req_abc","run_id":"run_123","mode":"column","tier":"regex","latency_ms":0.8,"outcome":"hit","results_count":1,"avg_confidence":0.99,"environment":"production","consumer":"scanner-bq","profile":"standard","budget_ms":null,"budget_remaining_ms":null}
{"type":"tier","timestamp":"2026-04-07T14:23:01.124Z","request_id":"req_abc","run_id":"run_123","mode":"column","tier":"column_name","latency_ms":0.3,"outcome":"hit","results_count":1,"avg_confidence":0.95,"environment":"production","consumer":"scanner-bq","profile":"standard","budget_ms":null,"budget_remaining_ms":null}
{"type":"classification","timestamp":"2026-04-07T14:23:01.125Z","request_id":"req_abc","run_id":"run_123","mode":"column","classified":true,"total_ms":1.2,"budget_ms":null,"budget_exhausted":false,"environment":"production","consumer":"scanner-bq","profile":"standard","tier_count":2,"result_count":2}
```

### Run Lifecycle

Runs are lightweight event wrappers — the library just tags events. Consumers build summaries from logs.

```python
# Start run — emits RunEvent(action="start")
run = classifier.start_run(
    environment="production",
    consumer="scanner-bq",
    metadata={"customer_id": "cust_123", "scan_target": "dataset.users"}
)

# All classifications within this run are tagged with run_id
result = classifier.classify_column(column, run_id=run.run_id)
result = classifier.classify_column(column2, run_id=run.run_id)

# Complete — emits RunEvent(action="complete")
classifier.complete_run(run.run_id)
```

### Consumer-Side Analysis (Examples)

**BigQuery analysis on exported event logs:**

```sql
-- Tier hit rate by environment (last 7 days)
SELECT tier, environment,
  COUNT(*) as invocations,
  COUNTIF(outcome = 'hit') / COUNT(*) as hit_rate,
  APPROX_QUANTILES(latency_ms, 100)[OFFSET(95)] as p95_ms
FROM classification_events
WHERE type = 'tier'
  AND timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY tier, environment

-- Sole contributor: tiers that were the ONLY one to detect something
SELECT tier, COUNT(*) as sole_hits
FROM (
  SELECT request_id, tier
  FROM classification_events
  WHERE type = 'tier' AND outcome = 'hit'
  GROUP BY request_id, tier
  HAVING COUNT(*) = 1
)
GROUP BY tier

-- Run summary from events
SELECT run_id,
  MIN(timestamp) as started,
  MAX(timestamp) as ended,
  TIMESTAMP_DIFF(MAX(timestamp), MIN(timestamp), MILLISECOND) as duration_ms,
  COUNTIF(type = 'classification') as total_classifications,
  COUNTIF(type = 'classification' AND classified = true) as classified,
  COUNTIF(type = 'tier' AND outcome = 'timeout') as timeouts
FROM classification_events
WHERE run_id = 'run_123'
GROUP BY run_id

-- Precision per tier (requires feedback events)
SELECT tier,
  COUNTIF(correct = true) as confirmed,
  COUNTIF(correct = false) as rejected,
  SAFE_DIVIDE(COUNTIF(correct = true), COUNT(*)) as precision
FROM classification_events
WHERE type = 'feedback'
GROUP BY tier
```

### Responsibility Split

![Tier Cascade](diagrams/02_tier_cascade.png)

### Stats API (Live, In-Memory)

The library exposes a lightweight `/stats` endpoint for real-time monitoring. This is derived from the in-memory latency tracker, NOT from persisted logs.

```
GET /stats

{
  "uptime_seconds": 3600,
  "latency_tracker": {
    "regex":       {"p50_ms": 0.5, "p95_ms": 1.2, "p99_ms": 2.1, "samples": 100},
    "gliner2":      {"p50_ms": 28,  "p95_ms": 42,  "p99_ms": 55,  "samples": 100},
    "cloud_dlp":   {"p50_ms": 85,  "p95_ms": 140, "p99_ms": 210, "samples": 87},
    "embeddings":  {"p50_ms": 12,  "p95_ms": 18,  "p99_ms": 25,  "samples": 62}
  },
  "active_runs": ["run_123", "run_456"],
  "loaded_models": ["gliner-pii-base-v1.0", "embeddinggemma-300m"],
  "memory_mb": 1842
}
```

### Feedback Flow

```
Consumer dashboard → User confirms/rejects classification
    → Consumer calls POST /feedback
        → Library emits FeedbackEvent via handler
        → Library returns validated training example
    → Consumer persists training example
    → Consumer periodically triggers fine-tuning pipeline
```

---

---

# Topic 2: Prompt Leak Detection — Analysing LLM Prompt Logs for Data Exfiltration

## Problem Statement

Organizations route employee prompts through a corporate LLM gateway (or audit ChatGPT/Copilot/Claude usage via proxy). The prompt logs contain:

- The raw prompt text
- User identity
- Timestamp
- Target LLM (ChatGPT, Copilot, Claude, Gemini, etc.)
- File attachments (if captured)

**Goal:** Analyze these logs to detect sensitive data leakage and classify intent — distinguishing accidental disclosure from potential exfiltration.

## Market Context

Research shows approximately 18% of enterprise employees paste data into GenAI tools, with over 50% of those paste events containing corporate information. Traditional DLP misses these because prompts are unstructured text pasted into browser-based interfaces, not files or emails. Leading vendors in this space (Cyberhaven, Strac, Nightfall, Endpoint Protector) intercept prompts at the browser/endpoint level. The analysis layer is where your classification library becomes reusable.

## Detection Architecture

![Prompt Analysis Flow](diagrams/10_prompt_analysis_flow.png)

## Layer 1: Content Scanning (Reuse Classification Library)

The same tiered classification engine scans prompt text:

- **Regex**: SSNs, credit cards, API keys, JWTs in prompt text
- **GLiNER2**: Person names, addresses, medical conditions in unstructured prompt text
- **Embeddings**: Semantic detection of confidential topics (M&A terms, unreleased product names)
- **Dictionaries**: Customer-specific confidential terms (project codenames, internal product names)

This is the direct reuse case — same library, different input (prompt text instead of database column values).

## Layer 2: Intent Classification

Not all sensitive data in prompts is a leak. Context matters:

| Intent Category | Example Prompt | Risk Level |
|----------------|---------------|------------|
| Summarize/rewrite | "Rewrite this report to be more concise" + confidential doc | HIGH — full document exposure |
| Debug/troubleshoot | "Fix this error" + stack trace with credentials | HIGH — credential exposure |
| Code assistance | "Help me write a query for this schema" + table structure | MEDIUM — schema exposure |
| General question | "What's the best way to handle PII?" | LOW — educational |
| Data analysis | "Analyze this spreadsheet" + customer data | HIGH — bulk data exposure |
| Translation | "Translate this contract to Spanish" + legal terms | MEDIUM — IP exposure |

### Intent Classification Approach

Use an SLM (same Tier 7 model) fine-tuned for prompt intent classification:

```python
INTENT_LABELS = [
    "document_rewrite",      # full document pasted for editing
    "code_debug",            # code/logs pasted for troubleshooting
    "data_analysis",         # data pasted for analysis/visualization
    "schema_exposure",       # database structure shared
    "credential_exposure",   # passwords/keys/tokens in context
    "general_knowledge",     # no sensitive data, just questions
    "translation",           # content translated
    "content_creation",      # drafting from scratch (low risk)
]
```

### Behavioral Signals

Beyond single-prompt analysis, detect patterns across time:

- **Volume anomaly**: User suddenly submitting 10x more prompts than baseline
- **Bulk paste detection**: Large text blocks (>5KB) pasted, especially from clipboard
- **Sequential extraction**: Multiple prompts extracting different sections of same document
- **After-hours activity**: Sensitive prompts outside business hours
- **Scope creep**: User querying about systems/data outside their normal access scope

## Layer 3: Risk Scoring

```python
@dataclass
class PromptRiskScore:
    content_risk: float       # from classification library (0-1)
    intent_risk: float        # from intent classifier (0-1)
    behavioral_risk: float    # from pattern analysis (0-1)
    composite_score: float    # weighted combination
    sensitive_entities: list   # what was found
    intent: str               # classified intent
    recommended_action: str   # alert/block/redact/log

def compute_risk(content_results, intent, behavior_signals) -> PromptRiskScore:
    content_risk = max(r.confidence for r in content_results) if content_results else 0
    intent_risk = INTENT_RISK_MAP[intent]
    behavioral_risk = compute_behavioral_anomaly(behavior_signals)

    composite = (content_risk * 0.5) + (intent_risk * 0.3) + (behavioral_risk * 0.2)

    if composite > 0.8:
        action = "block"
    elif composite > 0.6:
        action = "alert"
    elif composite > 0.3:
        action = "redact"
    else:
        action = "log"

    return PromptRiskScore(content_risk, intent_risk, behavioral_risk, composite, action=action)
```

## Layer 4: Actions

| Action | Trigger | Behavior |
|--------|---------|----------|
| **Log** | Low risk | Record for audit trail only |
| **Redact** | Medium risk | Replace sensitive spans with `[REDACTED]` before sending to LLM |
| **Alert** | High risk | Notify security team, allow prompt through |
| **Block** | Critical risk | Prevent prompt from reaching LLM, notify user |

### Redaction Integration

GLiNER2 span detection naturally supports redaction — detected entity spans map directly to character offsets that can be masked before the prompt reaches the external LLM.

## Synergy With Classification Library

The prompt leak detection system reuses 80% of the classification library code:

| Classification Library Component | Reuse in Prompt Leak Detection |
|----------------------------------|-------------------------------|
| Regex patterns | Scan prompt text for PII/credentials |
| GLiNER2 model | Entity detection in prompt text |
| Embeddings | Topic/sensitivity matching for prompt content |
| Customer dictionaries | Detect organization-specific confidential terms |
| SLM | Intent classification (new fine-tune target) |
| Orchestrator | Same cascade logic, different input source |

The main addition is the **intent layer** and **behavioral analysis** — everything else is reuse.

---

## Incremental Build Plan

Each stage is independently shippable. The orchestrator works from Stage 1 — you just add tiers over time.

### Stage 1: Foundation + Regex

**Deliverable:** Working library with one tier, usable by scanner immediately.

![Tier Cascade](diagrams/02_tier_cascade.png)

**What works after Stage 1:**
- `classifier.classify("Call me at 123-45-6789")` → detects SSN
- `/classify` API endpoint operational
- Scanner can integrate immediately (embedded or API)
- Free profile fully functional
- Patterns extensible via config (customer adds custom regex without code change)

**Tests:** Pattern accuracy suite — known PII samples, known non-PII samples, false positive rate.

---

### Stage 2: Heuristics

**Add:** `tiers/heuristic_tier.py`

Metadata-driven classification when consumer provides column/table context:

- Column name semantic matching (ship 400+ field name variants)
- Data shape analysis (length distribution, character classes, entropy)
- Table name context boost (column in `patients` table → higher PHI prior)

**What improves:** Scanner sends `metadata.column_name = "ssn"` → classified even if sample values are masked/tokenized. Works without any ML model loaded.

**Tests:** Column name matching accuracy across common schemas (Salesforce, SAP, healthcare, financial).

---

### Stage 3: Cloud DLP

**Add:** `tiers/cloud_dlp_tier.py`

- Google Cloud DLP `inspect_content` integration
- Configurable InfoTypes (default: all built-in)
- Batch optimization (combine samples per API call)
- Pluggable: interface allows swapping to AWS Macie later (Snowflake customers)

**What improves:** Standard profile now functional. Catches complex patterns regex misses (context-aware CC detection, international phone formats, etc.)

**Config addition:**
```python
"cloud_dlp": {
    "enabled": true,
    "project_id": "auto",          # use scanner's GCP project
    "min_likelihood": "LIKELY",
    "max_calls_per_scan": 1000,
    "custom_info_types": []         # customer-defined
}
```

**Tests:** Compare regex-only vs regex+DLP on benchmark dataset. Measure DLP API latency and cost per 1000 columns.

---

### Stage 4: Customer Dictionaries

**Add:** `tiers/dictionary_tier.py`, dictionary management API

- Load value lists from config (JSON/CSV)
- Hash-set lookup: exact, case-insensitive, prefix modes
- API endpoints: `POST /dictionaries`, `GET /dictionaries`, `DELETE /dictionaries/{id}`
- Each dictionary has: name, values, data_category, sensitivity, match_mode

**What improves:** Customers can now catch domain-specific terms (drug names, project codenames, internal IDs) without regex.

**Storage decision:** Dictionaries stored as files (embedded mode) or in PostgreSQL (service mode). Config points to either.

**Tests:** Lookup performance at 100K dictionary entries. False positive rate with common English words.

---

### Stage 5: GLiNER2 NER

**Add:** `tiers/gliner2_tier.py`, model loading infrastructure

- Load `knowledgator/gliner-pii-base-v1.0` (or edge variant for constrained environments)
- Ship pre-defined label sets: PII (10 labels), PHI (6), PCI (3), credentials (4)
- ONNX quantization for CPU inference
- Span detection → character offsets in response (enables redaction by consumers)

**What improves:** Catches entities with no regex pattern — person names, medical conditions, organization names in free text. Prompt leak consumer can now do real entity detection.

**Model loading strategy:**
```python
# Lazy load — model only loaded when tier is first invoked
# Reduces startup time for Free/Standard profiles that don't use GLiNER2
class GLiNER2Tier:
    def __init__(self, model_name, labels):
        self._model = None  # lazy
        self.labels = labels

    def _ensure_model(self):
        if self._model is None:
            self._model = GLiNER2.from_pretrained(self.model_name)
```

**Tests:** F1 score on standard PII benchmark. Latency per classification on CPU. Memory footprint.

---

### Stage 6: Embeddings

**Add:** `tiers/embedding_tier.py`, pre-computed reference taxonomy

- Load EmbeddingGemma (308M) — or fall back to MiniLM if resources constrained
- Ship pre-embedded reference taxonomy: 80+ sensitive data categories with 5 variants each
- Cosine similarity matching at runtime
- Matryoshka dimension selection per profile (768/256/128)

**What improves:** Semantic matching — catches `remuneration` → salary, `domicile` → address, `fecha_nacimiento` → date of birth. Multilingual coverage (100+ languages via EmbeddingGemma).

**Pre-computation (build-time, ships with library):**
```python
# Generated once, shipped as .npz file
taxonomy_embeddings = {}
for category, variants in SENSITIVITY_TAXONOMY.items():
    taxonomy_embeddings[category] = model.encode(variants)
# Saved to patterns/taxonomy_embeddings.npz (~5MB)
```

**Tests:** Semantic matching accuracy across languages. Embedding inference latency. Comparison: embeddings-only vs heuristics+embeddings.

---

### Stage 7: SLM

**Add:** `tiers/slm_tier.py`, model configuration

- Default: Gemma 3 4B-IT (quantized 4-bit via Unsloth/llama.cpp)
- Structured prompt → JSON output (classification result)
- Model size selector in config (1B / 4B / E4B MoE / 31B)
- Fallback: if model fails to load (resource constraints), tier skipped gracefully

**What improves:** Context-aware reasoning on ambiguous data. Handles cases where statistical signals and NER both return low confidence.

**Tests:** Classification accuracy vs GLiNER2-only. Latency per column. Memory footprint per model size.

---

### Stage 8: LLM Fallback

**Add:** `tiers/llm_tier.py`, provider abstraction

- Pluggable provider: Gemini API, Claude API, OpenAI API
- Budget controls: max calls per scan, max $ per month
- Response caching: same column pattern reuses classification
- Batch: group unclassified columns per table into single prompt

**What improves:** Maximum profile now functional. Catches everything previous tiers missed.

**Tests:** Incremental accuracy gain (what % of previously-unclassified columns does LLM catch?). Cost per scan.

---

### Stage 9: Feedback + Fine-Tuning Pipeline

**Add:** `/feedback` endpoint, training data collection, fine-tuning scripts

- Feedback stored per-consumer (scanner feedback separate from prompt feedback)
- Training data export for GLiNER2 and SLM fine-tuning
- GLiNER2 fine-tuning script (Hugging Face trainer)
- SLM LoRA fine-tuning script (Unsloth + Gemma)
- A/B evaluation: fine-tuned model vs base model on held-out test set
- Model versioning: rollback if fine-tuned model performs worse

**What improves:** Platform flywheel — accuracy improves over time. Earlier tiers (GLiNER2, SLM) catch more, reducing expensive LLM calls.

---

### Stage 10: Prompt Analysis Module (MVP)

**Add:** `prompt/analyzer.py`, `prompt/zone_detector.py`, `prompt/intent_classifier.py`

**Prerequisite:** Stage 5 (GLiNER2 NER) + Stage 6 (Embeddings)

- PromptAnalyzer takes Classifier as constructor argument — reuses all content detection engines
- Three-dimension analysis: content (what PII is present) × intent (what the user is doing) × zones (where data sits in the prompt)
- MVP uses heuristic zone detection (regex-based section headers, code block markers) and keyword-based intent classification
- Risk cross-correlation: content severity × zone weight × intent risk × volume → risk score
- Intent reframed as data flow directionality proxy: task type (document_rewrite, code_debug) is the observable signal for "is data leaving the org?"

**What improves:** Classification library can now analyze LLM prompts for data leak risk. First consumer: prompt gateways.

**Full spec:** doc 08 (prompt-analysis-module-spec.md, 1082 lines)

---

### Stage 11: Prompt Analysis (ML Tiers)

**Add:** ML-based zone segmentation (GLiNER2), intent classification cascade (6 tiers: keywords → GLiNER2 → embeddings → NLI → SLM → LLM)

- Replaces heuristic zone detection with GLiNER2 span extraction
- 6-tier intent cascade with early-exit: cheap tiers first, expensive only if ambiguous
- NLI cross-verification: "does this prompt entail data extraction?" — independent check on intent classification
- Behavioral signals: paste detection, prompt injection patterns, unusual volume

**What improves:** Prompt analysis moves from keyword heuristics to ML-powered detection. Major accuracy improvement on intent and zone segmentation.

---

### Stage 12: Structural Detection (Heuristic)

**Add:** `engines/structural_classifier.py`, `engines/boundary_detector.py`, `engines/secret_scanner.py`

Three new engines in the Fast tier:

- **Structural Content Classifier:** Identifies code vs config vs SQL vs log vs CLI vs markup vs prose. Ships as hand-tuned heuristics first (character distribution, keyword density, parse-success signals).
- **Boundary Detector:** Sliding window approach — runs structural classifier on overlapping 5-line windows, detects where classification changes. Localizes content-type transitions in mixed prompts.
- **Structured Secret Scanner:** Deterministic engine. Parses structure (JSON, YAML, env, XML, SQL, CLI args, HTTP headers, code string literals) → extracts key-value pairs → scores via curated key-name dictionary + Shannon entropy + anti-indicators + structure-type boost. Catches secrets regex misses: `DB_PASSWORD=kJ#9xMp$2wLq!`, `{"api_key": "8f14e45f..."}`.

**What improves:** Prompt analysis gets fine-grained zone boundaries. Secret detection catches structured secrets that regex patterns miss.

**Full spec:** doc 09 (structural-detection-spec.md, 1730 lines)

---

### Stage 13: ML Training Pipeline (Offline)

**Add:** `training/` directory with dataset collection, feature engineering, model training, evaluation, export scripts

- Collects training data from public code/config datasets (The Stack, GitHub)
- Engineers 40 numerical features from raw text (character distribution, line patterns, keyword density, structural signals, parse success, word-level, string literals)
- Multi-model benchmark: XGBoost, LightGBM, CatBoost, Random Forest via Optuna
- Exports trained model as pure Python decision rules (<200KB, <0.1ms inference, zero dependencies)
- **Secret scoring optimization:** Trains XGBoost on ~18 features from StarPii dataset (20,961 labeled secrets), then extracts optimized parameters (dictionary weights, entropy thresholds, combination weights, structure boosts) for the deterministic secret scanner. Runtime stays deterministic — only the parameter values are updated.
- Evaluation: 10-fold cross-validation, per-class F1, confusion matrix

**What improves:** Replaces Stage 12 heuristics with ML-trained models. Expected significant accuracy improvement from data-driven decision boundaries.

---

### Stage 14: ML-Trained Structural Detection

**Add:** Replace heuristic structural classifier and boundary detector with ML-trained versions

- Structural classifier: XGBoost on 40 features → pure Python decision rules
- Boundary detector: sliding window with ML classifier (or Mamba-based per-position classifier if Phase 4 of doc 10 justifies it)
- Secret scanner remains deterministic (no ML needed)

**What improves:** Structural engines reach production accuracy. Heuristics kept as fallback.

**ML architecture exploration:** doc 10 (1178 lines) covers CNN/RNN/Attention/SSM alternatives for potential Phase 2-4 neural feature discovery. ModernBERT and StarEncoder evaluated as pre-trained candidates. SSM/Mamba explored for boundary detection specifically (boundaries = state transitions). See docs 11-12 for SSM deep dive.

---

### Stage 15: Runtime Feedback Loop

**Add:** Collect runtime events with features → accumulate labeled examples → periodic retrain

- Consumer feedback (scanner corrections, prompt gateway overrides) becomes training data
- Monthly retrain: tree model on expanded dataset
- Quarterly: re-run neural feature discovery on accumulated data
- Annual: re-evaluate architecture choices, check for new pre-trained code models
- A/B evaluation before any model swap

**What improves:** Continuous accuracy improvement from production data. Closes the loop between deployment and training.

---

### Stage Summary

![Tier Cascade](diagrams/02_tier_cascade.png)

Accuracy estimates are directional — validate with your actual benchmark dataset per stage.

---

### Consumer Integration (Parallel Track)

These happen alongside library stages — scanner can integrate from Stage 1.

| When | Consumer | Integration |
|------|----------|-------------|
| After Stage 1 | **Scanner (BigQuery)** | Embed library, send column samples, map results to SailPoint |
| After Stage 1 | **Scanner (Snowflake)** | Same pattern, different sampler |
| After Stage 5 | **Prompt leak detector** | API consumer, uses spans for redaction |
| After Stage 3 | **CI/CD gate** | API consumer, checks config files for credentials |
| After Stage 5 | **Third-party API clients** | Document and publish API, auth layer |

---

## Key References & Tools

| Resource | Use |
|----------|-----|
| **Gemma 3** (1B/4B/12B/27B) | SLM tier — classification, Apache 2.0 |
| **Gemma 4** (E4B MoE/31B) | SLM tier — latest generation, MoE for best accuracy/compute |
| **EmbeddingGemma** (308M) | Embeddings tier — purpose-built, <200MB, 100+ languages |
| `knowledgator/gliner-pii-base-v1.0` | PII-specialized GLiNER2 model |
| `fastino-ai/GLiNER2` | Multi-task NER + classification |
| Microsoft Presidio + GLiNERRecognizer | Validated integration pattern |
| CASSED (ScienceDirect) | Context-based approach for structured sensitive data detection using BERT |
| Symmetry Systems blog | Architecture reference: per-customer SLM for data classification |
| distil labs | SLM distillation pipeline for PII redaction |
| Unsloth | LoRA/QLoRA fine-tuning with 2x speed, 70% VRAM reduction — Gemma day-one support |
| OWASP LLM Top 10 (2025) | LLM02: Sensitive Information Disclosure framework |
