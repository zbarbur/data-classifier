"""Per-class diagnostic for the meta-classifier training data.

Loads a training JSONL (from
``tests/benchmarks/meta_classifier/build_training_data.py``), runs
5-fold StratifiedGroupKFold CV with a logistic-regression classifier,
and reports per-class precision / recall / F1 plus engine firing
rates. Sorted by F1 ascending so "hardest" classes surface first.

Drop-in replacement for the research-branch e11_per_class_diagnostic
(which has research-only imports); this version depends only on
tests.benchmarks.meta_classifier.evaluate's feature-loading helpers.

Usage:
    python -m tests.benchmarks.meta_classifier.per_class_diagnostic \\
        --training tests/benchmarks/meta_classifier/training_data.jsonl

This module uses ``print`` (not ``logging``) because it is a CLI
diagnostic whose stdout output IS the user interface — the per-class
table goes to stdout so a human operator can read it directly. CLAUDE.md's
"no print statements" rule is for library code; CLI entrypoints are the
documented exception, which is why each ``print`` carries an explicit
``# noqa: T201`` annotation to survive a future ruff rule addition.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# Engine-confidence feature indices in the base 15-feature layout
# (unchanged by the Sprint 11 schema widening — new one-hot slots are
# appended at index 15+).
ENGINE_CONFIDENCE_INDICES: dict[str, int] = {
    "regex": 1,
    "column_name": 2,
    "heuristic": 3,
    "secret_scanner": 4,
}


@dataclass
class Row:
    column_id: str
    corpus: str
    mode: str
    source: str
    features: list[float]
    ground_truth: str


def load_rows(path: Path) -> list[Row]:
    rows: list[Row] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            rows.append(
                Row(
                    column_id=r["column_id"],
                    corpus=r["corpus"],
                    mode=r["mode"],
                    source=r["source"],
                    features=[float(x) for x in r["features"]],
                    ground_truth=r["ground_truth"],
                )
            )
    return rows


def per_class_report(rows: list[Row], *, best_c: float = 0.1) -> None:
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import f1_score, precision_score, recall_score
    from sklearn.model_selection import StratifiedGroupKFold
    from sklearn.preprocessing import StandardScaler

    X = np.asarray([r.features for r in rows], dtype=np.float64)
    y = np.asarray([r.ground_truth for r in rows])
    groups = np.asarray([r.corpus for r in rows])

    class_counts = Counter(y.tolist())

    per_class_corpora: dict[str, Counter[str]] = {}
    for r in rows:
        per_class_corpora.setdefault(r.ground_truth, Counter())[r.corpus] += 1

    per_class_engine_fires: dict[str, dict[str, float]] = {}
    per_class_total: dict[str, int] = {}
    for r in rows:
        gt = r.ground_truth
        per_class_total[gt] = per_class_total.get(gt, 0) + 1
        d = per_class_engine_fires.setdefault(gt, {e: 0.0 for e in ENGINE_CONFIDENCE_INDICES})
        for engine, idx in ENGINE_CONFIDENCE_INDICES.items():
            if r.features[idx] > 0.0:
                d[engine] += 1
    for gt, d in per_class_engine_fires.items():
        total = per_class_total[gt]
        for engine in d:
            d[engine] = d[engine] / total if total > 0 else 0.0

    n_groups = len(set(groups.tolist()))
    n_splits = min(5, n_groups)
    kf = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=20260414)

    y_true_all: list[str] = []
    y_pred_all: list[str] = []

    for train_idx, val_idx in kf.split(X, y, groups=groups):
        scaler = StandardScaler().fit(X[train_idx])
        clf = LogisticRegression(
            C=best_c,
            max_iter=2000,
            class_weight="balanced",
            solver="lbfgs",
        )
        clf.fit(scaler.transform(X[train_idx]), y[train_idx])
        pred = clf.predict(scaler.transform(X[val_idx]))
        y_true_all.extend(y[val_idx].tolist())
        y_pred_all.extend(pred.tolist())

    all_classes = sorted(set(y_true_all))

    per_class_f1: dict[str, float] = {}
    per_class_pr: dict[str, float] = {}
    per_class_rc: dict[str, float] = {}
    for cls in all_classes:
        y_true_bin = [1 if t == cls else 0 for t in y_true_all]
        y_pred_bin = [1 if p == cls else 0 for p in y_pred_all]
        per_class_f1[cls] = f1_score(y_true_bin, y_pred_bin, zero_division=0.0)
        per_class_pr[cls] = precision_score(y_true_bin, y_pred_bin, zero_division=0.0)
        per_class_rc[cls] = recall_score(y_true_bin, y_pred_bin, zero_division=0.0)

    print(  # noqa: T201
        f"{'class':<22} {'N':>6} {'corpora':<32} "
        f"{'P':>6} {'R':>6} {'F1':>6}  "
        f"{'regex':>6} {'col':>6} {'heur':>6} {'secret':>6}"
    )
    print("-" * 120)  # noqa: T201

    sorted_classes = sorted(all_classes, key=lambda c: per_class_f1[c])
    for cls in sorted_classes:
        n = class_counts[cls]
        corpora_summary = ", ".join(f"{c}:{v}" for c, v in per_class_corpora[cls].most_common(3))[:32]
        fires = per_class_engine_fires.get(cls, {})
        print(  # noqa: T201
            f"{cls:<22} {n:>6} {corpora_summary:<32} "
            f"{per_class_pr[cls]:>6.3f} {per_class_rc[cls]:>6.3f} {per_class_f1[cls]:>6.3f}  "
            f"{fires.get('regex', 0):>6.2%} {fires.get('column_name', 0):>6.2%} "
            f"{fires.get('heuristic', 0):>6.2%} {fires.get('secret_scanner', 0):>6.2%}"
        )

    print()  # noqa: T201
    print(f"Total rows: {len(rows)}")  # noqa: T201
    print(f"Total classes: {len(all_classes)}")  # noqa: T201
    macro = sum(per_class_f1.values()) / len(per_class_f1) if per_class_f1 else 0.0
    print(f"Macro F1 (unweighted mean): {macro:.4f}")  # noqa: T201
    print(f"Classes with F1 < 0.1:  {sum(1 for f in per_class_f1.values() if f < 0.1)}")  # noqa: T201
    print(f"Classes with F1 < 0.3:  {sum(1 for f in per_class_f1.values() if f < 0.3)}")  # noqa: T201
    print(f"Classes with F1 >= 0.5: {sum(1 for f in per_class_f1.values() if f >= 0.5)}")  # noqa: T201
    print(f"Classes with F1 >= 0.8: {sum(1 for f in per_class_f1.values() if f >= 0.8)}")  # noqa: T201


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--training",
        type=Path,
        default=Path("tests/benchmarks/meta_classifier/training_data.jsonl"),
    )
    parser.add_argument(
        "--best-c",
        type=float,
        default=0.1,
        help="L2 regularization strength for LogisticRegression (default 0.1 matches train_meta_classifier best_c).",
    )
    args = parser.parse_args(argv)

    rows = load_rows(args.training)
    per_class_report(rows, best_c=args.best_c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
