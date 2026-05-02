# Zone Detection Logic

How the browser scanner identifies code, markup, config, and other structured blocks in free text.

## Overview

Zone detection runs a 10-step Rust/WASM pipeline that classifies regions of text into structured zone types. It answers the question: "which parts of this prompt are code, which are config, which are markup, and which are just prose?"

The detector is built in Rust, compiled to WASM, and runs client-side in the Web Worker alongside the JS secret scanner. A single `scan()` call returns both secret findings and zone blocks.

### Zone Types

| Zone type | Description | Examples |
|-----------|-------------|----------|
| `code` | Programming language source code | Python functions, JavaScript classes, C++ structs |
| `config` | Configuration files | JSON objects, YAML manifests, ENV files |
| `markup` | Markup languages | HTML documents, XML data, SVG |
| `query` | Database/search queries | SQL SELECT, GraphQL queries |
| `cli_shell` | Command-line / shell | Bash scripts, Docker commands, kubectl |
| `data` | Structured data blocks | CSV rows, log entries |
| `error_output` | Error messages and stack traces | Python tracebacks, Java exceptions |
| `natural_language` | Prose inside fenced blocks | Text wrapped in ``` without code indicators |

### Quick Example

Input text:
```
Fix this Python function:

def calculate(x, y):
    return x + y / y - x

It should handle division by zero.
```

Zone detection result:
```json
{
  "total_lines": 7,
  "blocks": [
    {
      "start_line": 2,
      "end_line": 4,
      "zone_type": "code",
      "confidence": 0.95,
      "language_hint": "python",
      "language_confidence": 0.85
    }
  ]
}
```

Lines 0-1 and 5-6 are prose (no zone). Lines 2-3 are detected as Python code with 95% confidence.

## Detection Pipeline

The pipeline runs 10 steps in sequence. Each step claims line ranges and passes unclaimed lines to the next step.

### Step 1: Pre-screen

Fast-path rejection. Checks if the text is likely to contain any structured content at all. Rejects ~97% of pure prose inputs in <0.1ms by looking for basic code indicators (brackets, semicolons, keywords). If no indicators are found, the pipeline returns empty blocks immediately.

### Step 2: Structural Detection

Finds explicitly delimited blocks:

- **Fenced code blocks**: `` ``` `` and `~~~` with optional language tag. If a tag is present (e.g., `` ```python ``), the zone type and language are read from a tag-to-type mapping (`lang_tag_map`). If no tag, the interior is classified as code or prose based on character composition.
- **HTML delimiter pairs**: `<script>...</script>` maps to code/javascript. `<style>...</style>` maps to code/css.

Fenced blocks get the highest confidence (0.95). Lines claimed by structural detection are excluded from all subsequent steps.

### Step 3: Format Detection

Detects structured formats in unclaimed regions:

- **JSON**: Text that starts with `{` or `[` and is valid JSON (verified by parsing). Mapped to `config/json`.
- **XML**: Text with matching open/close tags (`<tag>...</tag>`). Mapped to `markup/xml`.
- **YAML**: Lines with `key: value` patterns, indentation structure, and low prose ratio. Mapped to `config/yaml`.
- **ENV**: Lines matching `KEY=value` pattern (uppercase key). Mapped to `config/env`.

Format detection requires contiguous non-empty lines (minimum 2). Each format is tried in order: JSON, XML, YAML, ENV. The first match claims the region.

### Step 4: Syntax Scoring

The most complex step. Assigns a code-likelihood score (0.0-1.0) to each unclaimed line using 5 features:

1. **Syntactic density**: Ratio of operators, brackets, and punctuation to total characters. Code has higher density than prose.
2. **Keyword presence**: Two-tier keyword matching:
   - *Strict keywords* (`def`, `class`, `import`, `function`, `return`): always counted
   - *Contextual keywords* (`if`, `for`, `while`): only counted when followed by structural characters (`({[:=`) within 20 characters
3. **Line endings**: Lines ending in `{`, `;`, `:`, `)`, `]` score higher
4. **Assignment patterns**: `=`, `=>`, `:=` operators boost the score
5. **Indentation**: Consistent indentation (2 or 4 spaces, tabs) boosts confidence

After raw scoring, two smoothing passes run:
- **Context smoothing**: A line between two high-scoring lines gets its score boosted (prevents single prose lines from splitting code blocks)
- **Comment bridging**: Multi-line comments (`/* */`, `<!-- -->`) between code lines are absorbed into the code block

### Step 5: Scope Tracking

Extends code blocks using structural signals:

- **Bracket continuation**: If a line opens a bracket (`{`, `(`, `[`) without closing it, subsequent lines are claimed until the bracket is balanced
- **Indentation scope**: If a line is indented deeper than the block's base indentation and follows a high-scoring line, it's claimed as continuation

### Step 6: Negative Filter (FP Suppression)

Reclassifies or removes false positives:

- **Error output**: Python tracebacks (`Traceback (most recent call last):`), Java exceptions (`at com.example.Class.method`), and log output are reclassified from `code` to `error_output`
- **Math/LaTeX**: Lines with math notation (`\frac`, `\sum`, `$...$`) are suppressed — they look like code but aren't
- **Prose suppression**: High alpha-ratio lines (>80% letters/spaces) with no keywords are removed
- **Dialog suppression**: Lines matching conversational patterns are removed

### Step 7: Block Assembly

Groups scored lines into contiguous blocks:

- Adjacent lines with scores above the threshold are merged into blocks
- Small gaps (1-2 blank lines) between code regions are bridged
- Repetitive structure detection: if lines follow a repeating pattern (e.g., data rows), they're grouped as a single block
- Code construct validation: blocks must contain at least one recognizable code construct (function definition, class, import, etc.) — otherwise they're suppressed as likely FP

### Step 8: Block Validation

Additional validation on assembled blocks:

- **Code construct counting**: Blocks without function definitions, class declarations, import statements, or other recognizable constructs get confidence reduced
- **Math indicator suppression**: Blocks where math indicators outnumber code constructs are suppressed

### Step 9: Language Detection

Assigns a programming language to each code block:

- **Fragment-hit analysis**: During syntax scoring, each line is tested against language-specific fragment patterns (e.g., `def \w+\(` for Python, `function \w+\(` for JavaScript). Hits are counted per language family.
- **Probability distribution**: Hit counts are normalized to a probability distribution. The top family becomes the `language_hint`.
- **C-family disambiguation**: If the top family is "c_family" (C/C++/Java/JavaScript/C#/Go), disambiguation markers are checked (e.g., `console.log` → JavaScript, `System.out.println` → Java, `#include` → C/C++).

The `language_confidence` reflects how dominant the top language is in the distribution. A confidence of 0.85 means 85% of fragment hits matched that language.

### Step 10: Block Merge

Final pass merging adjacent compatible blocks:

- Adjacent `code` blocks with the same language are merged
- `code` + `error_output` blocks (e.g., code followed by its traceback) are merged into a single block
- Error output interleaved within code (e.g., inline error messages between function definitions) is absorbed

## WASM Runtime

### Loading Strategy

The WASM module is lazy-loaded on the first `scan()` call with `zones: true`:

1. Worker starts (from the existing pool)
2. First zone-enabled scan triggers WASM fetch: `data_classifier_core_bg.wasm` (~1.4MB, ~500KB gzipped) + `zone_patterns.json` (14KB)
3. `init_detector()` compiles ~100 regex patterns from `zone_patterns.json`. Takes 15-25ms, happens once per worker lifetime
4. Subsequent scans reuse the compiled detector — ~0.5ms per prompt
5. On MV3 service worker suspend, WASM state is discarded. Next scan re-initializes

### Graceful Degradation

If WASM fails to load (network error, incompatible browser, corrupted binary):

- `initZoneDetector()` returns `false` and logs a warning
- `scanText()` returns `zones: null` (not an error)
- Secret detection continues normally — it's pure JS and unaffected
- Next scan retries WASM initialization

### Performance

Measured on the 647-prompt WildChat corpus:

| Runtime | Throughput | Init time |
|---------|-----------|-----------|
| Rust native | 320 prompts/sec | N/A |
| WASM (Chrome) | 266 prompts/sec | 15-25ms |
| Python (via pyo3) | 315 prompts/sec | N/A |

Per-prompt latency after initialization: ~0.5ms (P50), ~1.5ms (P95).

### Parity

The Rust crate is the single source of truth. The same `data_classifier_core` crate compiles to:
- **WASM** for the browser library (this package)
- **Native Python module** via pyo3/maturin for the server-side library

647/647 prompts produce identical results across all three runtimes (100.0% parity).

## Configuration

All detection thresholds, keywords, fragment patterns, and weights are loaded from `zone_patterns.json`. This file is shared between all build targets (Python, Rust native, WASM). Key configuration sections:

| Section | What it controls |
|---------|-----------------|
| `pre_screen` | Fast-path rejection thresholds |
| `structural` | Fenced/delimiter confidence values |
| `format` | JSON/XML/YAML/ENV detection thresholds |
| `syntax` | Line scoring weights, keyword lists, smoothing window |
| `negative` | FP suppression patterns (error, math, prose) |
| `assembly` | Block grouping gaps, minimum block size |
| `language` | Fragment patterns, C-family disambiguation markers |
| `lang_tag_map` | Fence tag → zone type mapping (e.g., `sql` → `query`) |

## Quality Metrics

Evaluated on 647 human-reviewed WildChat prompts:

| Metric | Value | Target |
|--------|-------|--------|
| Precision | 98.3% | >90% |
| Recall | 95.7% | >95% |
| F1 | 0.970 | >0.92 |
| Boundary recall | 99.5% | >85% |
| Fragmentation | 1.06x | <1.3x |

- **Precision**: Of all blocks the detector emitted, 98.3% were actually structured content
- **Recall**: Of all structured content in the corpus, the detector found 95.7%
- **Boundary recall**: 99.5% of zone boundaries are within 2 lines of the human-annotated boundary
- **Fragmentation**: The detector produces 1.06x as many blocks as the ground truth (almost no unnecessary splitting)

## Known Limitations

- **Unfenced JSON**: Small JSON objects (<10 lines) without ``` fences may not be detected. The format detector requires valid JSON parsing, so JavaScript objects with regex literals or trailing commas are rejected.
- **Math/LaTeX**: Complex mathematical notation can resemble code (operators, nested brackets). The negative filter catches common patterns but may miss novel notation.
- **Mixed-script prompts**: Prompts mixing CJK characters with code have lower confidence because alpha-ratio heuristics are calibrated for Latin scripts.
- **Short blocks**: Single-line code snippets (e.g., `print("hello")` in a sentence) are intentionally not detected to avoid false positives. Minimum block size is 2 lines.
