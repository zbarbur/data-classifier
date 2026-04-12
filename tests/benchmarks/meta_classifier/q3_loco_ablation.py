"""Q3 LOCO collapse investigation — feature ablation over the 13-D schema.

Diagnostic script only.  Runs two ablations against the Phase 2
training data:

1. **Forward drop-one.**  For each feature in the 13 effective dimensions
   (after dropping ALWAYS_DROP_REDUNDANT), retrain a logistic regression
   without that feature and measure LOCO macro F1 on ai4privacy and
   nemotron holdouts.  A feature whose removal IMPROVES LOCO is
   corpus-leaking.

2. **Inverse keep-one.**  For each feature, train a model whose only
   input is that single feature (+ intercept) and measure LOCO macro F1.
   The feature with the highest standalone LOCO F1 is the most
   universally generalizable signal.

Both ablations match the LOCO configuration used in
``tests/benchmarks/meta_classifier/evaluate.py``:
C=100.0, class_weight=balanced, StandardScaler fit on training corpora
only, seed 42.

Usage::

    python -m tests.benchmarks.meta_classifier.q3_loco_ablation \\
        --input tests/benchmarks/meta_classifier/training_data.jsonl \\
        --output /tmp/q3_ablation.json

The script does NOT modify any production code path and does NOT load
or touch ``meta_classifier_v1.pkl``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

os.environ.setdefault("PYTHONHASHSEED", "42")
os.environ.setdefault("DATA_CLASSIFIER_DISABLE_ML", "1")

from data_classifier.orchestrator.meta_classifier import FEATURE_NAMES  # noqa: E402
from scripts.train_meta_classifier import (  # noqa: E402
    RANDOM_STATE,
    LoadedDataset,
    load_jsonl,
    resolve_feature_subset,
)

# LOCO holdouts to match evaluate.py
LOCO_HOLDOUTS: tuple[str, ...] = ("ai4privacy", "nemotron")


@dataclass
class AblationRow:
    label: str
    feature: str | None
    loco_f1_ai4privacy: float
    loco_f1_nemotron: float

    @property
    def mean_loco(self) -> float:
        return 0.5 * (self.loco_f1_ai4privacy + self.loco_f1_nemotron)


@dataclass
class AblationReport:
    baseline: AblationRow
    drop_one: list[AblationRow] = field(default_factory=list)
    keep_one: list[AblationRow] = field(default_factory=list)


# ── LOCO fit/predict helper ────────────────────────────────────────────────


def _loco_f1(
    features,  # np.ndarray (n_rows, n_kept_features)
    y,  # np.ndarray (n_rows,)
    corpora,  # np.ndarray (n_rows,)
    *,
    subset_indices: list[int],
    holdout: str,
) -> float:
    """Fit LR on all rows not in holdout, predict on holdout rows.

    Returns macro F1 on the holdout.  Empty holdouts or empty training
    sets return NaN so they are obvious in the report.
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import f1_score
    from sklearn.preprocessing import StandardScaler

    if not subset_indices:
        return float("nan")

    feats = features[:, subset_indices]
    tr_mask = corpora != holdout
    te_mask = corpora == holdout
    if tr_mask.sum() == 0 or te_mask.sum() == 0:
        return float("nan")

    x_tr = feats[tr_mask]
    x_te = feats[te_mask]
    y_tr = y[tr_mask]
    y_te = y[te_mask]

    # Single-feature training sets need a 2-D shape.
    if x_tr.ndim == 1:
        x_tr = x_tr.reshape(-1, 1)
        x_te = x_te.reshape(-1, 1)

    scaler = StandardScaler()
    x_tr_s = scaler.fit_transform(x_tr)
    x_te_s = scaler.transform(x_te)

    clf = LogisticRegression(
        C=100.0,
        solver="lbfgs",
        max_iter=2000,
        class_weight="balanced",
        random_state=RANDOM_STATE,
    )
    clf.fit(x_tr_s, y_tr)
    preds = clf.predict(x_te_s)
    return float(f1_score(y_te, preds, average="macro", zero_division=0))


# ── Ablation driver ────────────────────────────────────────────────────────


def run_ablation(dataset: LoadedDataset) -> AblationReport:
    import numpy as np

    kept_names, kept_indices = resolve_feature_subset(dataset)
    features = np.asarray(dataset.features, dtype=np.float64)[:, kept_indices]
    y = np.asarray(dataset.labels)
    corpora = np.asarray(dataset.corpora)

    all_idx = list(range(len(kept_names)))

    baseline = AblationRow(
        label="baseline (all 13)",
        feature=None,
        loco_f1_ai4privacy=_loco_f1(features, y, corpora, subset_indices=all_idx, holdout="ai4privacy"),
        loco_f1_nemotron=_loco_f1(features, y, corpora, subset_indices=all_idx, holdout="nemotron"),
    )
    report = AblationReport(baseline=baseline)

    # Forward drop-one.
    for i, name in enumerate(kept_names):
        subset = [j for j in all_idx if j != i]
        row = AblationRow(
            label=f"drop {name}",
            feature=name,
            loco_f1_ai4privacy=_loco_f1(features, y, corpora, subset_indices=subset, holdout="ai4privacy"),
            loco_f1_nemotron=_loco_f1(features, y, corpora, subset_indices=subset, holdout="nemotron"),
        )
        report.drop_one.append(row)

    # Inverse keep-one.
    for i, name in enumerate(kept_names):
        subset = [i]
        row = AblationRow(
            label=f"keep only {name}",
            feature=name,
            loco_f1_ai4privacy=_loco_f1(features, y, corpora, subset_indices=subset, holdout="ai4privacy"),
            loco_f1_nemotron=_loco_f1(features, y, corpora, subset_indices=subset, holdout="nemotron"),
        )
        report.keep_one.append(row)

    return report


# ── Candidate model training (if hypothesis A/B) ───────────────────────────


def train_candidate(
    dataset: LoadedDataset,
    *,
    drop_feature_names: list[str],
    output: Path,
    metadata_path: Path,
    force_c: float | None = None,
) -> dict[str, float]:
    """Retrain the full meta-classifier pipeline with the given features
    dropped, and save the resulting pkl + metadata to the candidate
    paths.  Uses the production training pipeline verbatim so the
    payload format matches meta_classifier_v1.pkl.

    If ``force_c`` is given, the CV sweep is collapsed to a single
    value.  This lets Q3 save a candidate at the LOCO-optimal C without
    the production CV defaulting back to the i.i.d.-best C.
    """
    import scripts.train_meta_classifier as tmc

    kept_names, kept_indices = resolve_feature_subset(dataset)
    filtered_names: list[str] = []
    filtered_indices: list[int] = []
    for name, idx in zip(kept_names, kept_indices, strict=True):
        if name in drop_feature_names:
            continue
        filtered_names.append(name)
        filtered_indices.append(idx)

    saved_grid = tmc.C_GRID
    try:
        if force_c is not None:
            tmc.C_GRID = (float(force_c),)
        trained = tmc.train(dataset, kept_indices=filtered_indices)
        tmc.save_artifacts(
            trained,
            kept_names=filtered_names,
            dataset=dataset,
            output=output,
            metadata_path=metadata_path,
        )
    finally:
        tmc.C_GRID = saved_grid

    return {
        "cv_mean_f1": float(trained["cv_mean_f1"]),
        "cv_std_f1": float(trained["cv_std_f1"]),
        "test_f1": float(trained["test_f1"]),
        "best_c": float(trained["best_c"]),
    }


def loco_for_candidate(
    dataset: LoadedDataset,
    *,
    drop_feature_names: list[str],
) -> dict[str, float]:
    """Compute LOCO macro F1 for a candidate feature subset."""
    import numpy as np

    kept_names, kept_indices = resolve_feature_subset(dataset)
    features = np.asarray(dataset.features, dtype=np.float64)[:, kept_indices]
    y = np.asarray(dataset.labels)
    corpora = np.asarray(dataset.corpora)

    subset = [i for i, name in enumerate(kept_names) if name not in drop_feature_names]
    return {
        "ai4privacy": _loco_f1(features, y, corpora, subset_indices=subset, holdout="ai4privacy"),
        "nemotron": _loco_f1(features, y, corpora, subset_indices=subset, holdout="nemotron"),
    }


# ── Reporting ──────────────────────────────────────────────────────────────


def print_report(report: AblationReport, stream=sys.stdout) -> None:
    def _fmt(row: AblationRow) -> str:
        return (
            f"  {row.label:<44} "
            f"ai4p={row.loco_f1_ai4privacy:.4f}  "
            f"nemo={row.loco_f1_nemotron:.4f}  "
            f"mean={row.mean_loco:.4f}"
        )

    print("=" * 78, file=stream)
    print("BASELINE", file=stream)
    print("=" * 78, file=stream)
    print(_fmt(report.baseline), file=stream)

    print(file=stream)
    print("=" * 78, file=stream)
    print("FORWARD ABLATION (drop-one)  — sorted by mean LOCO desc", file=stream)
    print("=" * 78, file=stream)
    drop_sorted = sorted(report.drop_one, key=lambda r: -r.mean_loco)
    for row in drop_sorted:
        delta = row.mean_loco - report.baseline.mean_loco
        marker = "  ↑" if delta > 0.005 else ("  ↓" if delta < -0.005 else "  =")
        print(_fmt(row) + f"  Δ={delta:+.4f}{marker}", file=stream)

    print(file=stream)
    print("=" * 78, file=stream)
    print("INVERSE ABLATION (keep-one)  — sorted by mean LOCO desc", file=stream)
    print("=" * 78, file=stream)
    keep_sorted = sorted(report.keep_one, key=lambda r: -r.mean_loco)
    for row in keep_sorted:
        print(_fmt(row), file=stream)


def report_to_dict(report: AblationReport) -> dict[str, object]:
    def _row(r: AblationRow) -> dict[str, object]:
        return {
            "label": r.label,
            "feature": r.feature,
            "loco_f1_ai4privacy": r.loco_f1_ai4privacy,
            "loco_f1_nemotron": r.loco_f1_nemotron,
            "mean_loco": r.mean_loco,
        }

    return {
        "baseline": _row(report.baseline),
        "drop_one": [_row(r) for r in report.drop_one],
        "keep_one": [_row(r) for r in report.keep_one],
    }


# ── CLI ────────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("tests/benchmarks/meta_classifier/training_data.jsonl"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON output path for the ablation report.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    dataset = load_jsonl(args.input, FEATURE_NAMES)
    print(f"Loaded {len(dataset.labels)} rows from {args.input}")
    report = run_ablation(dataset)
    print_report(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report_to_dict(report), indent=2))
        print(f"\nWrote JSON report to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
