# Complete Zone Partitioning Design

**Goal:** Every block of text gets a zone type + confidence score. No unlabeled gaps. Two new detector passes (DataDetector, ProseDetector) fill the gaps left by existing detectors, producing a complete partition of the input text.

**Architecture:** Extend the existing 10-step zone detection pipeline with two additional passes. Extract a `BlockFeatures` struct from unclaimed blocks, designed as the feature vector for a future meta-classifier. Ship with hand-tuned weights as the v1 scoring layer.

**Tech Stack:** Rust (data_classifier_core), regex crate, existing zone detector infrastructure.

---

## 1. Pipeline Integration

The existing 10-step pipeline detects code, markup, config, query, CLI, and error_output blocks. Lines not claimed by any detector currently receive no zone annotation.

Two new passes run after the existing pipeline:

```
Steps 1-10:  Existing detectors (structural, format, syntax, negative,
             assembler, validator, language, merge) — unchanged.

Step 11:     DataDetector — claims unclaimed blocks that exhibit tabular,
             CSV, log, or structured-data patterns.

Step 12:     ProseDetector — claims all remaining unclaimed lines as
             natural_language with a confidence score.
```

**Ordering rationale:** DataDetector runs before ProseDetector because data patterns are more specific. A CSV block has high alpha content and would score as "prose" if not caught first. The general principle is specific-to-general, consistent with the existing pipeline (structural before syntax before negative).

After step 12, every line in the input belongs to exactly one block. The output is a complete partition of the text.

### Pre-screen fast path change

The current pre-screen (`pre_screen.rs`) short-circuits on "pure prose" and returns zero blocks. With complete partitioning:

- Pre-screen still skips expensive code detection (steps 2-10) when text has no code signals.
- Instead of returning an empty `PromptZones`, it runs the DataDetector and ProseDetector (steps 11-12) on the full text to produce a classified partition.
- The ProseDetector computes its own lightweight code-absence signals (keyword density, syntactic char ratio) from the raw text — it does not depend on SyntaxDetector scores. This keeps the fast path genuinely fast.
- Fast path becomes "skip code detection, classify as data or prose" rather than "return nothing."

---

## 2. Feature Extraction

Every unclaimed block of contiguous lines gets a `BlockFeatures` struct extracted. These features serve two purposes:

1. **Now:** Hand-tuned weighted scoring for v1 classification.
2. **Later:** Feature vector for a trained meta-classifier (logistic regression, decision tree, or similar), following the same pattern as the column-level meta-classifier in the structured path.

### BlockFeatures struct

```rust
struct BlockFeatures {
    // Prose signals
    alpha_space_ratio: f64,     // Fraction of chars that are letters or spaces
    sentence_score: f64,        // Sentence structure: capitals after periods, commas, question marks
    avg_word_length: f64,       // Mean word length in chars
    line_length_cv: f64,        // Coefficient of variation of line lengths

    // Data signals
    delimiter_density: f64,     // Ratio of |, \t, , per line
    line_uniformity: f64,       // Structural similarity across lines (char class profile)
    numeric_ratio: f64,         // Fraction of tokens that are numbers
    repeating_prefix: bool,     // Lines share a common prefix pattern (timestamps, log levels)

    // Negative signals (absence of code)
    code_keyword_density: f64,  // if/for/return/def/class etc. per line
    syntactic_char_ratio: f64,  // {}();=[] per char
    indentation_pattern: bool,  // Consistent indentation suggests code structure

    // Block metadata
    block_lines: usize,         // Line count
    blank_line_ratio: f64,      // Paragraph breaks (prose) vs no blanks (data)
}
```

### Design principles for features

- **Orthogonal:** Each feature measures a distinct signal. No feature is a derived combination of others.
- **Normalized:** All ratio features are in [0.0, 1.0]. This ensures they work with both hand-tuned weights and trained classifiers.
- **Cheap to compute:** No regex matching required for most features — character counting and simple string operations. The feature extraction must not become a performance bottleneck on 1.65M prompts.
- **Extensible:** New features can be added to the struct without changing the classification interface. The hand-tuned weights just get a new entry; a trained classifier gets retrained.

---

## 3. Classification Logic

Classification happens in two sequential steps on each unclaimed block:

### Step 1: Data detection

A block is classified as `data` if it meets any of these criteria:

- **Tabular:** `delimiter_density` above threshold (consistent `|` or `\t` delimiters across lines).
- **CSV:** `delimiter_density` above threshold with `,` as the dominant delimiter.
- **Log output:** `repeating_prefix` is true AND `line_uniformity` is high (lines follow a common pattern like `[timestamp] [level] message`).
- **Structured rows:** `line_uniformity` is high AND `numeric_ratio` is elevated AND `sentence_score` is low.

The `language_hint` field carries the best-effort sub-hint: `"csv"`, `"log"`, `"table"`, or `"structured"`. This follows the same pattern as code blocks where `language_hint` carries `"python"`, `"javascript"`, etc.

Data block confidence is driven by the strength of the matching signals: strong delimiter patterns yield 0.80-0.95, weak/ambiguous patterns yield 0.50-0.70.

### Step 2: Prose classification

All remaining unclaimed blocks are classified as `natural_language`. Confidence is a weighted sum of prose signals:

```
confidence = w1 * alpha_space_ratio
           + w2 * sentence_score
           + w3 * (1.0 - code_keyword_density)
           + w4 * (1.0 - syntactic_char_ratio)
           + w5 * size_bonus(block_lines)
```

Clamped to [0.20, 0.95].

**Confidence calibration:**

| Scenario | Expected confidence |
|---|---|
| Clear prose paragraph (5+ sentences, varied line lengths) | 0.80 - 0.95 |
| Short prose fragment ("This is the error:") | 0.40 - 0.65 |
| Ambiguous fragment (2-3 lines, unclear structure) | 0.20 - 0.40 |

Initial weights are hand-tuned. They will be replaced by trained weights once labeled zone data from WildChat reviews reaches sufficient volume.

---

## 4. Output Format

### No schema change

The new passes produce standard `ZoneBlock` values. No changes to the struct:

```rust
ZoneBlock {
    start_line: 0,
    end_line: 3,
    zone_type: ZoneType::NaturalLanguage,  // or ZoneType::Data
    confidence: 0.85,
    method: "prose_detector",              // or "data_detector"
    language_hint: "",                     // or "csv", "log", "table"
    language_confidence: 0.0,
    text: "...",
}
```

### Scan output changes

The scan index (lightweight per-prompt record) includes a zone composition summary:

```json
{
    "prompt_id": "abc123",
    "zone_summary": {
        "code": {"lines": 12, "max_conf": 0.92},
        "natural_language": {"lines": 45, "max_conf": 0.88},
        "data": {"lines": 8, "max_conf": 0.75}
    },
    "num_secrets": 1,
    "max_secret_confidence": 0.85
}
```

Full block details are stored only in the candidates file (prompts with findings).

---

## 5. Secret Scanner Integration

The existing `ZoneScorer` (`zone_scorer.rs`) adjusts secret finding confidence based on zone type. New rules for the added zone classifications:

| Zone | Value context | Delta | Rationale |
|---|---|---|---|
| `natural_language` | literal | -0.25 | Writing about secrets, not leaking them |
| `natural_language` | expression | -0.35 | Code reference in prose, very unlikely to be a real secret |
| `data` | any | 0.0 (no change) | Defer to future PII gating iteration |

These rules are additive to existing zone scoring configuration and loaded from `unified_patterns.json`.

---

## 6. Future: Meta-Classifier Promotion

The `BlockFeatures` struct is designed as the feature vector for a trained classifier. The promotion path:

1. **v1 (this iteration):** Hand-tuned weights. Ship, scan WildChat, collect labeled zone data via the reviewer tool.
2. **Labeling:** The reviewer already supports zone review (approve/reject). Zone labels accumulate in the review corpus.
3. **v2 (future iteration):** Train a classifier (logistic regression or small decision tree) on `BlockFeatures` + labeled zones. Replace the hand-tuned weights. Same features, different combination layer.
4. **v3 (future):** Add PII pattern gating based on zone type. `data` zones enable structured PII detection (column-aware scanning for names, emails, SSNs). `natural_language` zones suppress PII patterns.

---

## 7. Scope Boundary

**In scope (this iteration):**
- `DataDetector` pass (step 11) — tabular, CSV, log detection in unclaimed blocks
- `ProseDetector` pass (step 12) — natural_language classification with confidence
- `BlockFeatures` struct — feature extraction for all unclaimed blocks
- Pre-screen fast path update — prose classification instead of empty return
- `ZoneScorer` rules for `natural_language` suppression
- Scan script updates — zone summary in index, complete partition in candidates

**Out of scope (future iterations):**
- PII pattern gating by zone type
- Trained meta-classifier (requires labeled data volume)
- Data sub-type parsing (CSV column extraction, log field parsing)
- Prose sub-classification (instructional, narrative, conversational)
