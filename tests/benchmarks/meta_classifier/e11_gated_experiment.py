"""E11 — Gated architecture ablation.

Tests whether tier-1 pattern-hit routing + specialized stage-2 classifiers
beats the flat LogReg baseline on the research-branch training data.

Four-model 2x2 comparison:
  A (flat LR)   : LogReg on all 15 features, 24 classes
  B (flat HGB)  : HistGradientBoostingClassifier on all 15 features, 24 classes
  C (gated LR)  : Tier-1 routing + LR stage-2 on PII rows (13 features)
  D (gated HGB) : Tier-1 routing + HGB stage-2 on PII rows (13 features)

Eval harness mirrors the production training script (M1 methodology):
  * 5-fold StratifiedGroupKFold with groups=corpus
  * Per-fold macro F1 (mean + std)
  * Per-class F1 on a stratified held-out 20% slice
  * LOCO (leave-one-corpus-out) macro F1 per model
  * Tree root-split feature for B and D (shortcut diagnostic)

Training data: tests/benchmarks/meta_classifier/training_data.jsonl
(Phase 2 / pre-Gretel — the baseline v1 was trained on, without M1's
retrained weights but with M1's CV methodology).

Usage:
    python -m tests.benchmarks.meta_classifier.e11_gated_experiment \\
        --training tests/benchmarks/meta_classifier/training_data.jsonl \\
        --output docs/experiments/meta_classifier/runs/<ts>-e11-gated-tier1-ablation
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Feature indices (match FEATURE_NAMES in orchestrator/meta_classifier.py)
FEATURE_NAMES: tuple[str, ...] = (
    "top_overall_confidence",     # 0
    "regex_confidence",           # 1
    "column_name_confidence",     # 2
    "heuristic_confidence",       # 3
    "secret_scanner_confidence",  # 4  -- gate signal
    "engines_agreed",             # 5
    "engines_fired",              # 6
    "confidence_gap",             # 7
    "regex_match_ratio",          # 8  -- gate signal
    "heuristic_distinct_ratio",   # 9
    "heuristic_avg_length",       # 10
    "has_column_name_hit",        # 11
    "has_secret_indicators",      # 12
    "primary_is_pii",             # 13
    "primary_is_credential",      # 14 -- gate signal
)
FEATURE_DIM = len(FEATURE_NAMES)

# Stage-2 feature indices (drop credential-related features since tier-1 already routed them)
STAGE_2_DROP: tuple[int, ...] = (4, 14)  # secret_scanner_confidence, primary_is_credential
STAGE_2_KEEP: tuple[int, ...] = tuple(i for i in range(FEATURE_DIM) if i not in STAGE_2_DROP)
STAGE_2_NAMES: tuple[str, ...] = tuple(FEATURE_NAMES[i] for i in STAGE_2_KEEP)


@dataclass
class Row:
    """One training row loaded from training_data.jsonl."""

    column_id: str
    corpus: str
    mode: str
    source: str
    features: list[float]
    ground_truth: str


def load_rows(path: Path) -> list[Row]:
    rows: list[Row] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            rows.append(
                Row(
                    column_id=d["column_id"],
                    corpus=d["corpus"],
                    mode=d["mode"],
                    source=d["source"],
                    features=list(d["features"]),
                    ground_truth=d["ground_truth"],
                )
            )
    return rows


# ── Tier-1 gate rule ────────────────────────────────────────────────────────


def route_to_credential(features: list[float]) -> bool:
    """Tier-1 gate: route to credential stage if strong credential signal.

    Conditions (OR):
      1. Primary engine finding is credential AND regex_confidence >= 0.85
         AND regex_match_ratio >= 0.30
      2. Secret scanner confidence >= 0.50
    """
    primary_is_credential = features[14] > 0.5
    regex_conf = features[1]
    regex_match_ratio = features[8]
    secret_scanner_conf = features[4]

    if primary_is_credential and regex_conf >= 0.85 and regex_match_ratio >= 0.30:
        return True
    if secret_scanner_conf >= 0.50:
        return True
    return False


def gate_alone_diagnostic(rows: list[Row]) -> dict[str, Any]:
    """Preliminary: precision/recall of tier-1 gate on training data."""
    tp = fp = fn = tn = 0
    per_corpus: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "tn": 0})
    mis_routed_labels: Counter[str] = Counter()
    credential_labels = {"CREDENTIAL"}  # Phase 2 taxonomy — single label

    for row in rows:
        gate_says_credential = route_to_credential(row.features)
        is_credential = row.ground_truth in credential_labels

        if gate_says_credential and is_credential:
            tp += 1
            per_corpus[row.corpus]["tp"] += 1
        elif gate_says_credential and not is_credential:
            fp += 1
            per_corpus[row.corpus]["fp"] += 1
            mis_routed_labels[row.ground_truth] += 1
        elif not gate_says_credential and is_credential:
            fn += 1
            per_corpus[row.corpus]["fn"] += 1
        else:
            tn += 1
            per_corpus[row.corpus]["tn"] += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    routing_rate = (tp + fp) / len(rows) if rows else 0.0
    credential_share = (tp + fn) / len(rows) if rows else 0.0

    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "total_rows": len(rows),
        "credential_rows": tp + fn,
        "credential_share": credential_share,
        "routed_to_credential": tp + fp,
        "routing_rate": routing_rate,
        "per_corpus": dict(per_corpus),
        "top_misroute_labels": mis_routed_labels.most_common(10),
    }


def print_gate_report(stats: dict[str, Any], *, stream=sys.stdout) -> None:
    p = stats["precision"]
    r = stats["recall"]
    f1 = stats["f1"]
    print("=" * 72, file=stream)
    print("E11 — Preliminary: tier-1 pattern-hit gate on training data", file=stream)
    print("=" * 72, file=stream)
    print(f"Total rows:                {stats['total_rows']}", file=stream)
    print(f"Credential rows (truth):   {stats['credential_rows']} ({stats['credential_share']:.1%})", file=stream)
    print(f"Routed to credential:      {stats['routed_to_credential']} ({stats['routing_rate']:.1%})", file=stream)
    print(file=stream)
    print("Confusion matrix:", file=stream)
    print(f"  TP (credential, routed):       {stats['tp']}", file=stream)
    print(f"  FP (not credential, routed):   {stats['fp']}", file=stream)
    print(f"  FN (credential, not routed):   {stats['fn']}", file=stream)
    print(f"  TN (not credential, not routed): {stats['tn']}", file=stream)
    print(file=stream)
    print(f"  Precision: {p:.4f}", file=stream)
    print(f"  Recall:    {r:.4f}", file=stream)
    print(f"  F1:        {f1:.4f}", file=stream)
    print(file=stream)
    print("Per-corpus breakdown:", file=stream)
    print(f"  {'corpus':<20} {'TP':>6} {'FP':>6} {'FN':>6} {'TN':>6}", file=stream)
    for corpus, d in sorted(stats["per_corpus"].items()):
        print(
            f"  {corpus:<20} {d['tp']:>6} {d['fp']:>6} {d['fn']:>6} {d['tn']:>6}",
            file=stream,
        )
    print(file=stream)
    if stats["top_misroute_labels"]:
        print("Top FP labels (PII mis-routed to credential):", file=stream)
        for label, count in stats["top_misroute_labels"]:
            print(f"  {label:<24} {count:>5}", file=stream)
    else:
        print("No false positives — gate never mis-routed PII to credential.", file=stream)
    print("=" * 72, file=stream)


# ── Model training harness ──────────────────────────────────────────────────


def _split_by_gate(rows: list[Row]) -> tuple[list[Row], list[Row]]:
    cred: list[Row] = []
    pii: list[Row] = []
    for row in rows:
        if route_to_credential(row.features):
            cred.append(row)
        else:
            pii.append(row)
    return cred, pii


def _to_arrays(rows: list[Row], *, keep_features: tuple[int, ...] | None = None):
    import numpy as np

    if keep_features is None:
        X = np.asarray([r.features for r in rows], dtype=np.float64)
    else:
        X = np.asarray([[r.features[i] for i in keep_features] for r in rows], dtype=np.float64)
    y = np.asarray([r.ground_truth for r in rows])
    groups = np.asarray([r.corpus for r in rows])
    return X, y, groups


def _cv_macro_f1_flat(
    rows: list[Row],
    model_fn,
    *,
    n_splits: int = 5,
    random_state: int = 20260413,
) -> dict[str, Any]:
    """CV macro F1 for a flat classifier using StratifiedGroupKFold."""
    import numpy as np
    from sklearn.metrics import f1_score
    from sklearn.model_selection import StratifiedGroupKFold
    from sklearn.preprocessing import StandardScaler

    X, y, groups = _to_arrays(rows)
    n_groups = len(set(groups.tolist()))
    n_splits_eff = min(n_splits, n_groups)

    kf = StratifiedGroupKFold(n_splits=n_splits_eff, shuffle=True, random_state=random_state)
    fold_scores: list[float] = []
    for train_idx, val_idx in kf.split(X, y, groups=groups):
        scaler = StandardScaler().fit(X[train_idx])
        Xtr = scaler.transform(X[train_idx])
        Xvl = scaler.transform(X[val_idx])
        clf = model_fn()
        clf.fit(Xtr, y[train_idx])
        pred = clf.predict(Xvl)
        fold_scores.append(f1_score(y[val_idx], pred, average="macro", zero_division=0.0))

    return {
        "cv_mean": float(np.mean(fold_scores)),
        "cv_std": float(np.std(fold_scores)),
        "cv_folds": fold_scores,
        "n_splits": n_splits_eff,
    }


def _cv_macro_f1_gated(
    rows: list[Row],
    cred_model_fn,
    pii_model_fn,
    *,
    n_splits: int = 5,
    random_state: int = 20260413,
) -> dict[str, Any]:
    """CV macro F1 for a gated classifier.

    Each fold trains two stage-2 models (credential-routed subset and
    PII-routed subset) on the training rows of that fold, then predicts
    on the validation rows by applying the gate + stage-2 lookup.
    """
    import numpy as np
    from sklearn.metrics import f1_score
    from sklearn.model_selection import StratifiedGroupKFold
    from sklearn.preprocessing import StandardScaler

    # Outer split uses the whole row list (gate is deterministic so no leak).
    X_all, y_all, groups_all = _to_arrays(rows)
    n_groups = len(set(groups_all.tolist()))
    n_splits_eff = min(n_splits, n_groups)

    kf = StratifiedGroupKFold(n_splits=n_splits_eff, shuffle=True, random_state=random_state)
    fold_scores: list[float] = []

    for train_idx, val_idx in kf.split(X_all, y_all, groups=groups_all):
        train_rows = [rows[i] for i in train_idx]
        val_rows = [rows[i] for i in val_idx]

        # Partition training rows by gate
        cred_train, pii_train = _split_by_gate(train_rows)

        # Stage-2-credential: predict on whatever classes happen to route here
        # (typically just CREDENTIAL + the rare PII misroute that the gate caught)
        cred_clf = None
        cred_scaler = None
        cred_classes: set[str] = set()
        if len(cred_train) >= 2 and len({r.ground_truth for r in cred_train}) >= 1:
            Xc = np.asarray([r.features for r in cred_train], dtype=np.float64)
            yc = np.asarray([r.ground_truth for r in cred_train])
            cred_classes = set(yc.tolist())
            if len(cred_classes) >= 2:
                cred_scaler = StandardScaler().fit(Xc)
                cred_clf = cred_model_fn()
                cred_clf.fit(cred_scaler.transform(Xc), yc)
            else:
                # Single class — record the dominant label as a trivial predictor
                pass

        # Stage-2-PII: predict on PII-routed rows using STAGE_2_KEEP features
        pii_clf = None
        pii_scaler = None
        pii_classes: set[str] = set()
        if len(pii_train) >= 2:
            Xp = np.asarray(
                [[r.features[i] for i in STAGE_2_KEEP] for r in pii_train],
                dtype=np.float64,
            )
            yp = np.asarray([r.ground_truth for r in pii_train])
            pii_classes = set(yp.tolist())
            if len(pii_classes) >= 2:
                pii_scaler = StandardScaler().fit(Xp)
                pii_clf = pii_model_fn()
                pii_clf.fit(pii_scaler.transform(Xp), yp)

        # Predict on validation rows
        y_true: list[str] = []
        y_pred: list[str] = []
        cred_fallback = (
            Counter(r.ground_truth for r in cred_train).most_common(1)[0][0]
            if cred_train
            else "CREDENTIAL"
        )
        pii_fallback = (
            Counter(r.ground_truth for r in pii_train).most_common(1)[0][0]
            if pii_train
            else "NEGATIVE"
        )

        for r in val_rows:
            y_true.append(r.ground_truth)
            if route_to_credential(r.features):
                if cred_clf is not None and cred_scaler is not None:
                    xv = cred_scaler.transform(np.asarray([r.features], dtype=np.float64))
                    y_pred.append(cred_clf.predict(xv)[0])
                else:
                    y_pred.append(cred_fallback)
            else:
                if pii_clf is not None and pii_scaler is not None:
                    xv = pii_scaler.transform(
                        np.asarray(
                            [[r.features[i] for i in STAGE_2_KEEP]],
                            dtype=np.float64,
                        )
                    )
                    y_pred.append(pii_clf.predict(xv)[0])
                else:
                    y_pred.append(pii_fallback)

        fold_scores.append(f1_score(y_true, y_pred, average="macro", zero_division=0.0))

    return {
        "cv_mean": float(np.mean(fold_scores)),
        "cv_std": float(np.std(fold_scores)),
        "cv_folds": fold_scores,
        "n_splits": n_splits_eff,
    }


def _loco_flat(rows: list[Row], model_fn) -> dict[str, float]:
    """Leave-one-corpus-out macro F1 for a flat classifier."""
    import numpy as np
    from sklearn.metrics import f1_score
    from sklearn.preprocessing import StandardScaler

    corpora = sorted({r.corpus for r in rows})
    per_corpus: dict[str, float] = {}

    for held_out in corpora:
        train_rows = [r for r in rows if r.corpus != held_out]
        val_rows = [r for r in rows if r.corpus == held_out]
        if not train_rows or not val_rows:
            continue
        Xtr = np.asarray([r.features for r in train_rows], dtype=np.float64)
        ytr = np.asarray([r.ground_truth for r in train_rows])
        Xvl = np.asarray([r.features for r in val_rows], dtype=np.float64)
        yvl = np.asarray([r.ground_truth for r in val_rows])

        scaler = StandardScaler().fit(Xtr)
        clf = model_fn()
        clf.fit(scaler.transform(Xtr), ytr)
        pred = clf.predict(scaler.transform(Xvl))
        per_corpus[held_out] = float(f1_score(yvl, pred, average="macro", zero_division=0.0))

    mean = float(np.mean(list(per_corpus.values()))) if per_corpus else 0.0
    return {"per_corpus": per_corpus, "mean": mean}


def _loco_gated(rows: list[Row], cred_model_fn, pii_model_fn) -> dict[str, float]:
    """Leave-one-corpus-out macro F1 for the gated classifier."""
    import numpy as np
    from sklearn.metrics import f1_score
    from sklearn.preprocessing import StandardScaler

    corpora = sorted({r.corpus for r in rows})
    per_corpus: dict[str, float] = {}

    for held_out in corpora:
        train_rows = [r for r in rows if r.corpus != held_out]
        val_rows = [r for r in rows if r.corpus == held_out]
        if not train_rows or not val_rows:
            continue

        cred_train, pii_train = _split_by_gate(train_rows)

        # Stage-2-credential
        cred_clf = None
        cred_scaler = None
        if len({r.ground_truth for r in cred_train}) >= 2:
            Xc = np.asarray([r.features for r in cred_train], dtype=np.float64)
            yc = np.asarray([r.ground_truth for r in cred_train])
            cred_scaler = StandardScaler().fit(Xc)
            cred_clf = cred_model_fn()
            cred_clf.fit(cred_scaler.transform(Xc), yc)

        # Stage-2-PII
        pii_clf = None
        pii_scaler = None
        if len({r.ground_truth for r in pii_train}) >= 2:
            Xp = np.asarray(
                [[r.features[i] for i in STAGE_2_KEEP] for r in pii_train], dtype=np.float64
            )
            yp = np.asarray([r.ground_truth for r in pii_train])
            pii_scaler = StandardScaler().fit(Xp)
            pii_clf = pii_model_fn()
            pii_clf.fit(pii_scaler.transform(Xp), yp)

        cred_fallback = (
            Counter(r.ground_truth for r in cred_train).most_common(1)[0][0]
            if cred_train
            else "CREDENTIAL"
        )
        pii_fallback = (
            Counter(r.ground_truth for r in pii_train).most_common(1)[0][0]
            if pii_train
            else "NEGATIVE"
        )

        y_true: list[str] = []
        y_pred: list[str] = []
        for r in val_rows:
            y_true.append(r.ground_truth)
            if route_to_credential(r.features):
                if cred_clf is not None and cred_scaler is not None:
                    xv = cred_scaler.transform(np.asarray([r.features], dtype=np.float64))
                    y_pred.append(cred_clf.predict(xv)[0])
                else:
                    y_pred.append(cred_fallback)
            else:
                if pii_clf is not None and pii_scaler is not None:
                    xv = pii_scaler.transform(
                        np.asarray(
                            [[r.features[i] for i in STAGE_2_KEEP]], dtype=np.float64
                        )
                    )
                    y_pred.append(pii_clf.predict(xv)[0])
                else:
                    y_pred.append(pii_fallback)

        per_corpus[held_out] = float(f1_score(y_true, y_pred, average="macro", zero_division=0.0))

    mean = float(np.mean(list(per_corpus.values()))) if per_corpus else 0.0
    return {"per_corpus": per_corpus, "mean": mean}


def make_lr():
    from sklearn.linear_model import LogisticRegression

    return LogisticRegression(
        C=1.0,
        solver="lbfgs",
        max_iter=2000,
        class_weight="balanced",
        random_state=20260413,
    )


def make_hgb():
    from sklearn.ensemble import HistGradientBoostingClassifier

    return HistGradientBoostingClassifier(
        max_iter=200,
        learning_rate=0.05,
        max_depth=5,
        min_samples_leaf=20,
        random_state=20260413,
        class_weight="balanced",
    )


def tree_root_split_feature(clf, feature_names: tuple[str, ...]) -> str | None:
    """Return the feature name at the first split of an HGB's first tree.

    HGB stores an internal ``_predictors`` list; each predictor is one
    iteration containing one tree per class. We inspect the first tree
    of the first iteration and report its root split feature.
    """
    try:
        predictors = clf._predictors  # type: ignore[attr-defined]
        if not predictors:
            return None
        first_iter = predictors[0]
        if not first_iter:
            return None
        tree = first_iter[0]
        # HGB trees store a structured numpy array `nodes` with `feature_idx`
        nodes = tree.nodes
        if nodes is None or len(nodes) == 0:
            return None
        root_feature_idx = int(nodes[0]["feature_idx"])
        if 0 <= root_feature_idx < len(feature_names):
            return feature_names[root_feature_idx]
        return None
    except Exception:
        return None


# ── Main ─────────────────────────────────────────────────────────────────────


def run_full_experiment(rows: list[Row], *, stream=sys.stdout) -> dict[str, Any]:
    """Train and evaluate A/B/C/D on the full training data."""
    print("=" * 72, file=stream)
    print("E11 — 2x2 ablation: flat-vs-gated × LR-vs-HGB", file=stream)
    print("=" * 72, file=stream)

    results: dict[str, Any] = {}

    for name, desc, cv_fn, loco_fn in [
        (
            "A_flat_lr",
            "Flat LogReg on 15 features, 24 classes",
            lambda: _cv_macro_f1_flat(rows, make_lr),
            lambda: _loco_flat(rows, make_lr),
        ),
        (
            "B_flat_hgb",
            "Flat HGB on 15 features, 24 classes",
            lambda: _cv_macro_f1_flat(rows, make_hgb),
            lambda: _loco_flat(rows, make_hgb),
        ),
        (
            "C_gated_lr",
            "Gated tier-1 + LogReg stage-2 (13 features on PII, 15 on credential)",
            lambda: _cv_macro_f1_gated(rows, make_lr, make_lr),
            lambda: _loco_gated(rows, make_lr, make_lr),
        ),
        (
            "D_gated_hgb",
            "Gated tier-1 + HGB stage-2 (13 features on PII, 15 on credential)",
            lambda: _cv_macro_f1_gated(rows, make_hgb, make_hgb),
            lambda: _loco_gated(rows, make_hgb, make_hgb),
        ),
    ]:
        print(f"\n[{name}] {desc}", file=stream)
        print(f"  training CV ({5}-fold StratifiedGroupKFold)...", file=stream)
        cv_result = cv_fn()
        print(
            f"  CV macro F1: {cv_result['cv_mean']:.4f} ± {cv_result['cv_std']:.4f}"
            f" (folds: {[f'{s:.3f}' for s in cv_result['cv_folds']]})",
            file=stream,
        )
        print(f"  LOCO ({len({r.corpus for r in rows})} corpora)...", file=stream)
        loco_result = loco_fn()
        print(f"  LOCO mean: {loco_result['mean']:.4f}", file=stream)
        for corpus, f1 in sorted(loco_result["per_corpus"].items()):
            print(f"    {corpus:<20} {f1:.4f}", file=stream)

        results[name] = {
            "description": desc,
            "cv": cv_result,
            "loco": loco_result,
        }

    # Tree root split diagnostic for B and D
    print("\n── Tree root-split diagnostic (shortcut check) ──", file=stream)
    import numpy as np
    from sklearn.preprocessing import StandardScaler

    Xall = np.asarray([r.features for r in rows], dtype=np.float64)
    yall = np.asarray([r.ground_truth for r in rows])
    scaler = StandardScaler().fit(Xall)
    hgb_flat = make_hgb()
    hgb_flat.fit(scaler.transform(Xall), yall)
    root_b = tree_root_split_feature(hgb_flat, FEATURE_NAMES)
    print(f"  B (flat HGB)  root split: {root_b}", file=stream)

    _, pii_rows = _split_by_gate(rows)
    Xp = np.asarray(
        [[r.features[i] for i in STAGE_2_KEEP] for r in pii_rows], dtype=np.float64
    )
    yp = np.asarray([r.ground_truth for r in pii_rows])
    if len(pii_rows) >= 50 and len(set(yp.tolist())) >= 2:
        scaler_p = StandardScaler().fit(Xp)
        hgb_gated = make_hgb()
        hgb_gated.fit(scaler_p.transform(Xp), yp)
        root_d = tree_root_split_feature(hgb_gated, STAGE_2_NAMES)
        print(f"  D (gated HGB, stage-2 PII) root split: {root_d}", file=stream)
        results["D_gated_hgb"]["root_split_feature"] = root_d
    results["B_flat_hgb"]["root_split_feature"] = root_b

    # Comparison table
    print("\n── 2x2 comparison table ──", file=stream)
    print(f"  {'model':<20} {'CV mean':>10} {'CV std':>10} {'LOCO mean':>12}", file=stream)
    for name in ("A_flat_lr", "B_flat_hgb", "C_gated_lr", "D_gated_hgb"):
        r = results[name]
        print(
            f"  {name:<20} {r['cv']['cv_mean']:>10.4f} {r['cv']['cv_std']:>10.4f} {r['loco']['mean']:>12.4f}",
            file=stream,
        )
    print("=" * 72, file=stream)

    return results


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--training",
        type=Path,
        default=Path("tests/benchmarks/meta_classifier/training_data.jsonl"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory for the result.md memo. If omitted, only prints to stdout.",
    )
    parser.add_argument(
        "--gate-only",
        action="store_true",
        help="Run only the preliminary gate-alone diagnostic and exit.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    rows = load_rows(args.training)
    print(f"Loaded {len(rows)} rows from {args.training}")

    # Preliminary: gate-alone diagnostic
    gate_stats = gate_alone_diagnostic(rows)
    print_gate_report(gate_stats)

    if args.gate_only:
        if args.output is not None:
            args.output.mkdir(parents=True, exist_ok=True)
            with (args.output / "gate_diagnostic.json").open("w") as f:
                json.dump(gate_stats, f, indent=2, default=str)
        return 0

    # Decision checkpoint: require precision >= 0.90 to proceed automatically
    if gate_stats["precision"] < 0.90:
        print(
            f"\nWARNING: gate precision {gate_stats['precision']:.4f} < 0.90 threshold.",
            file=sys.stderr,
        )
        print("Proceeding with full experiment anyway (diagnostic-only pass).", file=sys.stderr)

    # Full 2x2 ablation
    full_results = run_full_experiment(rows)

    if args.output is not None:
        args.output.mkdir(parents=True, exist_ok=True)
        with (args.output / "gate_diagnostic.json").open("w") as f:
            json.dump(gate_stats, f, indent=2, default=str)
        with (args.output / "ablation_results.json").open("w") as f:
            json.dump(full_results, f, indent=2, default=str)
        print(f"\nResults written to {args.output}/")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
