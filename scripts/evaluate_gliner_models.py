"""Structured GLiNER model evaluation sweep.

Drives GLiNER (and optionally GLiNER2) directly — bypasses
``data_classifier.engines.gliner_engine`` so production code stays
untouched, per the research brief in ``docs/research/GLINER_MODEL_EVALUATION_BRIEF.md``.

Two sweep phases:

Phase A — threshold & description sweep (baseline labels)
    For each (model × corpus × description-mode) combination, run the
    model once with a near-zero threshold, then score the resulting raw
    predictions at every target threshold (post-hoc filtering is free).

Phase B — label-alternative sweep (best config from phase A)
    For each entity type with registered alternatives, swap ONE label at
    a time versus the phase-A winner and measure the delta.

Usage::

    python scripts/evaluate_gliner_models.py --quick   # 100-row smoke run
    python scripts/evaluate_gliner_models.py --full    # 500-row full sweep

Outputs two artefacts alongside the memo::

    docs/research/GLINER_MODEL_EVALUATION.raw.json     (raw sweep data)
    docs/research/GLINER_MODEL_EVALUATION.summary.json (aggregated table)

The memo itself (``GLINER_MODEL_EVALUATION.md``) is written by the
accompanying human/session workflow, not by this script.
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Allow `python scripts/evaluate_gliner_models.py` from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from data_classifier.core.types import ColumnInput  # noqa: E402
from tests.benchmarks.corpus_loader import (  # noqa: E402
    load_ai4privacy_corpus,
    load_nemotron_corpus,
)

logger = logging.getLogger("gliner_eval")


# ── Sweep configuration ─────────────────────────────────────────────────────

MODELS: list[str] = [
    "urchade/gliner_multi_pii-v1",
    "fastino/gliner2-base-v1",
]

THRESHOLDS: list[float] = [0.3, 0.4, 0.5, 0.55, 0.6, 0.7, 0.8]

CORPORA: list[str] = ["ai4privacy", "nemotron"]

# Near-zero threshold used when invoking GLiNER — actual threshold is
# applied post-hoc so we can sweep the threshold axis for free.
_NEAR_ZERO_THRESHOLD = 0.01

# Must match gliner_engine._SAMPLE_CHUNK_SIZE so measurements reflect
# production behaviour. Do NOT import the engine constant — the brief
# forbids touching engine code, and we also want this script to stand
# alone when the engine import path changes.
_CHUNK_SIZE = 50
_SAMPLE_SEPARATOR = " ; "


# Baseline labels + descriptions — copied from
# ``data_classifier/engines/gliner_engine.py:43`` at brief time
# (2026-04-13). The eval script MUST NOT import this table from the
# engine — any accidental edits to production must not leak in.
BASELINE_LABELS: dict[str, tuple[str, str]] = {
    "PERSON_NAME": (
        "person",
        "Names of people or individuals, including first and last names",
    ),
    "ADDRESS": (
        "street address",
        "Street names, roads, avenues, physical locations with or without house numbers",
    ),
    "ORGANIZATION": (
        "organization",
        "Company names, institutions, agencies, or other organizational entities",
    ),
    "DATE_OF_BIRTH": (
        "date of birth",
        "Dates representing when a person was born, in any format",
    ),
    "PHONE": (
        "phone number",
        "Telephone numbers in any international format with country codes, dashes, dots, or spaces",
    ),
    "SSN": (
        "national identification number",
        "Government-issued personal identification numbers such as SSN, national insurance, or tax ID",
    ),
    "EMAIL": (
        "email",
        "Email addresses including international domains and subdomains",
    ),
    "IP_ADDRESS": (
        "ip address",
        "IPv4 or IPv6 network addresses",
    ),
}


# One-at-a-time label swaps. Each alternative replaces the baseline label
# for a single entity type while the other 7 baselines stay fixed.
LABEL_ALTERNATIVES: dict[str, list[str]] = {
    "PERSON_NAME": ["person name", "full name", "individual name"],
    "ADDRESS": ["physical address", "mailing address", "home address"],
    "ORGANIZATION": ["company", "institution", "business name"],
    "DATE_OF_BIRTH": ["birthday", "birth date"],
    "PHONE": ["telephone", "phone", "contact number"],
    "SSN": ["social security number", "government id", "tax id"],
    "EMAIL": ["email address", "e-mail"],
    "IP_ADDRESS": ["internet protocol address", "ipv4 address"],
}


# Priority types per brief — these are the highest-error types per
# Sprint 5/6 numbers and MUST be covered even in --quick mode.
_PRIORITY_TYPES = ["PERSON_NAME", "ADDRESS", "ORGANIZATION", "SSN"]


# ── Result containers ───────────────────────────────────────────────────────


@dataclass
class RawPrediction:
    """A single GLiNER span above the near-zero threshold."""

    label: str
    text: str
    score: float


@dataclass
class ColumnPredictions:
    """All raw predictions for one corpus column at one (model, labels, desc) run."""

    column_id: str
    expected: str | None
    raw_preds: list[RawPrediction] = field(default_factory=list)
    latency_ms: float = 0.0  # total model time for this column


@dataclass
class EntityMetrics:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


@dataclass
class ScoredConfig:
    """One scored configuration (model, corpus, labels, desc, threshold)."""

    model_id: str
    corpus: str
    label_variant: str  # "baseline" or "swap:ENTITY=alt"
    use_descriptions: bool | None  # None when model does not support it
    threshold: float
    macro_f1: float
    per_type: dict[str, dict[str, float]]  # entity -> {p, r, f1, tp, fp, fn}
    mean_latency_ms_per_col: float
    n_columns: int

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


# ── Corpus loading ──────────────────────────────────────────────────────────


def load_corpus(name: str, max_rows: int) -> list[tuple[ColumnInput, str | None]]:
    """Load a blind corpus by name — blind mode is mandatory for this eval."""
    if name == "ai4privacy":
        return load_ai4privacy_corpus(max_rows=max_rows, blind=True)
    if name == "nemotron":
        return load_nemotron_corpus(max_rows=max_rows, blind=True)
    msg = f"Unknown corpus: {name!r}"
    raise ValueError(msg)


def restrict_corpus(
    corpus: list[tuple[ColumnInput, str | None]],
    allowed: Sequence[str],
) -> list[tuple[ColumnInput, str | None]]:
    """Keep only columns whose ground-truth type is in ``allowed``.

    Used to keep the test universe aligned with the label set we are
    sweeping. Columns whose gold label is not in the label set cannot be
    scored fairly (the model would never be asked about that type).
    """
    allowed_set = set(allowed)
    return [(c, gt) for c, gt in corpus if gt in allowed_set]


# ── Model loading (direct GLiNER driver) ────────────────────────────────────


def _is_v2_model(model_id: str) -> bool:
    return model_id.startswith("fastino/")


def load_model(model_id: str) -> Any:
    """Load a GLiNER (or GLiNER2) model directly — bypasses the engine class.

    Returns ``None`` if the required package is not installed. The caller
    should skip the model and record the failure as a finding.
    """
    if _is_v2_model(model_id):
        try:
            from gliner2 import GLiNER2  # type: ignore[import-not-found]
        except ImportError as e:
            logger.warning("gliner2 package not available for %s: %s", model_id, e)
            return None
        try:
            return GLiNER2.from_pretrained(model_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("GLiNER2.from_pretrained failed for %s: %s", model_id, e)
            return None
    else:
        try:
            from gliner import GLiNER  # type: ignore[import-not-found]
        except ImportError as e:
            logger.warning("gliner package not available for %s: %s", model_id, e)
            return None
        try:
            return GLiNER.from_pretrained(model_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("GLiNER.from_pretrained failed for %s: %s", model_id, e)
            return None


# ── Inference ───────────────────────────────────────────────────────────────


def _predict_v1(
    model: Any,
    text: str,
    labels: list[str],
) -> list[dict[str, Any]]:
    return model.predict_entities(text, labels, threshold=_NEAR_ZERO_THRESHOLD)


def _predict_v2(
    model: Any,
    text: str,
    labels: dict[str, str],
) -> list[dict[str, Any]]:
    """GLiNER2 ``extract_entities`` returns a nested dict — flatten it."""
    result = model.extract_entities(text, labels, include_confidence=True)
    flat: list[dict[str, Any]] = []
    for label_str, matches in result.get("entities", {}).items():
        for m in matches:
            if isinstance(m, dict):
                flat.append(
                    {
                        "label": label_str,
                        "text": m.get("text", ""),
                        "score": float(m.get("confidence", 0.5)),
                    }
                )
            else:
                flat.append({"label": label_str, "text": str(m), "score": 0.5})
    return flat


def predict_column(
    *,
    model: Any,
    model_id: str,
    column: ColumnInput,
    labels_by_type: dict[str, str],
    descriptions_by_type: dict[str, str] | None,
) -> ColumnPredictions:
    """Run GLiNER on one column's samples in chunks, return raw predictions.

    ``descriptions_by_type`` is only honoured by GLiNER2 models. When
    ``None`` or when the model is v1, the script runs in plain-label mode.
    """
    is_v2 = _is_v2_model(model_id)
    labels_v1: list[str] = list(labels_by_type.values())
    labels_v2: dict[str, str] | None = None
    if is_v2:
        if descriptions_by_type is None:
            # v2 without descriptions = empty-string descriptions (the
            # brief's "without descriptions" arm). Feeding ``""`` avoids
            # rejecting the run entirely and gives us a comparable baseline.
            labels_v2 = {labels_by_type[et]: "" for et in labels_by_type}
        else:
            labels_v2 = {labels_by_type[et]: descriptions_by_type.get(et, "") for et in labels_by_type}

    cp = ColumnPredictions(column_id=column.column_id, expected=None)
    t0 = time.perf_counter()

    for i in range(0, len(column.sample_values), _CHUNK_SIZE):
        chunk = column.sample_values[i : i + _CHUNK_SIZE]
        text = _SAMPLE_SEPARATOR.join(str(v) for v in chunk)
        try:
            if is_v2:
                raw = _predict_v2(model, text, labels_v2 or {})
            else:
                raw = _predict_v1(model, text, labels_v1)
        except Exception:
            logger.exception("GLiNER inference failed on chunk %d for column %s", i, column.column_id)
            continue

        for p in raw:
            cp.raw_preds.append(
                RawPrediction(
                    label=str(p.get("label", "")),
                    text=str(p.get("text", "")),
                    score=float(p.get("score", 0.0)),
                )
            )

    cp.latency_ms = (time.perf_counter() - t0) * 1000.0
    return cp


# ── Scoring ─────────────────────────────────────────────────────────────────


def score_run(
    *,
    column_preds: list[ColumnPredictions],
    ground_truth: dict[str, str | None],
    label_to_type: dict[str, str],
    threshold: float,
    evaluated_types: Sequence[str],
) -> tuple[float, dict[str, dict[str, float]]]:
    """Apply a threshold to raw predictions and compute macro-F1.

    Detection rule: entity_type X is considered detected on a column if
    the column has at least one raw prediction whose label maps to X and
    whose score is ≥ threshold.
    """
    metrics: dict[str, EntityMetrics] = {t: EntityMetrics() for t in evaluated_types}
    eval_set = set(evaluated_types)

    for cp in column_preds:
        gt = ground_truth.get(cp.column_id)
        detected: set[str] = set()
        for p in cp.raw_preds:
            if p.score < threshold:
                continue
            et = label_to_type.get(p.label)
            if et and et in eval_set:
                detected.add(et)

        for t in evaluated_types:
            has_pred = t in detected
            is_gt = gt == t
            if has_pred and is_gt:
                metrics[t].tp += 1
            elif has_pred and not is_gt:
                metrics[t].fp += 1
            elif not has_pred and is_gt:
                metrics[t].fn += 1

    per_type: dict[str, dict[str, float]] = {}
    for t, m in metrics.items():
        per_type[t] = {
            "precision": round(m.precision, 4),
            "recall": round(m.recall, 4),
            "f1": round(m.f1, 4),
            "tp": m.tp,
            "fp": m.fp,
            "fn": m.fn,
        }

    # Macro F1 — average across entity types with at least one gold column.
    f1s = [m.f1 for t, m in metrics.items() if (m.tp + m.fn) > 0]
    macro = sum(f1s) / len(f1s) if f1s else 0.0
    return macro, per_type


# ── Sweep ───────────────────────────────────────────────────────────────────


def _build_label_to_type(labels_by_type: dict[str, str]) -> dict[str, str]:
    return {label: et for et, label in labels_by_type.items()}


def _baseline_labels_only() -> dict[str, str]:
    return {et: lbl for et, (lbl, _) in BASELINE_LABELS.items()}


def _baseline_descriptions() -> dict[str, str]:
    return {et: desc for et, (_, desc) in BASELINE_LABELS.items()}


def _variant_labels(entity: str, alt_label: str) -> dict[str, str]:
    out = _baseline_labels_only()
    out[entity] = alt_label
    return out


def run_model_once(
    *,
    model: Any,
    model_id: str,
    corpus: list[tuple[ColumnInput, str | None]],
    labels_by_type: dict[str, str],
    descriptions_by_type: dict[str, str] | None,
) -> list[ColumnPredictions]:
    """Run one model across every corpus column with one label config."""
    out: list[ColumnPredictions] = []
    for col, gt in corpus:
        cp = predict_column(
            model=model,
            model_id=model_id,
            column=col,
            labels_by_type=labels_by_type,
            descriptions_by_type=descriptions_by_type,
        )
        cp.expected = gt
        out.append(cp)
    return out


def phase_a_threshold_sweep(
    *,
    model: Any,
    model_id: str,
    corpus_name: str,
    corpus: list[tuple[ColumnInput, str | None]],
    evaluated_types: list[str],
    use_descriptions: bool | None,
) -> list[ScoredConfig]:
    """Baseline labels + description-mode fixed, sweep every threshold."""
    labels = _baseline_labels_only()
    descs = _baseline_descriptions() if (use_descriptions and _is_v2_model(model_id)) else None

    logger.info(
        "phase A: %s | %s | descriptions=%s",
        model_id,
        corpus_name,
        use_descriptions,
    )
    column_preds = run_model_once(
        model=model,
        model_id=model_id,
        corpus=corpus,
        labels_by_type=labels,
        descriptions_by_type=descs,
    )
    ground_truth = {cp.column_id: cp.expected for cp in column_preds}
    label_to_type = _build_label_to_type(labels)

    latencies = [cp.latency_ms for cp in column_preds]
    mean_latency = statistics.mean(latencies) if latencies else 0.0

    results: list[ScoredConfig] = []
    for thr in THRESHOLDS:
        macro, per_type = score_run(
            column_preds=column_preds,
            ground_truth=ground_truth,
            label_to_type=label_to_type,
            threshold=thr,
            evaluated_types=evaluated_types,
        )
        results.append(
            ScoredConfig(
                model_id=model_id,
                corpus=corpus_name,
                label_variant="baseline",
                use_descriptions=use_descriptions if _is_v2_model(model_id) else None,
                threshold=thr,
                macro_f1=round(macro, 4),
                per_type=per_type,
                mean_latency_ms_per_col=round(mean_latency, 2),
                n_columns=len(column_preds),
            )
        )
    return results


def phase_b_label_sweep(
    *,
    model: Any,
    model_id: str,
    corpus_name: str,
    corpus: list[tuple[ColumnInput, str | None]],
    evaluated_types: list[str],
    entity_types_to_sweep: Sequence[str],
    winning_threshold: float,
    use_descriptions: bool | None,
) -> list[ScoredConfig]:
    """Swap one label at a time and re-score against the phase-A winner."""
    descs = _baseline_descriptions() if (use_descriptions and _is_v2_model(model_id)) else None
    out: list[ScoredConfig] = []

    for entity in entity_types_to_sweep:
        for alt in LABEL_ALTERNATIVES.get(entity, []):
            labels = _variant_labels(entity, alt)
            label_to_type = _build_label_to_type(labels)
            tag = f"swap:{entity}={alt}"
            logger.info("phase B: %s | %s | %s", model_id, corpus_name, tag)

            column_preds = run_model_once(
                model=model,
                model_id=model_id,
                corpus=corpus,
                labels_by_type=labels,
                descriptions_by_type=descs,
            )
            ground_truth = {cp.column_id: cp.expected for cp in column_preds}
            latencies = [cp.latency_ms for cp in column_preds]
            mean_latency = statistics.mean(latencies) if latencies else 0.0

            macro, per_type = score_run(
                column_preds=column_preds,
                ground_truth=ground_truth,
                label_to_type=label_to_type,
                threshold=winning_threshold,
                evaluated_types=evaluated_types,
            )
            out.append(
                ScoredConfig(
                    model_id=model_id,
                    corpus=corpus_name,
                    label_variant=tag,
                    use_descriptions=use_descriptions if _is_v2_model(model_id) else None,
                    threshold=winning_threshold,
                    macro_f1=round(macro, 4),
                    per_type=per_type,
                    mean_latency_ms_per_col=round(mean_latency, 2),
                    n_columns=len(column_preds),
                )
            )
    return out


def best_of(scored: list[ScoredConfig]) -> ScoredConfig:
    return max(scored, key=lambda s: (s.macro_f1, -s.threshold))


# ── Orchestration ───────────────────────────────────────────────────────────


@dataclass
class ModelStatus:
    model_id: str
    loaded: bool
    message: str = ""


def run_sweep(
    *,
    quick: bool,
    max_rows: int,
) -> dict[str, Any]:
    """Run both phases and return a single serialisable dict of results."""
    evaluated_types = list(BASELINE_LABELS.keys())

    if quick:
        label_sweep_types: list[str] = _PRIORITY_TYPES
    else:
        label_sweep_types = list(LABEL_ALTERNATIVES.keys())

    t_start = time.perf_counter()
    phase_a_all: list[ScoredConfig] = []
    phase_b_all: list[ScoredConfig] = []
    model_statuses: list[ModelStatus] = []

    # Pre-load and cache corpora — restricting to columns whose ground
    # truth is one of the entity types GLiNER even knows about.
    corpora: dict[str, list[tuple[ColumnInput, str | None]]] = {}
    for corpus_name in CORPORA:
        raw = load_corpus(corpus_name, max_rows=max_rows)
        restricted = restrict_corpus(raw, evaluated_types)
        logger.info(
            "corpus %s: %d columns after restricting to evaluated types",
            corpus_name,
            len(restricted),
        )
        corpora[corpus_name] = restricted

    for model_id in MODELS:
        logger.info("─── loading model: %s ───", model_id)
        model = load_model(model_id)
        if model is None:
            model_statuses.append(
                ModelStatus(
                    model_id=model_id,
                    loaded=False,
                    message="load_model returned None (package missing or download failed)",
                )
            )
            logger.warning("skipping %s — could not load", model_id)
            continue
        model_statuses.append(ModelStatus(model_id=model_id, loaded=True))

        desc_modes: list[bool | None]
        if _is_v2_model(model_id):
            desc_modes = [True, False]
        else:
            desc_modes = [None]

        for corpus_name, corpus in corpora.items():
            per_desc_phase_a: list[list[ScoredConfig]] = []
            for mode in desc_modes:
                scored = phase_a_threshold_sweep(
                    model=model,
                    model_id=model_id,
                    corpus_name=corpus_name,
                    corpus=corpus,
                    evaluated_types=evaluated_types,
                    use_descriptions=mode if mode is not None else False,
                )
                phase_a_all.extend(scored)
                per_desc_phase_a.append(scored)

            flat_a = [s for batch in per_desc_phase_a for s in batch]
            winner = best_of(flat_a)
            logger.info(
                "phase A winner for %s on %s: thr=%.2f desc=%s F1=%.4f",
                model_id,
                corpus_name,
                winner.threshold,
                winner.use_descriptions,
                winner.macro_f1,
            )

            b_scored = phase_b_label_sweep(
                model=model,
                model_id=model_id,
                corpus_name=corpus_name,
                corpus=corpus,
                evaluated_types=evaluated_types,
                entity_types_to_sweep=label_sweep_types,
                winning_threshold=winner.threshold,
                use_descriptions=winner.use_descriptions,
            )
            phase_b_all.extend(b_scored)

        # Free memory between models.
        del model

    wall_time_s = time.perf_counter() - t_start

    return {
        "meta": {
            "mode": "quick" if quick else "full",
            "max_rows": max_rows,
            "wall_time_seconds": round(wall_time_s, 1),
            "thresholds": THRESHOLDS,
            "models": MODELS,
            "corpora": CORPORA,
            "label_sweep_types": label_sweep_types,
            "baseline_labels": {et: lbl for et, (lbl, _) in BASELINE_LABELS.items()},
            "label_alternatives": LABEL_ALTERNATIVES,
        },
        "model_statuses": [asdict(s) for s in model_statuses],
        "phase_a": [s.to_json() for s in phase_a_all],
        "phase_b": [s.to_json() for s in phase_b_all],
    }


# ── Summary + CLI ───────────────────────────────────────────────────────────


def _format_summary(results: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append(f"GLiNER evaluation — {results['meta']['mode']}")
    lines.append(f"wall time: {results['meta']['wall_time_seconds']}s   max_rows: {results['meta']['max_rows']}")
    lines.append("=" * 78)

    for status in results["model_statuses"]:
        if not status["loaded"]:
            lines.append(f"  [!] {status['model_id']}: {status['message']}")

    # Best phase-A config per (model, corpus)
    lines.append("\n-- phase A: best (threshold, description) per model × corpus --")
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for s in results["phase_a"]:
        groups.setdefault((s["model_id"], s["corpus"]), []).append(s)
    for (model_id, corpus), rows in sorted(groups.items()):
        top = max(rows, key=lambda r: r["macro_f1"])
        lines.append(
            f"  {model_id:<40} {corpus:<12} "
            f"thr={top['threshold']:.2f}  desc={top['use_descriptions']!s:<5}  "
            f"F1={top['macro_f1']:.4f}  "
            f"lat={top['mean_latency_ms_per_col']:.1f}ms/col"
        )

    # Best phase-B swap per (model, corpus)
    lines.append("\n-- phase B: best label swap per model × corpus (vs baseline winner) --")
    b_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for s in results["phase_b"]:
        b_groups.setdefault((s["model_id"], s["corpus"]), []).append(s)
    for key, rows in sorted(b_groups.items()):
        rows_sorted = sorted(rows, key=lambda r: r["macro_f1"], reverse=True)
        top = rows_sorted[0]
        lines.append(f"  {key[0]:<40} {key[1]:<12} {top['label_variant']:<32} F1={top['macro_f1']:.4f}")
    return "\n".join(lines)


def _write_outputs(results: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "GLINER_MODEL_EVALUATION.raw.json"
    summary_path = out_dir / "GLINER_MODEL_EVALUATION.summary.json"

    raw_path.write_text(json.dumps(results, indent=2, sort_keys=True))

    summary = {
        "meta": results["meta"],
        "model_statuses": results["model_statuses"],
        "phase_a_best_per_model_corpus": _best_per_key(results["phase_a"]),
        "phase_b_best_per_model_corpus": _best_per_key(results["phase_b"]),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True))


def _best_per_key(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault((r["model_id"], r["corpus"]), []).append(r)
    return [max(v, key=lambda x: x["macro_f1"]) for v in groups.values()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--quick", action="store_true", help="100-row smoke run, priority entity types only")
    mode.add_argument("--full", action="store_true", help="500-row full sweep (default)")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_REPO_ROOT / "docs" / "research",
        help="Directory for the result JSON dumps",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    quick = args.quick and not args.full
    max_rows = 100 if quick else 500

    results = run_sweep(quick=quick, max_rows=max_rows)
    print(_format_summary(results))
    _write_outputs(results, args.out_dir)
    print(f"\nwrote raw: {args.out_dir / 'GLINER_MODEL_EVALUATION.raw.json'}")
    print(f"wrote summary: {args.out_dir / 'GLINER_MODEL_EVALUATION.summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
