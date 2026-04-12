"""Meta-classifier for learned engine arbitration (Sprint 6 Phase 1 skeleton).

Phase 1 provides only the class structure and feature extraction helpers
used by the training-data builder. Training, shadow inference, and
orchestrator integration are deferred to Phase 2 and Phase 3.

The ``extract_features`` function is intentionally pure (no I/O, no
logging, no globals) so it can be shared between:

  * offline training-data assembly, and
  * online shadow inference at classification time (Phase 3).

It operates on a list of ``ClassificationFinding`` objects coming from
an arbitrary set of engines. Each engine is scored independently; the
resulting feature vector has a fixed length of :data:`FEATURE_DIM`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from data_classifier.core.types import ClassificationFinding

# ── Feature schema ───────────────────────────────────────────────────────────

# 15 features. The order MUST match the order used by
# tests/benchmarks/meta_classifier/extract_features.py and by any future
# shadow-inference code path.
FEATURE_NAMES: tuple[str, ...] = (
    "top_overall_confidence",
    "regex_confidence",
    "column_name_confidence",
    "heuristic_confidence",
    "secret_scanner_confidence",
    "engines_agreed",
    "engines_fired",
    "confidence_gap",
    "regex_match_ratio",
    "heuristic_distinct_ratio",
    "heuristic_avg_length",
    "has_column_name_hit",
    "has_secret_indicators",
    "primary_is_pii",
    "primary_is_credential",
)
FEATURE_DIM: int = len(FEATURE_NAMES)

# Engine name constants — must match the ``name`` class attribute on each
# engine (see data_classifier/engines/*.py).
_ENGINE_REGEX = "regex"
_ENGINE_COLUMN_NAME = "column_name"
_ENGINE_HEURISTIC = "heuristic_stats"
_ENGINE_SECRET_SCANNER = "secret_scanner"


# ── Phase 2/3 placeholder types ─────────────────────────────────────────────


@dataclass
class MetaClassifierPrediction:
    """Shadow prediction from the meta-classifier.

    Phase 3 integration placeholder. ``agreement`` indicates whether the
    shadow model's preferred entity type matches the live pipeline's top
    finding for the same column.
    """

    column_id: str
    predicted_entity: str
    confidence: float
    live_entity: str
    agreement: bool


class MetaClassifier:
    """Skeleton meta-classifier.

    Phase 1 only exposes the class shape used by the training-data
    builder (so feature vectors have a documented owner). Phase 2 adds
    the real trained model, and Phase 3 wires :meth:`predict_shadow`
    into the orchestrator behind a feature flag.
    """

    def __init__(self, model: object | None = None) -> None:
        self._model = model

    def predict_shadow(
        self,
        findings: "list[ClassificationFinding]",  # noqa: ARG002 — phase 3
    ) -> MetaClassifierPrediction | None:
        """Return a shadow prediction. Phase 1/2 always return None."""
        raise NotImplementedError(
            "MetaClassifier.predict_shadow is implemented in Phase 3. "
            "Phase 1 only exposes extract_features for offline use."
        )


# ── Pure feature extraction ─────────────────────────────────────────────────


def _findings_for_engine(
    findings: "list[ClassificationFinding]",
    engine_name: str,
) -> "list[ClassificationFinding]":
    """Return findings produced by a specific engine, in insertion order."""
    return [f for f in findings if f.engine == engine_name]


def _best_confidence(findings: "list[ClassificationFinding]") -> float:
    """Return the max confidence across findings, or 0.0 if empty."""
    if not findings:
        return 0.0
    return max(f.confidence for f in findings)


def _top_finding(
    findings: "list[ClassificationFinding]",
) -> "ClassificationFinding | None":
    """Return the single highest-confidence finding, or None if empty."""
    if not findings:
        return None
    return max(findings, key=lambda f: f.confidence)


def extract_features(
    findings: "list[ClassificationFinding]",
    *,
    heuristic_distinct_ratio: float = 0.0,
    heuristic_avg_length: float = 0.0,
) -> list[float]:
    """Extract the 15-feature vector from a column's per-engine findings.

    The caller is expected to supply *all* findings produced for a single
    column, across every engine that ran. This function is pure: no I/O,
    no logging, no hidden state.

    ``heuristic_distinct_ratio`` and ``heuristic_avg_length`` are
    column-level statistics computed by the caller (they don't live on
    the finding object itself in the current library version). Pass 0.0
    when they can't be computed. ``heuristic_avg_length`` is expected to
    already be normalized — the caller should divide by 100 and clip to
    [0, 1] before passing.

    Features (index → name, see :data:`FEATURE_NAMES`):

    0  top_overall_confidence    — max confidence across all findings
    1  regex_confidence          — max confidence from the regex engine
    2  column_name_confidence    — max confidence from the column_name engine
    3  heuristic_confidence      — max confidence from the heuristic_stats engine
    4  secret_scanner_confidence — max confidence from the secret_scanner engine
    5  engines_agreed            — how many engines voted for the top entity type
    6  engines_fired             — how many distinct engines produced any finding
    7  confidence_gap            — top − second finding (1.0 if only one finding)
    8  regex_match_ratio         — sample_analysis.match_ratio for top regex finding
    9  heuristic_distinct_ratio  — caller-supplied column statistic
    10 heuristic_avg_length      — caller-supplied column statistic (normalized)
    11 has_column_name_hit       — 1.0 if column_name engine fired, else 0.0
    12 has_secret_indicators     — 1.0 if secret_scanner engine fired, else 0.0
    13 primary_is_pii            — 1.0 if top finding's category == "PII"
    14 primary_is_credential     — 1.0 if top finding's category == "Credential"
    """
    regex_findings = _findings_for_engine(findings, _ENGINE_REGEX)
    column_name_findings = _findings_for_engine(findings, _ENGINE_COLUMN_NAME)
    heuristic_findings = _findings_for_engine(findings, _ENGINE_HEURISTIC)
    secret_findings = _findings_for_engine(findings, _ENGINE_SECRET_SCANNER)

    top_overall_confidence = _best_confidence(findings)
    regex_confidence = _best_confidence(regex_findings)
    column_name_confidence = _best_confidence(column_name_findings)
    heuristic_confidence = _best_confidence(heuristic_findings)
    secret_scanner_confidence = _best_confidence(secret_findings)

    # engines_fired: count of distinct engines that produced at least one finding
    fired_engines: set[str] = {f.engine for f in findings}
    engines_fired = len(fired_engines)

    # engines_agreed: count of distinct engines whose highest-confidence
    # finding was for the top overall entity type.
    top = _top_finding(findings)
    if top is None:
        engines_agreed = 0
    else:
        top_entity = top.entity_type
        # Group findings by engine, take max-confidence-per-engine as that
        # engine's "vote", then count engines whose vote matches top_entity.
        votes: dict[str, str] = {}
        vote_confidence: dict[str, float] = {}
        for f in findings:
            cur = vote_confidence.get(f.engine, -1.0)
            if f.confidence > cur:
                vote_confidence[f.engine] = f.confidence
                votes[f.engine] = f.entity_type
        engines_agreed = sum(1 for et in votes.values() if et == top_entity)

    # confidence_gap: top − second. If there is only one finding, we have
    # maximum confidence — use 1.0 as the "no ambiguity" marker. If zero
    # findings, gap is 0.0.
    if not findings:
        confidence_gap = 0.0
    elif len(findings) == 1:
        confidence_gap = 1.0
    else:
        sorted_conf = sorted((f.confidence for f in findings), reverse=True)
        confidence_gap = sorted_conf[0] - sorted_conf[1]

    # regex_match_ratio: take the top regex finding's sample analysis
    regex_match_ratio = 0.0
    top_regex = _top_finding(regex_findings)
    if top_regex is not None and top_regex.sample_analysis is not None:
        regex_match_ratio = top_regex.sample_analysis.match_ratio

    has_column_name_hit = 1.0 if column_name_findings else 0.0
    has_secret_indicators = 1.0 if secret_findings else 0.0

    if top is None:
        primary_is_pii = 0.0
        primary_is_credential = 0.0
    else:
        primary_is_pii = 1.0 if top.category == "PII" else 0.0
        primary_is_credential = 1.0 if top.category == "Credential" else 0.0

    vector: list[float] = [
        float(top_overall_confidence),
        float(regex_confidence),
        float(column_name_confidence),
        float(heuristic_confidence),
        float(secret_scanner_confidence),
        float(engines_agreed),
        float(engines_fired),
        float(confidence_gap),
        float(regex_match_ratio),
        float(heuristic_distinct_ratio),
        float(heuristic_avg_length),
        float(has_column_name_hit),
        float(has_secret_indicators),
        float(primary_is_pii),
        float(primary_is_credential),
    ]
    assert len(vector) == FEATURE_DIM, f"feature vector length {len(vector)} != {FEATURE_DIM}"
    return vector
