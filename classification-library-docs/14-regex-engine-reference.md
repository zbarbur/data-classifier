# Regex Engine — Implementation Reference

**Purpose:** Explains how regex pattern matching works in the classification library, why we chose Google RE2 over Python `re`, the two-phase matching architecture, and performance characteristics. Reference for implementers.

**Decision:** D34 — Google RE2 for Regex Engine.

---

## 1. Two Fundamentally Different Regex Architectures

Every regex engine uses one of two approaches. The choice determines performance, security, and capability.

### Backtracking (Python `re`, Java, JavaScript, Perl, .NET)

The engine tries to match the pattern by exploring possibilities one at a time. When it hits a dead end, it backtracks and tries a different path.

```
Pattern: a.*b.*c
Text:    "aXXXbYYYcZZZ"

Step 1:  Match "a" at position 0.                           ✓
Step 2:  ".*" is greedy — consume EVERYTHING: "XXXbYYYcZZZ"
Step 3:  Try to match "b" — at end of string. No "b".
Step 4:  BACKTRACK — give back one character. Try "XXXbYYYcZZ"
Step 5:  "Z" isn't "b". Backtrack again.
Step 6:  Give back another. Try "XXXbYYYcZ". Still no "b". Backtrack.
...keep backtracking...
Step 10: Try "XXXb". Match "b"!                             ✓
Step 11: ".*" greedy again — consume "YYYcZZZ"
Step 12: Try "c" — at end. Backtrack again.
...more backtracking...
Step 15: Match "c" at position 8.                           ✓ Done.
```

This works. But backtracking can explode exponentially.

### Automaton (RE2, grep, awk)

The engine converts the regex into a state machine (finite automaton). It processes the input character by character. Each character causes exactly one state transition. No backtracking. No branching. No alternative paths to explore.

```
Pattern: a.*b
Text:    "aXXbYbc"

Position 0: 'a' → {start} → {seen_a}
Position 1: 'X' → {seen_a} → {seen_a}         (loop: .* matches any)
Position 2: 'X' → {seen_a} → {seen_a}
Position 3: 'b' → {seen_a} → {seen_a, ACCEPT}  ← match!
Position 4: 'Y' → {seen_a, ACCEPT} → {seen_a}
Position 5: 'b' → {seen_a} → {seen_a, ACCEPT}  ← match!
Position 6: 'c' → {seen_a, ACCEPT} → {seen_a}

7 characters → 7 transitions. Always O(n). Done.
```

---

## 2. Why Backtracking Is Dangerous — ReDoS

The exponential blowup is not theoretical. It's exploitable.

```
Pattern: (a+)+b
Text:    "aaaaaaaaaaaaaaaaaaaaaaac"    (22 a's, then "c" — no "b")

The backtracking engine tries every way to partition the a's:
  [aaaaaaaaaaaaaaaaaaaaaa] + fail
  [aaaaaaaaaaaaaaaaaaaaa][a] + fail
  [aaaaaaaaaaaaaaaaaaaa][aa] + fail
  [aaaaaaaaaaaaaaaaaaaa][a][a] + fail
  [aaaaaaaaaaaaaaaaaaa][aaa] + fail
  [aaaaaaaaaaaaaaaaaaa][aa][a] + fail
  [aaaaaaaaaaaaaaaaaaa][a][aa] + fail
  [aaaaaaaaaaaaaaaaaaa][a][a][a] + fail
  ...

Total paths: 2²² = 4,194,304 for 22 a's.
For 30 a's: 2³⁰ = 1,073,741,824.
For 40 a's: 2⁴⁰ ≈ 1 trillion paths.

A 40-character input can hang the process for minutes or hours.
```

This is ReDoS (Regular Expression Denial of Service). For a prompt gateway accepting arbitrary user input, this is a direct attack vector. An attacker sends a crafted string, the regex engine hangs, and the server becomes unresponsive.

**RE2 on the same input:**

```
Pattern: (a+)+b
Text:    "aaaaaaaaaaaaaaaaaaaaaaac"

RE2: 23 state transitions (one per character). 
Time: microseconds. Always. Regardless of input.
```

RE2 guarantees O(n) time where n is the input length. No exceptions. No pathological cases. This is not an optimization — it's a mathematical property of the automaton approach.

---

## 3. How RE2 Works Internally

### Step 1: Parse regex → AST

```
Pattern: \b\d{3}-\d{2}-\d{4}\b

Parsed to:
  WordBoundary
  Repeat(Digit, 3, 3)
  Literal('-')
  Repeat(Digit, 2, 2)
  Literal('-')
  Repeat(Digit, 4, 4)
  WordBoundary
```

### Step 2: AST → NFA (Nondeterministic Finite Automaton)

The NFA is a state machine that can be in multiple states simultaneously:

```
State 0 ──[\b]──→ State 1
State 1 ──[\d]──→ State 2
State 2 ──[\d]──→ State 3
State 3 ──[\d]──→ State 4
State 4 ──[-]───→ State 5
State 5 ──[\d]──→ State 6
State 6 ──[\d]──→ State 7
State 7 ──[-]───→ State 8
State 8 ──[\d]──→ State 9
State 9 ──[\d]──→ State 10
State 10 ─[\d]──→ State 11
State 11 ─[\d]──→ State 12
State 12 ─[\b]──→ State 13 (ACCEPT)
```

### Step 3: NFA → DFA (Deterministic Finite Automaton)

The NFA can be in multiple states at once (nondeterministic). The DFA converts each unique SET of NFA states into a single DFA state. Now each input character leads to exactly ONE next state:

```
DFA state {0}     ──[\b]──→ {1}
DFA state {1}     ──[\d]──→ {2}
DFA state {1}     ──[^\d]─→ DEAD (no match possible from here)
DFA state {2}     ──[\d]──→ {3}
...
DFA state {12}    ──[\b]──→ {13} = ACCEPT
```

Each input character: look up current state + input → next state. One table lookup. No branching.

### Step 4: Lazy DFA Construction

The full DFA can have an enormous number of states for complex patterns. RE2 doesn't build the entire DFA upfront. It builds states on demand:

```
Start: only build state {0}
See first digit: need transition from {0} on \d — build state {1}, cache it
See second digit: need transition from {1} on \d — build state {2}, cache it
See a letter: need transition from {2} on [a-z] — build DEAD state, cache it
```

DFA states are stored in a hash map. Common paths through the automaton get cached quickly. Rare paths are built lazily. RE2 caps the DFA cache at a configurable size (default ~8MB). If the cache fills up, RE2 falls back to NFA simulation (slower but still linear-time).

---

## 4. RE2 Set Matching — One Scan for All Patterns

This is the key feature for our use case. Instead of running 50 patterns independently, RE2 Set compiles all patterns into a single automaton.

### How it works

```
Pattern 0: SSN       → \d{3}-\d{2}-\d{4}
Pattern 1: Email     → \S+@\S+\.\S+
Pattern 2: AWS key   → AKIA[A-Z0-9]{16}
Pattern 3: JWT       → eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+
...all 50 patterns...
```

**Compilation:** Build one NFA that includes all 50 patterns, with each accepting state tagged by pattern ID:

```
Combined NFA:
  Start → (SSN branch) → Accept[pattern_0]
  Start → (Email branch) → Accept[pattern_1]
  Start → (AWS key branch) → Accept[pattern_2]
  ...
```

Convert to DFA. The DFA states are now sets of NFA states from ALL patterns. A single DFA state might simultaneously be tracking progress in SSN matching, email matching, and JWT matching.

**Matching:** One pass through the text. At each position, the DFA advances one step. If it reaches an accepting state, it records which pattern IDs are satisfied:

```
Text: "Contact john@acme.com, SSN 123-45-6789, key AKIAIOSFODNN7EXAMPLE"

Position 0-7:   tracking progress in email pattern
Position 8:     '@' → email pattern advancing
Position 12-15: Accept[pattern_1] → Email found!
Position 22-26: tracking SSN pattern
Position 27-29: Accept[pattern_0] → SSN found!
Position 36-39: 'AKIA' → AWS key pattern activated
Position 40-55: Accept[pattern_2] → AWS key found!

One scan. Three matches from three different patterns.
```

### Performance

```
Without Set matching:  50 patterns × scan text = 50 passes
With Set matching:     1 combined automaton × scan text = 1 pass

For 10KB text:
  50 individual scans: ~2ms
  1 Set scan:          ~0.3ms (+ literal prefiltering, see below)
```

---

## 5. Literal Prefiltering

Before running the full automaton, RE2 extracts literal substrings from patterns and uses fast string search to quickly eliminate patterns that can't possibly match.

```
Pattern: AKIA[A-Z0-9]{16}
  → RE2 extracts literal prefix: "AKIA"
  → Fast string search (memchr/SIMD) for "AKIA" in text
  → If "AKIA" not found → pattern cannot match → skip entirely

Pattern: eyJ[A-Za-z0-9_-]+\.eyJ
  → RE2 extracts literals: "eyJ" and ".eyJ"
  → Search for both — if either missing, skip

Pattern: \d{3}-\d{2}-\d{4}
  → No useful literal to extract (all character classes)
  → Must run through automaton
```

For a typical prompt:
- 50 patterns total
- ~40 have extractable literals (known prefixes like AKIA, eyJ, PEM headers, specific formats)
- ~35 of those literals are absent from the text
- Only ~15 patterns need automaton processing
- Of those, ~1-3 actually match

This is why RE2 Set screening is so fast — most patterns are eliminated before the DFA even runs.

---

## 6. Our Two-Phase Architecture

### Phase 1: Screening (RE2 Set)

One pass. Identifies WHICH of the 50+ patterns have matches. Returns pattern IDs only, not positions.

```python
import re2

class RegexEngine:
    def __init__(self, patterns: list[PatternConfig]):
        # Build the combined automaton
        self.pattern_set = re2.Set(re2.UNANCHORED)
        self.patterns = {}
        
        for i, p in enumerate(patterns):
            self.pattern_set.Add(p.regex)
            self.patterns[i] = p
        
        self.pattern_set.Compile()  # NFA → DFA, literal extraction
        
        # Also compile individual patterns for Phase 2 extraction
        self.compiled = {
            i: re2.compile(p.regex)
            for i, p in self.patterns.items()
        }
    
    def scan(self, text: str) -> list[Match]:
        # PHASE 1: which patterns match? (ONE pass, C++, releases GIL)
        hit_indices = self.pattern_set.Match(text)
        
        if not hit_indices:
            return []  # no patterns matched — fast exit
        
        # PHASE 2: extract positions (only for matched patterns)
        matches = []
        for idx in hit_indices:
            p = self.patterns[idx]
            for m in self.compiled[idx].finditer(text):
                value = m.group()
                
                # PHASE 3: secondary validation
                if p.validator and not p.validator(value):
                    continue
                
                matches.append(Match(
                    type=p.name,
                    category=p.category,
                    sensitivity=p.sensitivity,
                    value=value,
                    span=(m.start(), m.end()),
                    confidence=p.confidence,
                ))
        
        return matches
```

### Phase 2: Extraction (RE2 per-pattern)

Only for the 1-3 patterns that actually matched. Extract exact positions and captured groups.

### Phase 3: Validation (Python)

Secondary checks that can't be expressed as regex. Tiny Python functions, only called on actual matches (typically <5 per request).

```python
VALIDATORS = {
    "credit_card": luhn_check,      # Luhn checksum algorithm
    "us_ssn": validate_ssn_format,  # No all-zeros groups
    "ipv4": validate_ip_range,      # Each octet 0-255
    "aws_key": validate_aws_format, # Exactly 20 chars after AKIA
    "iban": validate_iban_check,    # Country-specific check digits
}

def luhn_check(number_str: str) -> bool:
    """Luhn algorithm — rejects numbers that look like credit cards but aren't."""
    digits = [int(d) for d in number_str if d.isdigit()]
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0

def validate_ssn_format(ssn: str) -> bool:
    """Reject invalid SSN formats that match the regex pattern."""
    parts = ssn.split('-')
    if len(parts) != 3:
        return False
    area, group, serial = parts
    if area == '000' or group == '00' or serial == '0000':
        return False
    if area == '666' or int(area) >= 900:
        return False
    return True
```

### Performance Breakdown

```
Per request (10KB prompt):

Phase 1 — RE2 Set screening:
  Literal prefilter:     ~0.05ms  (memchr for "AKIA", "eyJ", etc.)
  DFA scan:              ~0.25ms  (one pass, 10K chars, ~15 active patterns)
  Total Phase 1:         ~0.30ms  (C++, releases GIL)

Phase 2 — RE2 extraction:
  1-3 matched patterns:  ~0.05ms  (targeted scan, C++, releases GIL)

Phase 3 — Python validation:
  1-5 matches:           ~0.01ms  (Luhn check, format checks)
  (holds GIL but trivial)

Total:                   ~0.36ms
  Of which C++ (GIL-free): ~0.35ms (97%)
  Of which Python (GIL):   ~0.01ms (3%)
```

Compared to Python `re`:
```
50 × re.finditer():     ~2.0ms   (all holding GIL)
RE2 two-phase:          ~0.36ms  (97% GIL-free)

Speedup: ~6x raw, much more under concurrent load due to GIL difference
```

---

## 7. Pattern Library Design

### Pattern Configuration

Each pattern is a structured object, not just a regex string:

```python
@dataclass
class PatternConfig:
    name: str                    # "us_ssn", "credit_card", "aws_key"
    regex: str                   # the RE2 pattern string
    category: str                # "PII", "PCI", "PHI", "CREDENTIAL", "NETWORK"
    sensitivity: str             # "restricted", "confidential", "internal"
    confidence: float            # 0.7-0.99 — base confidence when pattern matches
    validator: Callable | None   # post-match validation function
    description: str             # human-readable description for reports
    examples: list[str]          # test cases for validation
    false_positive_notes: str    # known FP scenarios for documentation
```

### Built-in Pattern Categories

```
PII (Personally Identifiable Information):
  us_ssn            \b\d{3}-\d{2}-\d{4}\b                     + SSN format validator
  email             [a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}
  phone_us          \b\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b
  phone_intl        \+\d{1,3}[-.\s]?\d{4,14}
  passport_us       \b[A-Z]\d{8}\b                             + length check
  drivers_license   (state-specific patterns)

PCI (Payment Card Industry):
  credit_card       \b(?:\d[ -]*?){13,19}\b                   + Luhn validator
  iban              \b[A-Z]{2}\d{2}[A-Z0-9]{4,30}\b           + check digit validator
  cvv               \b\d{3,4}\b                                (only in context of card data)

PHI (Protected Health Information):
  mrn               (institution-specific patterns)
  dea_number        \b[A-Z][A-Z0-9]\d{7}\b                    + check digit
  npi               \b\d{10}\b                                 + Luhn variant

CREDENTIAL:
  aws_access_key    AKIA[A-Z0-9]{16}                           + length validator
  aws_secret_key    [A-Za-z0-9/+=]{40}                         (only near aws_access_key)
  github_token      ghp_[A-Za-z0-9]{36}
  github_fine       github_pat_[A-Za-z0-9]{22}_[A-Za-z0-9]{59}
  openai_key        sk-[A-Za-z0-9]{48}
  jwt               eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+
  pem_private_key   -----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----
  connection_string (provider-specific patterns)
  basic_auth        \bBasic\s+[A-Za-z0-9+/=]{10,}\b

NETWORK:
  ipv4              \b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b   + octet range validator
  ipv6              (standard IPv6 patterns including compressed)
  mac_address       \b([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b
  url_with_creds    https?://[^:]+:[^@]+@                      (credentials in URL)
```

### Consumer-Extensible Patterns

Consumers add custom patterns at initialization:

```python
engine = RegexEngine(
    patterns=BUILT_IN_PATTERNS + [
        PatternConfig(
            name="employee_id",
            regex=r"EMP-\d{6}",
            category="PII",
            sensitivity="confidential",
            confidence=0.95,
            validator=None,
            description="Internal employee ID format",
        ),
        PatternConfig(
            name="internal_project_code",
            regex=r"PRJ-[A-Z]{3}-\d{4}",
            category="INTERNAL",
            sensitivity="internal",
            confidence=0.90,
            validator=None,
            description="Project code format",
        ),
    ]
)
```

Custom patterns are compiled into the RE2 Set alongside built-in patterns — same single-pass performance regardless of how many patterns are added.

---

## 8. RE2 Limitations and Workarounds

RE2 guarantees linear time by rejecting certain regex features that require backtracking:

| Feature | Example | Supported? | Workaround |
|---------|---------|:----------:|-----------|
| Basic matching | `abc`, `\d+`, `[a-z]` | ✅ | — |
| Alternation | `cat\|dog` | ✅ | — |
| Repetition | `a{3,5}`, `a+?` | ✅ | — |
| Character classes | `[A-Z0-9]`, `\w`, `\s` | ✅ | — |
| Anchors | `^`, `$`, `\b` | ✅ | — |
| Capture groups | `(\d{3})-(\d{2})` | ✅ | — |
| Non-greedy | `.*?` | ✅ | — |
| Named groups | `(?P<area>\d{3})` | ✅ | — |
| Backreferences | `(abc)\1` | ❌ | Not needed for our patterns |
| Lookahead | `(?=abc)`, `(?!abc)` | ❌ | Restructure pattern or post-filter |
| Lookbehind | `(?<=abc)`, `(?<!abc)` | ❌ | Capture more, trim in validator |
| Possessive quantifiers | `a++` | ❌ | Not needed (no backtracking anyway) |
| Atomic groups | `(?>abc)` | ❌ | Not needed (no backtracking anyway) |
| Conditional | `(?(1)yes\|no)` | ❌ | Split into two patterns |

**For our 50+ pattern library:** None require backreferences or lookahead. All patterns are expressible in RE2 syntax. If a future pattern requires lookahead:

```python
# Special case: run one pattern with Python re (backtracking)
# while all others use RE2 (safe)
class RegexEngine:
    def __init__(self, patterns):
        self.re2_patterns = []     # 49 patterns → RE2 Set
        self.python_patterns = []  # 1 pattern → Python re (isolated)
        
        for p in patterns:
            if p.requires_backtracking:
                self.python_patterns.append(p)
            else:
                self.re2_patterns.append(p)
```

---

## 9. Memory and Startup

### Compiled Pattern Memory

```
50 built-in patterns:
  RE2 Set compiled program:  ~200KB (NFA + prefilter data)
  Individual compiled patterns: ~100KB (for Phase 2 extraction)
  Pattern metadata:          ~50KB (names, validators, configs)
  Total:                     ~350KB

With customer custom patterns (additional 20):
  Total:                     ~500KB
```

### Startup Time

```
First startup (compile from scratch):
  Parse 50 patterns:         ~1ms
  Build NFA:                 ~2ms
  Compile RE2 Set:           ~5ms
  Compile individual patterns: ~3ms
  Total:                     ~11ms

Subsequent startups (if serialized):
  Load compiled program:     ~1ms (memory-mapped)
```

### Worker Memory Sharing

When running multiple uvicorn workers, the compiled RE2 program can be shared via memory mapping. Each worker process maps the same read-only compiled program:

```
8 workers × 350KB = 2.8MB  (without sharing)
1 shared mmap × 350KB = 350KB + tiny per-worker overhead  (with sharing)
```

---

## 10. Future Option: Intel Hyperscan

If regex matching becomes a throughput bottleneck (>10,000 requests/second), Hyperscan provides the next level of performance.

**What Hyperscan does differently:**

RE2 uses a lazy DFA — builds states on demand, one at a time. Hyperscan pre-compiles ALL patterns into a fully materialized DFA and uses SIMD (Single Instruction Multiple Data) CPU instructions to process multiple bytes per clock cycle:

```
RE2:       process 1 byte per step → ~1 byte/nanosecond
Hyperscan: process 8-16 bytes per SIMD step → ~8-16 bytes/nanosecond
```

**Performance comparison:**

```
50 patterns, 10KB input:
  Python re:   ~2.0ms    (50 passes, backtracking risk, holds GIL)
  Google RE2:  ~0.3ms    (1 set scan + extraction, releases GIL)
  Hyperscan:   ~0.05ms   (1 SIMD scan, releases GIL)
```

**Tradeoffs vs RE2:**

| Aspect | RE2 | Hyperscan |
|--------|-----|-----------|
| Install | `pip install google-re2` | `pip install hyperscan` + `apt install libhyperscan-dev` |
| System dependency | None | libhs C library (must be installed on host) |
| Docker image | No change | Needs libhs in image (~5MB) |
| Pattern changes | Recompile Set at startup (~5ms) | Recompile database (~50ms) |
| Memory | ~350KB lazy | ~2MB fully materialized DFA |
| Capture groups | Supported | Not supported (reports start/end only) |

**When to switch:** Only if profiling shows regex is >10% of request latency at target throughput. For most deployments, RE2 is more than fast enough and simpler to deploy.

---

## 11. Relationship to Other Engines

The regex engine is one of several detection engines in the fast tier. Understanding how they complement each other:

```
Regex Engine:
  Catches: formatted patterns (SSN, credit card, JWT, AWS key, email)
  Misses:  unformatted secrets (DB_PASSWORD=xyz), entity names, context-dependent PII

Structured Secret Scanner:
  Catches: key-value secrets in parsed structures (JSON, YAML, env, code)
  Misses:  secrets in free text, formatted patterns (those go to regex first)

PII Base NER:
  Catches: entity names, medical terms, addresses — no consistent format
  Misses:  structured patterns (SSN better caught by regex than NER)

Cloud DLP:
  Catches: Google's 150+ InfoTypes with ML-backed detection
  Misses:  custom patterns, offline deployments
```

The engines are complementary, not competitive. Regex runs first (<0.5ms) and catches everything with a known format. Remaining text goes to other engines for what regex can't catch.

---

## Decision Log

**D34: Google RE2 for Regex Engine (Decided)**

Use Google RE2 instead of Python `re` for pattern matching. Two-phase matching: RE2 Set for single-pass screening, then targeted extraction for matched patterns only. Secondary Python validators for post-match checks (Luhn, format verification).

Three requirements met simultaneously:
1. **Security** — linear-time guarantee prevents ReDoS on prompt gateway
2. **Performance** — single-pass set matching vs 50 separate scans
3. **Concurrency** — C++ backend releases GIL, enables multi-threaded parallelism

Intel Hyperscan as future option if >10K requests/second needed.
