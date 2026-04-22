"""M4d Phase 2 — router-labeler for the multi-label LLM oracle.

Phase 1 (``llm_labeler.py``) hit a 0.7544 macro Jaccard plateau on the 50-row
heterogeneous gold set. The per-shape breakdown revealed that:

  * ``structured_single`` (n=11): Jaccard 1.000 under v1 — perfect.
  * ``opaque_tokens``     (n= 4): Jaccard 1.000 under v1 — perfect.
  * ``free_text_heterogeneous`` (n=35): Jaccard 0.649 — 20/35 below 0.8,
    ~85% of errors are over-firing (FP EMAIL / ADDRESS / PERSON_NAME /
    FINANCIAL / BANK_ACCOUNT / CREDENTIAL / SWIFT_BIC).

Phase 2 routes each column to a branch-specific system prompt using the
gold-set ``true_shape`` field. The structured_single and opaque_tokens
branches preserve Phase 1 v1 verbatim (don't break what's working). The
heterogeneous branch ships a precision-focused rewrite targeting the
observed failure modes.

This module reuses Phase 1's infrastructure (``LabelerCall``,
``LabelResponse``, ``build_user_message``, ``label_column``, allowed-entity
set) — only the system-prompt builder is new. Research-only; lives under
``tests/benchmarks/meta_classifier/`` per the research/production contract.

Requires the ``research-llm`` extras group::

    pip install -e ".[research-llm]"

Expects ``ANTHROPIC_API_KEY`` in the environment.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Literal

import anthropic

from data_classifier.patterns._decoder import decode_encoded_strings
from tests.benchmarks.meta_classifier.llm_labeler import (
    ALLOWED_ENTITIES,
    GOLD_SET_PATH,
    LabelerCall,
    label_column,
)

log = logging.getLogger(__name__)

ShapeName = Literal["structured_single", "free_text_heterogeneous", "opaque_tokens"]

VALID_SHAPES: tuple[ShapeName, ...] = (
    "structured_single",
    "free_text_heterogeneous",
    "opaque_tokens",
)


# ═══════════════════════════════════════════════════════════════════════════
# M4f-d1 — opaque-column decoder stage
# ═══════════════════════════════════════════════════════════════════════════
#
# Base64 is a reversible encoding, not secrecy. Columns routed to the
# opaque-tokens branch whose values are base64 envelopes around
# structured content (JSON payloads, plaintext, JWT-style objects) must
# be decoded before detection runs — otherwise the structurally-correct
# label (OPAQUE_SECRET) hides semantically-sensitive inner content
# (EMAIL, PHONE, etc.) and corrupts the OPAQUE_SECRET class by mixing
# decodable-with-structure into what should be the high-entropy
# residual category.
#
# This stage fires BEFORE the labeler on any opaque-tokens column.
# Shape-specific opaque (ETH 0x+40hex, BTC 64-hex, other
# hash-like) falls through to the existing OPAQUE_SECRET path — their
# bytes don't base64-decode to meaningful text.
#
# ═══════════════════════════════════════════════════════════════════════════


def try_decode_opaque_column(
    values: list[str],
    min_success_rate: float = 0.8,
    min_printable_rate: float = 0.9,
) -> tuple[list[str], ShapeName] | None:
    """Attempt base64 decoding on an opaque-tokens column.

    If ``min_success_rate`` of values decode to printable UTF-8, returns
    ``(decoded_values, recommended_shape)`` — values that individually
    failed to decode pass through in the returned list so the column's
    length is preserved. Otherwise returns ``None`` (column stays
    opaque-tokens).

    The recommended shape is always ``free_text_heterogeneous``:
    decoded base64 is typically JSON / free text with mixed entities,
    so the heterogeneous branch's multi-entity prompt is the right fit.

    ``min_printable_rate`` filters byte sequences that happen to be
    valid UTF-8 but aren't readable (control chars dominating). 0.9 is
    deliberately strict — a JWT payload is ~99% printable; random
    bytes that happen to form valid UTF-8 are far below that.
    """
    if not values:
        return None
    decoded: list[str] = []
    successes = 0
    for v in values:
        try:
            # Tolerate missing padding — base64 output strings are occasionally
            # stripped of trailing '=' by producers. validate=True rejects
            # non-base64 characters (catches hex, plain text, etc.).
            padding = (4 - len(v) % 4) % 4
            raw = base64.b64decode(v + "=" * padding, validate=True)
            text = raw.decode("utf-8", errors="strict")
        except (ValueError, UnicodeDecodeError, base64.binascii.Error):
            decoded.append(v)
            continue
        if not text:
            decoded.append(v)
            continue
        printable = sum(1 for c in text if c.isprintable() or c in "\n\t ")
        if printable / len(text) < min_printable_rate:
            decoded.append(v)
            continue
        decoded.append(text)
        successes += 1
    if successes / len(values) >= min_success_rate:
        return decoded, "free_text_heterogeneous"
    return None


# ═══════════════════════════════════════════════════════════════════════════
# USER CONTRIBUTION — PER-BRANCH LABELER INSTRUCTIONS
# ═══════════════════════════════════════════════════════════════════════════
#
# Three instruction blocks, one per Sprint 13 router branch. The structure
# of each block is identical to Phase 1's ``LABELER_INSTRUCTIONS`` — the
# system-prompt builder appends the allowed-entity enum, few-shot examples,
# and schema anchor after whichever block is selected.
#
# STRUCTURED_SINGLE and OPAQUE_TOKENS are held verbatim at Phase 1 v1 —
# both branches scored 1.000 Jaccard. Any rewrite here carries regression
# risk with zero upside. Edit only if Phase 2 measurement shows a previously-
# perfect row has flipped.
#
# HETEROGENEOUS_INSTRUCTIONS is the Phase 2 experimental variable. The rules
# below target the specific over-firing patterns observed in Phase 1:
#   * SO bio (10 cols, 0.583 Jaccard) — FP EMAIL / ADDRESS / PERSON_NAME
#   * CFPB narrative (15 cols, 0.600 Jaccard) — FP FINANCIAL; FN URL on bare-domain hits
#   * Sprint 12 log (5 cols, 0.764 Jaccard) — FP BANK_ACCOUNT / CREDENTIAL / SWIFT_BIC / ADDRESS
#   * HN comment (5 cols, 0.813 Jaccard) — FP PERSON_NAME on handle text
#
# ═══════════════════════════════════════════════════════════════════════════

# Phase 1 v1 verbatim — perfect on all 11 structured_single gold rows.
STRUCTURED_SINGLE_INSTRUCTIONS = """
Label this database column with every PII entity type that appears in at
least one sample value. Use entity names exactly from the allowed list
below — never invent new types or use subcomponents (use EMAIL, not
DOMAIN or LOCAL_PART).

Rules:
1. Prevalence floor is 1 — if a single value carries a confident entity,
   include that label. One SSN in 100 chat rows still yields SSN.
2. One label per value; the column's label list is the union across values.
   If a value could be two types, pick the primary one.
3. Return an empty list [] when no sample value carries real PII. CFPB
   narratives redacted to XXXX are the canonical empty case — XXXX is
   not evidence of a present entity.
4. Skip placeholders and weak signals unless surrounding values establish
   them as real: admin, password123, test, 0.0.0.0, 127.0.0.1,
   example.com, foo@example.com.
5. Label DATE_OF_BIRTH only when the date is explicitly a birth date
   (dob=1985-03-17). Generic timestamps are not DOB.
6. Base64-like payloads without semantic context are OPAQUE_SECRET, not
   API_KEY. Government IDs require visible shape match (SSN = 9 digits in
   XXX-XX-XXXX form), not just plausible length.

When genuinely uncertain, leave the label out — under-labeling is
recoverable, over-labeling skews downstream Jaccard.
""".strip()


# Post-M4f-d1 (2026-04-21): the "do NOT base64-decode" guardrail was
# removed. Decodable base64 is now handled upstream by
# ``try_decode_opaque_column`` — any column that reaches this branch is
# either shape-specific opaque (blockchain addresses, hashes) or
# high-entropy bytes that failed to decode. Treat what you receive at
# face value.
OPAQUE_TOKENS_INSTRUCTIONS = (
    STRUCTURED_SINGLE_INSTRUCTIONS
    + "\n\n"
    + """Surface-form branch: by the time values arrive here, upstream decoding
has already been attempted. Any base64-wrapped structured content
(JWT-style ``eyJ...`` payloads decoding to JSON, base64-wrapped plain
text, etc.) was decoded and re-routed away from this branch before the
call. What you see here is either:

  * Hex-prefixed values (``0x...``) matching a blockchain address shape:
    label ``ETHEREUM_ADDRESS`` / ``BITCOIN_ADDRESS`` / etc. as
    applicable.
  * Plain hex, hashes, or high-entropy base64 that failed upstream
    decode (e.g., random session tokens, cryptographic hashes, opaque
    identifiers): label ``OPAQUE_SECRET``.

``OPAQUE_SECRET`` is the high-entropy residual class — reserved for
values with no recoverable internal structure. Do not emit it for
values that carry a shape-specific label.""".strip()
)


# Phase 2 rewrite — precision-focused for the 35 heterogeneous rows.
HETEROGENEOUS_INSTRUCTIONS = """
This column contains free-text values from user-generated content (bios,
chat, support narratives), log streams, or mixed-schema records. Multiple
entity types may coexist in one column. Precision matters more than
recall here — Phase 1 analysis showed that over-labeling was the dominant
failure mode on free-text columns.

Use entity names exactly from the allowed list below — never invent new
types or use subcomponents (use EMAIL, not DOMAIN or LOCAL_PART).

Hard precision rules (follow strictly):

EMAIL — only when a value contains an actual email-shaped literal
(``name@domain.tld`` or ``name@sub.domain.tld``). Paraphrases of how to
reach someone ("contact me at...", "DM me", "email me"), intent hints
without a literal address, and placeholders (``example.com`` addresses,
``test@test``, ``foo@bar``) are NOT EMAIL.

PERSON_NAME — only when a value contains a full first+last name as a
real reference to a person ("I'm Tracy Wilson", "spoke with John Smith").
Usernames, SO / Twitter / GitHub handles, single first names
("alice", "bob123", "kenliu"), company names, product names, and
log-identifier name-like strings (e.g., apache access-log user fields
like ``- alice -``) are NOT PERSON_NAME.

ADDRESS — only for explicit geographic specificity beyond a country or
vague region. Full street address, city+state ("Houston, TX"), or full
postal address qualifies. Bio mentions like "I'm from Boston", "work in
SF", "based in Europe", "California dev" do NOT qualify — these are
biographical context, not address data.

Redaction carve-out for ADDRESS specifically: redaction placeholders
combined with a surviving bare state code (``XXXX, NY``,
``XXXX XXXX, MI``, ``at XXXX NJ``) do NOT qualify. The redacted
portion is not evidence of the pre-redaction entity (per the general
redaction-handling rule below), and the surviving state alone is
biographical context per the rule above. An entire column of narratives
using this ``XXXX, <STATE>`` pattern is correctly labeled ``[]`` even
though the pre-redaction content was likely an address. This is the
dominant CFPB complaint pattern and must stay unlabeled.

URL — label when a value contains an ``http(s)://`` URL OR a bare domain
embedded in narrative text. Bare-domain examples that DO qualify:
``Loanme.com``, ``Xoom.com``, ``github.com/user/repo``,
``example.co.uk/path``, ``carfinance.com``. Relative paths
("/api/users", "/login"), filesystem paths, and shell paths do NOT
qualify. When in doubt about a bare domain, lean toward labeling it.

FINANCIAL — do NOT label for narrative money mentions, loan amounts,
currency figures, or redacted money placeholders ("paid $500",
"{$500.00}", "10K loan", "$20000 balance"). FINANCIAL is an
account-identifier category; use IBAN / SWIFT_BIC / ABA_ROUTING /
BANK_ACCOUNT for specific account numbers and leave narrative monetary
mentions unlabeled.

BANK_ACCOUNT / CREDENTIAL / SWIFT_BIC — require structural shape match,
not keyword proximity. A string near "account:" that isn't a bank
account number structure is NOT BANK_ACCOUNT. A value like
"password123" or "admin" or "secret" is NOT CREDENTIAL — real
credentials have entropy AND a provider-shape anchor (e.g.,
``sk_live_``, ``ghp_``, ``AKIA``, long base64 payloads). IBAN-like
runs of alphanumerics that don't validate as IBAN should NOT be
SWIFT_BIC.

DATE_OF_BIRTH — only when a date is marked as a birth date (``dob=...``,
"born on ...", "birthday: ..."). Transaction dates, post dates, log
timestamps, and redacted dates (``XX/XX/XXXX``) are NOT DOB.

Redaction handling: ``XXXX`` / ``XX/XX/XXXX`` / ``{$...}`` placeholders
are evidence of a REDACTED entity — do NOT label the redacted entity on
the basis of the placeholder alone. An entire column of XXXX-redacted
narratives is correctly labeled ``[]``. Entities that survive redaction
in other values of the same column DO count at the column level.

Prevalence floor is 1 — one value carrying a confident entity that
passes the rules above yields that label at the column level. When
genuinely uncertain, leave the label out. Under-labeling is recoverable;
over-labeling dominates Jaccard loss on free-text columns.
""".strip()


# ═══════════════════════════════════════════════════════════════════════════
# USER CONTRIBUTION — PER-BRANCH FEW-SHOT EXAMPLES
# ═══════════════════════════════════════════════════════════════════════════
#
# Phase 1 mixed three shapes in one example list — fine for a generic
# prompt, but when routing we want each branch to see canonical examples
# from its own shape. Each tuple below ships with its branch's system
# prompt.
#
# Keep examples short — they're part of every API call's input, and the
# combined instructions + examples should stay well under the 4096-token
# cacheable-prefix target for Opus 4.7 to benefit from prompt caching.
#
# ═══════════════════════════════════════════════════════════════════════════

STRUCTURED_SINGLE_FEW_SHOT: tuple[dict[str, Any], ...] = (
    {
        "description": "Structured single-label column (employee emails)",
        "values": [
            "alice.chen@example.com",
            "bob.smith@example.com",
            "carol.wu@example.com",
        ],
        "labels": ["EMAIL"],
    },
    {
        "description": "Structured single-label column (city+state addresses)",
        "values": [
            "Austin, TX",
            "Houston, TX",
            "San Francisco, CA",
            "Brooklyn, NY",
        ],
        "labels": ["ADDRESS"],
    },
)


OPAQUE_TOKENS_FEW_SHOT: tuple[dict[str, Any], ...] = (
    {
        "description": "Opaque high-entropy tokens (likely base64-encoded secrets)",
        "values": [
            "aGVsbG8gd29ybGQgdGhpcyBpcyBhIHNlY3JldA==",
            "dGVzdCBwYXlsb2FkIHdpdGggbm8gY29udGV4dA==",
            "c29tZSBvdGhlciByYW5kb20gc3RyaW5n",
        ],
        "labels": ["OPAQUE_SECRET"],
    },
    {
        "description": "Opaque hex tokens (blockchain addresses)",
        "values": [
            "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0",
            "0x8626f6940E2eb28930eFb4CeF49B2d1F2C9C1199",
            "0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B",
        ],
        "labels": ["ETHEREUM_ADDRESS"],
    },
)


HETEROGENEOUS_FEW_SHOT: tuple[dict[str, Any], ...] = (
    {
        "description": "User bio — STRICT on PERSON_NAME / EMAIL / ADDRESS (handles are not names)",
        "values": [
            "<p>Hi I'm alice, a backend dev. Python/Go/Rust. I tweet at @aliceg.</p>",
            "<p>Full-stack developer. React, Django, Postgres. Based in the US.</p>",
            "<p>I'm Tracy Wilson, senior engineer at Acme Corp. Github: https://github.com/twilson.</p>",
        ],
        "labels": ["PERSON_NAME", "URL"],
    },
    {
        "description": (
            "CFPB-style narrative with XXXX redactions — empty list is the correct answer. "
            "Redacted-city + bare-state (XXXX, NY) does NOT restore ADDRESS"
        ),
        "values": [
            "Called XXXX about my account XX/XX/XXXX and they said XXXX would help.",
            "My account ending XXXX was charged {$500.00} on XX/XX/XXXX.",
            "I contacted XXXX XXXX XXXX about the debt; they never responded.",
            "I was at the ATM in XXXX, NJ when my card was declined. I live in XXXX XXXX, MI.",
            "The merchant XXXX XXXX in XXXX, NY was unauthorized to charge my account.",
        ],
        "labels": [],
    },
    {
        "description": "Log stream — multiple entities coexist at ≥1 prevalence",
        "values": [
            "2026-04-01 12:05:13 user=alice@co.com ip=10.0.0.5 path=/api/users",
            "2026-04-01 12:05:14 user=bob@co.com ip=192.168.1.22 phone=415-555-0100 card=4532-1234-5678-9010",
        ],
        "labels": ["CREDIT_CARD", "EMAIL", "IP_ADDRESS", "PHONE"],
    },
)


# ═══════════════════════════════════════════════════════════════════════════
# END USER CONTRIBUTION — infrastructure below
# ═══════════════════════════════════════════════════════════════════════════


_INSTRUCTIONS_BY_SHAPE: dict[ShapeName, str] = {
    "structured_single": STRUCTURED_SINGLE_INSTRUCTIONS,
    "opaque_tokens": OPAQUE_TOKENS_INSTRUCTIONS,
    "free_text_heterogeneous": HETEROGENEOUS_INSTRUCTIONS,
}

_FEW_SHOT_BY_SHAPE: dict[ShapeName, tuple[dict[str, Any], ...]] = {
    "structured_single": STRUCTURED_SINGLE_FEW_SHOT,
    "opaque_tokens": OPAQUE_TOKENS_FEW_SHOT,
    "free_text_heterogeneous": HETEROGENEOUS_FEW_SHOT,
}


def _render_example(example: dict[str, Any]) -> str:
    values_block = "\n".join(f"  - {v!r}" for v in example["values"])
    labels = json.dumps(example["labels"])
    return f'Example — {example["description"]}:\nSample values:\n{values_block}\nResponse: {{"labels": {labels}}}\n'


def build_system_prompt_for_shape(shape: ShapeName) -> list[dict[str, Any]]:
    """Assemble the cacheable system prompt for one router branch.

    Each branch gets its own cache_control breakpoint — the text differs
    between branches, so caching is per-shape, not global. Within a single
    Phase 2 run over the 50-row gold set, the 3 branches share 3 cache
    entries (one per shape).
    """
    if shape not in _INSTRUCTIONS_BY_SHAPE:
        raise ValueError(f"Unknown shape {shape!r}; expected one of {VALID_SHAPES}")

    entity_list = "\n".join(f"  - {e}" for e in ALLOWED_ENTITIES)
    examples = "\n".join(_render_example(e) for e in _FEW_SHOT_BY_SHAPE[shape])
    instructions = _INSTRUCTIONS_BY_SHAPE[shape]
    system_text = (
        "You are a multi-label PII / sensitive-data column labeler for a "
        "research benchmark. Given a sample of values from one database "
        f"column (routed to the ``{shape}`` branch), emit the set of "
        "entity types present at ≥1 instance.\n\n"
        f"{instructions}\n\n"
        "Allowed entity types (use these exact strings only, do not invent new ones):\n"
        f"{entity_list}\n\n"
        "Few-shot examples:\n\n"
        f"{examples}\n"
        "Respond with valid JSON matching this schema:\n"
        '  {"labels": ["ENTITY_TYPE_1", "ENTITY_TYPE_2", ...]}\n'
        "An empty list is valid when the column contains no sensitive data."
    )
    return [
        {
            "type": "text",
            "text": system_text,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def label_gold_set_via_router(
    gold_set_path: Path = GOLD_SET_PATH,
    only_human_reviewed: bool = True,
    limit: int | None = None,
    sleep_between_calls: float = 0.0,
    max_tokens: int = 4096,
) -> list[LabelerCall]:
    """Run the router-labeler over every row in the gold set.

    Each row's ``true_shape`` picks the branch-specific system prompt.
    Reuses Phase 1's ``label_column`` — only the system prompt changes.

    Args:
        gold_set_path: Path to ``heterogeneous_gold_set.jsonl``.
        only_human_reviewed: Skip rows where ``review_status != "human_reviewed"``.
        limit: Optional cap on rows (for smoke tests).
        sleep_between_calls: Optional inter-call delay for rate-limit headroom.

    Returns:
        One ``LabelerCall`` per row (even on API error — ``error`` field populated).
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY not set. Export it before running the labeler.")

    with gold_set_path.open() as f:
        rows = [json.loads(line) for line in f if line.strip()]
    if only_human_reviewed:
        rows = [r for r in rows if r.get("review_status") == "human_reviewed"]
    if limit is not None:
        rows = rows[:limit]

    client = anthropic.Anthropic()
    systems_by_shape: dict[ShapeName, list[dict[str, Any]]] = {
        shape: build_system_prompt_for_shape(shape) for shape in VALID_SHAPES
    }

    results: list[LabelerCall] = []
    for row in rows:
        shape = row.get("true_shape")
        if shape not in VALID_SHAPES:
            results.append(
                LabelerCall(
                    column_id=row["column_id"],
                    pred=[],
                    true=list(row["true_labels"]),
                    error=f"unrouted_shape: {shape!r}",
                )
            )
            continue

        # M4f-d1: opaque-column decoder stage. Base64-wrapped structured
        # content is decoded and re-routed to the heterogeneous branch so
        # nested entities (EMAIL, PHONE, ...) are labeled semantically
        # rather than hidden behind OPAQUE_SECRET. Shape-specific opaque
        # (ETH 0x+hex, hashes) fails the decode check and falls through.
        effective_row = row
        if shape == "opaque_tokens":
            raw_values = row["values"]
            if row.get("encoding") == "xor":
                raw_values = decode_encoded_strings(raw_values)
            decoder_result = try_decode_opaque_column(raw_values)
            if decoder_result is not None:
                decoded_values, new_shape = decoder_result
                effective_row = dict(row)
                effective_row["values"] = decoded_values
                effective_row["encoding"] = "plaintext"  # already decoded
                effective_row["true_shape"] = new_shape
                shape = new_shape
                log.info(
                    "decoder fired on %s: routed %s → %s",
                    row["column_id"],
                    "opaque_tokens",
                    new_shape,
                )

        system = systems_by_shape[shape]
        try:
            call = label_column(client, effective_row, system, max_tokens=max_tokens)
        except Exception as e:  # noqa: BLE001 — broad catch is intentional
            call = LabelerCall(
                column_id=row["column_id"],
                pred=[],
                true=list(row["true_labels"]),
                error=f"{type(e).__name__}: {e}",
            )
        results.append(call)
        if sleep_between_calls > 0:
            time.sleep(sleep_between_calls)
    return results
