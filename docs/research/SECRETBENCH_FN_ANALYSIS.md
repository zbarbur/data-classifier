# SecretBench False Negative Analysis

> **Sprint**: 5 (Stream C)
> **Status**: Framework ready; run `python3 scripts/analyze_secretbench_fns.py` after downloading corpus
> **Corpus**: brendtmcfeeley/SecretBench — 1,068 annotated samples (516 TP, 552 TN)

## Background

Sprint 4 benchmarks revealed 388 false negatives against SecretBench (75% FN rate, 24.8% recall).
This analysis categorizes those missed secrets to identify the highest-impact improvement areas.

## FN Category Framework

The analysis script classifies each false negative into one of these categories:

| Category | Description | Likely Fix |
|----------|-------------|------------|
| `connection_string` | JDBC, MongoDB, Redis, etc. URLs with embedded credentials | Add connection string parsers to `parsers.py` |
| `encoded_secret` | Base64-encoded or obfuscated secret values | Add base64 detection + decode step |
| `multiline_secret` | Secret spans multiple lines or split assignment | Multi-line parser support |
| `embedded_in_url` | Credentials in `user:pass@host` URL patterns | URL credential extraction |
| `non_standard_key` | Key name not in our dictionary | Expand `secret_key_names.json` |
| `low_entropy` | Short or dictionary-word secrets | Lower entropy threshold for definitive keys |
| `code_context` | Secrets in XML, TOML, function args, etc. | Additional structural parsers |
| `format_mismatch` | Known key name but value format not matched | Pattern/parser refinement |
| `out_of_scope` | Private keys, certificates (multi-line PEM blocks) | Separate detector or scope expansion |
| `other` | Uncategorized | Manual review |

## How to Run

```bash
# Step 1: Download the corpus (requires internet)
python3 scripts/download_corpora.py --corpus secretbench

# Step 2: Run the analysis
python3 scripts/analyze_secretbench_fns.py --verbose

# Step 3: Generate markdown report
python3 scripts/analyze_secretbench_fns.py --output docs/research/SECRETBENCH_FN_RESULTS.md
```

## Sprint 4 Baseline Numbers

From Sprint 4 benchmarks (SecretBench source):

| Metric | Value |
|--------|-------|
| Total samples | 1,067 |
| True positives | 128 |
| False positives | 263 |
| False negatives | 388 |
| Precision | 0.327 |
| Recall | 0.248 |

## Expected Distribution (Hypothesis)

Based on manual inspection of SecretBench samples:

1. **Connection strings** (~25-30%): JDBC and MongoDB URLs are common in SecretBench
2. **Non-standard key names** (~20-25%): SecretBench uses creative key naming
3. **Code context** (~15-20%): XML configs, TOML files, function arguments
4. **Embedded in URL** (~10-15%): HTTP basic auth patterns
5. **Out of scope** (~5-10%): PEM private keys, certificates
6. **Other** (~5-10%): Various edge cases

## Improvement Priorities

Based on the category distribution, recommended Sprint 6+ work:

### P1: Connection String Parsers
- JDBC URLs: `jdbc:mysql://host:port/db?user=X&password=Y`
- MongoDB: `mongodb+srv://user:pass@host/db`
- Redis: `redis://:password@host:port`
- Generic: `protocol://user:password@host`

### P2: Key-Name Dictionary Expansion
- Review SecretBench naming conventions
- Add entries for non-standard but common patterns
- Consider fuzzy/similarity matching for key names

### P3: Structural Parser Expansion
- XML config file parsing (`<property name="password" value="..."/>`)
- TOML section parsing
- Function argument parsing (e.g., `connect(password="...")`)

---

*Analysis framework created Sprint 5. Results populated after corpus download.*
