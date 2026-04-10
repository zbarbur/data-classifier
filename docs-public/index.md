# data_classifier

General-purpose, stateless Python library for detecting and classifying sensitive data in structured database columns. Connector-agnostic -- works with BigQuery, Snowflake, Postgres, or any structured data source.

## Quick Start

Install:
```bash
pip install data_classifier
```

Classify columns:
```python
from data_classifier import classify_columns, load_profile, ColumnInput

profile = load_profile("standard")
columns = [
    ColumnInput(
        column_id="users.email",
        column_name="email_address",
        data_type="STRING",
        sample_values=["john@example.com", "jane@company.org"],
    )
]

findings = classify_columns(columns, profile)
for f in findings:
    print(f"{f.column_id}: {f.entity_type} ({f.confidence:.0%})")
```

## Features

- **RE2 two-phase matching** -- linear-time guarantee, no ReDoS risk
- **43+ content patterns** across PII, Financial, Credential, Health categories
- **Checksum validators** -- Luhn, SSN, IBAN, VIN, and more
- **Column name semantics** -- 400+ field name variants with fuzzy matching
- **Sample-based confidence** -- prevalence-aware scoring
- **Category filtering** -- classify only PII, or only Credentials
- **Budget-aware orchestrator** -- latency budget per request
- **Pluggable events** -- structured telemetry for every classification

## Architecture

The library uses a tiered engine cascade:

1. **Column Name Engine** -- classifies by column name alone (<1ms)
2. **Regex Engine** -- RE2 pattern matching on sample values (<1ms)
3. *(Future)* ML engines, Cloud DLP, dictionary lookup

Each engine produces findings independently. The orchestrator merges results, keeping the highest confidence per entity type.
