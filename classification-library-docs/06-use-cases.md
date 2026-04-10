# Classification Library — Use Cases

## Use Case 1: BigQuery Data Classification for Access Governance

### Scenario

An organization uses BigQuery as their primary data warehouse. They need to discover and classify all sensitive data across their datasets to feed into SailPoint Identity Security Cloud for access governance, certification campaigns, and least-privilege enforcement.

**Scale:** Hundreds of datasets, thousands of tables, tens of thousands of columns. Many columns contain PII, PHI, PCI, or credentials that no one has formally inventoried. The classification must be accurate enough to drive automated access governance decisions — a false negative means sensitive data goes ungoverned; a false positive triggers unnecessary access restrictions.

### How the Library Addresses This

**Input:** The scanner samples each column (50-100 distinct non-null values), computes basic statistics (distinct count, length distribution, null percentage), and sends a `ColumnInput` to the library via the embedded Python interface or sidecar API.

**Mode:** Column mode (`classify_column` / `classify_table`).

**Profile:** Standard or Advanced — batch processing with no latency pressure, so no budget constraint. Full cascade runs for maximum accuracy.

**Run lifecycle:** One run per scan execution. Scanner starts a run, classifies all columns, completes the run. Events are exported for analysis.

### Column-by-Column Walkthrough

Here is how each tier contributes across representative column types found in a typical BigQuery data warehouse.

#### Column: `customer_email` (STRING, 95K distinct, 100K total)

```
Tier 1 — Column Name Semantics:
  "customer_email" → normalize → "email" → exact match
  Result: PII / email / confidential / confidence 0.95
  → SHORT-CIRCUIT. Classification done in <1ms.
  Tiers 2-9 never execute.
```

This represents the best case for structured data: a well-named column that the cheapest tier resolves instantly. In enterprise BigQuery warehouses with naming conventions, 30-50% of sensitive columns fall into this category.

#### Column: `cc_num` (STRING, all values 16 digits, 80K distinct, 80K total)

```
Tier 1 — Column Name Semantics:
  "cc_num" → substring match "cc" → maps to credit_card, but ambiguous (could be "country code")
  Result: PCI / credit_card / confidence 0.70 (below short-circuit threshold)

Tier 2 — Regex:
  Pattern "\b\d{16}\b" matches 98% of samples
  Luhn validation passes on 97% of matches
  Result: PCI / credit_card / restricted / confidence 0.97
  → HIGH-CONFIDENCE HIT. Combined with Tier 1, classification is definitive.
```

Two tiers corroborate each other. Column name suggests credit card; regex + Luhn confirms. Total time: ~2ms. This is the strength of the cascade: independent signals from different methods reinforce confidence.

#### Column: `notes` (STRING, high cardinality, variable length 10-2000 chars)

```
Tier 1 — Column Name: "notes" → no sensitive match. MISS.
Tier 2 — Regex: scans sample values. Finds email pattern in 3/50 samples, phone in 1/50. LOW confidence.
Tier 3 — Heuristics: high cardinality, variable length, string type → likely free-text field. No classification.
Tier 4 — Cloud DLP: finds PERSON_NAME (likelihood LIKELY) in 12/50 samples. Confidence 0.75.
Tier 5 — Dictionaries: no matches.
Tier 6 — GLiNER2: concatenated samples processed as text. Finds person names, phone numbers, medical conditions.
  Result: PII / mixed_pii / confidential / confidence 0.82
```

Free-text columns are the hardest case for structured data classification. Metadata-based tiers fail because the column name is generic and values have no consistent format. The content-analysis tiers (DLP, GLiNER2) are essential here — they detect entities embedded in natural language that patterns cannot.

#### Column: `remuneration_pkg` (FLOAT64, 45K distinct, 50K total, range 35000-850000)

```
Tier 1 — Column Name: "remuneration_pkg" → no exact match for "remuneration_pkg" in dictionary.
  Substring: "remuneration" found → maps to salary/compensation. Confidence 0.80.
  But FLOAT64 + range 35000-850000 could also be non-sensitive numeric data.

Tier 2 — Regex: numeric values, no pattern match. MISS.
Tier 3 — Heuristics: FLOAT64, high cardinality, range consistent with salary data. Supports classification.
Tier 7 — Embeddings: embed "remuneration_pkg" → cosine similarity 0.91 with "salary" reference vector.
  Result: PII / salary / confidential / confidence 0.91
```

This is where embeddings shine. "Remuneration" isn't in the column name dictionary (it's an unusual synonym), but the embedding model understands its semantic relationship to "salary." Without the embedding tier, this column might only be classified at 0.80 confidence from the substring match.

#### Column: `f7` (STRING, 50K distinct, 50K total, all values length 9, all digits)

```
Tier 1 — Column Name: "f7" → no match. Opaque name. MISS.
Tier 2 — Regex: 9-digit strings match SSN pattern \d{3}-?\d{2}-?\d{4} (without dashes). 
  But also matches ZIP+4, generic IDs. Confidence 0.55 (low).
Tier 3 — Heuristics: length exactly 9 for all values, all digits, 1:1 cardinality ratio.
  Strong signal for a formatted identifier. Confidence boost.
Tier 4 — Cloud DLP: identifies as US_SOCIAL_SECURITY_NUMBER with likelihood POSSIBLE (not LIKELY).
Tier 8 — SLM: receives all signals:
  "Column f7, table employees, STRING, all 9-digit numbers, unique per row, in HR schema"
  SLM reasons: opaque name + 9 digits + employee table + unique = likely SSN or employee ID.
  Result: PII / possible_ssn_or_id / confidential / confidence 0.75
```

The hardest case: opaque column name, ambiguous format, no definitive signal from any single tier. The SLM synthesizes all signals into a reasonable classification. A human reviewer can confirm or reject via the feedback loop, and that feedback improves future classification of similar patterns.

### BigQuery-Specific Considerations

**Sampling strategy:** BigQuery supports `TABLESAMPLE SYSTEM` for efficient random sampling without full table scans. The scanner should use this for tables >10K rows. For smaller tables, `SELECT DISTINCT` with a limit is sufficient.

**Nested and repeated fields:** BigQuery supports STRUCT and ARRAY types. The scanner should flatten nested fields into separate `ColumnInput` entries with qualified names (e.g., `address.street`, `address.city`), preserving the parent structure in the table context.

**Column descriptions:** BigQuery's Information Schema exposes column descriptions via `INFORMATION_SCHEMA.COLUMN_FIELD_PATHS`. These are high-value inputs for both the column name tier and the embedding tier — always include them when available.

**Cost management:** Cloud DLP API calls are the primary cost driver in column mode. With a Standard profile and 10,000 columns, the scanner makes ~3,000-5,000 DLP calls (after fast tiers classify the rest). At Google's current pricing, this is manageable for periodic scans. For continuous scanning, consider the Advanced profile with local-only tiers.

### Mapping to SailPoint

Classification results map to SailPoint entitlement types through the scanner (not the library):

| Classification | SailPoint Mapping |
|---------------|------------------|
| PII / restricted | Entitlement: `pii_restricted_access` → requires certification campaign |
| PHI / restricted | Entitlement: `phi_restricted_access` → HIPAA-governed access |
| PCI / restricted | Entitlement: `pci_data_access` → PCI-DSS scope |
| credentials / restricted | Flag for security team review |
| confidential (any) | Entitlement: `confidential_data_access` → periodic review |

---

## Use Case 2: LLM Prompt Analysis for Intent and Data Leakage

### Scenario

An organization's employees use public LLM services (ChatGPT, Copilot, Claude, Gemini) for daily work. The security team needs to monitor prompt logs to detect sensitive data being sent to these services — both accidental leakage (employee pastes a customer spreadsheet for summarization) and potentially intentional exfiltration (employee systematically extracts proprietary data through LLM queries).

Research data paints a stark picture: approximately 18% of enterprise employees paste data into GenAI tools, and over half of those paste events contain corporate information. Traditional DLP systems miss these because the data flows through browser-based interfaces as unstructured text, not as files or emails that conventional DLP can inspect.

### How the Library Addresses This

**Input:** A prompt gateway or browser extension captures prompt text before it reaches the LLM. The captured text is sent to the **prompt analysis module** via `/analyze/prompt`.

**Mode:** Prompt analysis mode — performs zone segmentation, content detection (delegated to classification library), intent classification, and risk cross-correlation in a single call.

**Profile:** Standard (GLiNER2 is the primary detector for text).

**Budget:** 50-150ms — prompt interception must be fast enough to not noticeably delay the user's LLM interaction.

**Three-dimensional analysis:** Unlike content-only DLP, the prompt module identifies structural zones (instruction vs pasted content), classifies user intent (document_rewrite, code_debug, question_answering), and cross-correlates content × intent × zones into a risk score. This eliminates false positives on educational questions while catching actual data disclosure.

### Prompt Analysis Walkthrough

#### Prompt A: Harmless question
```
User: "What's the best way to handle PII in a data pipeline?"

Module response:
{
  "zones": [{"type": "question", "start": 0, "end": 52}],
  "content": {"classified": false, "results": []},
  "intent": {"primary": "question_answering", "confidence": 0.95},
  "risk": {"score": 0.02, "level": "log", "factors": []},
  "actual_ms": 12
}

Gateway action: ALLOW. No sensitive data, question intent, low risk.
```

The module correctly identifies this as a question zone with question_answering intent. No PII is detected **in** the prompt — asking about PII concepts is not the same as sending PII. A content-only system might flag "PII" as a keyword; the zone + intent analysis correctly scores this as zero risk.

#### Prompt B: Accidental PII disclosure
```
User: "Rewrite this email to be more professional:
Hi John, your SSN 123-45-6789 was used to verify your account. 
Your credit card ending in 4532 was charged $299.99 on March 15."

Library response:
{
  "classified": true,
  "results": [
    {"data_type": "person_name", "sensitivity": "confidential", "tier": "gliner", 
     "span": {"start": 49, "end": 53, "text": "John"}, "confidence": 0.88},
    {"data_type": "ssn", "sensitivity": "restricted", "tier": "regex",
     "span": {"start": 65, "end": 76, "text": "123-45-6789"}, "confidence": 0.99},
    {"data_type": "credit_card_partial", "sensitivity": "confidential", "tier": "gliner",
     "span": {"start": 125, "end": 129, "text": "4532"}, "confidence": 0.72},
    {"data_type": "money", "sensitivity": "internal", "tier": "gliner",
     "span": {"start": 142, "end": 148, "text": "$299.99"}, "confidence": 0.85}
  ],
  "redacted_text": "Rewrite this email to be more professional:\nHi [PERSON_NAME], your SSN [SSN] was used to verify your account.\nYour credit card ending in [CREDIT_CARD_PARTIAL] was charged [MONEY] on March 15.",
  "actual_ms": 38
}

Gateway action: REDACT. Send redacted version to the LLM. Alert security team.
```

This is the canonical accidental leakage scenario. The user is trying to improve an email, not exfiltrate data, but the content includes a full SSN, partial credit card, and a person name. The library detects all of them — regex catches the SSN instantly (format match + Luhn-like structure), GLiNER2 catches the person name and contextual financial entities.

The redacted text preserves the user's intent (the LLM can still rewrite the email) while removing the sensitive data. This is the key UX decision: don't block the user's workflow, protect the data.

#### Prompt C: Code with credentials
```
User: "Fix the error in this Python code:
import boto3
client = boto3.client('s3',
    aws_access_key_id='AKIAIOSFODNN7EXAMPLE',
    aws_secret_access_key='wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'
)"

Library response:
{
  "classified": true,
  "results": [
    {"data_type": "aws_access_key", "sensitivity": "restricted", "tier": "regex",
     "span": {"start": 98, "end": 118, "text": "AKIAIOSFODNN7EXAMPLE"}, "confidence": 0.97},
    {"data_type": "aws_secret_key", "sensitivity": "restricted", "tier": "regex",
     "span": {"start": 150, "end": 190, "text": "wJalrXUtnFEMI..."}, "confidence": 0.95}
  ],
  "actual_ms": 3
}

Gateway action: BLOCK. AWS credentials must not reach any external LLM. 
Alert security team immediately.
```

Regex catches both credentials in 3ms via known provider prefixes (`AKIA` for access keys, high-entropy 40-char string for secret keys). No ML needed. This is the Free profile's strength — even without any ML tiers, credential detection is highly effective because credentials have distinctive patterns.

#### Prompt D: Bulk data paste (spreadsheet data)
```
User: "Summarize the key trends in this data:
Name, Email, Phone, Account Balance
John Smith, john.smith@acme.com, 555-123-4567, $45,230
Jane Doe, jane.doe@example.org, 555-987-6543, $128,450
Bob Johnson, bob.j@corp.net, 555-456-7890, $12,100
... (50 more rows)"

Library response:
{
  "classified": true,
  "results": [
    {"data_type": "person_name", "tier": "gliner", "confidence": 0.92, "count": 53},
    {"data_type": "email", "tier": "regex", "confidence": 0.99, "count": 53},
    {"data_type": "phone_number", "tier": "regex", "confidence": 0.95, "count": 53},
    {"data_type": "money", "tier": "gliner", "confidence": 0.88, "count": 53}
  ],
  "actual_ms": 85
}

Gateway action: BLOCK. Bulk PII (50+ records) warrants immediate block.
Security alert: "User X attempted to upload 53 customer records to ChatGPT."
```

Bulk data paste is the highest-risk leakage pattern. The library detects the entity types; the gateway applies volume-based policy (>10 records of PII = critical risk). The combination of library detection + gateway policy catches what neither could alone.

#### Prompt E: Contextual sensitivity (no explicit PII)
```
User: "Our Q3 revenue was $42M, down 15% from projections. 
The board is considering laying off 200 people from the Austin office.
Draft talking points for the all-hands meeting."

Library response:
{
  "classified": true,
  "results": [
    {"data_type": "money", "sensitivity": "internal", "tier": "gliner",
     "span": {"start": 21, "end": 25, "text": "$42M"}, "confidence": 0.90},
    {"data_type": "location", "sensitivity": "internal", "tier": "gliner",
     "span": {"start": 105, "end": 111, "text": "Austin"}, "confidence": 0.75}
  ],
  "actual_ms": 42
}
```

This is the hardest detection case. The prompt contains material non-public information (MNPI) — unreleased revenue figures and planned layoffs — but no PII/PHI/PCI in the traditional sense. The library detects the financial figure and location. The gateway must layer **intent analysis** and **topic classification** on top:

The library correctly detects what it can (financial amounts, locations). Recognizing that "Q3 revenue" and "layoffs" are MNPI requires business context the library doesn't have. This is where consumer-provided dictionaries add value: the organization can add "Q3 revenue", "board decision", "layoff", "restructuring" as confidential terms, and the dictionary tier catches them.

Alternatively, the embedding tier with a custom taxonomy entry for "material non-public financial information" would catch the semantic theme without keyword matching.

### Prompt Analysis Architecture (Library + Consumer)

![Prompt Analysis Architecture](diagrams/10_prompt_analysis_flow.png)

The prompt analysis module handles zone segmentation, content detection (delegated to the classification library), intent classification, and risk cross-correlation internally. The gateway only needs to call `/analyze/prompt` and act on the returned risk score. Behavioral signals (volume anomaly, after-hours) are provided by the gateway since it owns the user/session context.

### How the Library Design Serves This Use Case

**Latency budget (50-150ms):** Prompt interception must not perceptibly delay the user. The budget system ensures fast tiers always complete and slow tiers race within the deadline. If GLiNER2 finishes in 35ms, the user experiences near-zero delay. If Cloud DLP would take 140ms and exceed the budget, it's skipped — the result is slightly less comprehensive but delivered on time.

**Span detection with offsets:** Entity-level character offsets enable precise redaction. The gateway replaces exactly the sensitive spans, preserving the prompt's structure and intent. Without spans, the gateway would have to block the entire prompt or attempt crude substring replacement.

**Redacted text output:** The library pre-builds the redacted text with placeholder tags (`[SSN]`, `[PERSON_NAME]`). The gateway can send this redacted version to the LLM directly — the user still gets their task done, but without sensitive data leaving the perimeter.

**Profile flexibility:** Some organizations want maximum detection (Advanced profile with SLM, accept ~100ms latency). Others prioritize speed (Free profile with regex only, ~5ms). The profile system lets each deployment choose its accuracy/speed tradeoff.

**Event logging for forensics:** Every classification event includes request_id, timestamp, and tier execution details. The gateway can correlate these with user identity and session information for audit trails and incident investigation.

---

## How the Design Covers Both Use Cases

The two use cases exercise the library from opposite ends of its design space. Here is how each architectural decision serves both:

| Design Decision | BigQuery Classification | Prompt Analysis |
|----------------|------------------------|-----------------|
| **Dual-mode API** | Column mode: metadata + samples | Text mode: raw text + spans |
| **Tier cascade** | Column name + heuristics are primary | GLiNER2 + regex are primary |
| **Budget system** | Not used (batch, full cascade) | Critical (50-150ms deadline) |
| **Profiles** | Standard/Advanced (maximize accuracy) | Standard (balance speed/accuracy) |
| **Span detection** | Not needed (column-level classification) | Essential (redaction offsets) |
| **Redacted output** | Not needed | Core feature (send redacted prompt to LLM) |
| **Cloud DLP** | Primary value-add (batch, cost acceptable) | Often skipped (too slow for budget) |
| **GLiNER2** | Supplementary (free-text columns only) | Primary detector |
| **Embeddings** | High value (column name semantics) | Moderate value (topic detection) |
| **SLM** | Strong (synthesizes all column signals) | Strong (nuanced text classification) |
| **Stateless design** | Scanner owns persistence | Gateway owns persistence |
| **Event logging** | Run-scoped analysis | Real-time alerting + forensics |
| **Customer dictionaries** | Domain-specific data terms | Confidential topics, project names |
| **Fine-tuning** | Improves column classification accuracy | Improves entity detection + reduces false positives |

The library succeeds because the same core engine — tiered detection with mode-specific optimization — naturally adapts to both structured data governance and real-time text analysis. The orchestrator's budget awareness is the key enabler: the same tiers that run sequentially for 200ms in batch mode race in parallel for 100ms in real-time mode, producing the best results possible within each consumer's constraints.
