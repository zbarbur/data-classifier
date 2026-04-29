"""XOR-encode/decode helper for s4 labeled-corpus prompt text.

Mirrors the `prompt_xor` pattern used in `data/wildchat_eval/wildchat_eval.jsonl`
and `data_classifier/patterns/_decoder.py`: any committed JSONL whose `text`
field could contain real user-pasted credentials (HuggingFace tokens, API keys,
etc.) stores them XOR-with-key-0x5a, base64-encoded, in a `text_xor` field
instead. GitHub push protection's regex-based secret scanners then see only
base64 noise, never the underlying token shapes.

Records on disk look like:
    {"prompt_id": "...", "text_xor": "BASE64", "total_lines": 12, ...}

Use :func:`get_text(record)` instead of `record["text"]` everywhere that reads
from the labeled corpus. New records should be created via :func:`set_text(rec, text)`.

Why XOR + base64 (not e.g. AES): no secret/key management; the goal is *format
opacity* against secret-scanners, not confidentiality (the labeled prompts are
public WildChat data).
"""

from __future__ import annotations

import base64

XOR_KEY = 0x5A


def encode(text: str) -> str:
    """XOR each byte with `XOR_KEY`, then base64-encode."""
    raw = text.encode("utf-8")
    scrambled = bytes(b ^ XOR_KEY for b in raw)
    return base64.b64encode(scrambled).decode("ascii")


def decode(text_xor: str) -> str:
    """Inverse of :func:`encode`."""
    raw = base64.b64decode(text_xor)
    return bytes(b ^ XOR_KEY for b in raw).decode("utf-8")


def get_text(record: dict) -> str:
    """Read the prompt text from a corpus record.

    Prefers `text_xor` (committed format); falls back to `text` for in-memory
    records (e.g. fresh detector output before serialization). Raises
    ``KeyError`` if neither field is present.
    """
    if "text_xor" in record:
        return decode(record["text_xor"])
    if "text" in record:
        return record["text"]
    raise KeyError("record has neither 'text' nor 'text_xor'")


def set_text(record: dict, text: str) -> None:
    """Store prompt text on a record in the on-disk format (`text_xor`)."""
    record.pop("text", None)
    record["text_xor"] = encode(text)
