"""Lightweight tokenizer for line-level token profiling.

Produces per-line token profiles (identifier_ratio, string_ratio,
operator_count, dot_access_count) used by SyntaxDetector for semantic
scoring.  Not a full lexer — regex-based extraction of discriminative
features that separate code from prose and data.

Key insight: code has identifiers + operators + dot_access.
Prose has identifiers but no operators or dot_access.
Data has strings/numbers but few identifiers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- Token extraction regexes ---
_STRING_RE = re.compile(r'(?:"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`(?:[^`\\]|\\.)*`)')
_NUMBER_RE = re.compile(r"\b(?:0[xX][0-9a-fA-F]+|\d+\.?\d*(?:[eE][+-]?\d+)?)\b")
_IDENT_RE = re.compile(r"\b[a-zA-Z_]\w*\b")
_OPERATOR_RE = re.compile(r"[=<>!+\-*/%&|^~]+")
_DELIMITER_RE = re.compile(r"[(){}\[\],;:]")
_DOT_ACCESS_RE = re.compile(r"\w\.\w")

_PLACEHOLDER = " __S__ "


@dataclass
class TokenProfile:
    """Token distribution summary for a single line."""

    identifier_count: int = 0
    identifier_ratio: float = 0.0
    keyword_count: int = 0
    operator_count: int = 0
    delimiter_count: int = 0
    string_count: int = 0
    string_ratio: float = 0.0
    number_count: int = 0
    dot_access_count: int = 0
    total_tokens: int = 0


def tokenize_line(line: str, keywords: frozenset[str] | None = None) -> TokenProfile:
    """Produce a TokenProfile for *line*.

    Parameters
    ----------
    line:
        Raw source line (may include leading whitespace).
    keywords:
        Optional set of language keywords.  Matching identifiers are
        counted as keywords instead of identifiers.
    """
    stripped = line.strip()
    if not stripped:
        return TokenProfile()

    # 1. Extract and remove string literals so their contents don't
    #    interfere with identifier/operator/number extraction.
    strings = _STRING_RE.findall(stripped)
    no_strings = _STRING_RE.sub(_PLACEHOLDER, stripped)

    # 2. Dot access on the string-free text (word.word pattern).
    dot_accesses = _DOT_ACCESS_RE.findall(no_strings)

    # 3. Numbers (extract before identifiers so 0xFF doesn't leave stray
    #    letters that look like identifiers).
    numbers = _NUMBER_RE.findall(no_strings)
    no_nums = _NUMBER_RE.sub(" ", no_strings)

    # 4. Identifiers (skip our placeholder token).
    raw_idents = [m for m in _IDENT_RE.findall(no_nums) if m != "__S__"]

    # 5. Operators and delimiters.
    operators = _OPERATOR_RE.findall(no_strings)
    delimiters = _DELIMITER_RE.findall(no_strings)

    # 6. Separate keywords from identifiers.
    kw_count = 0
    ident_count = len(raw_idents)
    if keywords:
        for ident in raw_idents:
            if ident in keywords:
                kw_count += 1
                ident_count -= 1

    total = ident_count + kw_count + len(strings) + len(numbers) + len(operators) + len(delimiters)

    return TokenProfile(
        identifier_count=ident_count,
        identifier_ratio=ident_count / total if total > 0 else 0.0,
        keyword_count=kw_count,
        operator_count=len(operators),
        delimiter_count=len(delimiters),
        string_count=len(strings),
        string_ratio=len(strings) / total if total > 0 else 0.0,
        number_count=len(numbers),
        dot_access_count=len(dot_accesses),
        total_tokens=total,
    )
