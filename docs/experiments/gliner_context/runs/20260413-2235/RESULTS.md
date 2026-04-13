# GLiNER context injection — measurement run

- Model: `fastino/gliner2-base-v1`
- Corpus: Ai4Privacy fixture, 21 columns, 30 values each
- Threshold: 0.5
- Strategies: baseline, s1_nl_prompt, s2_per_column_descriptions, s3_label_narrowing

## Overall macro F1

| Strategy | Macro F1 | Columns | Latency p50 (ms) | Latency p95 (ms) | Wall (s) |
|---|---:|---:|---:|---:|---:|
| `baseline` | **0.4636** | 21 | 209.4 | 462.9 | 4.9 |
| `s1_nl_prompt` | **0.5182** | 21 | 218.6 | 415.8 | 4.97 |
| `s2_per_column_descriptions` | **0.4557** | 21 | 251.0 | 478.3 | 5.87 |
| `s3_label_narrowing` | **0.4483** | 21 | 198.9 | 380.9 | 4.45 |

## Per context-kind stratification (macro F1)

| Strategy | empty | helpful | misleading |
|---|---:|---:|---:|
| `baseline` | **0.4042** | **0.5417** | **0.4208** |
| `s1_nl_prompt` | **0.5476** | **0.6667** | **0.5208** |
| `s2_per_column_descriptions` | **0.4875** | **0.5208** | **0.3833** |
| `s3_label_narrowing` | **0.4042** | **0.7429** | **0.3381** |

## Per-entity F1 (baseline strategy only)

| Entity | P | R | F1 | TP | FP | FN |
|---|---:|---:|---:|---:|---:|---:|
| ADDRESS | 0.500 | 1.000 | **0.667** | 3 | 3 | 0 |
| DATE_OF_BIRTH | 0.300 | 1.000 | **0.462** | 3 | 7 | 0 |
| EMAIL | 0.750 | 1.000 | **0.857** | 3 | 1 | 0 |
| IP_ADDRESS | 0.333 | 1.000 | **0.500** | 3 | 6 | 0 |
| ORGANIZATION | 0.000 | 0.000 | **0.000** | 0 | 5 | 0 |
| PERSON_NAME | 0.300 | 1.000 | **0.462** | 3 | 7 | 0 |
| PHONE | 0.273 | 1.000 | **0.429** | 3 | 8 | 0 |
| SSN | 0.333 | 0.333 | **0.333** | 1 | 2 | 2 |
