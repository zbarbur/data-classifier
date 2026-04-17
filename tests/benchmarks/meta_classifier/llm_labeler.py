"""LLM-as-oracle multi-label labeler for the M4d gold-set validation run.

M4c produced 50 hand-labeled heterogeneous columns as the gold-set
evaluation anchor (``heterogeneous_gold_set.jsonl``). M4d Phase 1 asks:
can a strong LLM reproduce the human labels well enough (Jaccard ≥ 0.8)
to serve as a scalable labeler for the 500-1000 column M4d corpus?

This module ships the labeler harness. The critical experimental
variable is the ``LABELER_INSTRUCTIONS`` block below — the human-written
encoding of the M4c annotation protocol is what the LLM is trying to
internalize. Everything else (prompt scaffolding, schema, API plumbing,
scoring wiring) is infrastructure.

Research-only module. Lives under ``tests/benchmarks/meta_classifier/``
per the research/production contract — no ``data_classifier/``
production code imports anthropic.

Requires the ``research-llm`` extras group::

    pip install -e ".[research-llm]"

Expects ``ANTHROPIC_API_KEY`` in the environment.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anthropic
from pydantic import BaseModel, ConfigDict

from data_classifier.core.taxonomy import ENTITY_TYPE_TO_FAMILY
from data_classifier.patterns._decoder import decode_encoded_strings
from tests.benchmarks.meta_classifier.multi_label_metrics import ColumnResult

MODEL = "claude-opus-4-7"
GOLD_SET_PATH = Path(__file__).resolve().parent / "heterogeneous_gold_set.jsonl"

# Sorted list of allowed entity types. Injected into the system prompt so
# the labeler cannot invent new type names. Matches the exact strings the
# gold-set validator accepts, which is what ``multi_label_metrics`` scores
# against.
ALLOWED_ENTITIES: tuple[str, ...] = tuple(sorted(ENTITY_TYPE_TO_FAMILY.keys()))


# ═══════════════════════════════════════════════════════════════════════════
# USER CONTRIBUTION — LABELER INSTRUCTIONS
# ═══════════════════════════════════════════════════════════════════════════
#
# This block is the experimental variable of M4d Phase 1. The ~5-10 lines
# below determine how the LLM interprets the multi-label annotation task
# against the M4c human-reviewed gold set. Everything else in this file is
# infrastructure that should not affect the Jaccard-agreement outcome.
#
# The instructions should encode the M4c annotation protocol documented in
# ``docs/research/multi_label_gold_set_annotator_guide.md``. The protocol's
# key facets (verbatim from queue.md M4c spec):
#
#   1. Prevalence floor — everything-counts with ≥1 observed instance in
#      the sample. No ignore-rare-things filter.
#
#   2. Entity granularity — top-level entities only. ``EMAIL``, not
#      ``DOMAIN`` or ``LOCAL_PART`` subcomponents. Keeps taxonomy tractable.
#
#   3. Ambiguous values — one label per value; annotator judgment on
#      primary class; weak signals (e.g., ``admin`` as CREDENTIAL-
#      placeholder) excluded unless ≥0.5 confidence.
#
#   4. Empty column (no PII surviving redaction) — return ``[]``. This is
#      a valid positive outcome, not a failure. CFPB XXXX-redacted columns
#      are the canonical case.
#
#   5. Entity-type strings must be drawn exactly from the allowed list
#      injected into the system prompt. No inventing new types.
#
# The allowed entity list, three few-shot examples, and JSON-schema anchor
# are appended by ``build_system_prompt()`` after your instructions — do
# NOT duplicate those here.
#
# To iterate:
#   1. Edit the string below
#   2. Run the driver (``scripts/run_m4d_labeler_validation.py``)
#   3. Inspect ``result.md``'s per-column disagreement table
#   4. Repeat until Jaccard ≥ 0.8 against the 50 human-reviewed rows
#
# ═══════════════════════════════════════════════════════════════════════════

LABELER_INSTRUCTIONS = """
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

# ═══════════════════════════════════════════════════════════════════════════
# END USER CONTRIBUTION — infrastructure below
# ═══════════════════════════════════════════════════════════════════════════


# Three canonical examples covering the three Sprint 13 router branches:
# structured single-label, free-text heterogeneous, opaque tokens. These
# anchor the LLM's understanding of the three common output shapes.
FEW_SHOT_EXAMPLES: tuple[dict[str, Any], ...] = (
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
        "description": "Free-text heterogeneous column (web-server log lines)",
        "values": [
            "2026-04-01T12:05:13Z 192.168.1.5 GET /api/v1/users/alice?email=alice@co.com",
            "2026-04-01T12:05:14Z 10.0.0.22 POST /api/v1/login from bob@co.com",
        ],
        "labels": ["EMAIL", "IP_ADDRESS", "URL"],
    },
    {
        "description": "Column with no PII (CFPB narrative with all entities redacted)",
        "values": [
            "Called the bank on XX/XX/XXXX about account ending XXXX.",
            "Received a letter from XXXX on XX/XX/XXXX regarding my loan.",
        ],
        "labels": [],
    },
)


class LabelResponse(BaseModel):
    """Pydantic schema for the labeler's structured output.

    Enforced via ``client.messages.parse(output_format=LabelResponse)``.
    The SDK maps this to ``output_config.format`` on the underlying
    Messages API call and validates the response.
    """

    model_config = ConfigDict(extra="forbid")
    labels: list[str]


@dataclass
class LabelerCall:
    """Single-column labeler result + telemetry.

    Captures the prediction (for scoring) alongside usage metrics (for
    cache-hit verification and cost accounting). Written to
    ``predictions.jsonl`` one entry per row.
    """

    column_id: str
    pred: list[str]
    true: list[str]
    raw_response: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    unknown_labels: list[str] = field(default_factory=list)
    error: str | None = None

    def to_column_result(self) -> ColumnResult:
        """Drop telemetry, keep just the pred/true pair for M4a aggregation."""
        return ColumnResult(column_id=self.column_id, pred=self.pred, true=self.true)

    def to_jsonl_dict(self) -> dict[str, Any]:
        return {
            "column_id": self.column_id,
            "pred": self.pred,
            "true": self.true,
            "unknown_labels": self.unknown_labels,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "error": self.error,
        }


def _render_example(example: dict[str, Any]) -> str:
    values_block = "\n".join(f"  - {v!r}" for v in example["values"])
    labels = json.dumps(example["labels"])
    return f'Example — {example["description"]}:\nSample values:\n{values_block}\nResponse: {{"labels": {labels}}}\n'


def build_system_prompt() -> list[dict[str, Any]]:
    """Assemble the cacheable system prompt.

    Structure (stable across all 50 calls, hence cacheable):
      - labeler role
      - LABELER_INSTRUCTIONS (the user-written block)
      - allowed entity-type enum
      - three few-shot examples
      - schema anchor

    Rendered as a single text block with ``cache_control: ephemeral``.
    Opus 4.7's 4096-token minimum may not be met; if not, the call still
    works, cache_read_input_tokens just stays at 0.
    """
    entity_list = "\n".join(f"  - {e}" for e in ALLOWED_ENTITIES)
    examples = "\n".join(_render_example(e) for e in FEW_SHOT_EXAMPLES)
    system_text = (
        "You are a multi-label PII / sensitive-data column labeler for a "
        "research benchmark. Given a sample of values from one database "
        "column, emit the set of entity types present at ≥1 instance.\n\n"
        f"{LABELER_INSTRUCTIONS}\n\n"
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


def build_user_message(row: dict[str, Any], max_values: int = 50) -> str:
    """Render one gold-set row as the user-facing message.

    Decodes XOR-encoded values (per ``patterns/_decoder.py``) before
    sending. Truncates to ``max_values`` — sample-based labeling matches
    the library's design (``default_sample_size=100``). Does NOT leak
    ``true_shape`` / ``true_labels`` — labeler is blind.
    """
    encoding = row.get("encoding", "plaintext")
    values = row["values"][:max_values]
    if encoding == "xor":
        values = decode_encoded_strings(values)
    values_block = "\n".join(f"  {i + 1}. {v!r}" for i, v in enumerate(values))
    source = row.get("source", "unknown")
    source_ref = row.get("source_reference", "unknown")
    return (
        f"Column source: {source}\n"
        f"Column reference: {source_ref}\n"
        f"Sample count: {len(values)} values (of {len(row['values'])} in column)\n\n"
        f"Sample values:\n{values_block}\n\n"
        "Label the entity types present in this column."
    )


def label_column(
    client: anthropic.Anthropic,
    row: dict[str, Any],
    system: list[dict[str, Any]],
    max_tokens: int = 1024,
) -> LabelerCall:
    """Call the labeler on one column, return prediction + telemetry.

    Exceptions propagate — driver decides whether to retry / bail.
    """
    user_message = build_user_message(row)
    response = client.messages.parse(
        model=MODEL,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": user_message}],
        output_format=LabelResponse,
    )
    parsed: LabelResponse = response.parsed_output
    # Filter to allowed entity types only — any invented labels are
    # reported separately so the memo can flag prompt-compliance issues.
    allowed = set(ALLOWED_ENTITIES)
    pred = [label for label in parsed.labels if label in allowed]
    unknown = [label for label in parsed.labels if label not in allowed]
    raw_text = next((b.text for b in response.content if b.type == "text"), "")
    usage = response.usage
    return LabelerCall(
        column_id=row["column_id"],
        pred=pred,
        true=list(row["true_labels"]),
        raw_response=raw_text,
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        unknown_labels=unknown,
    )


def label_gold_set(
    gold_set_path: Path = GOLD_SET_PATH,
    only_human_reviewed: bool = True,
    limit: int | None = None,
    sleep_between_calls: float = 0.0,
) -> list[LabelerCall]:
    """Run the labeler over every row in the gold set, return results.

    Args:
        gold_set_path: Path to ``heterogeneous_gold_set.jsonl``.
        only_human_reviewed: Skip rows where ``review_status != "human_reviewed"``.
            Default True — pre-filled rows aren't honest ground truth.
        limit: Optional cap on rows (for smoke tests / dry runs).
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
    system = build_system_prompt()
    results: list[LabelerCall] = []
    for row in rows:
        try:
            call = label_column(client, row, system)
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
