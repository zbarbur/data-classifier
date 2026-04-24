"""Block-level code construct validator.

Scans a candidate block for recognizable programming constructs
(function definitions, assignments, imports, control flow with
structural tokens, method chains, decorators).  Returns an evidence
count that the assembler uses to adjust confidence:

    0 constructs → block is not code → suppress
    1 construct  → borderline → no adjustment
    2+ constructs → definitely code → boost

This catches false positives that pass per-line scoring (e.g.
Midjourney templates with ``[N] = description`` patterns, structured
lists with colons) AND boosts true positives that have weak per-line
scores (e.g. short Verilog/C blocks without our keyword list).
"""

from __future__ import annotations

import re

# --- Construct patterns ---
# Each pattern detects a recognizable code construct.
# Ordered by reliability (lowest FP risk first).

# 1. Function / method definitions
#    def foo(  /  function bar(  /  func baz(  /  fn qux(
_FUNC_DEF_RE = re.compile(
    r"^\s*(?:def|function|func|fn|sub)\s+[a-zA-Z_]\w*\s*\(", re.MULTILINE
)

# 2. Variable assignment: identifier = value (not [N] = or label: )
#    x = 1  /  result = process(data)  /  self.x = y
_ASSIGNMENT_RE = re.compile(
    r"^\s*[a-zA-Z_]\w*(?:\.\w+)*\s*(?::?\s*\w+\s*)?=(?!=)\s*\S", re.MULTILINE
)

# 3. Import / include / require / using / package
#    import json  /  from x import y  /  #include <stdio.h>
_IMPORT_RE = re.compile(
    r"^\s*(?:import|from|#include|require|using|package)\s+[\w\"'<{./]", re.MULTILINE
)

# 4. Class / struct / enum / interface / trait definitions
#    class Foo:  /  struct Bar {  /  enum Baz {
_CLASS_DEF_RE = re.compile(
    r"^\s*(?:class|struct|enum|interface|trait)\s+[A-Za-z_]\w*\s*[\(\{:<]", re.MULTILINE
)

# 5. Control flow with structural followers
#    if (  /  for (  /  while (  /  else {  /  elif x:  /  } else {
_CONTROL_FLOW_RE = re.compile(
    r"^\s*(?:if|else\s*if|elif|for|while|switch|match)\s*[\(\{]", re.MULTILINE
)

# 6. Method chain: identifier.identifier(
#    obj.method(  /  self.process(  /  response.json(
_METHOD_CHAIN_RE = re.compile(
    r"\b[a-zA-Z_]\w*\.[a-zA-Z_]\w*\s*\("
)

# 7. Decorator / annotation: @symbol at line start
#    @app.route  /  @Override  /  @dataclass
_DECORATOR_RE = re.compile(
    r"^\s*@[a-zA-Z_]\w*", re.MULTILINE
)

# 8. Preprocessor directives
#    #define  /  #ifdef  /  #pragma
_PREPROCESSOR_RE = re.compile(
    r"^\s*#(?:define|ifdef|ifndef|endif|pragma|import)\s", re.MULTILINE
)

# 9. Return / raise / throw / yield at line start with value or semicolon
#    return x  /  raise ValueError  /  throw new Error  /  yield data
_RETURN_RE = re.compile(
    r"^\s*(?:return|raise|throw|yield)\s+\S", re.MULTILINE
)

# 10. Statement-ending semicolons (strong C-family signal)
#     x = 1;  /  console.log(x);
_SEMICOLON_STMT_RE = re.compile(
    r"\S.*;\s*$", re.MULTILINE
)

# 11. Bare function call: ident( — no space between name and paren
#     dict(set())  /  process(data)  /  smr_init()
#     Prose uses space: "called (Midjourney)" → no match
#     LaTeX excluded: \left( → no match (negative lookbehind for \)
_FUNC_CALL_RE = re.compile(
    r"(?<!\\)\b[a-zA-Z_]\w*\("
)

# 12. SQL statements: two SQL keywords together (low FP risk)
#     CREATE TABLE  /  SELECT ... FROM  /  INSERT INTO  /  ALTER TABLE
_SQL_RE = re.compile(
    r"^\s*(?:CREATE\s+TABLE|SELECT\s+.+\s+FROM\s|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|ALTER\s+TABLE|DROP\s+TABLE)",
    re.MULTILINE | re.IGNORECASE,
)

# 13. R / Julia assignment: identifier <- value
#     x <- 5  /  result <- compute(data)
_R_ASSIGNMENT_RE = re.compile(
    r"^\s*[a-zA-Z_][\w.]*\s*<-\s*\S", re.MULTILINE
)

_ALL_PATTERNS = [
    _FUNC_DEF_RE,
    _ASSIGNMENT_RE,
    _IMPORT_RE,
    _CLASS_DEF_RE,
    _CONTROL_FLOW_RE,
    _METHOD_CHAIN_RE,
    _DECORATOR_RE,
    _PREPROCESSOR_RE,
    _RETURN_RE,
    _SEMICOLON_STMT_RE,
    _FUNC_CALL_RE,
    _SQL_RE,
    _R_ASSIGNMENT_RE,
]

# --- Math / LaTeX negative indicators ---
# These signal that a block contains mathematical notation, not code.
# Used to suppress blocks with weak code evidence (≤2 constructs)
# that are really math/academic text.

# LaTeX commands: \frac, \left, \cdot, \sum, etc.
_LATEX_CMD_RE = re.compile(
    r"\\(?:left|right|frac|cdot|sum|int|sqrt|begin|end|text|mathbb|infty|partial|nabla)\b"
)

# Unicode math symbols (Greek letters used as variables, operators, etc.)
_UNICODE_MATH_RE = re.compile(
    r"[∑∏∫∂∇λΔΣΩπμθαβγδεζηξρστφχψω≈≠≤≥±∓∈∉⊂⊃∪∩∞⟹]"
)


def count_code_constructs(block_text: str) -> int:
    """Count distinct code construct types found in *block_text*.

    Each pattern is counted at most once (we care about construct
    diversity, not repetition).  Returns 0-13.
    """
    count = 0
    for pattern in _ALL_PATTERNS:
        if pattern.search(block_text):
            count += 1
    return count


def has_math_notation(block_text: str) -> bool:
    """Return True if the block contains LaTeX commands or Unicode math symbols."""
    return bool(_LATEX_CMD_RE.search(block_text) or _UNICODE_MATH_RE.search(block_text))
