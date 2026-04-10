# Changelog

## Sprint 2 (current)

- Added MkDocs-based documentation site with auto-generated API reference
- Added catalog generation script for patterns, entity types, profiles, and validators
- Added integration guide and code examples

## Sprint 1

- Initial release of the `data_classifier` library
- RE2-based regex engine with two-phase matching (column name + content patterns)
- 43 content patterns across PII, Financial, Credential, and Health categories
- Checksum validators: Luhn (credit cards), SSN zero-group rejection, IPv4 reserved filtering
- Column name matching with 400+ field name variants and fuzzy matching
- Sample-based confidence scoring with prevalence-aware match ratios
- Classification profiles with YAML-based rule definitions
- Bundled `standard` profile with 15 entity types
- Rollup computation (column to table to dataset aggregation)
- Pluggable event telemetry (TierEvent, ClassificationEvent)
- Budget-aware orchestrator with latency budget support
- 234 tests, full CI with ruff linting and formatting
