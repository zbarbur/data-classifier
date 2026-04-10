# Engineering Gotchas — data_classifier

> Lessons learned from development. Check here before making architectural decisions.

---

## 1. RE2 Compatibility

### 1.1 No lookahead/lookbehind
RE2 guarantees linear-time matching by rejecting backreferences, lookahead (`(?=...)`), and lookbehind (`(?<=...)`). Every pattern must be tested with `re2.compile()` before adding to the library.

**Fix:** Use character classes and alternation instead. Test every pattern in `test_patterns.py`.

### 1.2 Word boundaries behave differently
RE2's `\b` doesn't match before non-word characters like `+`. The international phone pattern `\b\+\d{1,3}...` fails because `+` is not a word character.

**Fix:** Drop `\b` from patterns that start with non-word characters, or use alternation.

### 1.3 RE2 Set needs an anchor argument
`re2.Set()` requires `re2._Anchor.UNANCHORED` as the first argument. Omitting it raises `TypeError`.

```python
# Wrong
s = re2.Set()

# Right
s = re2.Set(re2._Anchor.UNANCHORED)
```

### 1.4 RE2 Set.Match returns None, not empty list
When no patterns match, `re2.Set.Match()` returns `None`, not `[]`. Always check for `None`.

---

## 2. GitHub Push Protection

### 2.1 Credential test examples trigger push protection
GitHub scans for token prefixes (`xoxb-`, `sk_live_`, `glpat-`, `shpat_`, `dapi`) even with all-zeros values. Base64 encoding is also decoded.

**Fix:** XOR-encode credential examples in `default_patterns.json` (key=0x5A). The pattern loader decodes them at runtime. Credential examples masked in HTML reference.

### 2.2 Push protection is org-level
Disabling push protection in repo settings may not override org-level rules. The `.github/secret_scanning.yml` `paths-ignore` only applies to scanning alerts, not push protection.

**Fix:** XOR encoding is the reliable solution. Alternatively, use the "allow secret" URLs GitHub provides per blocked push.

---

## 3. Profile Rule Ordering

### 3.1 First-match-wins means ordering matters
`classify_columns()` matches column names against profile rules in order. The first matching rule wins. More specific patterns MUST come before less specific ones.

**Example:** `ip_address` matches the `ADDRESS` rule's pattern `(^|_)(address|...)` before reaching the `IP_ADDRESS` rule. Fix: move `IP_ADDRESS` before `ADDRESS` in the profile.

**Fix:** Golden fixture tests catch ordering bugs. Always add a fixture for new entity types.

### 3.2 RE2 Set index order maps to rule order
The profile Set is built by iterating rules in YAML order. The lowest Set index that matches maps to the earliest rule. This preserves first-match-wins semantics with RE2.

---

## 4. Confidence Model

### 4.1 Confidence is not prevalence
Confidence answers "does this entity type exist in the column?" (0.0-1.0). Prevalence is `sample_analysis.match_ratio` — what fraction of the column contains this type. Don't conflate them.

### 4.2 Single match confidence is low
One matching sample value gives confidence ~0.65 × base. This is by design — a single match could be coincidence. Consumers should use `min_confidence` to control their sensitivity.

### 4.3 Validation failures reduce confidence proportionally
If 10 values match the SSN regex but only 2 pass the zero-group validator, confidence drops to `base * (2/10) * match_count_factor`. This correctly handles columns with order numbers that look like SSNs.

---

## 5. Testing

### 5.1 Credential examples need special handling
Credential pattern `examples_match` are XOR-encoded in the JSON. The test harness decodes them via `load_default_patterns()`. Tests that construct patterns manually must call `_decode_examples()`.

### 5.2 Golden fixtures are the behavioral contract
The `tests/fixtures/golden_column_name.yaml` and `golden_rollups.yaml` fixtures were ported from the BigQuery connector. If these tests pass, Sprint 27 migration cannot regress. Never weaken a golden fixture assertion.

### 5.3 ClassificationFinding has category as a required field
When constructing `ClassificationFinding` in tests, the `category` field must be provided. Tests ported from the BQ connector need this added.

---

## 6. Packaging

### 6.1 setuptools build backend
Use `setuptools.build_meta`, not `setuptools.backends._legacy:_Backend` (which doesn't exist in all setuptools versions).

### 6.2 Package data requires explicit inclusion
YAML profiles and JSON patterns must be declared in `pyproject.toml`:
```toml
[tool.setuptools.package-data]
data_classifier = ["profiles/*.yaml", "patterns/*.json"]
```

---

## 7. API Design

### 7.1 Category dimension is separate from regulatory
`regulatory` (GDPR, HIPAA) answers "which compliance framework cares." `category` (PII, Financial) answers "what kind of data." `sensitivity` (CRITICAL, HIGH) answers "how dangerous." All three are independent dimensions.

### 7.2 Post-filter category, pre-filter for ML
Category filtering currently happens after engine results (post-filter). This is fine for regex (<1ms). For ML engines (iteration 3+), the orchestrator should skip engines that can't produce wanted categories (pre-filter) to save 30ms+ per engine.

### 7.3 ColumnInput.column_id is opaque
The library never parses column_id. It's the connector's responsibility to define the format. BQ uses `resource:table:proj.ds.tbl:col`. Postgres might use `schema.table.col`. The library just echoes it back.
