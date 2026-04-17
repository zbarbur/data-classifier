"""Train binary PII gate — 4 model arms on v5's 49-feature vector.

Research-track experiment (Sprint 14 backlog item
``research-binary-pii-gate-model-evaluation``). Evaluates whether a
binary "is this real PII?" gate can suppress the 273 NEGATIVE FPs
surfaced by Sprint 13's family benchmark without regressing true-
positive recall.

Four arms evaluated on the same split, same features, same CV folds:

    G0_LR                 LogisticRegression(C=1.0, class_weight='balanced')
    G1_LR_interactions    LR + top-5 pairwise interaction features
    G2_XGBoost            XGBClassifier(n_estimators=100, max_depth=4,
                                       scale_pos_weight=auto)
    G3_MLP                MLPClassifier(hidden_layer_sizes=(32,), max_iter=500)

Per-arm metrics:
    CV              mean/std F1, precision, recall, AUC-ROC, Brier
    LOCO            per-corpus F1 on a user-specified subset
    Threshold       PR curve, threshold where recall>=0.99, FP suppression
    Importance      LR coefs (G0/G1), SHAP (G2/G3)

Promotion decision (written to memo as GREEN/YELLOW/RED):
    GREEN   LOCO F1 >= 0.85 AND FP suppression >= 50% at recall>=0.99
    YELLOW  LOCO F1 in [0.75, 0.85] OR FP suppression in [30%, 50%]
    RED     LOCO F1 < 0.75 OR FP suppression < 30%

Usage (from repo root)::

    # Smoke test (first 200 rows, G0 only):
    .venv/bin/python -m scripts.train_binary_pii_gate --smoke

    # Full run (all 4 arms, default LOCO subset):
    .venv/bin/python -m scripts.train_binary_pii_gate

    # Custom LOCO subset:
    .venv/bin/python -m scripts.train_binary_pii_gate \\
        --loco-subset secretbench,nemotron,gretel_en,gitleaks

    # Custom output directory:
    .venv/bin/python -m scripts.train_binary_pii_gate \\
        --out-dir docs/experiments/meta_classifier/runs/20260417-binary-pii-gate-v1

The script is print-based (not logging) because it is a research CLI
whose stdout IS the interactive progress report, matching the pattern
established by ``scripts/train_meta_classifier.py`` and the M4d
labeler driver.

Research-ml extras (xgboost, shap) must be installed:

    .venv/bin/pip install -e ".[research-ml]"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

os.environ.setdefault("PYTHONHASHSEED", "42")
os.environ.setdefault("DATA_CLASSIFIER_DISABLE_ML", "1")

# Keep feature schema wiring central — FEATURE_NAMES and FEATURE_SCHEMA_VERSION
# are the canonical definitions.
from data_classifier.orchestrator.meta_classifier import (  # noqa: E402
    FEATURE_NAMES,
    FEATURE_SCHEMA_VERSION,
)

# Import primitives from the production training script. Research ownership
# contract: we append to train_meta_classifier.py additively; read-only
# imports are always safe.
from scripts.train_meta_classifier import (  # noqa: E402
    CV_FOLDS,
    RANDOM_STATE,
    LoadedDataset,
    load_jsonl,
    resolve_feature_subset,
)

if TYPE_CHECKING:
    import numpy as np

DEFAULT_INPUT = Path("tests/benchmarks/meta_classifier/training_data_binary_gate.jsonl")
DEFAULT_LOCO_SUBSET = ("secretbench", "nemotron", "gretel_en")
TARGET_RECALL = 0.99  # threshold-selection target
BRIER_SKILL_FLOOR = 0.0  # Brier below this is worse than constant baseline


# ── Arm results schema ────────────────────────────────────────────────────


@dataclass
class ArmResult:
    """All metrics + snapshots for one model arm."""

    name: str
    # CV metrics (means over 5 folds)
    cv_mean_f1: float = 0.0
    cv_std_f1: float = 0.0
    cv_mean_precision: float = 0.0
    cv_mean_recall: float = 0.0
    cv_mean_auc_roc: float = 0.0
    cv_mean_brier: float = 0.0
    # Held-out test metrics (single-threshold)
    test_f1: float = 0.0
    test_precision: float = 0.0
    test_recall: float = 0.0
    test_auc_roc: float = 0.0
    # Threshold sweep result — threshold where test recall >= TARGET_RECALL
    best_threshold: float = 0.5
    fp_suppression_at_best: float = 0.0
    recall_at_best: float = 0.0
    precision_at_best: float = 0.0
    # Threshold sweep — serialized as list of dicts
    threshold_sweep: list[dict[str, float]] = field(default_factory=list)
    # LOCO results — corpus -> {f1, precision, recall, fp_suppression}
    loco_per_corpus: dict[str, dict[str, float]] = field(default_factory=dict)
    # Feature importance — list of {feature, importance, rank}
    feature_importance: list[dict[str, object]] = field(default_factory=list)
    # Training time (seconds) for cost/benefit
    train_seconds: float = 0.0


# ── Data prep ─────────────────────────────────────────────────────────────


def binary_target(labels: list[str]) -> np.ndarray:
    """y = 1 if label != 'NEGATIVE' (is real PII), 0 if NEGATIVE (not PII)."""
    import numpy as np

    return (np.asarray(labels) != "NEGATIVE").astype(int)


def base_shard_ids_from(column_ids: np.ndarray, modes: np.ndarray) -> np.ndarray:
    """Collapse named/blind shard twins onto a single base ID.

    Duplicates the helper in ``train_meta_classifier.train()`` so the
    shard-twin leak invariant can be enforced here too. Sprint 11 Phase
    4 fix — do not delete.
    """
    import numpy as np

    return np.asarray(
        [cid.replace(f"_{m}_", "_base_", 1) for cid, m in zip(column_ids, modes, strict=True)],
    )


def split_train_test(
    X: "np.ndarray",
    y: "np.ndarray",
    column_ids: "np.ndarray",
    corpora: "np.ndarray",
    modes: "np.ndarray",
) -> dict[str, object]:
    """80/20 split with shard-twin leak protection.

    Adaptive fallback to stratified split when group count < 5 (unit-
    test fixtures). Production training data has thousands of groups.
    """
    import numpy as np
    from sklearn.model_selection import StratifiedGroupKFold, train_test_split

    base_ids = base_shard_ids_from(column_ids, modes)
    n_groups = len(np.unique(base_ids))
    if n_groups >= 5:
        sgkf = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
        train_idx, test_idx = next(sgkf.split(X, y, groups=base_ids))
        # Shard-twin leak invariant (Sprint 11 Phase 4).
        train_base = set(base_ids[train_idx].tolist())
        test_base = set(base_ids[test_idx].tolist())
        assert not (train_base & test_base), "shard-twin leak"
        return {
            "X_train": X[train_idx],
            "X_test": X[test_idx],
            "y_train": y[train_idx],
            "y_test": y[test_idx],
            "corpora_train": corpora[train_idx],
            "corpora_test": corpora[test_idx],
            "base_train": base_ids[train_idx],
            "base_test": base_ids[test_idx],
            "ids_train": column_ids[train_idx],
            "ids_test": column_ids[test_idx],
        }
    (X_train, X_test, y_train, y_test, c_train, c_test, m_train, m_test, id_train, id_test) = train_test_split(
        X,
        y,
        corpora,
        modes,
        column_ids,
        test_size=0.2,
        random_state=RANDOM_STATE,
        stratify=y,
    )
    return {
        "X_train": X_train,
        "X_test": X_test,
        "y_train": y_train,
        "y_test": y_test,
        "corpora_train": c_train,
        "corpora_test": c_test,
        "base_train": base_shard_ids_from(id_train, m_train),
        "base_test": base_shard_ids_from(id_test, m_test),
        "ids_train": id_train,
        "ids_test": id_test,
    }


def top_k_pairwise_interactions(
    X: "np.ndarray",
    y: "np.ndarray",
    feature_names: list[str],
    k: int = 5,
) -> list[tuple[int, int, str]]:
    """Return the top-k (i, j, name) pairwise interactions by |corr to y|.

    Mirrors v5 A2's approach: score each product x_i * x_j by its
    absolute Pearson correlation with the binary target and keep the
    top-k.
    """
    import numpy as np

    n_feat = X.shape[1]
    scores: list[tuple[float, int, int]] = []
    y_centered = y - y.mean()
    y_std = y.std() if y.std() > 0 else 1.0
    for i in range(n_feat):
        xi = X[:, i]
        for j in range(i + 1, n_feat):
            xj = X[:, j]
            prod = xi * xj
            if prod.std() == 0:
                continue
            r = float(np.mean((prod - prod.mean()) * y_centered) / (prod.std() * y_std))
            scores.append((abs(r), i, j))
    scores.sort(reverse=True)
    return [(i, j, f"{feature_names[i]}__X__{feature_names[j]}") for _, i, j in scores[:k]]


def add_interaction_features(
    X: "np.ndarray",
    pairs: list[tuple[int, int, str]],
) -> "np.ndarray":
    import numpy as np

    cols = [X[:, i] * X[:, j] for i, j, _ in pairs]
    if not cols:
        return X
    return np.column_stack([X, *cols])


# ── Arm trainers ──────────────────────────────────────────────────────────


def cv_metrics(
    clf_factory,
    X_train: "np.ndarray",
    y_train: "np.ndarray",
    groups: "np.ndarray",
    scaler: object | None = None,
) -> dict[str, float]:
    """5-fold grouped CV with F1, precision, recall, AUC-ROC, Brier.

    ``clf_factory`` is a zero-arg callable returning a fresh untrained
    estimator. ``scaler`` is an optional preprocessor (fit per fold to
    prevent train/validation leakage).
    """
    import numpy as np
    from sklearn.metrics import brier_score_loss, f1_score, precision_score, recall_score, roc_auc_score
    from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold

    n_groups = len(np.unique(groups))
    use_group = n_groups >= CV_FOLDS
    kf = (
        StratifiedGroupKFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_STATE)
        if use_group
        else StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    )
    split_iter = kf.split(X_train, y_train, groups=groups) if use_group else kf.split(X_train, y_train)

    f1s, precs, recs, aucs, briers = [], [], [], [], []
    for tr, va in split_iter:
        X_tr, X_va = X_train[tr], X_train[va]
        y_tr, y_va = y_train[tr], y_train[va]
        if scaler is not None:
            s = type(scaler)()
            s.fit(X_tr)
            X_tr, X_va = s.transform(X_tr), s.transform(X_va)
        clf = clf_factory()
        clf.fit(X_tr, y_tr)
        preds = clf.predict(X_va)
        # predict_proba for AUC / Brier; fall back to decision_function for linear SVM-ish arms.
        if hasattr(clf, "predict_proba"):
            probs = clf.predict_proba(X_va)[:, 1]
        elif hasattr(clf, "decision_function"):
            probs = clf.decision_function(X_va)
            # Min-max normalize so Brier is defined in [0, 1].
            if probs.max() > probs.min():
                probs = (probs - probs.min()) / (probs.max() - probs.min())
        else:
            probs = preds.astype(float)
        f1s.append(f1_score(y_va, preds, zero_division=0))
        precs.append(precision_score(y_va, preds, zero_division=0))
        recs.append(recall_score(y_va, preds, zero_division=0))
        # AUC undefined if one class missing in y_va.
        if len(set(y_va)) == 2:
            aucs.append(roc_auc_score(y_va, probs))
        briers.append(brier_score_loss(y_va, probs))

    return {
        "cv_mean_f1": float(np.mean(f1s)),
        "cv_std_f1": float(np.std(f1s)),
        "cv_mean_precision": float(np.mean(precs)),
        "cv_mean_recall": float(np.mean(recs)),
        "cv_mean_auc_roc": float(np.mean(aucs)) if aucs else float("nan"),
        "cv_mean_brier": float(np.mean(briers)),
    }


def threshold_sweep(
    y_true: "np.ndarray",
    probs: "np.ndarray",
    n_points: int = 40,
) -> tuple[list[dict[str, float]], float, dict[str, float]]:
    """Return (sweep_rows, best_threshold, best_row) at recall>=TARGET_RECALL.

    best_threshold is the smallest threshold (most permissive) where
    positive-class recall >= TARGET_RECALL — i.e., the gate keeps
    virtually all real PII through.  best_row captures P/R/FP-suppression
    at that threshold.
    """
    import numpy as np

    # Include edges + a few fine points near the natural operating region.
    thresholds = list(np.linspace(0.01, 0.99, n_points))
    rows: list[dict[str, float]] = []
    total_neg = int((y_true == 0).sum())
    # Ensure monotonic reading order.
    for t in thresholds:
        preds = (probs >= t).astype(int)
        tp = int(((preds == 1) & (y_true == 1)).sum())
        fp = int(((preds == 1) & (y_true == 0)).sum())
        fn = int(((preds == 0) & (y_true == 1)).sum())
        tn = int(((preds == 0) & (y_true == 0)).sum())
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        fp_suppression = (tn / total_neg) if total_neg > 0 else float("nan")
        rows.append(
            {
                "threshold": float(t),
                "precision": float(prec),
                "recall": float(rec),
                "fp_suppression": float(fp_suppression),
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "tn": tn,
            },
        )

    # Lowest threshold where recall >= TARGET_RECALL (maximize FP suppression
    # subject to the recall floor).
    eligible = [r for r in rows if r["recall"] >= TARGET_RECALL]
    best_row = max(eligible, key=lambda r: r["fp_suppression"]) if eligible else rows[0]
    return rows, best_row["threshold"], best_row


def loco_evaluate(
    arm_name: str,
    clf_factory,
    X: "np.ndarray",
    y: "np.ndarray",
    corpora: "np.ndarray",
    loco_subset: tuple[str, ...],
    scaler_factory=None,
) -> dict[str, dict[str, float]]:
    """Per-corpus leave-one-out evaluation.

    For each corpus in ``loco_subset``: fit on rows from all OTHER
    corpora, predict on rows from THIS corpus, report F1 + P/R + FP
    suppression.
    """
    from sklearn.metrics import f1_score, precision_score, recall_score

    out: dict[str, dict[str, float]] = {}
    for held_out in loco_subset:
        test_mask = corpora == held_out
        train_mask = ~test_mask
        if test_mask.sum() == 0 or train_mask.sum() == 0:
            out[held_out] = {
                "f1": float("nan"),
                "precision": float("nan"),
                "recall": float("nan"),
                "fp_suppression": float("nan"),
                "n_test": int(test_mask.sum()),
                "skipped": 1.0,
            }
            continue
        X_tr, X_te = X[train_mask], X[test_mask]
        y_tr, y_te = y[train_mask], y[test_mask]
        if scaler_factory is not None:
            scaler = scaler_factory()
            scaler.fit(X_tr)
            X_tr, X_te = scaler.transform(X_tr), scaler.transform(X_te)
        clf = clf_factory()
        clf.fit(X_tr, y_tr)
        preds = clf.predict(X_te)
        total_neg = int((y_te == 0).sum())
        tn = int(((preds == 0) & (y_te == 0)).sum())
        out[held_out] = {
            "f1": float(f1_score(y_te, preds, zero_division=0)),
            "precision": float(precision_score(y_te, preds, zero_division=0)),
            "recall": float(recall_score(y_te, preds, zero_division=0)),
            "fp_suppression": float(tn / total_neg) if total_neg > 0 else float("nan"),
            "n_test": int(len(y_te)),
            "n_neg": total_neg,
        }
    return out


def feature_importance_lr(
    clf,
    feature_names: list[str],
) -> list[dict[str, object]]:
    """Logistic regression: absolute coefficient ranking with signed direction."""
    import numpy as np

    coefs = clf.coef_[0]
    abs_coefs = np.abs(coefs)
    order = np.argsort(-abs_coefs)
    return [
        {
            "feature": feature_names[i],
            "abs_importance": float(abs_coefs[i]),
            "coef": float(coefs[i]),
            "direction": "positive" if coefs[i] > 0 else "negative",
            "rank": int(r + 1),
        }
        for r, i in enumerate(order[:10])
    ]


def feature_importance_shap(
    clf,
    X_bg: "np.ndarray",
    X_eval: "np.ndarray",
    feature_names: list[str],
    *,
    n_bg: int = 100,
    n_eval: int = 200,
) -> list[dict[str, object]]:
    """SHAP-based mean |contribution| for non-linear arms (G2, G3)."""
    import numpy as np
    import shap

    rng = np.random.default_rng(RANDOM_STATE)
    bg_idx = rng.choice(len(X_bg), min(n_bg, len(X_bg)), replace=False)
    eval_idx = rng.choice(len(X_eval), min(n_eval, len(X_eval)), replace=False)
    bg = X_bg[bg_idx]
    evl = X_eval[eval_idx]

    # Use the tree explainer for XGBoost, KernelExplainer otherwise.
    try:
        explainer = shap.TreeExplainer(clf)
        vals = explainer.shap_values(evl)
    except Exception:
        explainer = shap.KernelExplainer(
            clf.predict_proba if hasattr(clf, "predict_proba") else clf.predict,
            bg,
        )
        vals = explainer.shap_values(evl, nsamples=100, silent=True)

    # vals shape: (n_eval, n_features) for binary or (n_classes, n_eval, n_features)
    arr = np.asarray(vals)
    if arr.ndim == 3:
        arr = arr[1]  # positive class
    mean_abs = np.abs(arr).mean(axis=0)
    order = np.argsort(-mean_abs)
    return [
        {
            "feature": feature_names[i],
            "abs_importance": float(mean_abs[i]),
            "rank": int(r + 1),
        }
        for r, i in enumerate(order[:10])
    ]


# ── Per-arm driver ────────────────────────────────────────────────────────


def run_arm(
    arm: str,
    feature_names: list[str],
    split: dict[str, object],
    loco_subset: tuple[str, ...],
) -> ArmResult:
    import time

    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score
    from sklearn.neural_network import MLPClassifier
    from sklearn.preprocessing import StandardScaler

    result = ArmResult(name=arm)
    X_train, y_train = split["X_train"], split["y_train"]
    X_test, y_test = split["X_test"], split["y_test"]
    groups = split["corpora_train"]
    corpora_all = np.concatenate([split["corpora_train"], split["corpora_test"]])
    X_all = np.concatenate([X_train, X_test])
    y_all = np.concatenate([y_train, y_test])

    t_start = time.time()

    if arm == "G0_LR":
        factory = lambda: LogisticRegression(  # noqa: E731
            C=1.0,
            solver="lbfgs",
            max_iter=1000,
            class_weight="balanced",
            random_state=RANDOM_STATE,
        )
        scaler_factory = StandardScaler
        cv = cv_metrics(factory, X_train, y_train, groups, scaler=StandardScaler())
        # Fit final for test + importance
        scaler = StandardScaler()
        scaler.fit(X_train)
        clf = factory()
        clf.fit(scaler.transform(X_train), y_train)
        probs_test = clf.predict_proba(scaler.transform(X_test))[:, 1]
        importance = feature_importance_lr(clf, feature_names)
        scaler.transform(X_train)
        scaler.transform(X_test)

    elif arm == "G1_LR_interactions":
        pairs = top_k_pairwise_interactions(X_train, y_train, feature_names, k=5)
        interaction_names = [p[2] for p in pairs]
        all_names = feature_names + interaction_names
        X_train_int = add_interaction_features(X_train, pairs)
        X_test_int = add_interaction_features(X_test, pairs)
        X_all_int = np.concatenate([X_train_int, X_test_int])
        factory = lambda: LogisticRegression(  # noqa: E731
            C=1.0,
            solver="lbfgs",
            max_iter=1000,
            class_weight="balanced",
            random_state=RANDOM_STATE,
        )
        scaler_factory = StandardScaler
        cv = cv_metrics(factory, X_train_int, y_train, groups, scaler=StandardScaler())
        scaler = StandardScaler()
        scaler.fit(X_train_int)
        clf = factory()
        clf.fit(scaler.transform(X_train_int), y_train)
        probs_test = clf.predict_proba(scaler.transform(X_test_int))[:, 1]
        importance = feature_importance_lr(clf, all_names)
        scaler.transform(X_train_int)
        scaler.transform(X_test_int)
        # For LOCO below, use the pre-scaled interaction-augmented matrix.
        X_all_for_loco = X_all_int

    elif arm == "G2_XGBoost":
        from xgboost import XGBClassifier

        pos = float((y_train == 1).sum())
        neg = float((y_train == 0).sum())
        scale_pos_weight = neg / pos if pos > 0 else 1.0
        factory = lambda: XGBClassifier(  # noqa: E731
            n_estimators=100,
            max_depth=4,
            scale_pos_weight=scale_pos_weight,
            random_state=RANDOM_STATE,
            n_jobs=1,
            eval_metric="logloss",
            verbosity=0,
        )
        scaler_factory = None  # XGBoost doesn't need scaling.
        cv = cv_metrics(factory, X_train, y_train, groups, scaler=None)
        clf = factory()
        clf.fit(X_train, y_train)
        probs_test = clf.predict_proba(X_test)[:, 1]
        importance = feature_importance_shap(clf, X_train, X_test, feature_names)

    elif arm == "G3_MLP":
        factory = lambda: MLPClassifier(  # noqa: E731
            hidden_layer_sizes=(32,),
            max_iter=500,
            random_state=RANDOM_STATE,
        )
        scaler_factory = StandardScaler
        cv = cv_metrics(factory, X_train, y_train, groups, scaler=StandardScaler())
        scaler = StandardScaler()
        scaler.fit(X_train)
        clf = factory()
        clf.fit(scaler.transform(X_train), y_train)
        probs_test = clf.predict_proba(scaler.transform(X_test))[:, 1]
        importance = feature_importance_shap(clf, scaler.transform(X_train), scaler.transform(X_test), feature_names)
        scaler.transform(X_train)
        scaler.transform(X_test)

    else:
        raise ValueError(f"Unknown arm: {arm}")

    # Apply CV metrics.
    result.cv_mean_f1 = cv["cv_mean_f1"]
    result.cv_std_f1 = cv["cv_std_f1"]
    result.cv_mean_precision = cv["cv_mean_precision"]
    result.cv_mean_recall = cv["cv_mean_recall"]
    result.cv_mean_auc_roc = cv["cv_mean_auc_roc"]
    result.cv_mean_brier = cv["cv_mean_brier"]

    # Held-out test set metrics at threshold 0.5.
    preds_test = (probs_test >= 0.5).astype(int)
    result.test_f1 = float(f1_score(y_test, preds_test, zero_division=0))
    result.test_precision = float(precision_score(y_test, preds_test, zero_division=0))
    result.test_recall = float(recall_score(y_test, preds_test, zero_division=0))
    if len(set(y_test)) == 2:
        result.test_auc_roc = float(roc_auc_score(y_test, probs_test))

    # Threshold sweep on test set.
    sweep, best_t, best_row = threshold_sweep(y_test, probs_test)
    result.threshold_sweep = sweep
    result.best_threshold = float(best_t)
    result.fp_suppression_at_best = float(best_row["fp_suppression"])
    result.recall_at_best = float(best_row["recall"])
    result.precision_at_best = float(best_row["precision"])

    # LOCO — this re-fits the factory 3 times (one per held-out corpus).
    # For G1 we need the interaction-augmented matrix; for others X_all.
    if arm == "G1_LR_interactions":
        loco_X = X_all_for_loco
    else:
        loco_X = X_all
    result.loco_per_corpus = loco_evaluate(
        arm,
        factory,
        loco_X,
        y_all,
        corpora_all,
        loco_subset,
        scaler_factory=scaler_factory,
    )
    result.feature_importance = importance
    result.train_seconds = time.time() - t_start
    return result


# ── Promotion decision ────────────────────────────────────────────────────


def promotion_decision(result: ArmResult, loco_subset: tuple[str, ...]) -> tuple[str, str]:
    """Return (GREEN/YELLOW/RED, rationale)."""
    loco_f1s = [v["f1"] for v in result.loco_per_corpus.values() if not (v.get("skipped") or v["f1"] != v["f1"])]
    if not loco_f1s:
        return "RED", "No LOCO F1 values computed."
    mean_loco_f1 = sum(loco_f1s) / len(loco_f1s)
    fp_supp = result.fp_suppression_at_best

    # Ignore NaN (no NEGATIVE rows in test corpus).
    if fp_supp != fp_supp:
        fp_supp = 0.0

    if mean_loco_f1 >= 0.85 and fp_supp >= 0.50:
        return "GREEN", (
            f"LOCO mean F1 {mean_loco_f1:.3f} ≥ 0.85 AND FP suppression "
            f"{fp_supp:.3f} ≥ 0.50 at recall ≥ {TARGET_RECALL}. Promote "
            "to Sprint 14 production item."
        )
    if mean_loco_f1 >= 0.75 or fp_supp >= 0.30:
        return "YELLOW", (
            f"LOCO mean F1 {mean_loco_f1:.3f} and FP suppression "
            f"{fp_supp:.3f} are in the iterate range. Needs more "
            "features or data before promotion."
        )
    return "RED", (
        f"LOCO mean F1 {mean_loco_f1:.3f} and FP suppression "
        f"{fp_supp:.3f} below the minimum threshold. Gate not viable "
        "on current feature set."
    )


# ── Memo writer ───────────────────────────────────────────────────────────


def write_memo(
    memo_path: Path,
    results: list[ArmResult],
    loco_subset: tuple[str, ...],
    dataset_stats: dict[str, object],
    training_data_path: Path,
) -> None:
    # Pick winning arm by LOCO mean F1.
    def mean_loco(r: ArmResult) -> float:
        fs = [v["f1"] for v in r.loco_per_corpus.values() if not (v.get("skipped") or v["f1"] != v["f1"])]
        return sum(fs) / len(fs) if fs else 0.0

    winner = max(results, key=mean_loco) if results else None
    winner_verdict, winner_rationale = (
        promotion_decision(winner, loco_subset) if winner is not None else ("RED", "No arms completed.")
    )

    lines: list[str] = []
    lines.append("# Binary PII gate — model evaluation\n\n")
    lines.append(f"**Run date:** {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n")
    lines.append(f"**Training data:** `{training_data_path}` ({dataset_stats['n_rows']} rows)\n")
    lines.append(f"**Feature schema:** v{FEATURE_SCHEMA_VERSION}, dim={dataset_stats['feature_dim']}\n")
    lines.append(f"**LOCO subset:** {', '.join(loco_subset)}\n")
    lines.append(f"**Target recall:** {TARGET_RECALL}\n\n")

    lines.append("## Promotion decision\n\n")
    lines.append(f"**Verdict:** {winner_verdict}\n")
    lines.append(f"**Winning arm:** `{winner.name if winner else 'none'}`\n")
    lines.append(f"**Rationale:** {winner_rationale}\n\n")

    lines.append("## Arm comparison\n\n")
    lines.append(
        "| Arm | CV F1 | CV AUC | CV Brier | Test F1 | LOCO mean F1 | Threshold | FP supp | Recall | Train (s) |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n"
    )
    for r in results:
        loco_mean = mean_loco(r)
        lines.append(
            f"| `{r.name}` | "
            f"{r.cv_mean_f1:.3f} ± {r.cv_std_f1:.3f} | "
            f"{r.cv_mean_auc_roc:.3f} | "
            f"{r.cv_mean_brier:.3f} | "
            f"{r.test_f1:.3f} | "
            f"{loco_mean:.3f} | "
            f"{r.best_threshold:.2f} | "
            f"{r.fp_suppression_at_best:.3f} | "
            f"{r.recall_at_best:.3f} | "
            f"{r.train_seconds:.1f} |\n"
        )
    lines.append("\n")

    lines.append("## Per-corpus LOCO\n\n")
    for r in results:
        lines.append(f"### `{r.name}`\n\n")
        lines.append("| Corpus | F1 | Precision | Recall | FP supp | N test | N neg |\n")
        lines.append("|---|---|---|---|---|---|---|\n")
        for corpus, m in r.loco_per_corpus.items():
            if m.get("skipped"):
                lines.append(f"| `{corpus}` | *skipped (no data)* |  |  |  |  |  |\n")
                continue
            fp = f"{m['fp_suppression']:.3f}" if m["fp_suppression"] == m["fp_suppression"] else "n/a"
            lines.append(
                f"| `{corpus}` | {m['f1']:.3f} | {m['precision']:.3f} | "
                f"{m['recall']:.3f} | {fp} | {m['n_test']} | {m.get('n_neg', 0)} |\n"
            )
        lines.append("\n")

    lines.append("## Threshold sweep (winner)\n\n")
    if winner:
        lines.append(f"Arm `{winner.name}`. Full sweep at 40 points — showing 10 representative rows.\n\n")
        lines.append("| Threshold | Precision | Recall | FP supp | TP | FP | FN | TN |\n")
        lines.append("|---|---|---|---|---|---|---|---|\n")
        sweep = winner.threshold_sweep
        # Print every 4th row for a compact view.
        for row in sweep[::4]:
            lines.append(
                f"| {row['threshold']:.2f} | {row['precision']:.3f} | "
                f"{row['recall']:.3f} | {row['fp_suppression']:.3f} | "
                f"{row['tp']} | {row['fp']} | {row['fn']} | {row['tn']} |\n"
            )
        lines.append("\n")
        lines.append(
            f"**Recommended threshold:** `{winner.best_threshold:.2f}` — "
            f"keeps recall ≥ {TARGET_RECALL} while suppressing "
            f"{winner.fp_suppression_at_best:.1%} of NEGATIVE FPs on the held-out test set.\n\n"
        )

    lines.append("## Feature importance (winner)\n\n")
    if winner:
        lines.append(f"Arm `{winner.name}`. Top 10 features ranked by |importance|.\n\n")
        cols = "| Rank | Feature | |importance| |"
        sep = "|---|---|---|"
        has_direction = any("direction" in f for f in winner.feature_importance)
        if has_direction:
            cols += " Coef | Direction |"
            sep += "---|---|"
        lines.append(cols + "\n")
        lines.append(sep + "\n")
        for f in winner.feature_importance:
            row = f"| {f['rank']} | `{f['feature']}` | {f['abs_importance']:.3f} |"
            if has_direction:
                row += f" {f.get('coef', 0):+.3f} | {f.get('direction', 'n/a')} |"
            lines.append(row + "\n")
        lines.append("\n")

    lines.append("## Dataset composition\n\n")
    lines.append("| Corpus | Row count |\n|---|---|\n")
    for corpus, count in sorted(dataset_stats["corpora"].items()):
        lines.append(f"| `{corpus}` | {count:,} |\n")
    lines.append("\n")
    lines.append(
        f"**NEGATIVE rows:** {dataset_stats['n_negative']:,} "
        f"({dataset_stats['n_negative'] / dataset_stats['n_rows']:.1%} of dataset).\n\n"
    )

    lines.append("## Reproducibility\n\n")
    lines.append(
        "- Script: `scripts/train_binary_pii_gate.py`\n"
        "- Training data regeneration: `python -m tests.benchmarks.meta_classifier.build_training_data "
        "--output tests/benchmarks/meta_classifier/training_data_binary_gate.jsonl`\n"
        f"- Random seed: `{RANDOM_STATE}`\n"
        f"- CV folds: `{CV_FOLDS}`, stratified-group k-fold grouped by corpus\n"
        "- Train/test split: 80/20 StratifiedGroupKFold by base shard ID\n"
        f"- Feature schema: `v{FEATURE_SCHEMA_VERSION}`, dim={dataset_stats['feature_dim']}\n"
    )

    memo_path.write_text("".join(lines))


# ── Main ──────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "", formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Training JSONL (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory (default: docs/experiments/meta_classifier/runs/<date>-binary-pii-gate/)",
    )
    parser.add_argument(
        "--arms",
        type=str,
        default="G0_LR,G1_LR_interactions,G2_XGBoost,G3_MLP",
        help="Comma-separated list of arms to run.",
    )
    parser.add_argument(
        "--loco-subset",
        type=str,
        default=",".join(DEFAULT_LOCO_SUBSET),
        help=f"Comma-separated LOCO corpora (default: {','.join(DEFAULT_LOCO_SUBSET)})",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run G0 only on first 500 rows (fast sanity check).",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"❌ Training data not found: {args.input}", file=sys.stderr)  # noqa: T201
        print(  # noqa: T201
            f"   Run: python -m tests.benchmarks.meta_classifier.build_training_data --output {args.input}",
            file=sys.stderr,
        )
        return 2

    if args.smoke:
        args.arms = "G0_LR"

    arms = tuple(a.strip() for a in args.arms.split(",") if a.strip())
    loco_subset = tuple(c.strip() for c in args.loco_subset.split(",") if c.strip())
    out_dir = args.out_dir or (
        Path("docs/experiments/meta_classifier/runs") / f"{datetime.now().strftime('%Y%m%d')}-binary-pii-gate"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    import numpy as np

    print(f"Binary PII gate evaluation → {out_dir}")  # noqa: T201
    print(f"Training data: {args.input}")  # noqa: T201
    print(f"Arms: {', '.join(arms)}")  # noqa: T201
    print(f"LOCO subset: {', '.join(loco_subset)}")  # noqa: T201
    print()  # noqa: T201

    dataset = load_jsonl(args.input, FEATURE_NAMES)
    if args.smoke:
        # Stratified random sample to ensure NEGATIVE rows land in the subset.
        # Simple first-N slice pulls only nemotron (no NEGATIVE).
        import random

        rng = random.Random(RANDOM_STATE)
        neg_idx = [i for i, lbl in enumerate(dataset.labels) if lbl == "NEGATIVE"]
        pos_idx = [i for i, lbl in enumerate(dataset.labels) if lbl != "NEGATIVE"]
        rng.shuffle(neg_idx)
        rng.shuffle(pos_idx)
        keep = sorted(neg_idx[:200] + pos_idx[:300])
        dataset = LoadedDataset(
            features=[dataset.features[i] for i in keep],
            labels=[dataset.labels[i] for i in keep],
            column_ids=[dataset.column_ids[i] for i in keep],
            corpora=[dataset.corpora[i] for i in keep],
            modes=[dataset.modes[i] for i in keep],
            sources=[dataset.sources[i] for i in keep],
            feature_names=dataset.feature_names,
        )

    kept_names, kept_indices = resolve_feature_subset(dataset)
    print(f"Loaded {len(dataset.labels)} rows, {len(kept_names)} features (after drops)")  # noqa: T201

    from collections import Counter

    corpora_counts = Counter(dataset.corpora)
    neg_count = sum(1 for lbl in dataset.labels if lbl == "NEGATIVE")
    dataset_stats = {
        "n_rows": len(dataset.labels),
        "feature_dim": len(kept_names),
        "corpora": dict(corpora_counts),
        "n_negative": neg_count,
    }
    print(f"NEGATIVE rows: {neg_count} ({neg_count / len(dataset.labels):.1%})")  # noqa: T201
    print(f"Corpora: {dict(corpora_counts)}")  # noqa: T201
    print()  # noqa: T201

    X = np.asarray(dataset.features, dtype=np.float64)[:, kept_indices]
    y = binary_target(dataset.labels)
    column_ids = np.asarray(dataset.column_ids)
    corpora = np.asarray(dataset.corpora)
    modes = np.asarray(dataset.modes)

    split = split_train_test(X, y, column_ids, corpora, modes)
    print(  # noqa: T201
        f"Split: train={len(split['y_train'])}, test={len(split['y_test'])}, "
        f"train_pos={int(split['y_train'].sum())}, test_pos={int(split['y_test'].sum())}"
    )
    print()  # noqa: T201

    results: list[ArmResult] = []
    for arm in arms:
        print(f"━━━ {arm} ━━━")  # noqa: T201
        try:
            r = run_arm(arm, kept_names, split, loco_subset)
        except Exception as e:
            print(f"❌ {arm} failed: {type(e).__name__}: {e}")  # noqa: T201
            continue
        results.append(r)
        print(  # noqa: T201
            f"  CV F1 = {r.cv_mean_f1:.3f} ± {r.cv_std_f1:.3f}  "
            f"(prec {r.cv_mean_precision:.3f}, rec {r.cv_mean_recall:.3f}, "
            f"AUC {r.cv_mean_auc_roc:.3f})"
        )
        print(  # noqa: T201
            f"  Test F1 = {r.test_f1:.3f}  "
            f"(threshold={r.best_threshold:.2f}: "
            f"P={r.precision_at_best:.3f}, R={r.recall_at_best:.3f}, "
            f"FP suppression={r.fp_suppression_at_best:.3f})"
        )
        loco_f1s = [v["f1"] for v in r.loco_per_corpus.values() if not v.get("skipped")]
        print(  # noqa: T201
            f"  LOCO F1 mean = {sum(loco_f1s) / len(loco_f1s):.3f}  ({len(loco_f1s)} corpora)"
        )
        print(f"  Train seconds: {r.train_seconds:.1f}")  # noqa: T201
        print()  # noqa: T201

    # Write results.json
    results_path = out_dir / "results.json"
    with results_path.open("w") as f:
        json.dump(
            {
                "run_date": datetime.now(timezone.utc).isoformat(),
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "dataset_stats": dataset_stats,
                "loco_subset": list(loco_subset),
                "arms": [asdict(r) for r in results],
            },
            f,
            indent=2,
        )

    # Write memo
    memo_path = Path("docs/research/meta_classifier/binary_pii_gate_evaluation_memo.md")
    memo_path.parent.mkdir(parents=True, exist_ok=True)
    write_memo(memo_path, results, loco_subset, dataset_stats, args.input)

    print(f"Wrote {results_path}")  # noqa: T201
    print(f"Wrote {memo_path}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
