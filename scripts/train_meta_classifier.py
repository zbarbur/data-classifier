"""Train the Phase 2 meta-classifier and write the model + metadata.

Usage (from repo root)::

    python -m scripts.train_meta_classifier \\
        --input tests/benchmarks/meta_classifier/training_data.jsonl \\
        --output data_classifier/models/meta_classifier_v1.pkl \\
        --metadata data_classifier/models/meta_classifier_v1.metadata.json

The model artifact is a pickled dict (decision D5 in the Phase 2 dispatch):
``{model, scaler, feature_names, class_labels, dropped_features,
random_state}``.  We produce both ends of the pickle and load it only
from a committed in-repo path, so the usual pickle-untrusted-input
caveats do not apply.

The script:

1. Loads the JSONL training data produced by
   ``tests.benchmarks.meta_classifier.build_training_data``
2. Drops constant and redundant features per Session A §2.1
3. Fits a StandardScaler + multinomial logistic regression on a
   stratified 80/20 train/test split (seed 42)
4. Performs 5-fold cross-validation over L2 strength ``C`` in the grid
   ``[0.01, 0.1, 1.0, 10.0, 100.0]``
5. Saves the trained model (scaler + classifier + feature names +
   class labels) as a pickled dict to the output path
6. Writes a sibling metadata JSON with training date, git SHA, row
   counts, CV mean ± std macro F1, held-out test macro F1, BCa 95% CI,
   and top-5 feature importances

sklearn is imported INSIDE this module on purpose — the optional `[meta]`
extra keeps the core library free of sklearn at import time.  Anything
that imports ``data_classifier`` will not pull sklearn unless this
script is run.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Deterministic RNG for every library that reads PYTHONHASHSEED or numpy.
os.environ.setdefault("PYTHONHASHSEED", "42")
os.environ.setdefault("DATA_CLASSIFIER_DISABLE_ML", "1")

# The Phase 2 model artifact is a pickled dict — we produce both ends of
# the pickle and load only from a committed in-repo path, so there is no
# untrusted-input exposure.  See D5 in the Phase 2 dispatch.
import pickle as _pickle_impl  # noqa: S403

# ── Features to drop (Session A §2.1) ──────────────────────────────────────

# Always redundant — perfectly correlated with other features in the set.
ALWAYS_DROP_REDUNDANT: tuple[str, ...] = (
    "has_column_name_hit",  # |r|>0.99 with column_name_confidence
    "engines_fired",  # |r|>0.9 with engines_agreed
)

# Candidates for dropping only IF they are still constant zero after the
# corpus expansion.  Phase 1 had these as constant; Phase 2 re-checks.
CONDITIONAL_DROP_IF_CONSTANT: tuple[str, ...] = (
    "secret_scanner_confidence",
    "has_secret_indicators",
)

RANDOM_STATE: int = 42
CV_FOLDS: int = 5
C_GRID: tuple[float, ...] = (0.01, 0.1, 1.0, 10.0, 100.0)
BOOTSTRAP_RESAMPLES: int = 2000


# ── Data loading ───────────────────────────────────────────────────────────


@dataclass
class LoadedDataset:
    features: list[list[float]]
    labels: list[str]
    column_ids: list[str]
    corpora: list[str]
    modes: list[str]
    sources: list[str]
    feature_names: list[str]


def load_jsonl(path: Path, feature_names: tuple[str, ...]) -> LoadedDataset:
    features: list[list[float]] = []
    labels: list[str] = []
    column_ids: list[str] = []
    corpora: list[str] = []
    modes: list[str] = []
    sources: list[str] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            features.append([float(x) for x in row["features"]])
            labels.append(row["ground_truth"])
            column_ids.append(row["column_id"])
            corpora.append(row["corpus"])
            modes.append(row["mode"])
            sources.append(row["source"])
    return LoadedDataset(
        features=features,
        labels=labels,
        column_ids=column_ids,
        corpora=corpora,
        modes=modes,
        sources=sources,
        feature_names=list(feature_names),
    )


def resolve_feature_subset(
    dataset: LoadedDataset,
) -> tuple[list[str], list[int]]:
    """Return (kept_feature_names, kept_column_indices).

    Drops ``ALWAYS_DROP_REDUNDANT`` unconditionally plus any
    ``CONDITIONAL_DROP_IF_CONSTANT`` column that is all-zero.
    """
    import numpy as np

    X = np.asarray(dataset.features, dtype=np.float64)

    kept_names: list[str] = []
    kept_indices: list[int] = []
    for i, name in enumerate(dataset.feature_names):
        if name in ALWAYS_DROP_REDUNDANT:
            continue
        if name in CONDITIONAL_DROP_IF_CONSTANT:
            col = X[:, i] if X.size else np.zeros(0)
            if col.size == 0 or np.all(col == 0.0):
                continue
        kept_names.append(name)
        kept_indices.append(i)
    return kept_names, kept_indices


# ── Training ───────────────────────────────────────────────────────────────


def train(
    dataset: LoadedDataset,
    *,
    kept_indices: list[int],
) -> dict[str, object]:
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import classification_report, f1_score
    from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold, train_test_split
    from sklearn.preprocessing import StandardScaler

    X_full = np.asarray(dataset.features, dtype=np.float64)[:, kept_indices]
    y = np.asarray(dataset.labels)
    column_ids = np.asarray(dataset.column_ids)
    corpora_arr = np.asarray(dataset.corpora)

    X_train, X_test, y_train, y_test, id_train, id_test, corpora_train, _corpora_test = train_test_split(
        X_full,
        y,
        column_ids,
        corpora_arr,
        test_size=0.2,
        random_state=RANDOM_STATE,
        stratify=y,
    )

    # Column-id leak invariant
    train_ids = set(id_train.tolist())
    test_ids = set(id_test.tolist())
    assert not (train_ids & test_ids), "column_id leaked between train/test"

    # Scale only on training data.
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s = scaler.transform(X_test)

    # 5-fold CV over C grid.
    # M1 fix (Sprint 9, Q3 diagnosis): use StratifiedGroupKFold with
    # groups=corpora so best-C selection does NOT reward corpus
    # fingerprinting. Prior StratifiedKFold leaked across corpora and
    # picked C=100 (worst LOCO). GroupKFold picks a smaller C and raises
    # LOCO. See docs/experiments/meta_classifier/runs/m1-2026-04-13/result.md
    # on research/meta-classifier for the honest-CV analysis.
    #
    # Adaptive fallback: when the training data has fewer unique corpora
    # than CV_FOLDS (e.g., single-corpus test fixtures), StratifiedGroupKFold
    # can't produce enough distinct folds. In that case fall back to plain
    # StratifiedKFold — there's no cross-corpus leakage to prevent when
    # there's only one corpus.
    n_unique_groups = len(np.unique(corpora_train))
    use_group_kfold = n_unique_groups >= CV_FOLDS
    if use_group_kfold:
        kf = StratifiedGroupKFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    else:
        kf = StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    best_c = 1.0
    best_cv_mean = -1.0
    best_cv_std = 0.0
    cv_history: list[dict[str, float]] = []

    for C in C_GRID:
        fold_f1s: list[float] = []
        split_iter = (
            kf.split(X_train_s, y_train, groups=corpora_train)
            if use_group_kfold
            else kf.split(X_train_s, y_train)
        )
        for tr_idx, va_idx in split_iter:
            clf = LogisticRegression(
                C=C,
                solver="lbfgs",
                max_iter=1000,
                class_weight="balanced",
                random_state=RANDOM_STATE,
            )
            clf.fit(X_train_s[tr_idx], y_train[tr_idx])
            preds = clf.predict(X_train_s[va_idx])
            fold_f1s.append(f1_score(y_train[va_idx], preds, average="macro", zero_division=0))
        mean = float(np.mean(fold_f1s))
        std = float(np.std(fold_f1s))
        cv_history.append({"C": C, "mean_f1": mean, "std_f1": std})
        if mean > best_cv_mean:
            best_cv_mean = mean
            best_cv_std = std
            best_c = C

    # Fit final model on the full train set with best C.
    final_clf = LogisticRegression(
        C=best_c,
        solver="lbfgs",
        max_iter=1000,
        class_weight="balanced",
        random_state=RANDOM_STATE,
    )
    final_clf.fit(X_train_s, y_train)

    # Held-out test set evaluation.
    test_preds = final_clf.predict(X_test_s)
    test_f1 = float(f1_score(y_test, test_preds, average="macro", zero_division=0))
    report = classification_report(y_test, test_preds, output_dict=True, zero_division=0)

    # Feature importances by sum of absolute coefficients across classes.
    coef = final_clf.coef_
    abs_sum = np.sum(np.abs(coef), axis=0)
    pairs = sorted(
        zip(range(len(abs_sum)), abs_sum.tolist(), strict=True),
        key=lambda p: -p[1],
    )
    top_importances = [
        {"feature": dataset.feature_names[kept_indices[i]], "abs_coef_sum": float(w)} for i, w in pairs[:5]
    ]

    return {
        "model": final_clf,
        "scaler": scaler,
        "best_c": best_c,
        "cv_mean_f1": best_cv_mean,
        "cv_std_f1": best_cv_std,
        "cv_history": cv_history,
        "X_train": X_train,
        "X_test": X_test,
        "y_train": y_train,
        "y_test": y_test,
        "id_train": id_train,
        "id_test": id_test,
        "test_f1": test_f1,
        "test_report": report,
        "top_importances": top_importances,
    }


# ── Bootstrap confidence interval for single-model F1 ─────────────────────


def bootstrap_f1_ci(
    y_true,
    y_pred,
    *,
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    random_state: int = RANDOM_STATE,
) -> tuple[float, float, float]:
    """BCa bootstrap 95% CI on macro-F1 of a single model."""
    import numpy as np
    from scipy.stats import bootstrap
    from sklearn.metrics import f1_score

    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)

    def stat(idx, axis: int = 0):  # noqa: ARG001 — signature required by scipy
        idx = np.asarray(idx, dtype=int)
        return f1_score(y_true[idx], y_pred[idx], average="macro", zero_division=0)

    idx = np.arange(len(y_true))
    rng = np.random.default_rng(random_state)
    res = bootstrap(
        (idx,),
        stat,
        n_resamples=n_resamples,
        method="BCa",
        random_state=rng,
        confidence_level=0.95,
        vectorized=False,
    )
    point = float(f1_score(y_true, y_pred, average="macro", zero_division=0))
    return point, float(res.confidence_interval.low), float(res.confidence_interval.high)


# ── Save artifacts ─────────────────────────────────────────────────────────


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def save_artifacts(
    trained: dict[str, object],
    *,
    kept_names: list[str],
    dataset: LoadedDataset,
    output: Path,
    metadata_path: Path,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)

    model = trained["model"]
    scaler = trained["scaler"]

    payload = {
        "model": model,
        "scaler": scaler,
        "feature_names": kept_names,
        "class_labels": list(model.classes_),
        "dropped_features": list(ALWAYS_DROP_REDUNDANT)
        + [name for name in CONDITIONAL_DROP_IF_CONSTANT if name not in kept_names and name in dataset.feature_names],
        "random_state": RANDOM_STATE,
    }
    with output.open("wb") as f:
        _pickle_impl.dump(payload, f)

    # Confidence interval on the held-out test set macro F1.
    y_test = trained["y_test"]
    X_test_s = scaler.transform(trained["X_test"])
    test_preds = model.predict(X_test_s)
    test_f1, ci_low, ci_high = bootstrap_f1_ci(y_test, test_preds)

    # Per-class counts in the full dataset.
    from collections import Counter

    class_counts = Counter(dataset.labels)

    metadata = {
        "training_date": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "random_state": RANDOM_STATE,
        "cv_folds": CV_FOLDS,
        "c_grid": list(C_GRID),
        "best_c": trained["best_c"],
        "cv_mean_macro_f1": trained["cv_mean_f1"],
        "cv_std_macro_f1": trained["cv_std_f1"],
        "cv_history": trained["cv_history"],
        "held_out_test_macro_f1": test_f1,
        "held_out_test_ci_95_bca": {"low": ci_low, "high": ci_high, "width": ci_high - ci_low},
        "total_rows": len(dataset.labels),
        "per_class_counts": dict(sorted(class_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "train_rows": int(len(trained["y_train"])),
        "test_rows": int(len(trained["y_test"])),
        "feature_names": kept_names,
        "dropped_features": payload["dropped_features"],
        "class_labels": list(map(str, model.classes_)),
        "top_5_feature_importances": trained["top_importances"],
        "per_class_f1_on_test": {
            label: {
                "precision": float(v["precision"]),
                "recall": float(v["recall"]),
                "f1": float(v["f1-score"]),
                "support": int(v["support"]),
            }
            for label, v in trained["test_report"].items()
            if isinstance(v, dict) and label not in {"accuracy", "macro avg", "weighted avg"}
        },
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, default=str))

    print(f"Saved model to {output}")
    print(f"Saved metadata to {metadata_path}")
    print(f"  best C = {trained['best_c']}")
    print(f"  CV mean macro F1 = {trained['cv_mean_f1']:.4f} ± {trained['cv_std_f1']:.4f}")
    print(f"  held-out test macro F1 = {test_f1:.4f}")
    print(f"  95% BCa CI = [{ci_low:.4f}, {ci_high:.4f}] (width {ci_high - ci_low:.4f})")
    print("  top 5 features:")
    for entry in trained["top_importances"]:
        print(f"    {entry['feature']:<32} {entry['abs_coef_sum']:.4f}")


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
        default=Path("data_classifier/models/meta_classifier_v1.pkl"),
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=Path("data_classifier/models/meta_classifier_v1.metadata.json"),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # Use the canonical feature-name list from the library skeleton.
    from data_classifier.orchestrator.meta_classifier import FEATURE_NAMES

    dataset = load_jsonl(args.input, FEATURE_NAMES)
    if not dataset.labels:
        print(f"No training rows in {args.input}", file=sys.stderr)
        return 1

    kept_names, kept_indices = resolve_feature_subset(dataset)
    print(f"Loaded {len(dataset.labels)} rows; using {len(kept_names)} features: {kept_names}")

    trained = train(dataset, kept_indices=kept_indices)
    save_artifacts(
        trained,
        kept_names=kept_names,
        dataset=dataset,
        output=args.output,
        metadata_path=args.metadata,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
