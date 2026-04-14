"""Meta-classifier for learned engine arbitration (Sprint 6).

Phase 1 landed the feature schema and pure ``extract_features`` helper.
Phase 2 trained a logistic-regression model and serialized it to
``data_classifier/models/meta_classifier_v1.pkl`` (a trusted build
artifact shipped inside the wheel). Phase 3 wires shadow inference into
the orchestrator as an observability-only path — predictions are logged
via ``MetaClassifierEvent`` but never modify the live classification
result.

Design invariants:
  * ``extract_features`` is pure (no I/O, no logging, no globals) so it
    is safe to share between offline training and online inference.
  * The ``MetaClassifier`` class lazy-loads its model on first use. If
    the optional ``[meta]`` extra is not installed, or if the pickle is
    missing, ``predict_shadow`` returns ``None`` and emits a single
    warning. The live classification path is **never** affected.
  * ``sklearn`` is imported lazily inside :meth:`_ensure_loaded` — the
    library must import cleanly without the optional extra.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from data_classifier.core.types import ClassificationFinding

_log = logging.getLogger(__name__)

# ── Feature schema ───────────────────────────────────────────────────────────

# Feature schema version. Bump whenever FEATURE_NAMES changes in a way
# that invalidates trained model artifacts. Stored in the artifact and
# checked on load — a mismatch disables shadow inference rather than
# silently producing garbage predictions.
#
# Version history:
#   1 — Sprint 6 original (15 features).
#   2 — Sprint 11 widening (15 base + 31 primary_entity_type one-hot = 46).
FEATURE_SCHEMA_VERSION: int = 2

# Base column-level features. Do NOT reorder these 15 — downstream code
# indexes them positionally in several places.
_BASE_FEATURE_NAMES: tuple[str, ...] = (
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

# Primary-entity-type one-hot vocabulary. The top finding's entity_type
# is encoded as a 1.0 in exactly one of these slots (or UNKNOWN if the
# top entity_type is not in the vocab). Union of:
#   - regex default_patterns.json entity types
#   - GLiNER engine ENTITY_LABEL_DESCRIPTIONS keys
#   - secret_scanner primary bucket (CREDENTIAL)
#
# APPEND-ONLY: when adding a new entity type, add it at the end (before
# UNKNOWN) and bump FEATURE_SCHEMA_VERSION. Reordering silently corrupts
# trained artifacts.
PRIMARY_ENTITY_TYPES: tuple[str, ...] = (
    "ABA_ROUTING",
    "ADDRESS",
    "API_KEY",
    "BITCOIN_ADDRESS",
    "CANADIAN_SIN",
    "CREDENTIAL",
    "CREDIT_CARD",
    "DATE_OF_BIRTH",
    "DATE_OF_BIRTH_EU",
    "DEA_NUMBER",
    "EIN",
    "EMAIL",
    "ETHEREUM_ADDRESS",
    "HEALTH",
    "IBAN",
    "IP_ADDRESS",
    "MAC_ADDRESS",
    "MBI",
    "NATIONAL_ID",
    "NPI",
    "OPAQUE_SECRET",
    "ORGANIZATION",
    "PASSWORD_HASH",
    "PERSON_NAME",
    "PHONE",
    "PRIVATE_KEY",
    "SSN",
    "SWIFT_BIC",
    "URL",
    "VIN",
    "UNKNOWN",
)

# Full feature schema = 15 base + 31 entity-type one-hot slots = 46.
FEATURE_NAMES: tuple[str, ...] = _BASE_FEATURE_NAMES + tuple(f"primary_entity_type={t}" for t in PRIMARY_ENTITY_TYPES)
FEATURE_DIM: int = len(FEATURE_NAMES)

# Precomputed index map: entity_type -> slot in FEATURE_NAMES. Used by
# extract_features to set the one-hot bit without a linear scan.
_PRIMARY_ENTITY_TYPE_INDEX: dict[str, int] = {
    t: len(_BASE_FEATURE_NAMES) + i for i, t in enumerate(PRIMARY_ENTITY_TYPES)
}
_UNKNOWN_ENTITY_TYPE_INDEX: int = _PRIMARY_ENTITY_TYPE_INDEX["UNKNOWN"]

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


_DEFAULT_MODEL_PACKAGE = "data_classifier.models"
_DEFAULT_MODEL_RESOURCE = "meta_classifier_v1.pkl"


class MetaClassifier:
    """Lazy-loaded meta-classifier for shadow inference.

    Loads the pickled model on first use. If the optional ``[meta]``
    extra is not installed, or if the model artifact is missing,
    :meth:`predict_shadow` returns ``None`` and logs a warning **once**.
    The orchestrator's live path is never affected — every failure mode
    is a graceful no-op.

    Phase 3 wires this into :meth:`Orchestrator.classify_column` to log
    shadow predictions via ``MetaClassifierEvent`` without modifying the
    return value.
    """

    def __init__(self, model_path: Path | str | None = None) -> None:
        self._model_path: Path | None = Path(model_path) if model_path else None
        self._loaded: bool = False
        self._available: bool = False
        self._model: object | None = None
        self._scaler: object | None = None
        self._feature_names: tuple[str, ...] = ()
        self._class_labels: tuple[str, ...] = ()
        self._dropped_feature_indices: tuple[int, ...] = ()
        self._load_warning_emitted: bool = False

    # ── Model loading ────────────────────────────────────────────────

    def _read_model_bytes(self) -> bytes:
        """Return the pickle bytes.

        Prefers an explicit constructor argument (useful for tests),
        otherwise resolves via :mod:`importlib.resources` against the
        ``data_classifier.models`` subpackage. Reading bytes inside the
        ``as_file`` context is required — the contract only guarantees
        the path is live inside the ``with`` block, which matters for
        zipapp/pex/frozen deployments.
        """
        if self._model_path is not None:
            return self._model_path.read_bytes()
        from importlib.resources import as_file, files

        resource = files(_DEFAULT_MODEL_PACKAGE).joinpath(_DEFAULT_MODEL_RESOURCE)
        with as_file(resource) as path:
            return Path(path).read_bytes()

    def _ensure_loaded(self) -> bool:
        """Lazy load. Returns ``True`` if the model is ready, ``False`` if degraded."""
        if self._loaded:
            return self._available
        self._loaded = True

        # sklearn is an optional dependency — import lazily so the
        # library imports cleanly without the [meta] extra.
        try:
            import sklearn  # noqa: F401
        except ImportError:
            self._log_load_failure(
                "scikit-learn not installed; install data_classifier[meta] to enable",
            )
            return False

        try:
            import pickle  # noqa: S403 — loading a trusted in-wheel artifact

            try:
                raw = self._read_model_bytes()
            except FileNotFoundError as exc:
                self._log_load_failure(f"model artifact not found: {exc}")
                return False
            blob = pickle.loads(raw)  # noqa: S301 — trusted first-party artifact

            # Version gate. Artifacts produced before Sprint 11 did not
            # store a schema version and only have 15 feature names —
            # silently using them with the current FEATURE_NAMES (46) via
            # the drop-indices fallback would treat the 31 one-hot slots
            # as "dropped" and predict on the wrong subspace. Refuse.
            artifact_version = blob.get("feature_schema_version", 1)
            if artifact_version != FEATURE_SCHEMA_VERSION:
                self._log_load_failure(
                    f"feature schema version mismatch: artifact v{artifact_version}, "
                    f"code expects v{FEATURE_SCHEMA_VERSION}. "
                    f"Retrain the meta-classifier against the current schema.",
                )
                return False

            self._model = blob["model"]
            self._scaler = blob["scaler"]
            self._feature_names = tuple(blob["feature_names"])
            self._class_labels = tuple(blob["class_labels"])
            # Compute which indices in the FULL feature vector the
            # trained model was NOT given (so we drop them at inference).
            # Only meaningful for a same-version artifact trained on a
            # subset of features; cross-version gaps are blocked above.
            self._dropped_feature_indices = self._compute_dropped_indices(
                kept=self._feature_names,
                full=FEATURE_NAMES,
            )
            self._available = True
            return True
        except Exception as exc:  # pragma: no cover — defensive
            self._log_load_failure(f"failed to load meta-classifier model: {exc}")
            return False

    @staticmethod
    def _compute_dropped_indices(
        kept: tuple[str, ...],
        full: tuple[str, ...],
    ) -> tuple[int, ...]:
        """Return indices in ``full`` whose names are not in ``kept``."""
        kept_set = set(kept)
        return tuple(i for i, name in enumerate(full) if name not in kept_set)

    def _log_load_failure(self, msg: str) -> None:
        if self._load_warning_emitted:
            return
        self._load_warning_emitted = True
        _log.warning("MetaClassifier disabled: %s", msg)

    # ── Shadow inference ─────────────────────────────────────────────

    def predict_shadow(
        self,
        findings: "list[ClassificationFinding]",
        sample_values: "list[str] | None" = None,
    ) -> MetaClassifierPrediction | None:
        """Shadow inference. Returns ``None`` on any error or degradation.

        Shadow semantics: the caller logs this prediction for offline
        comparison against the live pipeline. It must **never** be used
        to modify ``classify_columns`` return values. Every exception
        path returns ``None`` so that shadow inference cannot crash the
        live path.
        """
        if not self._ensure_loaded():
            return None

        values = sample_values or []
        distinct = _distinct_ratio(values)
        avg_len = _avg_length_normalized(values)

        try:
            full_vec = extract_features(
                findings,
                heuristic_distinct_ratio=distinct,
                heuristic_avg_length=avg_len,
            )
            dropped = set(self._dropped_feature_indices)
            kept_vec = [v for i, v in enumerate(full_vec) if i not in dropped]
            if len(kept_vec) != len(self._feature_names):
                _log.debug(
                    "MetaClassifier feature-dim mismatch: got %d, expected %d",
                    len(kept_vec),
                    len(self._feature_names),
                )
                return None

            import numpy as np

            x = np.asarray([kept_vec], dtype=float)
            x_scaled = self._scaler.transform(x)  # type: ignore[attr-defined]
            probs = self._model.predict_proba(x_scaled)[0]  # type: ignore[attr-defined]
            top_idx = int(probs.argmax())
            predicted_entity = str(self._class_labels[top_idx])
            confidence = float(probs[top_idx])

            # Compare against the live pipeline's top finding for agreement
            live_entity = ""
            column_id = ""
            if findings:
                live_top = max(findings, key=lambda f: f.confidence)
                live_entity = live_top.entity_type
                column_id = live_top.column_id
            agreement = predicted_entity == live_entity

            return MetaClassifierPrediction(
                column_id=column_id,
                predicted_entity=predicted_entity,
                confidence=confidence,
                live_entity=live_entity,
                agreement=agreement,
            )
        except Exception as exc:  # pragma: no cover — defensive
            _log.debug(
                "MetaClassifier predict_shadow failed: %s",
                exc,
                exc_info=True,
            )
            return None


# ── Column-statistic helpers (shared with training-data builder) ────────────
#
# These intentionally mirror tests/benchmarks/meta_classifier/extract_features.py
# so offline training and online shadow inference compute identical stats.
# They live inline here (not imported from tests/) to avoid taking a runtime
# dependency on the test tree.


def _distinct_ratio(values: list[str]) -> float:
    if not values:
        return 0.0
    return len(set(values)) / len(values)


def _avg_length_normalized(values: list[str]) -> float:
    if not values:
        return 0.0
    total = sum(len(v) for v in values)
    mean = total / len(values)
    normalized = mean / 100.0
    if normalized < 0.0:
        return 0.0
    if normalized > 1.0:
        return 1.0
    return normalized


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
    """Extract the 46-feature vector from a column's per-engine findings.

    The caller is expected to supply *all* findings produced for a single
    column, across every engine that ran. This function is pure: no I/O,
    no logging, no hidden state.

    ``heuristic_distinct_ratio`` and ``heuristic_avg_length`` are
    column-level statistics computed by the caller (they don't live on
    the finding object itself in the current library version). Pass 0.0
    when they can't be computed. ``heuristic_avg_length`` is expected to
    already be normalized — the caller should divide by 100 and clip to
    [0, 1] before passing.

    Feature layout (see :data:`FEATURE_NAMES` for exact names):

    0..14  — base column-level features:
        0  top_overall_confidence    — max confidence across all findings
        1  regex_confidence          — max from the regex engine
        2  column_name_confidence    — max from the column_name engine
        3  heuristic_confidence      — max from the heuristic_stats engine
        4  secret_scanner_confidence — max from the secret_scanner engine
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

    15..45 — primary_entity_type one-hot (31 slots, see
    :data:`PRIMARY_ENTITY_TYPES`). Exactly one slot is 1.0: the slot for
    the top finding's entity_type, or the UNKNOWN slot when there is no
    top finding or the entity_type is outside the vocab.
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

    # primary_entity_type one-hot. Exactly one slot is 1.0 (UNKNOWN when
    # there is no top finding or the entity_type is not in the vocab);
    # the rest are 0.0.
    one_hot = [0.0] * len(PRIMARY_ENTITY_TYPES)
    if top is None:
        one_hot[_UNKNOWN_ENTITY_TYPE_INDEX - len(_BASE_FEATURE_NAMES)] = 1.0
    else:
        slot = _PRIMARY_ENTITY_TYPE_INDEX.get(top.entity_type)
        if slot is None:
            one_hot[_UNKNOWN_ENTITY_TYPE_INDEX - len(_BASE_FEATURE_NAMES)] = 1.0
        else:
            one_hot[slot - len(_BASE_FEATURE_NAMES)] = 1.0
    vector.extend(one_hot)

    assert len(vector) == FEATURE_DIM, f"feature vector length {len(vector)} != {FEATURE_DIM}"
    return vector
