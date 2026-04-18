# Secret Detection Logic

How the browser scanner detects credentials in free text.

## Overview

The scanner runs two passes over the input text:

1. **Regex pass** — iterates credential regex patterns against the text via
   `String.prototype.matchAll`. Each match is validated, filtered against
   stopwords and allowlists, and emitted as a finding.

2. **Secret-scanner pass** — parses key-value pairs (JSON, env files, code
   literals), scores each key against 271 known secret-key patterns, and
   applies a tiered entropy gate to the value.

Findings from both passes are merged, redacted, and returned.

## Regex pass

For each Credential pattern (123 of 159 total):

1. Compile the regex once (at worker init, not per-scan)
2. `text.matchAll(compiledRe)` yields all matches with offsets
3. Skip if the match is a stopword (per-pattern or global)
4. Skip if the match hits an allowlist pattern
5. Run the validator (if any): `aws_secret_not_hex`, `random_password`,
   `not_placeholder_credential`, or always-true stub for unported validators
6. Emit finding with `engine: "regex"`

Patterns with `requires_column_hint = true` are excluded (no column
context in browser text scanning).

## Secret-scanner pass

### Step 1: Parse key-value pairs

Three parsers run in sequence:

- **JSON** — `JSON.parse` the text. If valid, flatten nested keys with
  dotted notation (`a.b.c`). Return early.
- **Env** — match `export KEY=VALUE` and `KEY=VALUE` lines (quoted or
  unquoted values).
- **Code literals** — match `key = "value"`, `key: "value"`,
  `key := "value"` patterns in source code.

Each parser returns `{key, value, valueStart, valueEnd}` with character
offsets into the original text.

### Step 2: Filter

For each KV pair, reject if:

- `value.length < 8` (minimum value length threshold)
- Key or value contains an anti-indicator (`example`, `test`, `demo`,
  `sample`, etc.)
- Value is a known placeholder (`changeme`, `password`, `secret`, etc.)
- Value matches a placeholder pattern (repeated chars, template markers,
  `YOUR_API_KEY_HERE`, `{{VAR}}`, `${VAR}`, etc. — 21 regex patterns)

### Step 3: Score the key name

Iterate 271 key-name patterns. Each has:

- **pattern** — the string to match (e.g., `password`, `access_token`)
- **match_type** — `substring` (default), `word_boundary`, or `suffix`
- **score** — 0.0 to 1.0 (e.g., `password` = 0.95, `token` = 0.85)
- **tier** — `definitive`, `strong`, or `contextual`
- **subtype** — entity type override (e.g., `API_KEY`, `OPAQUE_SECRET`)

The highest-scoring match wins.

### Step 4: Tiered entropy gate

The tier determines how much evidence the value must provide:

| Tier | Key example | Gate | Rationale |
|------|-------------|------|-----------|
| **definitive** | `password`, `secret_key` | Value is not obviously non-secret | Key name alone is strong enough |
| **strong** | `token`, `auth_token` | Relative entropy >= 0.5 OR diversity >= 3 | Key suggests a secret, value must look random-ish |
| **contextual** | `session_key`, `data_key` | Relative entropy >= 0.7 AND diversity >= 3 | Ambiguous key, value must look very random |

**Entropy measures:**

- **Shannon entropy** — information content in bits per character
- **Relative entropy** — Shannon / max possible for the detected charset
  (hex, base64, alphanumeric, or full printable)
- **Char-class diversity** — count of character classes present
  (uppercase, lowercase, digits, symbols). Range 1-4.

### Step 5: Emit finding

Confidence = `key_score * tier_multiplier_or_entropy_score`, rounded to
4 decimal places. Finding includes `engine: "secret_scanner"`, evidence
string with scoring breakdown, and `kv: {key, tier}`.

## Suppression mechanisms

| Mechanism | What it catches | Source |
|-----------|----------------|--------|
| Anti-indicators | `example`, `test`, `demo`, `sample` in key or value | Generated from Python config |
| Placeholder values | `changeme`, `password`, `secret` (lowercase set) | Generated from Python JSON |
| Placeholder patterns | `(.)\1{7,}`, `<...>`, `YOUR_*_KEY`, `{{VAR}}` | Generated from Python (21 regexes) |
| Config values | `true`, `false`, `production`, `development` | Generated from Python (19 values) |
| URL detection | Values starting with `http://` or `https://` | Generated from Python regex |
| Date detection | Values matching `YYYY-MM-DD` or `YYYY/MM/DD` | Generated from Python regex |
| Prose detection | Values with spaces and >60% alphabetic characters | Threshold from Python config |
| Stopwords | Global + per-pattern stopword sets | Generated from Python JSON |

All suppression data is generated from the Python source via
`scripts/generate_browser_patterns.py`. Changes to the Python library
propagate automatically on the next `npm run generate`.

## Redaction

Four strategies, applied right-to-left (so earlier offsets stay valid):

| Strategy | Output | Example |
|----------|--------|---------|
| `type-label` (default) | `[REDACTED:<TYPE>]` | `[REDACTED:API_KEY]` |
| `asterisk` | `*` repeated to match length | `**********` |
| `placeholder` | Fixed Unicode token | `\u00ABsecret\u00BB` |
| `none` | Original text unchanged | (passthrough) |

## Python parity

The browser scanner operates on free text, not database columns.
Key differences from the Python `data_classifier` library:

- No column-name engine (no column context)
- No heuristic engine (no column-level statistics)
- No meta-classifier (no multi-engine fusion)
- No ML/GLiNER engine
- `requires_column_hint` patterns excluded
- Stopwords checked against match substrings, not full column values

Parity is enforced by `PYTHON_LOGIC_VERSION` (SHA-256 of 6 Python logic
files). The differential test compares JS scanner output against
Python-generated fixtures.
