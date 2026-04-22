# Zone Detector v2 — Production Design

**Date:** 2026-04-22
**Branch:** `research/prompt-analysis`
**Status:** Design complete — ready for implementation planning
**Supersedes:** `zone_detector_v2_spec.md` (initial architecture sketch)
**Research basis:** `research_prior_art.md`

---

## 1. Goals

Detect code, structured data, error output, and other non-prose zones within
free-form LLM prompts. Drop-in replacement for v1 with:

| Metric | v1 baseline | v2 target |
|---|---|---|
| Detection precision | 80.3% | >90% |
| Detection recall | 99.1% | >95% (accept minor recall trade) |
| Boundary recall | 70% | >85% |
| Block fragmentation rate | ~2.5x | <1.3x |
| Throughput (Python) | 3,113 prompts/sec | >1,500 prompts/sec |
| Latency (JS, P99) | n/a | <10ms per prompt |

**Non-goals:** Inline code detection (`` `backtick` `` within prose),
natural language intent classification, semantic understanding of code
purpose.

---

## 2. Design Principles

### 2.1 Cascade: cheap before expensive

Detectors run in confidence order. High-confidence structural detection
claims spans before heuristic scoring runs. 97% of prompts have no code
— the pre-screen exits before any detector fires.

### 2.2 Single source of truth

All patterns, weights, and thresholds live in a shared JSON configuration
(`zone_patterns.json`). Both Python and JavaScript runtimes load this
file. Detection logic is specified precisely enough that both runtimes
produce identical output on identical input, validated by differential
test.

### 2.3 Performance is a feature

Each detector has a computational budget. Pre-screen eliminates 97% of
prompts in <0.1ms. Pre-compiled regexes avoid per-scan overhead. The
architecture is designed for the browser's 100ms worker timeout budget
(zone + secret scanning combined).

### 2.4 Negative signals first

From WildChat analysis: 79% of FPs are "not code at all" — structured
text that superficially resembles code. Preventing these FPs (via
negative signals) is higher ROI than improving positive detection.
The architecture dedicates an entire detector (NegativeFilter) to
this.

### 2.5 CRF-ready features

The line-level features computed by SyntaxDetector are designed to
feed a CRF sequence labeler in a future upgrade. Adding a CRF layer
requires no architectural changes — it replaces the rule-based scoring
with a learned model over the same feature vector.

### 2.6 Configurable sensitivity

Presets (`high_recall`, `balanced`, `high_precision`) adjust thresholds
and detector toggles. Individual detectors can be enabled/disabled.
All thresholds are empirically derived from 507+ reviewed WildChat
prompts with documented rationale.

---

## 3. Architecture

```
                    ┌─────────────────────────┐
                    │     Input: raw text      │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │      Pre-Screen         │
                    │  (fast path: 97% exit)  │
                    └────────────┬────────────┘
                           pass? │ no → return empty
                                 ▼
          ┌──────────────────────────────────────────┐
          │           ZoneOrchestrator                │
          │                                          │
          │  ┌────────────────────────────────────┐  │
          │  │ 1. StructuralDetector              │  │
          │  │    fenced blocks + delimiter pairs  │  │
          │  │    → claims line ranges            │  │
          │  └──────────────┬─────────────────────┘  │
          │                 │ claimed_ranges          │
          │                 ▼                         │
          │  ┌────────────────────────────────────┐  │
          │  │ 2. FormatDetector                  │  │
          │  │    JSON / XML / YAML / ENV parse   │  │
          │  │    → claims format blocks          │  │
          │  └──────────────┬─────────────────────┘  │
          │                 │ claimed_ranges          │
          │                 ▼                         │
          │  ┌────────────────────────────────────┐  │
          │  │ 3. SyntaxDetector                  │  │
          │  │    line scoring + fragments +      │  │
          │  │    context window (unclaimed only) │  │
          │  │    → per-line scores + types       │  │
          │  └──────────────┬─────────────────────┘  │
          │                 │ line_scores             │
          │                 ▼                         │
          │  ┌────────────────────────────────────┐  │
          │  │ 4. NegativeFilter                  │  │
          │  │    error / dialog / list / math /  │  │
          │  │    ratio suppression               │  │
          │  │    → suppressed lines + retypes    │  │
          │  └──────────────┬─────────────────────┘  │
          │                 │ filtered_scores         │
          │                 ▼                         │
          │  ┌────────────────────────────────────┐  │
          │  │ 5. BlockAssembler                  │  │
          │  │    grouping + gap bridging +       │  │
          │  │    bracket validation +            │  │
          │  │    repetitive structure test +     │  │
          │  │    opening context check +         │  │
          │  │    selective parse validation      │  │
          │  │    → final blocks                  │  │
          │  └──────────────┬─────────────────────┘  │
          │                 │                         │
          │                 ▼                         │
          │  ┌────────────────────────────────────┐  │
          │  │ 6. LanguageDetector (optional)     │  │
          │  │    fragment accumulation →         │  │
          │  │    language probability per block  │  │
          │  └────────────────────────────────────┘  │
          └──────────────────────────────────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │  Output: PromptZones    │
                    └─────────────────────────┘
```

### Detector interface

Each detector implements:

```python
class ZoneDetectorComponent:
    """Base for all detector components."""

    def __init__(self, config: ZoneConfig, patterns: ZonePatterns):
        """Load patterns, pre-compile regexes."""
        ...

    def startup(self) -> None:
        """One-time initialization (compile regexes, etc.)."""
        ...
```

Detectors are **not** interchangeable plugins — they have specific
ordering and data dependencies. But they are independently testable
and configurable.

---

## 4. Dual-Runtime Strategy

### 4.1 Shared configuration: `zone_patterns.json`

Single JSON file containing all patterns, weights, and thresholds.
Both Python and JavaScript runtimes load this file at startup.

**Location:** `data_classifier/patterns/zone_patterns.json` (canonical)

**Generated JS asset:** `data_classifier/clients/browser/src/generated/zone-patterns.js`
(generated by extending `scripts/generate_browser_patterns.py`)

### 4.2 Runtime implementations

| Component | Python | JavaScript |
|---|---|---|
| Orchestrator | `zone_detector.py` | `zone-detector.js` |
| Regex engine | `re2` | `RegExp` |
| JSON parse | `json.loads` | `JSON.parse` |
| Python parse | `ast.parse` | skip (accept divergence) |
| YAML heuristic | key-value regex | same regex (from config) |
| XML heuristic | tag regex | same regex (from config) |
| Configuration | load from JSON | import from generated JS |

### 4.3 Parity boundary

**Identical output required:** Pre-screen, StructuralDetector,
FormatDetector, SyntaxDetector, NegativeFilter, BlockAssembler.
These must produce the same blocks on the same input.

**Allowed divergence:** Parse validation (Python-only: `ast.parse`).
JS skips this pass. The differential test validates the core pipeline
(everything except parse validation). A block that Python confirms via
`ast.parse` has higher confidence in Python than JS — this is acceptable.

### 4.4 Differential test

Extends the existing `scripts/ci_browser_parity.sh` pattern:

1. Generate zone patterns to JS (`generate_browser_patterns.py`)
2. Build JS bundle
3. Run Python zone detector on seed corpus → expected output
4. Run JS zone detector on same corpus → actual output
5. Compare: `{zone_type, start_line, end_line, method}` per block
6. FAIL if any block differs (excluding parse-validation-only blocks)

**Seed corpus:** 50 prompts from the reviewed WildChat set —
25 with code blocks (various types) + 25 negatives. Committed
as `zone_fixtures.json` alongside `fixtures.json`.

### 4.5 Version stamping

`ZONE_LOGIC_VERSION` = SHA-256 hash (16-char) of:
- `zone_patterns.json`
- Python zone detector source files

Stored in generated `constants.js`. Differential test validates
version match between fixture expectations and runtime.

---

## 5. Pre-Screen: Fast Path

97.14% of WildChat prompts contain no code or structured blocks.
The pre-screen detects this and returns empty results without
running any detector.

### Algorithm

```python
def pre_screen(text: str) -> bool:
    """Return True if the text MIGHT contain code/structured blocks.

    False means definitely no blocks — skip all detectors.
    Must have ZERO false negatives (never skip a prompt with code).
    """
    # Check 1: fence markers
    if '```' in text or '~~~' in text:
        return True

    # Check 2: syntactic character density
    # Code has >5% syntactic chars; pure prose has <2%
    total = len(text)
    if total == 0:
        return False
    syn_count = sum(1 for c in text if c in _PRESCREEN_CHARS)
    if syn_count / total > 0.03:
        return True

    # Check 3: indentation patterns (4+ spaces at line start)
    if '\n    ' in text or '\n\t' in text:
        return True

    # Check 4: tag-like patterns
    if '</' in text:  # closing tag = likely markup
        return True

    return False

_PRESCREEN_CHARS = set('{}()[];=<>|&@#$^~')
```

### Performance

- O(n) single pass over text
- No regex compilation, no pattern matching
- Target: <0.1ms for typical prompt (500 chars)
- False positive rate: ~15-20% (some prose passes the screen but
  is rejected by later detectors). This is fine — false positives
  here just mean we run the full pipeline unnecessarily.
- **False negative rate: 0%.** The screen must never skip a prompt
  that contains code. Conservative thresholds ensure this.

### Shared

Pre-screen logic and thresholds are in `zone_patterns.json`:

```json
{
  "pre_screen": {
    "fence_markers": ["```", "~~~"],
    "syntactic_chars": "{}()[];=<>|&@#$^~",
    "density_threshold": 0.03,
    "indentation_markers": ["\n    ", "\n\t"],
    "tag_marker": "</"
  }
}
```

---

## 6. Zone Taxonomy

8 zone types. `natural_language` is the default for any unclassified
region (not emitted as a block).

| Type | Definition | Examples |
|---|---|---|
| `code` | Executable source code in any programming language | Python function, JS class, C struct |
| `markup` | Document markup languages | HTML, XML, SVG |
| `config` | Configuration and data-serialization formats | JSON, YAML, TOML, INI, ENV, .properties |
| `query` | Database and API query languages | SQL, GraphQL, Cypher |
| `cli_shell` | Shell commands, terminal sessions, CLI invocations | bash one-liners, `$ prompt` sessions |
| `data` | Tabular or structured data content | CSV, TSV, fixed-width tables, data listings |
| `error_output` | Diagnostic output: stack traces, compiler errors, logs, build output | Python traceback, npm ERR!, Rust `-->` errors |
| `natural_language` | Prose, instructions, conversation (default) | Not emitted as a block |

### Language tag mapping (for fenced blocks)

Stored in `zone_patterns.json` under `lang_tag_map`:

```json
{
  "lang_tag_map": {
    "python": {"type": "code", "lang": "python"},
    "py": {"type": "code", "lang": "python"},
    "javascript": {"type": "code", "lang": "javascript"},
    "js": {"type": "code", "lang": "javascript"},
    "typescript": {"type": "code", "lang": "typescript"},
    "ts": {"type": "code", "lang": "typescript"},
    "java": {"type": "code", "lang": "java"},
    "c": {"type": "code", "lang": "c"},
    "cpp": {"type": "code", "lang": "cpp"},
    "c++": {"type": "code", "lang": "cpp"},
    "csharp": {"type": "code", "lang": "csharp"},
    "cs": {"type": "code", "lang": "csharp"},
    "go": {"type": "code", "lang": "go"},
    "golang": {"type": "code", "lang": "go"},
    "rust": {"type": "code", "lang": "rust"},
    "ruby": {"type": "code", "lang": "ruby"},
    "rb": {"type": "code", "lang": "ruby"},
    "php": {"type": "code", "lang": "php"},
    "swift": {"type": "code", "lang": "swift"},
    "kotlin": {"type": "code", "lang": "kotlin"},
    "scala": {"type": "code", "lang": "scala"},
    "r": {"type": "code", "lang": "r"},
    "lua": {"type": "code", "lang": "lua"},
    "perl": {"type": "code", "lang": "perl"},
    "dart": {"type": "code", "lang": "dart"},
    "haskell": {"type": "code", "lang": "haskell"},
    "hs": {"type": "code", "lang": "haskell"},
    "elixir": {"type": "code", "lang": "elixir"},
    "clojure": {"type": "code", "lang": "clojure"},
    "jsx": {"type": "code", "lang": "jsx"},
    "tsx": {"type": "code", "lang": "tsx"},
    "vue": {"type": "code", "lang": "vue"},
    "svelte": {"type": "code", "lang": "svelte"},
    "matlab": {"type": "code", "lang": "matlab"},
    "julia": {"type": "code", "lang": "julia"},
    "objective-c": {"type": "code", "lang": "objective-c"},
    "objc": {"type": "code", "lang": "objective-c"},
    "groovy": {"type": "code", "lang": "groovy"},
    "powershell": {"type": "code", "lang": "powershell"},
    "ps1": {"type": "code", "lang": "powershell"},
    "vb": {"type": "code", "lang": "vb"},
    "vba": {"type": "code", "lang": "vba"},
    "asm": {"type": "code", "lang": "assembly"},
    "assembly": {"type": "code", "lang": "assembly"},
    "nasm": {"type": "code", "lang": "assembly"},

    "sql": {"type": "query", "lang": "sql"},
    "graphql": {"type": "query", "lang": "graphql"},
    "gql": {"type": "query", "lang": "graphql"},
    "cypher": {"type": "query", "lang": "cypher"},

    "html": {"type": "markup", "lang": "html"},
    "xml": {"type": "markup", "lang": "xml"},
    "svg": {"type": "markup", "lang": "svg"},
    "css": {"type": "code", "lang": "css"},
    "scss": {"type": "code", "lang": "scss"},
    "sass": {"type": "code", "lang": "sass"},
    "less": {"type": "code", "lang": "less"},

    "json": {"type": "config", "lang": "json"},
    "yaml": {"type": "config", "lang": "yaml"},
    "yml": {"type": "config", "lang": "yaml"},
    "toml": {"type": "config", "lang": "toml"},
    "ini": {"type": "config", "lang": "ini"},
    "env": {"type": "config", "lang": "env"},
    "dotenv": {"type": "config", "lang": "env"},
    "properties": {"type": "config", "lang": "properties"},
    "hcl": {"type": "config", "lang": "hcl"},
    "tf": {"type": "config", "lang": "hcl"},

    "csv": {"type": "data", "lang": "csv"},
    "tsv": {"type": "data", "lang": "tsv"},

    "bash": {"type": "cli_shell", "lang": "bash"},
    "sh": {"type": "cli_shell", "lang": "sh"},
    "shell": {"type": "cli_shell", "lang": "sh"},
    "zsh": {"type": "cli_shell", "lang": "zsh"},
    "fish": {"type": "cli_shell", "lang": "fish"},
    "bat": {"type": "cli_shell", "lang": "bat"},
    "cmd": {"type": "cli_shell", "lang": "cmd"},
    "console": {"type": "cli_shell", "lang": "sh"},
    "terminal": {"type": "cli_shell", "lang": "sh"},

    "text": {"type": "natural_language", "lang": ""},
    "txt": {"type": "natural_language", "lang": ""},
    "plaintext": {"type": "natural_language", "lang": ""},
    "markdown": {"type": "natural_language", "lang": ""},
    "md": {"type": "natural_language", "lang": ""}
  }
}
```

---

## 7. Detector 1: StructuralDetector

Claims spans bounded by unambiguous structural delimiters. Runs first
because these delimiters are highest-confidence (0.95) and prevent
interior content from being misclassified.

### 7.1 Fenced blocks

Detect `` ``` `` and `~~~` fenced blocks with optional language tags.
Carried from v1 (working well, 0.95 confidence).

```python
def _detect_fenced(lines: list[str]) -> list[ZoneCandidate]:
    """Detect ``` and ~~~ fenced blocks."""
    # Match opening fence: ^(`{3,}|~{3,})\s*(\w+)?\s*$
    # Find matching closing fence (same char, >= same length)
    # Map language tag via lang_tag_map
    # If no tag: check interior for code-likeness (alpha ratio + keywords)
    # Confidence: 0.95 (fenced = explicit author intent)
```

**Interior classification for untagged fences:** If no language tag,
check interior content. If avg alpha ratio >0.80 AND zero code keywords
AND <20% of lines have syntactic chars → `natural_language` (backtick-
quoted prose). Otherwise → `code`.

### 7.2 Delimiter pairs

Scan for matched open/close delimiter pairs. These create zones that
are not re-scored by later detectors.

#### High confidence (claim unconditionally)

| Opener | Closer | Interior type | Confidence |
|---|---|---|---|
| `/*` | `*/` | inherit parent | 0.90 |
| `<!--` | `-->` | markup (comment) | 0.90 |
| `"""` (Python) | `"""` | inherit parent | 0.90 |
| `'''` (Python) | `'''` | inherit parent | 0.90 |
| `<script>` / `<script ...>` | `</script>` | code (js) | 0.90 |
| `<style>` / `<style ...>` | `</style>` | code (css) | 0.90 |
| `<<MARKER` (heredoc) | `MARKER` | code | 0.85 |

**Nesting rule:** Process outermost delimiters first. `<script>` inside
`<!-- -->` is suppressed (comment wins). `/* */` inside a fenced block
is ignored (fence claims the span).

**Unclosed delimiters:** If no matching closer is found by end of text,
do not claim. Fall through to later detectors.

**`<script>` / `<style>` zone splitting:** When found within a markup
block, the parent block is split:
- markup (before `<script>`) → code/js (inside) → markup (after `</script>`)

### 7.3 Configuration

```json
{
  "structural": {
    "fence_patterns": {
      "open": "^(`{3,}|~{3,})\\s*(\\w+)?\\s*$",
      "close": "^(`{3,}|~{3,})\\s*$"
    },
    "delimiter_pairs": [
      {"open": "/*", "close": "*/", "type": "inherit", "confidence": 0.90},
      {"open": "<!--", "close": "-->", "type": "markup", "confidence": 0.90},
      {"open": "\"\"\"", "close": "\"\"\"", "type": "inherit", "confidence": 0.90},
      {"open": "'''", "close": "'''", "type": "inherit", "confidence": 0.90},
      {"open": "<script", "close_tag": "</script>", "type": "code", "lang": "javascript", "confidence": 0.90},
      {"open": "<style", "close_tag": "</style>", "type": "code", "lang": "css", "confidence": 0.90}
    ],
    "fenced_confidence": 0.95,
    "delimiter_confidence": 0.90
  }
}
```

### 7.4 Performance

- O(n) linear scan with stack for nesting
- No regex on every line (fence regex only on lines starting with `` ` `` or `~`)
- Budget: <0.3ms for typical prompt

---

## 8. Detector 2: FormatDetector

Detects structured data formats (JSON, XML, YAML, ENV) by attempting
lightweight parsing on candidate regions. Runs on unclaimed lines only.

### 8.1 JSON detection

```python
def _try_json(text: str) -> bool:
    """Strict JSON validation. High confidence (0.90) because
    json.loads / JSON.parse is definitive."""
    text = text.strip()
    if not (text.startswith(("{", "[")) and text.endswith(("}", "]"))):
        return False
    try:
        json.loads(text)  # Python: json.loads / JS: JSON.parse
        return True
    except (json.JSONDecodeError, ValueError):
        return False
```

Confidence: 0.90. Both runtimes have identical JSON parsing.

### 8.2 XML/HTML detection (tightened from v1)

v1 triggered on any `<>` presence, causing FPs when NL instructions
used angle brackets (`<CLAIM>`, `<MEASURE>`). v2 requires matched
open/close tags.

```python
def _looks_like_xml(text: str) -> bool:
    """Require actual HTML/XML tag structure, not just angle brackets."""
    open_tags = re.findall(r'<(\w+)[\s>]', text)
    close_tags = re.findall(r'</(\w+)>', text)
    if len(open_tags) < 2 or len(close_tags) < 1:
        return False
    # Must have at least one matching open+close pair
    return bool(set(t.lower() for t in open_tags) &
                set(t.lower() for t in close_tags))
```

Confidence: 0.80. Regex-only, works in both runtimes.

### 8.3 YAML detection (carried from v1, working well)

Requires `key: value` mapping lines (not just bullet lists). Rejects
prose sentences, long multi-word keys. Minimum 3 mapping lines.

Confidence: 0.80. Regex-only, works in both runtimes.

### 8.4 ENV detection

```python
def _looks_like_env(lines: list[str]) -> bool:
    """Detect .env / KEY=VALUE format."""
    # Pattern: ^[A-Z][A-Z0-9_]+=.+$
    # Require 2+ matching lines AND >50% of non-empty lines match
```

Confidence: 0.85. Regex-only, works in both runtimes.

### 8.5 Candidate region selection

FormatDetector doesn't scan every possible substring. It operates on
**contiguous non-empty regions** in unclaimed lines:

1. Walk unclaimed lines
2. Find contiguous runs of non-empty lines (allow 1-2 blank gaps)
3. For runs with 5+ non-empty lines, try JSON → XML → YAML → ENV
4. First match wins (JSON is strictest, try first)

### 8.6 Configuration

```json
{
  "format": {
    "min_non_empty_lines": 5,
    "max_blank_gap": 2,
    "json_confidence": 0.90,
    "xml_confidence": 0.80,
    "yaml_confidence": 0.80,
    "env_confidence": 0.85,
    "yaml_min_kv_lines": 3,
    "yaml_max_key_words": 3,
    "yaml_max_prose_ratio": 0.50,
    "xml_min_open_tags": 2,
    "xml_min_close_tags": 1
  }
}
```

### 8.7 Performance

- O(n) to find candidate regions
- Parse attempts only on candidates (typically 0-3 per prompt)
- JSON/XML/YAML parsing is fast (microseconds for typical blocks)
- Budget: <0.5ms

---

## 9. Detector 3: SyntaxDetector

The workhorse — responsible for 88% of detected blocks in WildChat.
Scores each unclaimed line for code-likeness using syntax features,
statement fragment matching, and a 3-line context window.

### 9.1 Syntax scoring (per-line)

Each line receives a base score from 0.0 to 1.0 based on surface
features. Weights are from `zone_patterns.json` and empirically
calibrated against the 507+ reviewed WildChat corpus.

```python
def _line_syntax_score(line: str, weights: dict) -> float:
    stripped = line.strip()
    if not stripped:
        return 0.0

    score = 0.0

    # Feature 1: Syntactic character density
    syn_count = sum(1 for c in stripped if c in SYNTACTIC_CHARS)
    syn_density = syn_count / len(stripped)
    if syn_density > weights["syn_density_high"]:       # 0.15
        score += weights["syn_density_high_weight"]     # 0.30
    elif syn_density > weights["syn_density_med"]:      # 0.08
        score += weights["syn_density_med_weight"]      # 0.15

    # Feature 2: Code keywords
    kw_count = count_keyword_matches(stripped)
    if kw_count >= 2:
        score += weights["keyword_multi_weight"]        # 0.30
    elif kw_count >= 1:
        score += weights["keyword_single_weight"]       # 0.15

    # Feature 3: Code-like line ending
    if stripped[-1] in SYNTACTIC_ENDINGS:                # {;)],
        score += weights["line_ending_weight"]          # 0.10

    # Feature 4: Assignment pattern (identifier = value)
    if ASSIGNMENT_RE.match(stripped):
        score += weights["assignment_weight"]           # 0.10

    # Feature 5: Indentation (2+ spaces or tab)
    indent = len(line) - len(line.lstrip())
    if indent >= 2:
        score += weights["indentation_weight"]          # 0.05

    return min(score, 1.0)
```

#### Syntactic characters

```json
"syntactic_chars": "{}()[];=<>|&!@#$^*/\\~"
```

#### Syntactic line endings

```json
"syntactic_endings": "{;)],:"
```

#### Code keywords

Complete list (loaded from config):

```json
{
  "code_keywords": [
    "import", "from", "def", "class", "function", "return",
    "if", "else", "elif", "for", "while", "do",
    "try", "except", "catch", "throw", "throws", "finally",
    "new", "var", "let", "const", "val",
    "public", "private", "protected", "static", "abstract",
    "void", "int", "string", "bool", "boolean", "float", "double", "char", "long",
    "package", "interface", "implements", "extends", "override",
    "async", "await", "yield",
    "lambda", "raise", "assert",
    "include", "require", "module", "export", "default",
    "struct", "enum", "trait", "impl", "fn", "match", "use", "pub", "mut",
    "println", "printf", "fmt", "console", "System", "std",
    "switch", "case", "break", "continue", "goto",
    "sizeof", "typedef", "extern", "volatile", "register",
    "defer", "go", "chan", "select", "fallthrough",
    "type", "namespace", "using", "unsafe", "virtual",
    "self", "super", "this"
  ]
}
```

#### Assignment pattern

```json
"assignment_pattern": "^\\s*[a-z_]\\w*\\s*[:=]"
```

Requires lowercase identifier start — prevents matching `Prob[A] = 0.7`
or `Title: description`.

#### Scoring weights

```json
{
  "scoring_weights": {
    "syn_density_high": 0.15,
    "syn_density_high_weight": 0.30,
    "syn_density_med": 0.08,
    "syn_density_med_weight": 0.15,
    "keyword_multi_weight": 0.30,
    "keyword_single_weight": 0.15,
    "line_ending_weight": 0.10,
    "assignment_weight": 0.10,
    "indentation_weight": 0.05,
    "fragment_match_boost": 0.25
  }
}
```

**Calibration basis:** v1 weights with threshold analysis from WildChat
data. TP median score: 0.697, FP median score: 0.658. Weights are
additive features, not learned coefficients — suitable for CRF upgrade
where the CRF would learn optimal weights from data.

### 9.2 Statement fragment matching

In addition to the base syntax score, each line is checked against
**statement fragment patterns** grouped by syntax family. A match adds
+0.25 to the score and records which family matched (for language
detection in LanguageDetector).

Fragment matching is a strong confirmation signal — it distinguishes
actual code statements from text that merely contains code-like
punctuation.

#### C-family fragments (JS, TS, Java, C, C++, C#, Go)

```json
{
  "c_family": [
    "^\\s*(if|else|for|while|switch|case|return|break|continue)\\s*[\\({]",
    "^\\s*(const|let|var|int|string|bool|boolean|float|double|void|char|long|auto)\\s+\\w+",
    "^\\s*(func|function|public|private|protected|static|class|interface|struct|enum)\\s",
    "^\\s*\\w+\\.\\w+\\(.*\\)",
    "^\\s*\\w+\\s*:?=\\s*.+[;,]?\\s*$",
    "[{};]\\s*$",
    "^\\s*(try|catch|finally|throw|throws)\\s*[\\({]",
    "^\\s*(package|import|using|namespace)\\s+[\\w.]+",
    "^\\s*(defer|go|chan|select)\\s",
    "^\\s*#(include|define|ifdef|ifndef|endif|pragma)\\s"
  ]
}
```

#### Python fragments

```json
{
  "python": [
    "^\\s*(def|class|import|from|return|yield|raise|assert|pass|del|global|nonlocal)\\s",
    "^\\s*(if|elif|else|for|while|try|except|finally|with|as|match|case)\\s.*:\\s*(#.*)?$",
    "^\\s*@\\w+",
    "^\\s*\\w+\\s*=\\s*.+$",
    "^\\s*(print|len|range|type|isinstance|hasattr|getattr|setattr|super|input|open)\\s*\\(",
    "^\\s*(self|cls)\\.\\w+"
  ]
}
```

#### Markup fragments (HTML, XML, CSS)

```json
{
  "markup": [
    "<\\w+[\\s>]",
    "</\\w+>",
    "^\\s*\\w[\\w-]*\\s*:\\s*.+;",
    "^\\s*[\\.\\#@]\\w+.*\\{",
    "^\\s*<\\?xml\\s",
    "^\\s*<!DOCTYPE\\s"
  ]
}
```

#### SQL / query fragments

```json
{
  "sql": [
    "^\\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|MERGE)\\s",
    "^\\s*(FROM|WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|CROSS|ON|AND|OR|NOT|IN|EXISTS)\\s",
    "^\\s*(GROUP\\s+BY|ORDER\\s+BY|HAVING|LIMIT|OFFSET|UNION|EXCEPT|INTERSECT)\\s",
    "^\\s*(BEGIN|COMMIT|ROLLBACK|GRANT|REVOKE|EXPLAIN|ANALYZE)\\s",
    "^\\s*(CREATE|ALTER)\\s+(TABLE|INDEX|VIEW|FUNCTION|PROCEDURE|TRIGGER)\\s",
    "^\\s*(SET|DECLARE|EXEC|EXECUTE|CALL|RETURN)\\s"
  ]
}
```

#### Shell / CLI fragments

```json
{
  "shell": [
    "^\\s*\\$\\s+\\w",
    "^\\s*(sudo|chmod|chown|mkdir|rmdir|touch|cp|mv|rm|ln)\\s",
    "^\\s*(curl|wget|docker|kubectl|git|npm|pip|brew|apt|yum|dnf|pacman)\\s",
    "^\\s*(export|source|alias|unalias|echo|printf|read|eval|exec)\\s",
    "^\\s*(systemctl|service|journalctl|crontab|at|nohup)\\s",
    "^\\s*(ssh|scp|rsync|sftp|telnet|nc|netstat|ss|lsof)\\s",
    "^\\s*(find|grep|sed|awk|sort|uniq|head|tail|wc|cut|tr|xargs)\\s",
    "\\|\\s*(grep|awk|sed|sort|head|tail|wc|xargs|cut|tr)\\s"
  ]
}
```

#### Assembly fragments (Tier 2)

```json
{
  "assembly": [
    "^\\s*(mov|push|pop|call|ret|jmp|jne|je|jz|jnz|jge|jle|cmp|test|add|sub|mul|imul|div|idiv|xor|and|or|not|shl|shr|lea|nop|int|hlt)\\s",
    "\\b(eax|ebx|ecx|edx|esi|edi|esp|ebp|rax|rbx|rcx|rdx|rsi|rdi|rsp|rbp|r[89]|r1[0-5]|r0|r1|r2|r3|r4|r5|r6|r7|sp|lr|pc|fp)\\b",
    "^\\s*section\\s+\\.",
    "^\\s*\\.?(text|data|bss|global|extern|align|byte|word|long|quad|ascii|asciz)\\b"
  ]
}
```

#### Rust fragments (Tier 2)

```json
{
  "rust": [
    "^\\s*(fn|let\\s+mut|pub\\s+fn|pub\\s+struct|pub\\s+enum|impl|trait|mod|use|crate|extern)\\s",
    "\\bunwrap\\(\\)|\\bexpect\\(\"",
    "::\\w+",
    "->\\s*\\w+",
    "^\\s*#\\[\\w+",
    "\\bOption<|\\bResult<|\\bVec<|\\bBox<|\\bArc<|\\bRc<"
  ]
}
```

### 9.3 Context window (3 lines)

After base scoring and fragment matching, apply a 3-line context
window to smooth scores:

```python
def _contextualized_score(
    i: int,
    raw_scores: list[float],
    lines: list[str],
    weights: dict,
) -> float:
    raw = raw_scores[i]
    stripped = lines[i].strip()

    # Skip already-claimed lines
    if raw < 0:
        return raw

    # Neighbor scores (±1 line)
    above = raw_scores[i - 1] if i > 0 and raw_scores[i - 1] >= 0 else 0
    below = raw_scores[i + 1] if i < len(lines) - 1 and raw_scores[i + 1] >= 0 else 0
    neighbor_avg = (above + below) / 2

    # Transition boost: prose line preceding code
    transition_boost = 0.0
    if i > 0:
        prev = lines[i - 1].strip()
        if prev.endswith((":", "{")) and above > 0.2:
            transition_boost = weights["transition_colon_boost"]    # 0.10
        elif _INTRO_PHRASE_RE.search(prev):
            transition_boost = weights["transition_phrase_boost"]   # 0.15

    # Comment bridging: zero-score line with comment marker
    # surrounded by code
    comment_bridge = 0.0
    if raw == 0 and neighbor_avg > 0.3:
        if _COMMENT_MARKER_RE.match(stripped):
            comment_bridge = neighbor_avg * weights["comment_bridge_factor"]  # 0.80

    # Blend
    blended = (
        raw * weights["self_weight"]           # 0.70
        + neighbor_avg * weights["neighbor_weight"]  # 0.20
        + transition_boost
        + comment_bridge
    )
    return min(blended, 1.0)
```

#### Intro phrase pattern

```json
"intro_phrase_pattern": "(?:example|code|output|command|result|script|snippet|run this|here is|as follows|shown below|see below).*:?\\s*$"
```

#### Comment marker pattern

```json
"comment_marker_pattern": "^\\s*(?:#(?!include|define|ifdef|ifndef|endif|pragma)|//|--|/\\*|\\*(?!/)| \\*\\s|%|REM\\s)"
```

Note: `#` excludes C preprocessor directives which look like comments
but are code.

#### Context weights

```json
{
  "context": {
    "window_size": 3,
    "self_weight": 0.70,
    "neighbor_weight": 0.20,
    "transition_colon_boost": 0.10,
    "transition_phrase_boost": 0.15,
    "comment_bridge_factor": 0.80
  }
}
```

### 9.4 Performance

- O(n) per line: feature extraction + 1 regex check per fragment family
- Fragment families checked: up to 7 (c_family, python, markup, sql,
  shell, assembly, rust) × ~8 patterns each = ~56 regex matches per
  line in worst case
- **Optimization:** Short-circuit on first family match (a line matching
  Python fragments doesn't need to check assembly). Pre-compile all
  fragment regexes at startup.
- Context window: O(1) per line (just index neighbors)
- Budget: <3ms for typical prompt

---

## 10. Detector 4: NegativeFilter

Identifies lines that score as code-like but are NOT code. Each
negative signal either suppresses the line's score to 0 or retypes
it to a non-code zone type.

### 10.1 Error output patterns

Lines matching these are retyped to `error_output`:

```json
{
  "error_output": [
    "^\\s*Traceback \\(most recent call last\\)",
    "^\\s*File \".+\", line \\d+",
    "^\\s*at \\w[\\w.]+\\([^)]*\\.(?:java|kt|scala|cs|js|ts|py):\\d+\\)",
    "^\\s*at \\w[\\w.]+\\s\\(.+:\\d+:\\d+\\)",
    "^\\s*at \\w[\\w.]+\\.<",
    "^\\w+Error:\\s",
    "^\\w+Exception:\\s",
    "^\\w+Warning:\\s",
    "^\\s*error\\[?\\w*\\]?\\s*:",
    "^\\s*warning\\[?\\w*\\]?\\s*:",
    "^\\s*-->\\s+\\S+:\\d+:\\d+",
    "^\\s*\\^+\\s*$",
    "^\\s*~~~+\\s*$",
    "^\\s*\\|$",
    "^\\s*npm ERR!",
    "^\\s*pip ERR",
    "^\\s*Requirement already satisfied:",
    "^\\s*(?:ERROR|WARN|INFO|DEBUG|FATAL|CRITICAL)\\s",
    "^\\d{4}-\\d{2}-\\d{2}[T ]\\d{2}:\\d{2}",
    "^\\[\\d{4}-\\d{2}-\\d{2}",
    "^\\[?(?:ERROR|WARN|INFO|DEBUG)\\]?\\s",
    "panic:\\s",
    "goroutine \\d+ \\[",
    "^\\s*\\w+\\.rb:\\d+:in\\s",
    "^\\s*from\\s+\\S+:\\d+:in\\s"
  ]
}
```

**Evidence from reviews:** 4 FPs — Rust compiler, Node stack trace,
pip output, pylint output.

**Dual signal:** Error output blocks get elevated priority for secret
detection (credential leaks in stack traces). The `error_output` zone
type signals this to downstream consumers.

### 10.2 Dialog / conversation patterns

Lines matching these with high alpha ratio (>0.70) are suppressed:

```json
{
  "dialog": [
    "^\\s*[A-Z][a-z]{1,20}:\\s*\"",
    "^\\s*[A-Z][a-z]{1,20}:\\s*[A-Z]",
    "^\\s*\\([A-Z][a-z]{1,20}\\)\\s",
    "^\\s*\\[[A-Z][a-z]{1,20}\\]\\s"
  ],
  "dialog_min_alpha_ratio": 0.70
}
```

**Evidence:** 3 FPs — character dialog with `Name: "text"` format.

### 10.3 List prefix pattern

If >70% of lines in a candidate region start with list markers, the
region is reclassified as `natural_language`:

```json
{
  "list_prefix": {
    "pattern": "^\\s*(?:\\d+[.):]\\s+|[-\\u2022*]\\s+|[a-z][.)]\\s+)",
    "threshold": 0.70
  }
}
```

**Rationale:** Code blocks almost never have every line starting with
a list marker. Lists of code fragments (`- dict(set())`) are reference
material, not executable code.

**Evidence:** 6 FPs — Japanese glossaries, game legends, Python
function comparison lists.

### 10.4 Math / notation patterns

Lines matching these are suppressed:

```json
{
  "math": [
    "\\\\frac|\\\\begin|\\\\end|\\\\sum|\\\\int|\\\\alpha|\\\\beta|\\\\theta",
    "(?:\\u2229|\\u222A|\\u2264|\\u2265|\\u2282|\\u2286|\\u2208|\\u2209|\\u2192|\\u2190|\\u2194|\\u2200|\\u2203|\\u2205)",
    "\\b(?:cos|sin|tan|log|ln|exp|sqrt|lim|inf|sup|det|dim|ker|deg)\\b",
    "\\b(?:theorem|lemma|proof|corollary|hypothesis|proposition)\\b",
    "Prob\\[|P\\[|E\\[|Var\\[|Cov\\["
  ]
}
```

**Evidence:** 3 FPs — `p(0,1) p(1,-1)` patterns, inequality
expressions.

### 10.5 Ratio / non-code colon patterns

```json
{
  "ratio": [
    "^\\s*\\d+:\\d+\\s",
    "^\\s*\\d+:\\d{2}\\s"
  ]
}
```

**Evidence:** 7 FPs (20% of all FPs) — MidJourney aspect ratio
templates.

### 10.6 Prose sentence pattern

Lines that are clearly prose sentences (start with capital, end with
period/question/exclamation, high alpha ratio):

```json
{
  "prose": {
    "pattern": "^[A-Z][a-z].+[.!?]$",
    "min_alpha_ratio": 0.75
  }
}
```

### 10.7 Application order

1. Math patterns → score = 0 (highest priority negative)
2. Error output → score = 0 + retype to `error_output`
3. Prose sentence → score = 0
4. Dialog → score = 0 (combined with repetitive structure in assembler)
5. Ratio → score = 0
6. List prefix → per-block in assembler (needs block context)

### 10.8 Performance

- O(n) per line: check each negative pattern
- Short-circuit: stop on first match (order matters)
- Pre-compiled regexes at startup
- Budget: <0.5ms

---

## 11. BlockAssembler

Takes per-line scores + types from SyntaxDetector + NegativeFilter
and assembles them into final ZoneBlocks.

### 11.1 Run-based grouping

Group consecutive lines into runs:

```python
def _group_runs(line_scores, line_types, lines):
    """Group consecutive same-type lines into candidate runs.

    A run is a maximal sequence of lines with:
    - score > 0 (positive signal), OR
    - type override from NegativeFilter (e.g., error_output)

    Blank lines within a run are included if they're between
    scored lines. The gap bridging rules determine when blanks
    terminate a run vs. continue it.
    """
```

### 11.2 Gap bridging rules

| Gap type | Bridge? | Condition |
|---|---|---|
| 1 blank line | Yes | Always bridge within a run |
| 2 blank lines | Yes | If both sides are same type |
| 3+ blank lines | No | Break the run |
| 1-2 comment lines | Yes | If comment marker matches and neighbors are code |
| 1-2 zero-score non-blank lines | Conditional | Bridge if both sides score >0.3 and within same indentation level |
| Type transition (code → error) | No | Always break |

### 11.3 Bracket balance validation

After assembly, validate each block's bracket balance:

```python
def _brackets_balanced(block_lines: list[str]) -> tuple[bool, dict[str, int]]:
    """Check bracket balance and return per-bracket imbalance.

    Returns (is_balanced, counts) where counts maps bracket type
    to its imbalance (positive = more opens, negative = more closes).
    """
    counts = {"(": 0, "[": 0, "{": 0}
    closers = {")": "(", "]": "[", "}": "{"}
    for line in block_lines:
        in_string = False
        quote_char = None
        for c in line:
            if c in ('"', "'") and not in_string:
                in_string = True
                quote_char = c
            elif c == quote_char and in_string:
                in_string = False
            elif not in_string:
                if c in counts:
                    counts[c] += 1
                elif c in closers:
                    counts[closers[c]] -= 1
    return all(v == 0 for v in counts.values()), counts
```

**Boundary extension:** If brackets are unbalanced with excess opens
(e.g., `{` count > 0), try extending the block end by up to 5 lines
to find matching closes. This catches the case where a closing `}`
was excluded because its line had low syntax score.

**Block splitting prevention:** If splitting a block at a blank line
would produce two unbalanced halves, don't split. This prevents
fragmenting the long-dict case.

### 11.4 Repetitive structure test

Detects blocks with repetitive line-level structure — a strong
signal that the content is not code:

```python
def _detect_repetitive_structure(lines: list[str], threshold=0.50):
    """If >50% of non-empty lines share a common prefix pattern,
    the block has repetitive structure.

    Returns the dominant prefix or None.
    """
    non_empty = [l.strip() for l in lines if l.strip()]
    if len(non_empty) < 3:
        return None

    # Extract first significant token(s) as prefix fingerprint
    prefixes = []
    for line in non_empty:
        # First word + any leading punctuation
        m = re.match(r'^(\s*\S+(?:\s+\S+)?)', line)
        if m:
            prefixes.append(m.group(1).strip())

    from collections import Counter
    counts = Counter(prefixes)
    if not counts:
        return None

    most_common_prefix, count = counts.most_common(1)[0]
    if count / len(non_empty) >= threshold:
        return most_common_prefix
    return None
```

**Application:**
- Blocks with repetitive error prefixes (`npm ERR!`, `File "..."`) →
  reclassify as `error_output`
- Blocks with repetitive dialog prefixes (`Name: "..."`) → reclassify
  as `natural_language`
- Blocks with repetitive ratio patterns (`4:3`, `16:9`) → reclassify
  as `natural_language`

**Evidence:** This single mechanism catches 14/35 FPs (40%).

### 11.5 Opening context check

Examine the first 3-5 non-blank lines of each assembled block. If
the opening contains strong code signals, the entire block retains
`code` classification even if the interior looks like config/data:

```python
STRONG_OPENERS = [
    r'^\s*(def|class|function|func)\s',    # function/class definition
    r'^\s*(import|from|require|include)\s', # import statement
    r'^\s*\w+\s*=\s*\{',                   # assignment to dict/object
    r'^\s*\w+\s*=\s*\[',                   # assignment to array
    r'^\s*(if|for|while)\s.*[:{]',          # control flow
]
```

**The long-dict case:** Opening line `config = {` confirms code.
Interior `"host": "localhost"` stays code (not reclassified as config).

### 11.6 Parse validation (Python only, selective)

Applied only to ambiguous blocks (confidence 0.50-0.70) after assembly.
High-confidence and low-confidence blocks skip this.

| Validator | Input | Confidence boost | Runtime |
|---|---|---|---|
| `ast.parse` | Python blocks | +0.15 | Python only |
| `json.loads` | JSON-shaped blocks | +0.10 | Both |
| C-family structural | bracket balance + 3+ statements | +0.10 | Both |
| Tag balance | matched open/close tags | +0.10 | Both |

**Limit:** Maximum 10 parse attempts per prompt (configurable). Prevents
performance degradation on prompts with many small ambiguous blocks.

### 11.7 Minimum block size

```json
"min_block_lines": 8
```

**Rationale from WildChat analysis:**
- FP median block size: 12 lines
- TP median block size: 27 lines
- 5-10 line blocks: 37% of FPs but only 14% of TPs
- min_block_lines=8 eliminates 32% of FPs at 5.5% recall cost
- F1 drops trivially: 0.933 → 0.925

Blocks below `min_block_lines` are discarded after assembly.

### 11.8 Block confidence computation

Final confidence for assembled blocks:

```python
def _compute_confidence(
    method: str,
    avg_score: float,
    high_ratio: float,
    parse_validated: bool,
    block_lines: int,
) -> float:
    """Compute block confidence from component signals."""
    if method in ("fenced",):
        return 0.95
    if method in ("json_parse",):
        return 0.90
    if method in ("xml_heuristic", "yaml_heuristic", "env_heuristic"):
        return 0.80

    # syntax_score method
    base = 0.40 + avg_score  # 0.40-1.0 range
    if parse_validated:
        base += 0.15

    # Size bonus: larger blocks are more reliable
    if block_lines >= 20:
        base += 0.05
    elif block_lines >= 50:
        base += 0.10

    # High-scoring line ratio bonus
    if high_ratio >= 0.70:
        base += 0.05

    return min(base, 0.95)
```

### 11.9 Performance

- Assembly: O(n) single pass
- Bracket validation: O(n) per block
- Repetitive structure: O(n) per block
- Parse validation: O(1) per block (constant-time parsers, limited
  to 10 attempts)
- Budget: <1ms total

---

## 12. LanguageDetector

Optional secondary output. Computes a language probability distribution
per detected block by accumulating fragment matches from SyntaxDetector.

### 12.1 Algorithm

```python
def _detect_language(block_lines, fragment_hits):
    """Compute language probability from accumulated fragment hits.

    fragment_hits: dict mapping family → count of matching lines
    """
    if not fragment_hits:
        return "", 0.0, {}

    total = sum(fragment_hits.values())
    probs = {family: count / total
             for family, count in fragment_hits.items()}

    # C-family disambiguation (optional, best-effort)
    if "c_family" in probs and probs["c_family"] > 0.5:
        lang = _disambiguate_c_family(block_lines)
        if lang:
            probs[lang] = probs.pop("c_family")

    top_family = max(probs, key=probs.get)
    return top_family, probs[top_family], probs
```

### 12.2 C-family disambiguation

When a block is classified as C-family, attempt to narrow:

```python
C_FAMILY_MARKERS = {
    "javascript": [r'\bconsole\.\w+', r'\bdocument\.\w+', r'\bwindow\.\w+',
                   r'\brequire\s*\(', r'\bmodule\.exports'],
    "typescript": [r':\s*\w+\s*[=;{]', r'\binterface\s+\w+\s*\{',
                   r'<\w+>', r'\bas\s+\w+'],
    "java":       [r'\bSystem\.out\.', r'\bpublic\s+static\s+void\s+main',
                   r'\bpackage\s+\w+\.\w+', r'@Override'],
    "go":         [r'\bfmt\.', r'\bfunc\s+\w+\(', r':=',
                   r'\bpackage\s+main', r'\bdefer\s'],
    "csharp":     [r'\bConsole\.Write', r'\busing\s+System',
                   r'\bvar\s+\w+\s*=', r'\basync\s+Task'],
    "cpp":        [r'\bcout\s*<<', r'\bstd::', r'#include\s*<',
                   r'\btemplate\s*<', r'\bvector<'],
    "c":          [r'\bprintf\s*\(', r'#include\s*<stdio',
                   r'\bmalloc\s*\(', r'\bfree\s*\(', r'\b->\\w+'],
}
```

Best-effort — if no specific markers hit, report `c_family`.

---

## 13. Configuration Model

### 13.1 ZoneConfig

```python
@dataclass
class ZoneConfig:
    """Configuration for zone detection. All fields have sensible defaults."""

    # Sensitivity preset — overrides individual thresholds if set
    sensitivity: str = "balanced"  # "high_recall" | "balanced" | "high_precision"

    # Zone types to detect (others classified as natural_language)
    enabled_types: list[str] = field(default_factory=lambda: [
        "code", "markup", "config", "query", "cli_shell",
        "data", "error_output",
    ])

    # Minimum block size (lines) to emit
    min_block_lines: int = 8

    # Minimum confidence to emit
    min_confidence: float = 0.50

    # Detector toggles
    structural_enabled: bool = True
    format_enabled: bool = True
    syntax_enabled: bool = True
    negative_filter_enabled: bool = True
    parse_validation_enabled: bool = True  # Python-only, no-op in JS
    language_detection_enabled: bool = True

    # Context window size (1, 3, or 5)
    context_window: int = 3

    # Performance
    pre_screen_enabled: bool = True
    max_parse_attempts: int = 10

    # Advanced: override specific scoring weights
    weight_overrides: dict = field(default_factory=dict)
```

### 13.2 Sensitivity presets

| Preset | min_block_lines | min_confidence | parse_validation | Notes |
|---|---|---|---|---|
| `high_recall` | 3 | 0.40 | off | Catch everything, accept FPs |
| `balanced` | 8 | 0.50 | on (Python) | Default — best F1 |
| `high_precision` | 10 | 0.65 | on | Fewer FPs, miss some blocks |

### 13.3 Browser preset

```json
{
  "sensitivity": "balanced",
  "parse_validation_enabled": false,
  "language_detection_enabled": false,
  "max_parse_attempts": 0
}
```

Minimal config for browser — skip Python-only features, disable
optional enrichments, prioritize speed.

---

## 14. Data Structures

### 14.1 ZoneBlock

```python
@dataclass
class ZoneBlock:
    start_line: int             # 0-indexed inclusive
    end_line: int               # 0-indexed exclusive
    zone_type: str              # one of ZONE_TYPES
    confidence: float           # 0.0-1.0
    method: str                 # detection method that produced this block
    language_hint: str = ""     # top language (e.g., "python", "c_family")
    language_confidence: float = 0.0
    text: str = ""              # actual block text (stripped from serialization)
```

### 14.2 PromptZones

```python
@dataclass
class PromptZones:
    prompt_id: str
    total_lines: int
    blocks: list[ZoneBlock] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "prompt_id": self.prompt_id,
            "total_lines": self.total_lines,
            "blocks": [asdict(b) for b in self.blocks],
        }
        for b in d["blocks"]:
            del b["text"]  # strip text from serialization
        return d
```

### 14.3 JS types (TypeScript definitions)

```typescript
interface ZoneBlock {
  startLine: number;        // 0-indexed inclusive
  endLine: number;          // 0-indexed exclusive
  zoneType: string;
  confidence: number;
  method: string;
  languageHint?: string;
  languageConfidence?: number;
}

interface PromptZones {
  promptId: string;
  totalLines: number;
  blocks: ZoneBlock[];
}

interface ZoneConfig {
  sensitivity?: "high_recall" | "balanced" | "high_precision";
  enabledTypes?: string[];
  minBlockLines?: number;
  minConfidence?: number;
  preScreenEnabled?: boolean;
  contextWindow?: 1 | 3 | 5;
}
```

---

## 15. Performance Architecture

### 15.1 Budget per component (browser, P99)

| Component | Budget | Complexity | Notes |
|---|---|---|---|
| Pre-screen | <0.1ms | O(n) | Character scan, no regex |
| StructuralDetector | <0.3ms | O(n) | Linear scan + stack |
| FormatDetector | <0.5ms | O(n) | Parse attempts on 0-3 candidates |
| SyntaxDetector | <3ms | O(n × f) | f = fragment families, short-circuit |
| NegativeFilter | <0.5ms | O(n) | Pattern check per line, short-circuit |
| BlockAssembler | <0.5ms | O(n) | Merge + bracket validation |
| LanguageDetector | <0.2ms | O(b) | b = number of blocks |
| **Total** | **<5ms** | | **Within 100ms worker budget** |

### 15.2 Optimization strategies

**Pre-compilation:** All regex patterns compiled at module load time
(not per-scan). Both Python (`re.compile`) and JS (`new RegExp`)
support this.

**Fragment short-circuit:** When checking fragment families, stop on
first match. If a line matches a Python fragment, skip C-family,
assembly, etc. Expected reduction: ~60% of fragment checks skipped.

**Negative signal short-circuit:** Check negative signals in
effectiveness order (math first, then error, then prose, then dialog,
then ratio). Stop on first match. Expected: 90%+ of lines need
only 1-2 checks.

**Backend cache:** Pre-compiled pattern sets cached by configuration
key (same pattern as scanner-core.js `getBackend()`).

**Block-level early exit:** If pre-screen passes but StructuralDetector
and FormatDetector find nothing, and average syntax score across all
lines is <0.10, skip SyntaxDetector assembly (the prompt is prose with
occasional punctuation).

### 15.3 Memory

- Pattern config: ~50KB loaded once
- Per-prompt state: O(lines) for score arrays, O(blocks) for output
- No persistent state between scans
- Stateless design compatible with worker pool

### 15.4 Worker integration (browser)

Zone detection runs in the **same Web Worker** as secret scanning.
No additional worker pool needed. The worker entrypoint dispatches
to either `scanText()` or `detectZones()` based on the message type:

```javascript
self.addEventListener("message", (event) => {
  const { id, type, text, opts } = event.data;
  let result;
  if (type === "scan") {
    result = scanText(text, opts);
  } else if (type === "zones") {
    result = detectZones(text, opts);
  }
  self.postMessage({ id, result });
});
```

Combined budget (zones + secrets) must stay within the 100ms worker
timeout. With zones at <5ms and secrets at <3ms (P99), this is
well within budget.

---

## 16. Edge Cases

### 16.1 Markdown formatting in prose

Markdown formatting (`**bold**`, `[link](url)`, `# heading`) should
NOT trigger code detection. These are prose formatting, not markup
zones.

**Handling:** The pre-screen's density threshold (3%) is below
markdown's typical density. Markdown headings (`#`) are handled by
the comment marker exclusion in the context window. Bold/italic
markers (`*`, `_`) are not in the syntactic character set.

### 16.2 Unicode / CJK text

Chinese, Japanese, Korean, Arabic, Cyrillic text should never trigger
code detection. These prompts are 95%+ alpha with no syntactic chars.

**Handling:** The alpha ratio in negative signals and pre-screen density
threshold naturally exclude CJK. Additional safety: lines where >50%
of characters are outside ASCII range get score = 0 (non-ASCII =
human language, not code).

### 16.3 REPL sessions

```python
>>> x = 1 + 2
3
>>> print("hello")
hello
```

The `>>>` lines are code; the output lines are... output. Mixed content.

**Handling:** `>>>` is in the shell fragment patterns. Output lines
(no `>>>`, no code features) score 0 but are bridged by gap rules
(1-2 zero-score lines between code lines). The entire REPL session
stays as one `code` block. Type: `code`, language hint: `python`
(from `>>>` marker).

### 16.4 Pseudocode

```
Step 1: Initialize the array
Step 2: Loop through each element
Step 3: Compare adjacent elements
Step 4: Swap if out of order
```

**Handling:** Numbered list prefix detection (>70% match) reclassifies
as `natural_language`. No code keywords, no syntactic chars → syntax
score is 0.

### 16.5 API documentation

```
POST /api/users
Content-Type: application/json
Authorization: Bearer <token>

{
  "name": "John",
  "email": "john@example.com"
}
```

**Handling:** The HTTP method line has no code features. The headers
look like `key: value` (YAML heuristic possible but requires ≥3 KV
lines). The JSON body is detected by FormatDetector. Result: likely
a `config` block for the JSON body, headers may or may not be included
depending on gap bridging.

### 16.6 Very long prompts

WildChat max block: 4,241 lines. Pre-screen and all detectors are O(n)
so performance scales linearly. No recursion, no O(n²) operations.

### 16.7 Empty / whitespace-only input

```python
if not text or not text.strip():
    return PromptZones(prompt_id=prompt_id, total_lines=0, blocks=[])
```

### 16.8 Binary / corrupted input

Pre-screen handles this: non-text content has no syntactic chars, no
fence markers, no indentation patterns → pre-screen returns False →
empty result.

---

## 17. Validation Plan

### 17.1 Metrics

| Metric | v1 baseline | v2 target | Measurement |
|---|---|---|---|
| Precision | 80.3% | >90% | TP / (TP + FP) on reviewed corpus |
| Recall | 99.1% | >95% | TP / (TP + FN) on reviewed corpus |
| F1 | 88.7% | >92% | Harmonic mean |
| Boundary recall | 70% | >85% | Line-level Jaccard vs human marks |
| Fragmentation rate | ~2.5x | <1.3x | Detected blocks / true blocks |
| FP rate (syntax_score) | 11.9% | <5% | FPs from syntax_score method |
| Throughput (Python) | 3,113/sec | >1,500/sec | Prompts per second |
| Latency (JS, P99) | n/a | <10ms | Per-prompt in browser |

### 17.2 Evaluation corpus

**Primary:** 507+ reviewed prompts from `s4_labeled_corpus.jsonl`
with human verdicts (correct/wrong/corrected), boundary corrections,
and secret TP/FP flags.

**Regression set:** 212 true positives + 298 true negatives must
remain correctly classified. Zero TP regression allowed.

**FP audit:** All 35 known FPs must be fixed. Any new FPs introduced
by v2 are manually reviewed and categorized.

### 17.3 Differential test (Python ↔ JS)

50-prompt seed corpus covering:
- 10 fenced code blocks (various languages)
- 10 unfenced code blocks (Python, JS, Java, C)
- 5 config blocks (JSON, YAML, ENV)
- 5 markup blocks (HTML, XML)
- 5 error output blocks (tracebacks, build errors)
- 5 known FP cases (aspect ratios, dialog, math)
- 10 pure prose (negatives)

Both runtimes must produce identical `{zone_type, start_line, end_line,
method}` on all 50 prompts. Parse-validation-only confidence differences
are allowed.

### 17.4 Performance benchmark

Run on 10K WildChat prompts (reservoir sample, seed=42):

| Metric | Target |
|---|---|
| Python throughput | >1,500 prompts/sec |
| Python P99 latency | <2ms |
| JS P99 latency (headless Chrome) | <10ms |
| Pre-screen skip rate | >95% |
| Memory (Python, 10K batch) | <50MB |

---

## 18. FP Coverage Matrix

All 35 known FPs mapped to v2 mechanisms:

| # | Category | Count | Mechanism | Pass |
|---|---|---|---|---|
| 1 | Aspect ratio lists | 7 | Ratio negative signal + repetitive structure | 4+5 |
| 2 | Structured lists / glossaries | 6 | List prefix detection (>70%) | 4 |
| 3 | Error messages / build output | 4 | Error output patterns + repetitive structure | 4+5 |
| 4 | Dialog / conversation | 3 | Dialog patterns + repetitive structure | 4+5 |
| 5 | Math / data notation | 3 | Math negative signals | 4 |
| 6 | XML heuristic over-trigger | 2 | Require matched open/close tags | 2 |
| 7 | Tabular / ASCII tables | 2 | Repetitive column structure | 5 |
| 8 | Low-confidence misc | 4 | No fragment match → score stays low + min_block_lines=8 | 3+5 |
| 9 | BBCode markup | 1 | `[tag]` not matched by markup patterns | 2 |
| 10 | CSV academic data | 1 | FormatDetector types as `data`, not `code` | 2 |
| 11 | Fenced non-code (Gaussian log) | 1 | **Accepted edge case** (fenced = author intent) | — |

**34/35 covered. 1 accepted.**

---

## 19. Implementation Sequencing

Recommended build order (each step is independently testable):

### Phase 1: Foundation

1. **Shared config format** — Create `zone_patterns.json` with all
   patterns, weights, thresholds from this spec. Validate schema.
2. **Data structures** — `ZoneBlock`, `PromptZones`, `ZoneConfig`
   (same for Python and JS TypeScript definitions).
3. **Pre-screen** — Fast path implementation + tests.

### Phase 2: Detectors (Python first)

4. **StructuralDetector** — Port fenced detection from v1, add
   delimiter pair scanning. Test against reviewed corpus.
5. **FormatDetector** — Port JSON/YAML/XML/ENV from v1, tighten XML
   (require matched tags). Test.
6. **SyntaxDetector** — Refactor v1 syntax scoring, add fragment
   matching, add context window. Test.
7. **NegativeFilter** — All negative signal patterns. Test against
   35 known FPs.
8. **BlockAssembler** — Assembly rules, gap bridging, bracket
   validation, repetitive structure, opening context, parse
   validation. Test.
9. **LanguageDetector** — Fragment accumulation, C-family
   disambiguation. Test.

### Phase 3: Orchestration

10. **ZoneOrchestrator** — Wire detectors in order, manage claimed
    ranges, apply configuration. Run full evaluation on reviewed
    corpus, measure all metrics.

### Phase 4: JS port

11. **Generate zone patterns** — Extend `generate_browser_patterns.py`
    to emit `zone-patterns.js`.
12. **JS implementation** — Port orchestrator + all detectors to JS.
    Follow scanner-core.js patterns.
13. **Differential test** — Create `zone_fixtures.json`, extend
    `differential.spec.js`, validate parity.
14. **Worker integration** — Add zone detection dispatch to worker.js.

### Phase 5: Validation

15. **Full evaluation** — Run on reviewed corpus, measure all metrics
    from §17.1. Compare to v1 baseline.
16. **Performance benchmark** — Run on 10K WildChat, measure throughput
    and latency.
17. **Review tool update** — Update prompt_reviewer.py to use v2
    detector, verify UI compatibility.

---

## 20. Upgrade Paths

### 20.1 CRF sequence labeler

The SyntaxDetector features are designed as a CRF feature vector.
Adding a CRF layer:

1. Export per-line features from SyntaxDetector (10+ features per line)
2. Train `sklearn-crfsuite` model on 507+ reviewed prompts
3. Replace rule-based scoring with CRF predictions
4. BlockAssembler remains unchanged (operates on CRF output)

**Expected improvement:** Boundary recall from 85% to 90%+. The CRF
learns transition weights (e.g., CODE → BLANK → CODE stays CODE)
that rule-based gap bridging approximates.

**Prerequisite:** 500+ reviewed prompts (already available).

### 20.2 Incremental detection

For real-time browser use (user typing), detect zones incrementally:

1. Hash each line
2. On re-scan, identify changed lines
3. Re-score only changed lines + context window neighbors
4. Re-run assembly only for blocks touching changed regions

**Prerequisite:** Stable API + performance baseline.

### 20.3 Confidence calibration

Use the reviewed corpus to calibrate confidence → precision:

| Confidence | Observed precision |
|---|---|
| 0.50-0.60 | ~70% |
| 0.60-0.70 | ~85% |
| 0.70-0.80 | ~90% |
| 0.80-0.90 | ~95% |
| 0.90-1.00 | ~99% |

Report calibrated precision alongside raw confidence for downstream
consumers.

---

## Appendix A: Complete `zone_patterns.json` Schema

```json
{
  "$schema": "zone_patterns/v2",
  "version": "2.0.0",

  "zone_types": [
    "code", "markup", "config", "query", "cli_shell",
    "data", "error_output", "natural_language"
  ],

  "pre_screen": { "..." : "see §5" },
  "lang_tag_map": { "..." : "see §6" },
  "structural": { "..." : "see §7.3" },
  "format": { "..." : "see §8.6" },

  "syntax": {
    "syntactic_chars": "{}()[];=<>|&!@#$^*/\\~",
    "syntactic_endings": "{;)],:",
    "code_keywords": ["...see §9.1..."],
    "assignment_pattern": "^\\s*[a-z_]\\w*\\s*[:=]",
    "scoring_weights": { "..." : "see §9.1" },
    "fragment_patterns": {
      "c_family": ["...see §9.2..."],
      "python": ["..."],
      "markup": ["..."],
      "sql": ["..."],
      "shell": ["..."],
      "assembly": ["..."],
      "rust": ["..."]
    },
    "context": { "..." : "see §9.3" }
  },

  "negative": {
    "error_output": ["...see §10.1..."],
    "dialog": { "..." : "see §10.2" },
    "list_prefix": { "..." : "see §10.3" },
    "math": ["...see §10.4..."],
    "ratio": ["...see §10.5..."],
    "prose": { "..." : "see §10.6" }
  },

  "assembly": {
    "min_block_lines": 8,
    "min_confidence": 0.50,
    "max_blank_gap": 2,
    "max_comment_gap": 2,
    "repetitive_threshold": 0.50,
    "max_parse_attempts": 10,
    "bracket_extension_limit": 5
  },

  "language": {
    "c_family_markers": { "..." : "see §12.2" }
  }
}
```

## Appendix B: Cross-Signal with Secret Detection

Zone types influence secret scanning behavior:

| Zone type | Secret scanning strategy |
|---|---|
| `error_output` | **Elevate** — credentials in errors are real leaks |
| `code` | **Standard** — code examples may contain demo keys |
| `config` | **Elevate** — config files often contain real credentials |
| `cli_shell` | **Elevate** — CLI commands may expose env vars |
| `natural_language` | **Standard** — standard scanning |
| `markup` | **Standard** — HTML may contain API keys in scripts |
| `data` | **Reduce** — tabular data rarely contains credentials |
| `query` | **Standard** — SQL may contain connection strings |

This is an architectural capability for future integration, not a v2
deliverable. The zone type is available as metadata for the scan_text
pipeline to consume.

## Appendix C: File Structure (promotion target)

```
data_classifier/
├── zones/
│   ├── __init__.py              # Public API: detect_zones, ZoneBlock, PromptZones
│   ├── types.py                 # ZoneBlock, PromptZones, ZoneConfig
│   ├── orchestrator.py          # ZoneOrchestrator (wires detectors)
│   ├── structural.py            # StructuralDetector
│   ├── format_detector.py       # FormatDetector
│   ├── syntax.py                # SyntaxDetector
│   ├── negative.py              # NegativeFilter
│   ├── assembler.py             # BlockAssembler
│   ├── language.py              # LanguageDetector
│   └── config.py                # ZoneConfig loading, presets
├── patterns/
│   └── zone_patterns.json       # Shared config (single source of truth)
└── clients/browser/
    └── src/
        ├── zone-detector.js     # JS implementation
        └── generated/
            └── zone-patterns.js # Generated from zone_patterns.json
```

Research location (current):
`docs/experiments/prompt_analysis/s4_zone_detection/zone_detector.py`

Promotion: via sprint backlog item, after v2 validation passes all
metrics in §17.
