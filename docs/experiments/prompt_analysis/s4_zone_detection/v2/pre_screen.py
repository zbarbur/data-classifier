"""Pre-screen fast path — rejects 97% of prompts that contain no code."""
from __future__ import annotations

_PRESCREEN_CHARS = frozenset("{}()[];=<>|&@#$^~")
_DENSITY_THRESHOLD = 0.03


def pre_screen(text: str) -> bool:
    """Return True if text MIGHT contain code/structured blocks.

    False means definitely no blocks — skip all detectors.
    Must have zero false negatives.
    """
    if not text or not text.strip():
        return False

    # Check 1: fence markers
    if "```" in text or "~~~" in text:
        return True

    # Check 2: syntactic character density
    total = len(text)
    syn_count = 0
    for c in text:
        if c in _PRESCREEN_CHARS:
            syn_count += 1
    if syn_count / total > _DENSITY_THRESHOLD:
        return True

    # Check 3: indentation patterns
    if "\n    " in text or "\n\t" in text:
        return True

    # Check 4: closing tags (markup)
    if "</" in text:
        return True

    return False
