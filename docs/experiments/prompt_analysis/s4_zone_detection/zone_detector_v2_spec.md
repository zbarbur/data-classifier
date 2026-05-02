# Zone Detector v2 — Architecture Specification

**Date:** 2026-04-21
**Branch:** `research/prompt-analysis`
**Status:** Design — pending implementation
**Research basis:** `research_prior_art.md` (companion document)

---

## 1. Goal

Replace the v1 heuristic zone detector with a multi-pass cascade
architecture that:

1. Maintains or improves detection accuracy (currently 90%)
2. Raises boundary recall from 70% to 85%+
3. Eliminates the 35 known FP patterns identified in 507+ human reviews
4. Adds `error_output` as a zone type
5. Produces secondary language probability per detected block
6. Cross-signals with secret detection (elevated scanning in error output)

## 2. Zone Taxonomy (v2)

```
code             → executable source code
markup           → HTML, XML
config           → YAML, JSON, ENV, properties, TOML, INI
query            → SQL, GraphQL
cli_shell        → shell commands, terminal sessions
data             → CSV, tables, structured data
error_output     → stack traces, compiler errors, logs, build output  ← NEW
natural_language → prose, conversation (default for unclassified)
```

**Change from v1:** Added `error_output`. Removed v1's `structured_data`
(split into `config` and `data` for clarity — this split already existed
in the review tool).

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Input: raw text                         │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│  Pass 0: Bracket / Delimiter Scan                               │
│  ─────────────────────────────────                              │
│  Claim delimited spans with matched open/close markers.         │
│  These spans are NOT re-scored by later passes.                 │
│                                                                 │
│  High confidence:                                               │
│    ``` ... ```           fenced code blocks                     │
│    /* ... */             multi-line comments (within code)       │
│    <!-- ... -->          HTML comments                           │
│    """ ... """           Python docstrings/multiline strings     │
│    <script>...</script>  language injection markers              │
│    <style>...</style>    language injection markers              │
│    heredoc <<MARK...MARK heredoc blocks                         │
│                                                                 │
│  Medium confidence (require opening line to score as code):     │
│    { ... }               multi-line brace blocks                │
│    [ ... ]               multi-line array/list brackets         │
│                                                                 │
│  Output: set of claimed line ranges + their types               │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│  Pass 1: Line-Level Scoring (unclaimed lines only)              │
│  ────────────────────────────────────────────────               │
│  For each unclaimed line, compute:                              │
│    a) Syntax score (character density, keywords, indentation)   │
│    b) Fragment matching (does it match a statement pattern?)     │
│    c) Negative signal check (error, dialog, list, math)         │
│    d) 3-line window context (neighbor scores, transitions)      │
│                                                                 │
│  Output: per-line score + tentative type + fragment matches     │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│  Pass 2: Block Assembly + Boundary Validation                   │
│  ────────────────────────────────────────────                   │
│  a) Group consecutive same-type lines into candidate blocks     │
│  b) Bridge gaps: merge blocks separated by 1-2 blank lines     │
│     or comment lines when surrounding blocks are same type      │
│  c) Bracket balance validation: verify block boundaries         │
│     don't split balanced bracket pairs                          │
│  d) Repetitive structure test: if >50% of block lines share     │
│     same prefix pattern → reclassify (error_output, dialog)     │
│                                                                 │
│  Output: assembled blocks with boundaries                       │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│  Pass 3: Block-Level Confirmation                               │
│  ────────────────────────────────                               │
│  For each assembled block:                                      │
│    a) Check opening 3-5 lines for type confirmation             │
│    b) Selective parse attempt (ambiguous blocks only):           │
│       - Python: ast.parse                                       │
│       - JSON: json.loads                                        │
│       - C-family: bracket balance + statement count             │
│       - Markup: tag open/close balance                          │
│    c) Compute language probability distribution                 │
│    d) Downgrade blocks that fail validation                     │
│                                                                 │
│  Output: final blocks with confidence + language probability    │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│  Output: PromptZones with ZoneBlock list                        │
│  (same interface as v1 — drop-in replacement)                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Pass 0: Bracket / Delimiter Scan

### 4.1 Purpose

Claim spans that have unambiguous structural delimiters before any
heuristic scoring runs. Interior content of claimed spans is not
re-evaluated, preventing misclassification of content that "looks
like" something else (e.g., prose inside `/* */` comments, YAML inside
backtick fences).

### 4.2 Rationale

**Problem solved:** Multi-line comments (`/* ... */`) contain prose
that scores high on alpha ratio. Without Pass 0, the comment interior
fragments the surrounding code block. Similarly, `<script>` tags
create legitimate zone transitions that Pass 1 alone would try to
smooth over.

**Research basis:** Island grammar parsing (Bacchelli et al.) shows
that recognizing delimited constructs first, then classifying the
"water" between them, is more accurate than uniform line-level
classification. Tree-sitter's language injection mechanism follows
the same principle.

### 4.3 Delimiter Pairs

#### High confidence — claim unconditionally

| Opener | Closer | Zone type | Language hint |
|---|---|---|---|
| ` ``` ` / `~~~` | matching fence | from lang tag or infer | from tag |
| `/*` | `*/` | inherit from parent block | parent language |
| `<!--` | `-->` | markup | html/xml |
| `"""` | `"""` | inherit from parent block | python |
| `'''` | `'''` | inherit from parent block | python |
| `<script>` / `<script ...>` | `</script>` | code | javascript |
| `<style>` / `<style ...>` | `</style>` | code | css |
| `heredoc <<MARKER` | `MARKER` (same string) | code | from context |

#### Medium confidence — require context

| Opener | Closer | Condition | Zone type |
|---|---|---|---|
| `{` (at end of code line) | matching `}` | opening line scores as code in Pass 1 | code |
| `[` (at start of line) | matching `]` | multi-line, >3 lines | data |

Medium-confidence delimiters are identified in Pass 0 but only claimed
after Pass 1 confirms the opening line scores as code. This prevents
claiming every `{` in prose.

### 4.4 Implementation Notes

- Bracket matching is a linear scan with a stack. No recursion needed.
- Nested delimiters: `<script>` inside `<!-- -->` is handled by
  processing outermost delimiters first.
- Unclosed delimiters: if no matching closer is found by end of text,
  do not claim the span. Fall through to Pass 1.
- `<script>` / `<style>` create a **zone transition** within a markup
  block — the parent block is split into markup → code → markup.

---

## 5. Pass 1: Line-Level Scoring

### 5.1 Purpose

Score each unclaimed line for code-likeness, applying positive signals
(syntax features, fragment matching) and negative signals (error output,
dialog, lists, math), with a 3-line context window for smoothing.

### 5.2 Rationale

**Research basis:** Line-level is the consensus granularity (CLOC, SCC,
our v1). The 3-line window is justified by SCC++ finding that context
adds 13.9% accuracy. Three lines captures ~80% of contextual signal;
beyond 5 lines gains are marginal.

**Why 3 lines, not 5:** The structural cases that need more than 3 lines
of context (long dicts, multi-line comments, `<script>` blocks) are
handled by Pass 0 (bracket scan) and Pass 3 (block-level opening
context). Pass 1's window only needs to handle local smoothing — blank
lines and comments between code lines.

### 5.3 Positive Signals

#### 5.3.1 Syntax Score (carried from v1, refined)

Per-line feature computation:

| Feature | Weight | Description |
|---|---|---|
| Syntactic char density >0.15 | +0.30 | `{}()[];=<>|&!@#$^*/\\~` |
| Syntactic char density >0.08 | +0.15 | Lower density still significant |
| 2+ code keywords | +0.30 | `def`, `class`, `import`, `function`, etc. |
| 1 code keyword | +0.15 | Single keyword |
| Code-like line ending | +0.10 | Ends with `{`, `;`, `)`, `]`, `,` |
| Assignment pattern | +0.10 | `identifier = value` (not `Prob[A] = 0.7`) |
| Indentation ≥2 spaces | +0.05 | Code tends to be indented |

Score capped at 1.0.

#### 5.3.2 Fragment Matching (NEW)

Check if the line matches a known statement pattern from one of three
syntax families. A fragment match is a strong confirmation signal that
boosts the line's score by +0.25 and records which family matched.

**C-family patterns** (JS/TS, Java, C/C++, C#, Go):

```python
C_FAMILY_FRAGMENTS = [
    r'^\s*(if|else|for|while|switch|case|return)\s*[\({]',
    r'^\s*(const|let|var|int|string|bool|float|void)\s+\w+',
    r'^\s*(func|function|public|private|static|class|interface|struct)\s',
    r'^\s*\w+\.\w+\(.*\)',              # method call
    r'^\s*\w+\s*:?=\s*.+[;,]?\s*$',    # assignment (Go := too)
    r'[{};]\s*$',                        # line ends with brace/semi
]
```

**Python patterns:**

```python
PYTHON_FRAGMENTS = [
    r'^\s*(def|class|import|from|return|yield|raise|assert)\s',
    r'^\s*(if|elif|else|for|while|try|except|finally|with|as)\s.*:\s*(#.*)?$',
    r'^\s*@\w+',                         # decorator
    r'^\s*\w+\s*=\s*.+$',               # assignment
    r'^\s*(print|len|range|type|isinstance|hasattr|getattr)\s*\(',
]
```

**Markup patterns** (HTML, XML, CSS):

```python
MARKUP_FRAGMENTS = [
    r'<\w+[\s>]',                        # opening tag
    r'</\w+>',                           # closing tag
    r'^\s*\w[\w-]*\s*:\s*.+;',          # CSS property
    r'^\s*[\.\#@]\w+.*\{',              # CSS selector
]
```

**Tier 2 — distinctive outlier languages** (cheap, high precision):

```python
ASSEMBLY_FRAGMENTS = [
    r'^\s*(mov|push|pop|call|ret|jmp|jne|je|jz|jnz|cmp|add|sub|mul|div|xor|and|or|not|lea|nop)\s',
    r'\b(eax|ebx|ecx|edx|esi|edi|esp|ebp|rax|rbx|rcx|rdx|r[0-9]+)\b',
]

RUST_FRAGMENTS = [
    r'^\s*(fn|let\s+mut|impl|pub\s+fn|use\s+\w+|mod\s+\w+)\s',
    r'\bunwrap\(\)|\bexpect\("',
    r'::\w+',                            # path separator
]

SQL_FRAGMENTS = [
    r'^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|FROM|WHERE|JOIN)\s',
    r'^\s*(GROUP BY|ORDER BY|HAVING|LIMIT|OFFSET|UNION)\s',
]

SHELL_FRAGMENTS = [
    r'^\s*\$\s+\w',                      # $ prompt
    r'^\s*(sudo|chmod|chown|mkdir|curl|wget|docker|kubectl|git)\s',
    r'\|\s*(grep|awk|sed|sort|head|tail|wc|xargs|cut|tr)\s',
]
```

**Design rationale:** We don't need to identify WHICH C-family language
it is — just that it IS C-family code. JS vs Java vs Go doesn't matter
for zone detection. Language identification within the zone is a
secondary enrichment step (Pass 3). This reduces 10 language detectors
to 3 syntax families + a handful of distinctive Tier 2 patterns.

### 5.4 Negative Signals (NEW)

Negative signals suppress the code score for lines that have code-like
surface features but are not code. Each signal returns a type
reclassification or a score suppression.

#### 5.4.1 Error Output Patterns

```python
ERROR_OUTPUT_PATTERNS = [
    # Python traceback
    r'^\s*File ".+", line \d+',
    r'^\s*Traceback \(most recent call last\)',
    r'^\w+Error:\s',
    r'^\w+Exception:\s',
    r'^\w+Warning:\s',

    # Java/JS stack traces
    r'^\s*at \w[\w.]+\(.+:\d+\)',
    r'^\s*at \w[\w.]+\s\(.+:\d+:\d+\)',

    # Compiler errors
    r'^\s*error\[?\w*\]?\s*:',
    r'^\s*warning\[?\w*\]?\s*:',
    r'^\s*-->\s+\S+:\d+:\d+',
    r'^\s*\^+\s',
    r'^\s*\|$',

    # Package manager / build
    r'^\s*npm ERR!',
    r'^\s*(ERROR|WARN|INFO|DEBUG|FATAL|CRITICAL)\s',
    r'^\s*Requirement already satisfied:',

    # Log output (timestamp prefix)
    r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}',
    r'^\[\d{4}-\d{2}-\d{2}',
    r'^\[?(ERROR|WARN|INFO|DEBUG)\]?\s',
]
```

**Effect:** Line score set to 0; line tentatively typed as
`error_output`. Block-level confirmation in Pass 2 (repetitive
structure test) finalizes the type.

**Dual signal value:**
1. **Negative** — this line is not code, end the code zone here
2. **Positive** — code almost certainly exists nearby (debugging
   context), and the error block itself is a high-value target for
   secret detection (connection strings, tokens, env vars leak in
   stack traces)

**Evidence from reviews:** 4 FPs in our corpus were error/build output
(Rust compiler, Node stack trace, pip output, pylint output). All had
confidence 0.650-0.700 because they contain file paths, line numbers,
and module references.

#### 5.4.2 Dialog / Conversation Patterns

```python
DIALOG_PATTERNS = [
    r'^\s*[A-Z][a-z]+:\s*"',            # Name: "speech"
    r'^\s*[A-Z][a-z]+:\s*[A-Z]',        # Name: Sentence
    r'^\s*\([A-Z][a-z]+\)\s',           # (Name) speech
    r'^\s*\[[A-Z][a-z]+\]\s',           # [Name] speech
]
```

**Condition:** Line matches dialog pattern AND has high alpha ratio
(>0.70) in the remainder. Combined with the repetitive structure test
in Pass 2: if >50% of block lines match the same dialog prefix pattern,
classify as `natural_language`.

**Evidence from reviews:** 3 FPs — character dialog with `Name: "text"`
format (Monika/Natsuki dialog, scam email).

#### 5.4.3 List Item Prefix Detection

```python
LIST_ITEM_PREFIX = r'^\s*(?:\d+[.)]\s+|[-•*]\s+|[a-z][.)]\s+)'
```

**Rule:** If >70% of lines in a candidate block start with a list
marker (`-`, `*`, `•`, `1.`, `a)`), the block is a list ABOUT
something, not executable code — regardless of what individual items
contain.

**Rationale:** Real code blocks almost never have every line starting
with a list marker. Lists of code fragments (like `- dict(set())`,
`- defaultdict({})`) are reference material, not executable code.

**Evidence from reviews:** 6 FPs — Japanese glossaries, game legends,
Python function comparison lists. All had every line starting with
a bullet or number.

#### 5.4.4 Math / Numeric Notation

```python
MATH_PATTERNS = [
    # Chained comparisons (not assignment)
    r'[<>=]=?\s*\w+\s*[<>=]=?',
    # Function-like with only numeric arguments: p(0,1)
    r'^\s*[\w(]+[\d,.\-]+\)',
    # Pure number sequences with delimiters
    r'^\s*[\d\s;,]+$',
    # LaTeX / math notation (from v1, expanded)
    r'\\frac|\\begin|\\end|\\sum|\\int',
    r'\b(cos|sin|tan|log|exp|sqrt)\b',
    r'(?:∩|∪|≤|≥|⊂|⊆|∈|∉|→|←|↔|∀|∃|∅)',
]
```

**Condition:** Line matches math pattern AND all "arguments" within
parentheses are numeric → suppress code score.

**Evidence from reviews:** 3 FPs — `p(0,1) p(1,-1)` patterns,
semicolon-delimited numbers, inequality expressions.

#### 5.4.5 Aspect Ratio / Non-Code Colon Patterns

```python
RATIO_PATTERN = r'^\s*\d+:\d+\s'           # 4:3, 16:9
NON_CODE_COLON = r'^\s*[A-Z][\w\s]+:\s'    # "Title: description"
```

**Evidence from reviews:** 7 FPs (20% of all FPs!) from a single
MidJourney template with aspect ratios. Colon-separated ratios
trigger code-like syntax scoring.

### 5.5 3-Line Context Window

For each line `i`, the final score incorporates neighbors:

```python
def contextualized_score(i, line_scores, lines):
    raw = line_scores[i]

    # Neighbor influence (±1 line)
    above = line_scores[i-1] if i > 0 else 0
    below = line_scores[i+1] if i < len(lines)-1 else 0
    neighbor_avg = (above + below) / 2

    # Transition signals
    transition_boost = 0
    if i > 0:
        prev = lines[i-1].strip()
        # Line above ends with colon or opening brace
        if prev.endswith((':','{')) and above > 0.2:
            transition_boost = 0.1
        # Prose-to-code transition phrases
        if re.match(r'.*(example|code|output|run this|here is|below).*:?\s*$',
                     prev, re.IGNORECASE):
            transition_boost = 0.15

    # Comment detection within code context
    comment_in_code = 0
    if raw == 0 and neighbor_avg > 0.3:
        stripped = lines[i].strip()
        if stripped.startswith(('#','//','--','/*','*','%')):
            comment_in_code = neighbor_avg * 0.8

    # Blend: own score + neighbor influence + transitions
    final = raw * 0.7 + neighbor_avg * 0.2 + transition_boost + comment_in_code
    return min(final, 1.0)
```

**Design rationale:** The window is deliberately small (3 lines). Larger
context windows blur legitimate boundaries (like `<script>` transitions)
and don't help with the long-range problems (long dicts, multi-line
comments) that Pass 0 and Pass 3 handle.

---

## 6. Pass 2: Block Assembly + Boundary Validation

### 6.1 Purpose

Group scored lines into blocks, merge fragments, and validate block
coherence using bracket balancing and repetitive structure detection.

### 6.2 Block Assembly Rules

1. **Group consecutive same-type lines** into candidate blocks.
   Lines scoring >0 are "code"; lines with type overrides from
   negative signals keep their assigned type.

2. **Bridge blank-line gaps:** If two code blocks are separated by
   1-2 blank lines, merge them into one block. The blank lines become
   part of the code block (type `code`, not `natural_language`).

3. **Bridge comment gaps:** If a line scores 0 but starts with a
   comment marker (`#`, `//`, `--`, `/*`, `*`) and both neighbors
   score as code, include it in the code block.

4. **Break on 3+ zero-score non-blank lines:** This indicates a real
   prose section between code blocks. Do not merge.

5. **Break on type transitions:** A line scored as `error_output`
   terminates the preceding code block. Error lines become their own
   block.

### 6.3 Bracket Balance Validation

After assembly, check each block for balanced brackets:

```python
def brackets_balanced(lines):
    counts = {'(': 0, '[': 0, '{': 0}
    closers = {')': '(', ']': '[', '}': '{'}
    for line in lines:
        for ch in line:
            if ch in counts:
                counts[ch] += 1
            elif ch in closers:
                counts[closers[ch]] -= 1
    return all(v == 0 for v in counts.values())
```

**If a block has unbalanced brackets:**
- Check if extending the block by 1-5 lines in the direction of the
  imbalance restores balance. If so, extend the boundary.
- This catches the case where a closing `}` or `)` was excluded because
  the line had low syntax score.

**If splitting a block produces unbalanced halves:**
- Don't split. Keep as one block.
- This prevents fragmenting the long-dict case (splitting at a blank
  line inside `{...}` produces two unbalanced halves).

### 6.4 Repetitive Structure Test

```python
def detect_repetitive_prefix(lines, threshold=0.5):
    """If >50% of non-empty lines share the same prefix pattern,
    the block has repetitive structure (error output, dialog, etc.)."""
    patterns = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Extract prefix (first 2-3 "words" or distinctive pattern)
        prefix = re.match(r'^(\s*\S+\s*\S*)', stripped)
        if prefix:
            patterns.append(prefix.group(1))

    if not patterns:
        return None

    # Find most common prefix
    from collections import Counter
    counts = Counter(patterns)
    most_common, count = counts.most_common(1)[0]
    if count / len(patterns) >= threshold:
        return most_common
    return None
```

**Application:**
- Blocks with repetitive `npm ERR!`, `File "...", line`, `at Module.`
  → reclassify as `error_output`
- Blocks with repetitive `Name: "..."` → reclassify as
  `natural_language` (dialog)
- Blocks with repetitive `4:3`, `16:9` → reclassify as
  `natural_language`

**Evidence:** This single mechanism catches error output (4 FPs),
dialog (3 FPs), and aspect ratios (7 FPs) — 14/35 FPs, 40% of all
false positives, from one test.

---

## 7. Pass 3: Block-Level Confirmation

### 7.1 Purpose

Final validation of assembled blocks using opening-line context and
selective parse attempts. Produces language probability and downgrades
blocks that fail validation.

### 7.2 Opening Context Check

Examine the first 3-5 non-blank lines of each block. If the opening
is clearly code (contains `def`, `function`, `class`, `import`, `{`,
or other strong statement patterns), the entire block retains its code
classification even if the interior looks like config/data.

**The long-dict case:** Opening line `config = {` confirms the block
is code. Interior lines like `"host": "localhost"` stay within the
code block despite looking like JSON.

### 7.3 Parse Validation (Selective)

Only applied to **ambiguous blocks** — blocks where confidence is in
the gray zone (0.50-0.70) after assembly. High-confidence blocks
(>0.70) and low-confidence blocks (<0.50, already filtered) skip this.

#### 7.3.1 Python — `ast.parse`

```python
import ast

def validate_python(block_text):
    try:
        ast.parse(block_text)
        return 'code', 'python', 0.90
    except SyntaxError:
        return None, None, 0.0
```

Definitive for Python. Available via stdlib, zero cost.

#### 7.3.2 JSON — `json.loads`

```python
import json

def validate_json(block_text):
    text = block_text.strip()
    if not (text.startswith(('{','[')) and text.endswith(('}',']'))):
        return None, None, 0.0
    try:
        json.loads(text)
        return 'config', 'json', 0.90
    except (json.JSONDecodeError, ValueError):
        return None, None, 0.0
```

Definitive for JSON. Strict syntax = strong signal.

#### 7.3.3 C-family — Structural Validation

No stdlib parser available. Use structural heuristics:

```python
def validate_c_family(block_lines):
    # Bracket balance
    balanced = brackets_balanced(block_lines)
    # Statement pattern count
    statement_count = sum(1 for l in block_lines
                         if any(re.match(p, l) for p in C_FAMILY_FRAGMENTS))
    # Need balanced brackets AND multiple statements
    if balanced and statement_count >= 3:
        return 'code', 'c_family', 0.80
    elif statement_count >= 5:  # unbalanced but many statements (snippet)
        return 'code', 'c_family', 0.70
    return None, None, 0.0
```

#### 7.3.4 Markup — Tag Balance

```python
def validate_markup(block_text):
    open_tags = re.findall(r'<(\w+)[\s>]', block_text)
    close_tags = re.findall(r'</(\w+)>', block_text)
    if len(open_tags) >= 2 and len(close_tags) >= 1:
        # Check for matching pairs
        matched = set(open_tags) & set(close_tags)
        if matched:
            return 'markup', 'html', 0.85
    return None, None, 0.0
```

**Fixes the xml_heuristic boundary problem:** v1 triggered on any `<>`
characters. v2 requires actual matched open/close tags, preventing NL
instructions with `<CLAIM>` from triggering markup detection.

#### 7.3.5 YAML — Heuristic Only

YAML parse validation is explicitly NOT used. YAML is too permissive —
plain strings are valid YAML, so `Hello world` parses as a YAML scalar.
Continue using the key-value heuristic from v1 (requires `key: value`
pairs, not just bullet lists).

### 7.4 Language Probability

Each block gets a language probability distribution computed from
fragment match accumulation across the block:

```python
# Accumulate fragment matches across all lines in the block
family_hits = {
    'python': count_python_fragments,
    'c_family': count_c_family_fragments,
    'markup': count_markup_fragments,
    'assembly': count_assembly_fragments,
    'sql': count_sql_fragments,
    'shell': count_shell_fragments,
    'rust': count_rust_fragments,
}

# Normalize to probability distribution
total = sum(family_hits.values()) or 1
language_probs = {k: v/total for k, v in family_hits.items() if v > 0}
```

For C-family, further disambiguation is possible but low priority:
- `console.log` → JavaScript
- `System.out.println` → Java
- `fmt.Println` → Go
- `cout <<` → C++

The top language and its probability are stored on the `ZoneBlock`:

```python
@dataclass
class ZoneBlock:
    # ... existing fields ...
    language_hint: str       # top language (e.g., "python", "c_family")
    language_confidence: float  # probability of top language
    language_probs: dict     # full distribution (optional, for research)
```

---

## 8. FP Coverage Analysis

Validation of the architecture against all 35 known FPs from 507+
human reviews:

| FP Category | Count | Pass | Mechanism | Status |
|---|---|---|---|---|
| Aspect ratio lists | 7 | 1+2 | No fragment match + repetitive prefix | **Covered** |
| Structured lists | 6 | 1 | List prefix detection (>70% list markers) | **Covered** |
| Error output | 4 | 1+2 | Error patterns + repetitive structure | **Covered** |
| Dialog / conversation | 3 | 1+2 | Dialog patterns + repetitive prefix | **Covered** |
| Math / data notation | 3 | 1 | Math patterns + numeric-only args | **Covered** |
| XML over-trigger | 2 | 3 | Require matched open/close tags | **Covered** |
| Tabular / ASCII | 2 | 2 | Repetitive column structure | **Covered** |
| Low-confidence misc | 4 | 1 | Fragment matching rejects (no statements) | **Covered** |
| BBCode | 1 | 0 | `[tag]` ≠ `<tag>`, not matched | **Covered** |
| CSV academic | 1 | 1 | Retype as data (delimiter consistency) | **Covered** |
| Fenced Gaussian log | 1 | — | Fenced = trusted (edge case) | **Accepted** |

**Coverage: 34/35 FPs addressed. 1 accepted edge case.**

---

## 9. Cross-Signal with Secret Detection

### 9.1 Error Output as Credential Leak Vector

Error output blocks are high-value targets for secret detection:

- **Stack traces** leak file paths and internal architecture
- **Connection errors** leak database URLs with credentials
  (`postgresql://admin:s3cret@prod-db:5432/users`)
- **Log output** leaks API calls with auth headers
  (`Authorization: Bearer sk_live_...`)
- **Build output** leaks env vars
  (`ENV GITHUB_TOKEN=ghp_...`)

### 9.2 Integration Point

When `scan_text` (or the browser scanner) operates on a prompt:

1. Run zone detection first
2. For `error_output` zones: elevate secret scanning confidence
   (findings in error output are more likely real credentials, not
   code examples)
3. For `code` zones: reduce FP weight for certain patterns
   (API key shapes in code are often examples, not live credentials)
4. For `natural_language` zones: standard scanning

This cross-signal is an architectural capability, not a v2 requirement.
It becomes actionable when zone detection integrates with the scan_text
pipeline.

---

## 10. Data Structures

### 10.1 ZoneBlock (v2)

```python
@dataclass
class ZoneBlock:
    start_line: int          # 0-indexed inclusive
    end_line: int            # 0-indexed exclusive
    zone_type: str           # one of ZONE_TYPES
    confidence: float        # 0.0-1.0
    method: str              # detection method / pass that produced it
    language_hint: str = ""  # top language (e.g., "python", "c_family")
    language_confidence: float = 0.0  # probability of top language
    text: str = ""           # actual block text (stripped from serialization)
```

### 10.2 PromptZones (unchanged)

```python
@dataclass
class PromptZones:
    prompt_id: str
    total_lines: int
    blocks: list[ZoneBlock]
```

### 10.3 Interface Compatibility

v2 is a drop-in replacement for v1:

```python
def detect_zones(text: str, prompt_id: str = "") -> PromptZones:
    """Same signature, improved internals."""
```

The review tool, run_scan.py, and build_labeled_set.py continue to
work without changes.

---

## 11. Validation Plan

### 11.1 Metrics

| Metric | v1 baseline | v2 target |
|---|---|---|
| Detection accuracy | 90% | ≥90% (maintain) |
| Boundary recall | 70% | ≥85% |
| FP rate (pure FP) | 6.2% (35/564) | <2% |
| FP rate (mistype) | 1.9% (11/564) | <1% |
| Block fragmentation rate | ~2.5x | <1.3x |

### 11.2 Evaluation Method

1. **Re-run on 507+ reviewed corpus.** Compare v2 output against human
   verdicts. Measure all metrics above.

2. **Regression check.** All 510 correct verdicts (212 TP + 298 TN)
   must remain correct. Zero TP regression.

3. **FP audit.** Manually review any new FPs introduced by v2 that
   were not present in v1. Categorize and assess.

4. **Boundary quality.** For the 138 boundary corrections, measure
   how close v2 boundaries are to human-marked boundaries
   (line-level Jaccard similarity).

### 11.3 Performance

v1 processes 3,113 prompts/sec. v2 should remain within 2x of this
(>1,500 prompts/sec). Pass 0 and Pass 2 are O(n) linear scans.
Pass 1 adds neighbor lookups (O(1) per line). Pass 3 parse validation
is selective (only ambiguous blocks). No expected performance concern.

---

## 12. Implementation Sequencing

Recommended build order:

1. **Pass 0 (bracket scan)** — foundation, other passes depend on
   claimed ranges
2. **Pass 1 negative signals** — highest FP reduction per effort
   (error output, dialog, list prefix, math, ratios)
3. **Pass 1 fragment matching** — improves confidence calibration
4. **Pass 1 context window** — smooth local boundaries
5. **Pass 2 block assembly** — bridge gaps, bracket validation,
   repetitive structure test
6. **Pass 3 parse validation** — selective confirmation
7. **Pass 3 language probability** — secondary enrichment

Each step is independently testable against the reviewed corpus.

---

## 13. Open Questions

1. **CRF as future upgrade.** The literature suggests a CRF with
   hand-crafted features would push boundary recall to 90%+. We have
   sufficient training data (507+ reviewed). Should we build the
   rule-based v2 first and evaluate, or go directly to CRF? Current
   recommendation: rule-based v2 first (simpler, faster iteration),
   CRF if boundary recall plateaus below 85%.

2. **Inline code detection.** v2 operates at line level and cannot
   detect inline code within prose (e.g., "use the `requests` library").
   This is a known limitation. Adding character-level detection is a
   separate scope item.

3. **Language disambiguation within C-family.** Low priority but
   useful for downstream consumers. Could add per-language keyword
   sets (Pygments multi-voter pattern) as a future enhancement.

4. **Confidence calibration.** v1 confidence values are heuristic
   (not probability-calibrated). v2 should produce better-calibrated
   scores by combining multiple evidence sources, but true calibration
   requires a held-out evaluation set.

---

## Appendix A: v1 → v2 Change Summary

| Component | v1 | v2 |
|---|---|---|
| Zone types | 7 (no error_output) | 8 (added error_output) |
| Passes | 2 (fenced + unfenced) | 4 (bracket, scoring, assembly, confirmation) |
| Line scoring | Isolated (no context) | 3-line context window |
| Fragment matching | None | 3 syntax families + Tier 2 |
| Negative signals | 4 (math, error, list, prose) | 6 (+ dialog, ratios) |
| Block merging | Break on 3+ zero lines | Bridge blanks + comments, bracket validation |
| Parse validation | JSON only | Python, JSON, C-family, Markup (selective) |
| Language hint | From fence tags only | Fragment-based probability distribution |
| XML detection | Any `<>` presence | Matched open/close tags required |
| FPs covered | n/a | 34/35 known FPs |

## Appendix B: Syntax Family Coverage

| Family | Languages | % of LLM prompts (est.) |
|---|---|---|
| C-family | JS, TS, Java, C, C++, C#, Go | ~50% |
| Python | Python | ~25% |
| Markup | HTML, XML, CSS | ~10% |
| SQL | SQL, GraphQL | ~5% |
| Shell | Bash, sh, zsh, PowerShell | ~5% |
| Assembly | x86, ARM, MIPS | ~1% |
| Rust | Rust | ~2% |
| Other (Ruby, Perl, Haskell, etc.) | Various | ~2% |

Tier 1 (C-family + Python + Markup) covers ~85% of code in prompts.
Adding Tier 2 (SQL, Shell, Assembly, Rust) reaches ~95%.
