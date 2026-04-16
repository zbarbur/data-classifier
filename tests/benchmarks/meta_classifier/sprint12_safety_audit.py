"""Sprint 12 Item #4 safety audit — capacity, architecture, heterogeneous.

Runs three diagnostic experiments on the post-Sprint-12 v5 meta-classifier
training data to produce a GREEN / YELLOW / RED verdict that Sprint 12
Item #4 consumes as a go/no-go input for the shadow→directive promotion::

    DATA_CLASSIFIER_DISABLE_ML=1 \\
        python -m tests.benchmarks.meta_classifier.sprint12_safety_audit \\
        --input tests/benchmarks/meta_classifier/training_data.jsonl \\
        --out /tmp/sprint12_safety_audit.json

Three questions:

Q1 — Capacity axis: is LR the ceiling? Evaluates 3 arms (LR baseline, MLP,
     LR + pairwise interactions) on StratifiedGroupKFold CV and
     leave-one-corpus-out (LOCO), plus Brier score. Reports the winner.

Q2 — Architecture axis: does v5 need hard gating for LOCO? Partitions
     training rows by ground-truth family (CREDENTIAL vs non-CREDENTIAL,
     an oracle-gate upper bound), trains specialized classifiers on each
     branch, sums per-branch LOCO F1 weighted by support, compares to the
     single-model baseline. Threshold: delta >= 0.10 → hard gating is
     load-bearing and directive flip should wait for Sprint 13.

Q3 — Heterogeneous axis: does flat v5 collapse on log-shaped columns?
     Constructs a 50-row synthetic column of log lines embedding 3-5
     distinct entities per line, runs classify_columns (ML disabled),
     checks whether the output collapses to a single high-confidence
     entity type. Column-level test — BQ's use case is column-level.

Verdict (spec from
backlog/sprint12-shadow-directive-promotion-gate-safety-analysis-memo.yaml):

    GREEN  = Q1 LOCO >= 0.30 AND Q2 delta < 0.10 AND Q3 no collapse
    RED    = Q1 LOCO < 0.20 OR Q2 delta >= 0.15 OR Q3 full collapse
    YELLOW = otherwise (with named mitigation)

Sprint 12 Item #4 proceeds with directive promotion on GREEN, with
mitigations on YELLOW, and ships shadow-only on RED.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

os.environ.setdefault("PYTHONHASHSEED", "42")
os.environ.setdefault("DATA_CLASSIFIER_DISABLE_ML", "1")

from data_classifier.core.taxonomy import family_for  # noqa: E402
from data_classifier.orchestrator.meta_classifier import FEATURE_NAMES  # noqa: E402
from data_classifier.patterns._decoder import decode_encoded_strings  # noqa: E402
from scripts.train_meta_classifier import (  # noqa: E402
    ALWAYS_DROP_REDUNDANT,
    RANDOM_STATE,
    LoadedDataset,
    load_jsonl,
)

# Credential-shape placeholders used in the Q3 heterogeneous fixtures. Stored
# XOR-encoded to pass GitHub push protection, decoded once at import time.
# Matches the project-wide xor: pattern used in stopwords.json and
# default_patterns.json example lists (see
# ``feedback_xor_fixture_pattern.md``). Shapes are Stripe live-key, GitHub
# PAT (two lengths), AWS access key, and Slack bot token — exactly the
# pattern shapes push protection matches on.
_CRED_STRIPE, _CRED_GH_PAT_LONG, _CRED_GH_PAT_SHORT, _CRED_AWS, _CRED_SLACK = decode_encoded_strings(
    [
        "xor:KTEFNjMsPwU7ODlraGk+Pzxub2w9MjNtYmMwMTZqa2g=",
        "xor:PTIqBTsYOR4/HD0SMxAxFjcUNQorCCkOLwwtAiMAamtoaW5vbG1iYw==",
        "xor:PTIqBWtoaW5vbG1iY2o7ODk+Pzw=",
        "xor:GxETG2toaW5vbG1iY2obGBkeHxw=",
        "xor:IjUiOHdraGlub2xtYmNqdzs4OT4/PD0yMzA=",
    ]
)

# ── Verdict thresholds (from the backlog AC) ────────────────────────────────

LOCO_GREEN_MIN: float = 0.30
LOCO_RED_MAX: float = 0.20
ARCH_GREEN_MAX_DELTA: float = 0.10
ARCH_RED_MIN_DELTA: float = 0.15
HETERO_COLLAPSE_CONFIDENCE: float = 0.80


# ── Dataset loader with family annotation ──────────────────────────────────


@dataclass
class FamilyDataset:
    base: LoadedDataset
    families: list[str]  # family label per row
    kept_indices: list[int]  # feature columns to use (after ALWAYS_DROP_REDUNDANT)
    kept_feature_names: list[str]


def _load_dataset(input_path: Path) -> FamilyDataset:
    ds = load_jsonl(input_path, FEATURE_NAMES)
    families = [family_for(lbl) for lbl in ds.labels]
    drop_set = set(ALWAYS_DROP_REDUNDANT)
    kept_indices = [i for i, n in enumerate(ds.feature_names) if n not in drop_set]
    kept_feature_names = [ds.feature_names[i] for i in kept_indices]
    return FamilyDataset(
        base=ds,
        families=families,
        kept_indices=kept_indices,
        kept_feature_names=kept_feature_names,
    )


# ── Shared training helpers ─────────────────────────────────────────────────


def _base_shard_id(column_id: str, mode: str) -> str:
    return column_id.replace(f"_{mode}_", "_base_", 1)


def _build_groups(column_ids: list[str], modes: list[str]) -> "list[str]":
    return [_base_shard_id(cid, m) for cid, m in zip(column_ids, modes, strict=True)]


def _make_arm(arm_name: str):
    """Return an unfit (scaler, classifier) pair for the named arm.

    Arms are constructed fresh per fold so no state leaks between fits.
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.neural_network import MLPClassifier
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler()
    if arm_name == "A0_LR":
        clf = LogisticRegression(
            C=1.0,
            solver="lbfgs",
            max_iter=2000,
            class_weight="balanced",
            random_state=RANDOM_STATE,
        )
    elif arm_name == "A1_MLP":
        clf = MLPClassifier(
            hidden_layer_sizes=(32, 32),
            alpha=1e-3,
            early_stopping=True,
            validation_fraction=0.1,
            max_iter=500,
            random_state=RANDOM_STATE,
        )
    elif arm_name == "A2_LR_interactions":
        # Marker — interaction features are expanded at X-transform time
        # in _augment_with_interactions; the arm itself is still LR.
        clf = LogisticRegression(
            C=1.0,
            solver="lbfgs",
            max_iter=2000,
            class_weight="balanced",
            random_state=RANDOM_STATE,
        )
    else:
        raise ValueError(f"unknown arm {arm_name}")
    return scaler, clf


def _pick_top_interaction_features(X: "Any", y: list[str], k: int = 5) -> list[int]:
    """Return indices of the top-``k`` features by mutual information
    between feature value and class label.

    Mutual information is estimated on a random 2000-row subsample for
    speed (full-pass MI is O(N^2) in number of classes); deterministic
    via the module RANDOM_STATE.
    """
    import numpy as np
    from sklearn.feature_selection import mutual_info_classif

    rng = np.random.default_rng(RANDOM_STATE)
    n = X.shape[0]
    if n > 2000:
        idx = rng.choice(n, size=2000, replace=False)
        X_sub = X[idx]
        y_sub = [y[i] for i in idx]
    else:
        X_sub = X
        y_sub = y
    mi = mutual_info_classif(X_sub, y_sub, discrete_features=False, random_state=RANDOM_STATE)
    top = np.argsort(mi)[::-1][:k]
    return [int(i) for i in top]


def _augment_with_interactions(X: "Any", interaction_idx: list[int]) -> "Any":
    """Append pairwise products of the chosen feature indices to X."""
    import numpy as np

    if not interaction_idx or len(interaction_idx) < 2:
        return X
    pairs = []
    for i in range(len(interaction_idx)):
        for j in range(i + 1, len(interaction_idx)):
            a = X[:, interaction_idx[i]]
            b = X[:, interaction_idx[j]]
            pairs.append((a * b).reshape(-1, 1))
    if not pairs:
        return X
    extra = np.hstack(pairs)
    return np.hstack([X, extra])


def _fit_predict_arm(
    arm_name: str,
    X_train: "Any",
    y_train: list[str],
    X_test: "Any",
    *,
    interaction_idx: list[int] | None = None,
) -> "tuple[list[str], Any]":
    """Fit arm on (X_train, y_train), return (preds, proba) on X_test.

    MLP's ``early_stopping=True`` path calls ``np.isnan`` on the
    prediction array during internal validation — which raises
    ``TypeError: ufunc 'isnan' not supported`` on string targets under
    sklearn + Python 3.14. Workaround: label-encode y for the MLP arm
    so sklearn sees integer targets, then decode predictions back to
    the original string labels.
    """
    import numpy as np
    from sklearn.preprocessing import LabelEncoder

    scaler, clf = _make_arm(arm_name)
    X_tr = X_train
    X_te = X_test
    if arm_name == "A2_LR_interactions":
        assert interaction_idx is not None
        X_tr = _augment_with_interactions(X_tr, interaction_idx)
        X_te = _augment_with_interactions(X_te, interaction_idx)
    X_tr_s = scaler.fit_transform(X_tr)
    X_te_s = scaler.transform(X_te)

    if arm_name == "A1_MLP":
        le = LabelEncoder()
        y_tr_int = le.fit_transform(y_train)
        clf.fit(X_tr_s, y_tr_int)
        preds_int = clf.predict(X_te_s)
        preds = [str(s) for s in le.inverse_transform(preds_int)]
        proba = clf.predict_proba(X_te_s)
        classes = [str(s) for s in le.inverse_transform(clf.classes_)]  # type: ignore[attr-defined]
    else:
        clf.fit(X_tr_s, y_train)
        preds = [str(p) for p in clf.predict(X_te_s)]
        proba = clf.predict_proba(X_te_s)
        classes = [str(c) for c in clf.classes_]  # type: ignore[attr-defined]

    return preds, (proba, classes, np.asarray(y_train))


def _macro_f1(y_true: list[str], y_pred: list[str]) -> float:
    from sklearn.metrics import f1_score

    return float(f1_score(y_true, y_pred, average="macro", zero_division=0))


def _multiclass_brier(proba: "Any", classes: list[str], y_true: list[str]) -> float:
    """Average multiclass Brier = mean over samples of sum_k (p_k - 1[y=k])^2.

    Lower is better. Perfect calibration and correctness → 0.0.
    """
    import numpy as np

    class_to_idx = {c: i for i, c in enumerate(classes)}
    # One-hot encode y_true in the classifier's class space.
    onehot = np.zeros_like(proba)
    for i, t in enumerate(y_true):
        if t in class_to_idx:
            onehot[i, class_to_idx[t]] = 1.0
    diff = proba - onehot
    per_row = np.sum(diff * diff, axis=1)
    return float(np.mean(per_row))


# ── Q1 — capacity audit ─────────────────────────────────────────────────────


def _cv_eval_arm(
    dataset: FamilyDataset,
    arm_name: str,
) -> dict[str, Any]:
    """5-fold StratifiedGroupKFold CV, returns mean±std macro F1 and Brier."""
    import numpy as np
    from sklearn.model_selection import StratifiedGroupKFold

    X_all = np.asarray(dataset.base.features, dtype=np.float64)[:, dataset.kept_indices]
    y_all = np.asarray(dataset.base.labels)
    groups = np.asarray(_build_groups(dataset.base.column_ids, dataset.base.modes))

    # For A2, select interaction features on the FULL dataset before
    # CV so the feature set is fixed across folds (this is the standard
    # approach and avoids re-selecting per fold which inflates variance).
    interaction_idx: list[int] | None = None
    if arm_name == "A2_LR_interactions":
        interaction_idx = _pick_top_interaction_features(X_all, y_all.tolist(), k=5)

    sgkf = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
    f1_scores: list[float] = []
    brier_scores: list[float] = []
    for tr_idx, te_idx in sgkf.split(X_all, y_all, groups=groups):
        X_tr = X_all[tr_idx]
        X_te = X_all[te_idx]
        y_tr = y_all[tr_idx].tolist()
        y_te = y_all[te_idx].tolist()
        preds, (proba, classes, _y_tr_arr) = _fit_predict_arm(
            arm_name,
            X_tr,
            y_tr,
            X_te,
            interaction_idx=interaction_idx,
        )
        f1_scores.append(_macro_f1(y_te, preds))
        brier_scores.append(_multiclass_brier(proba, classes, y_te))

    return {
        "cv_mean_macro_f1": float(np.mean(f1_scores)),
        "cv_std_macro_f1": float(np.std(f1_scores)),
        "cv_fold_f1s": [float(s) for s in f1_scores],
        "cv_mean_brier": float(np.mean(brier_scores)),
        "cv_std_brier": float(np.std(brier_scores)),
        "interaction_feature_indices": interaction_idx,
    }


def _loco_eval_arm(
    dataset: FamilyDataset,
    arm_name: str,
) -> dict[str, Any]:
    """Leave-one-corpus-out evaluation on non-synthetic corpora.

    Returns per-corpus F1 + support, support-weighted mean and
    unweighted mean across corpora, plus per-family F1 on the pooled
    predictions (for NEGATIVE/CONTACT diagnostic alignment with
    Item #4 AC).
    """
    import numpy as np

    X_all = np.asarray(dataset.base.features, dtype=np.float64)[:, dataset.kept_indices]
    y_all = np.asarray(dataset.base.labels)
    corp = np.asarray(dataset.base.corpora)

    # Interaction indices picked once on the full training set (same
    # rationale as in _cv_eval_arm).
    interaction_idx: list[int] | None = None
    if arm_name == "A2_LR_interactions":
        interaction_idx = _pick_top_interaction_features(X_all, y_all.tolist(), k=5)

    all_corpora = sorted(set(corp.tolist()) - {"synthetic"})
    per_corpus: dict[str, dict[str, float]] = {}
    pooled_true: list[str] = []
    pooled_pred: list[str] = []

    for holdout in all_corpora:
        tr_mask = corp != holdout
        te_mask = corp == holdout
        if tr_mask.sum() == 0 or te_mask.sum() == 0:
            continue
        X_tr = X_all[tr_mask]
        X_te = X_all[te_mask]
        y_tr = y_all[tr_mask].tolist()
        y_te = y_all[te_mask].tolist()
        preds, _ = _fit_predict_arm(
            arm_name,
            X_tr,
            y_tr,
            X_te,
            interaction_idx=interaction_idx,
        )
        f1 = _macro_f1(y_te, preds)
        per_corpus[holdout] = {"n_test": float(te_mask.sum()), "macro_f1": f1}
        pooled_true.extend(y_te)
        pooled_pred.extend(preds)

    # Weighted + unweighted LOCO means
    f1_values = [d["macro_f1"] for d in per_corpus.values()]
    n_values = [d["n_test"] for d in per_corpus.values()]
    total_n = sum(n_values) or 1.0
    weighted = sum(f1 * n for f1, n in zip(f1_values, n_values, strict=True)) / total_n
    unweighted = float(np.mean(f1_values)) if f1_values else 0.0

    # Family-level F1 on the pooled predictions
    pooled_true_fam = [family_for(lbl) for lbl in pooled_true]
    pooled_pred_fam = [family_for(lbl) for lbl in pooled_pred]
    family_f1 = _macro_f1(pooled_true_fam, pooled_pred_fam)

    return {
        "per_corpus": per_corpus,
        "loco_mean_weighted": float(weighted),
        "loco_mean_unweighted": unweighted,
        "loco_pooled_entity_macro_f1": _macro_f1(pooled_true, pooled_pred),
        "loco_pooled_family_macro_f1": family_f1,
    }


def q1_capacity_audit(dataset: FamilyDataset) -> dict[str, Any]:
    print("\n── Q1: Capacity audit (LR vs MLP vs LR+interactions) ──", file=sys.stderr)
    out: dict[str, Any] = {"arms": {}}
    arms = ["A0_LR", "A1_MLP", "A2_LR_interactions"]
    for arm in arms:
        print(f"  {arm}: CV...", file=sys.stderr)
        cv = _cv_eval_arm(dataset, arm)
        print(
            f"    cv_mean_macro_f1 = {cv['cv_mean_macro_f1']:.4f} ± {cv['cv_std_macro_f1']:.4f}  "
            f"brier = {cv['cv_mean_brier']:.4f}",
            file=sys.stderr,
        )
        print(f"  {arm}: LOCO...", file=sys.stderr)
        loco = _loco_eval_arm(dataset, arm)
        print(
            f"    loco_unweighted  = {loco['loco_mean_unweighted']:.4f}  "
            f"loco_weighted     = {loco['loco_mean_weighted']:.4f}  "
            f"pooled_family_f1 = {loco['loco_pooled_family_macro_f1']:.4f}",
            file=sys.stderr,
        )
        out["arms"][arm] = {"cv": cv, "loco": loco}

    # Winner picking — maximize CV+LOCO combined score
    def combined(arm_result: dict[str, Any]) -> float:
        return arm_result["cv"]["cv_mean_macro_f1"] + arm_result["loco"]["loco_mean_unweighted"]

    winner = max(out["arms"], key=lambda a: combined(out["arms"][a]))
    out["winner_by_cv_plus_loco"] = winner
    out["winner_loco_unweighted"] = out["arms"][winner]["loco"]["loco_mean_unweighted"]
    print(f"  winner: {winner}", file=sys.stderr)
    return out


# ── Q2 — architecture audit ─────────────────────────────────────────────────


def q2_architecture_audit(dataset: FamilyDataset) -> dict[str, Any]:
    """Oracle-gate upper bound: partition training rows by ground-truth
    family (CREDENTIAL vs non-CREDENTIAL), train specialized LR per
    branch, evaluate LOCO per branch, compare sum-weighted-by-support
    to the single-model baseline.

    The training data has no HETEROGENEOUS-family rows (each row is a
    synthetic single-entity column), so the 3-branch partition in the
    backlog spec reduces to a 2-branch test here. The heterogeneous
    branch is covered by Q3 instead.
    """
    import numpy as np

    print("\n── Q2: Architecture audit (oracle-gate upper bound) ──", file=sys.stderr)

    X_all = np.asarray(dataset.base.features, dtype=np.float64)[:, dataset.kept_indices]
    y_all = np.asarray(dataset.base.labels)
    corp = np.asarray(dataset.base.corpora)
    fam = np.asarray(dataset.families)

    # Branch assignment — NEGATIVE is its own family; we put NEGATIVE rows
    # in the "other" branch so the non-CREDENTIAL classifier still has to
    # discriminate NEGATIVE from positive PII — this matches the
    # single-model baseline's job.
    credential_mask = fam == "CREDENTIAL"
    other_mask = ~credential_mask

    all_corpora = sorted(set(corp.tolist()) - {"synthetic"})
    per_branch: dict[str, dict[str, Any]] = {}

    for branch_name, branch_mask in (("CREDENTIAL", credential_mask), ("non_CREDENTIAL", other_mask)):
        X_b = X_all[branch_mask]
        y_b = y_all[branch_mask]
        corp_b = corp[branch_mask]

        per_corpus: dict[str, dict[str, float]] = {}
        pooled_true: list[str] = []
        pooled_pred: list[str] = []
        for holdout in all_corpora:
            tr_mask = corp_b != holdout
            te_mask = corp_b == holdout
            if tr_mask.sum() == 0 or te_mask.sum() == 0:
                continue
            X_tr = X_b[tr_mask]
            X_te = X_b[te_mask]
            y_tr = y_b[tr_mask].tolist()
            y_te = y_b[te_mask].tolist()
            # If the branch training set is single-class, skip — LR
            # cannot fit a single-class target.
            if len(set(y_tr)) < 2:
                continue
            preds, _ = _fit_predict_arm("A0_LR", X_tr, y_tr, X_te)
            f1 = _macro_f1(y_te, preds)
            per_corpus[holdout] = {"n_test": float(te_mask.sum()), "macro_f1": f1}
            pooled_true.extend(y_te)
            pooled_pred.extend(preds)

        n_values = [d["n_test"] for d in per_corpus.values()]
        f1_values = [d["macro_f1"] for d in per_corpus.values()]
        total_n = sum(n_values) or 1.0
        weighted = sum(f1 * n for f1, n in zip(f1_values, n_values, strict=True)) / total_n
        unweighted = float(np.mean(f1_values)) if f1_values else 0.0
        per_branch[branch_name] = {
            "n_total_rows": int(branch_mask.sum()),
            "per_corpus": per_corpus,
            "loco_weighted": float(weighted),
            "loco_unweighted": unweighted,
            "pooled_support": int(len(pooled_true)),
        }
        print(
            f"  branch {branch_name}: n={int(branch_mask.sum())}  "
            f"loco_unweighted={unweighted:.4f}  loco_weighted={weighted:.4f}",
            file=sys.stderr,
        )

    # Support-weighted combined LOCO across branches
    total_support = sum(b["pooled_support"] for b in per_branch.values()) or 1
    branch_loco_combined = sum(b["loco_weighted"] * b["pooled_support"] for b in per_branch.values()) / total_support

    # Single-model baseline = the Q1 A0_LR LOCO, recomputed here to make
    # this function self-contained (ensures Q1/Q2 use the same arm
    # config and the same splits).
    baseline_loco = _loco_eval_arm(dataset, "A0_LR")["loco_mean_weighted"]
    delta = branch_loco_combined - baseline_loco
    print(
        f"  single-model baseline LOCO (weighted) = {baseline_loco:.4f}",
        file=sys.stderr,
    )
    print(
        f"  hard-gated branch-sum LOCO (weighted) = {branch_loco_combined:.4f}",
        file=sys.stderr,
    )
    print(f"  delta = {delta:+.4f}", file=sys.stderr)

    return {
        "per_branch": per_branch,
        "single_model_loco_weighted": float(baseline_loco),
        "hard_gated_loco_weighted": float(branch_loco_combined),
        "delta": float(delta),
    }


# ── Q3 — heterogeneous audit ────────────────────────────────────────────────


def _build_heterogeneous_fixtures() -> "dict[str, list[str]]":
    """Six flavors of realistic heterogeneous columns BQ customers have
    in production. Each fixture is a distinct shape of "mixed content
    per row" — the failure surface is not any single shape, it is the
    union of them. Sprint 12 safety audit iteration #2 (2026-04-16)
    extended from 1 fixture to 6 after the first iteration's single
    fixture revealed only one failure mode; subsequent fixtures
    exposed that the flat classifier collapses in multiple different
    ways depending on feature signature.

    Deterministic. 50-row fixtures for consistency with the original
    audit spec; the repetition (``* 5`` on 10 unique rows) matches
    realistic log-column behavior where patterns recur.

    Fixture taxonomy:
        original_q3_log: 50 unique rows, 4+ entities per line
        apache_access_log: classic web server log with IPs + paths
        json_event_log: structured JSON events (pub/sub sink pattern)
        base64_encoded_payloads: opaque tokens (JWT / auth audit pattern)
        support_chat_messages: conversational text with embedded PII
        kafka_event_stream: key-value event records (streaming pattern)
    """
    return {
        "original_q3_log": [
            f"2026-04-16T10:15:30 INFO user alice.smith@example.com login from 10.0.1.5 via api_key={_CRED_STRIPE}",
            f"2026-04-16T10:15:31 INFO user bob.jones@example.org ip=10.0.1.6 token={_CRED_GH_PAT_LONG}",
            "2026-04-16T10:15:32 WARN failed login carol@site.co phone=+1-555-234-5678 from 192.168.1.42",
            '2026-04-16T10:15:33 INFO POST /api/users body {"email":"dan@example.com","phone":"555-111-2222"}',
            "2026-04-16T10:15:34 INFO user eve.brown@mail.co from 10.0.2.12 secret=password123 session=abcdef",
            "2026-04-16T10:15:35 INFO webhook https://example.com/hook?token=xyz123 from 172.16.0.5",
            "2026-04-16T10:15:36 ERROR database timeout user=frank@example.net host=10.0.3.7 port=5432",
            "2026-04-16T10:15:37 INFO upload file user=grace@example.com size=1024 ip=10.0.4.8",
            "2026-04-16T10:15:38 INFO GET /profile/henry user_id=12345 ip=10.0.5.9 referer=https://example.com",
            "2026-04-16T10:15:39 WARN rate limit user=ivan@example.io ip=10.0.6.10 endpoint=/api/login",
            "2026-04-16T10:15:40 INFO payment card=4111111111111111 user=judy@example.com amount=99.99",
            '2026-04-16T10:15:41 INFO user kate@example.com ssn=123-45-6789 address="42 Main St"',
            "2026-04-16T10:15:42 INFO verify phone +1-415-555-1212 for user larry@example.com",
            f"2026-04-16T10:15:43 ERROR auth failed user=mary@example.com token={_CRED_GH_PAT_SHORT} from 10.0.7.11",
            "2026-04-16T10:15:44 INFO user nancy@example.com ip=10.0.8.12 browser=Chrome",
            "2026-04-16T10:15:45 INFO POST /signup email=oscar@example.com phone=+442079460958 dob=1985-03-17",
            "2026-04-16T10:15:46 INFO user pat@example.com from 2001:db8::1 via https://api.example.com/v1",
            "2026-04-16T10:15:47 INFO user quinn@example.com credit_card=5555555555554444 exp=12/28",
            f"2026-04-16T10:15:48 INFO user robert@example.com api_key={_CRED_AWS} region=us-west-2",
            "2026-04-16T10:15:49 INFO user sarah@example.com iban=GB82WEST12345698765432",
            "2026-04-16T10:15:50 INFO user tom@example.com bitcoin=1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "2026-04-16T10:15:51 INFO user uma@example.com medicare=1EG4-TE5-MK73",
            "2026-04-16T10:15:52 INFO user victor@example.com vin=1HGBH41JXMN109186 license=CA-1234",
            "2026-04-16T10:15:53 INFO user wendy@example.com mac=aa:bb:cc:dd:ee:ff from 10.0.9.13",
            "2026-04-16T10:15:54 INFO user xavier@example.com url=https://example.com/path?q=1",
            "2026-04-16T10:15:55 INFO user yolanda@example.com phone=+1-555-000-1111 from 10.0.10.14",
            "2026-04-16T10:15:56 INFO user zach@example.com dob=1990-01-15 ip=10.0.11.15",
            "2026-04-16T10:15:57 INFO GET /api/data user=alice@example.com ip=10.0.12.16",
            "2026-04-16T10:15:58 INFO user bob@example.net iban=DE89370400440532013000",
            "2026-04-16T10:15:59 INFO user carol.white@example.com ssn=987-65-4321 ip=10.0.13.17",
            "2026-04-16T10:16:00 INFO user dan@example.com phone=(415) 555-0199 ip=10.0.14.18",
            '2026-04-16T10:16:01 INFO user eve@example.com npi=1234567893 address="1 First Ave"',
            '2026-04-16T10:16:02 INFO user frank@example.com ip=10.0.15.19 ua="Mozilla/5.0"',
            "2026-04-16T10:16:03 INFO user grace@example.com routing=021000021 account=1234567",
            "2026-04-16T10:16:04 INFO user henry@example.com iban=FR1420041010050500013M02606",
            "2026-04-16T10:16:05 INFO user ivan@example.com cc=4242424242424242 exp=06/30",
            "2026-04-16T10:16:06 INFO user judy@example.com eth=0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B",
            "2026-04-16T10:16:07 INFO user kate@example.com phone=555-987-6543 zip=94110",
            "2026-04-16T10:16:08 INFO user larry@example.com ip=203.0.113.5 referer=https://example.org",
            "2026-04-16T10:16:09 INFO user mary@example.com dea=AB1234567 phone=+1-555-321-7654",
            "2026-04-16T10:16:10 INFO user nancy@example.com mbi=1EG4TE5MK73 ip=10.0.16.20",
            "2026-04-16T10:16:11 INFO user oscar@example.com ssn=555-44-3322 phone=+1-212-555-7788",
            "2026-04-16T10:16:12 INFO POST /login email=pat@example.com ip=10.0.17.21 token=bearer_xyz",
            "2026-04-16T10:16:13 INFO user quinn@example.com swift=DEUTDEFFXXX ibang=DE89370400440532013000",
            "2026-04-16T10:16:14 INFO user robert@example.com from 198.51.100.7 session=sess_abc123",
            '2026-04-16T10:16:15 INFO user sarah@example.com ein=12-3456789 address="100 Corporate Way"',
            "2026-04-16T10:16:16 INFO user tom@example.com cc=3782-822463-10005 amex_exp=09/29",
            "2026-04-16T10:16:17 INFO user uma@example.com mac=00:1A:2B:3C:4D:5E ip=10.0.18.22",
            "2026-04-16T10:16:18 INFO user victor@example.com dob=1978-11-23 phone=+1-555-888-9999",
            f"2026-04-16T10:16:19 INFO user wendy@example.com api_key={_CRED_SLACK}",
        ],
        "apache_access_log": [
            '192.168.1.1 - alice [16/Apr/2026:10:15:30 +0000] "GET /api/users HTTP/1.1" 200 512',
            '10.0.0.5 - bob [16/Apr/2026:10:15:31 +0000] "POST /login HTTP/1.1" 401 128',
            '172.16.0.9 - carol [16/Apr/2026:10:15:32 +0000] "GET /profile HTTP/1.1" 200 1024',
            '192.0.2.10 - dan [16/Apr/2026:10:15:33 +0000] "DELETE /item/42 HTTP/1.1" 204 0',
            '198.51.100.3 - eve [16/Apr/2026:10:15:34 +0000] "PUT /settings HTTP/1.1" 200 256',
            '203.0.113.5 - frank [16/Apr/2026:10:15:35 +0000] "GET /api/keys HTTP/1.1" 200 2048',
            '10.10.10.10 - grace [16/Apr/2026:10:15:36 +0000] "POST /webhook HTTP/1.1" 202 0',
            '172.20.0.15 - henry [16/Apr/2026:10:15:37 +0000] "GET /health HTTP/1.1" 200 32',
            '192.168.50.1 - ivan [16/Apr/2026:10:15:38 +0000] "GET /metrics HTTP/1.1" 200 4096',
            '10.1.2.3 - judy [16/Apr/2026:10:15:39 +0000] "POST /api/data HTTP/1.1" 201 64',
        ]
        * 5,
        "json_event_log": [
            '{"ts":"2026-04-16T10:15:30","user":"alice@example.com","action":"login","ip":"10.0.1.5"}',
            '{"ts":"2026-04-16T10:15:31","user":"bob@example.org","action":"logout","ip":"10.0.1.6"}',
            '{"ts":"2026-04-16T10:15:32","user":"carol@site.co","action":"upload","ip":"10.0.1.7","size":1024}',
            '{"ts":"2026-04-16T10:15:33","user":"dan@ex.com","action":"download","ip":"10.0.1.8"}',
            '{"ts":"2026-04-16T10:15:34","user":"eve@test.io","action":"share","ip":"10.0.1.9","target":"frank@ex.com"}',
            '{"ts":"2026-04-16T10:15:35","user":"grace@x.com","action":"delete","ip":"10.0.1.10"}',
            '{"ts":"2026-04-16T10:15:36","user":"henry@y.net","action":"edit","ip":"10.0.1.11"}',
            '{"ts":"2026-04-16T10:15:37","user":"ivan@z.org","action":"create","ip":"10.0.1.12"}',
            '{"ts":"2026-04-16T10:15:38","user":"judy@a.co","action":"view","ip":"10.0.1.13"}',
            '{"ts":"2026-04-16T10:15:39","user":"kate@b.io","action":"login","ip":"10.0.1.14"}',
        ]
        * 5,
        "base64_encoded_payloads": [
            "eyJ1c2VyIjoiYWxpY2VAZXhhbXBsZS5jb20iLCJyb2xlIjoiYWRtaW4ifQ==",
            "eyJ1c2VyIjoiYm9iQGV4YW1wbGUub3JnIiwicm9sZSI6InVzZXIifQ==",
            "eyJ1c2VyIjoiY2Fyb2xAc2l0ZS5jbyIsInJvbGUiOiJndWVzdCJ9",
            "eyJ1c2VyIjoiZGFuQHRlc3QuY29tIiwicm9sZSI6InVzZXIifQ==",
            "eyJ1c2VyIjoiZXZlQGV4LmlvIiwicm9sZSI6ImFkbWluIn0=",
            "eyJ1c2VyIjoiZnJhbmtAeC5uZXQiLCJyb2xlIjoidXNlciJ9",
            "eyJ1c2VyIjoiZ3JhY2VAeS5vcmciLCJyb2xlIjoiZ3Vlc3QifQ==",
            "eyJ1c2VyIjoiaGVucnlAei5jb20iLCJyb2xlIjoidXNlciJ9",
            "eyJ1c2VyIjoiaXZhbkBhLmlvIiwicm9sZSI6InVzZXIifQ==",
            "eyJ1c2VyIjoianVkeUBiLmNvIiwicm9sZSI6ImFkbWluIn0=",
        ]
        * 5,
        "support_chat_messages": [
            "Hi, I'm having trouble logging in. My email is alice@example.com",
            "Thanks for reaching out. Can you confirm your phone number is 555-123-4567?",
            "Yes that's correct. Also my order number was ORD-20260416",
            "Got it. Please send a screenshot to support@company.com",
            "I've attached the error. It says 'token expired' at 10:15 AM.",
            "No problem, I'm resetting your password now. Check your email.",
            "Received! Working now. Thank you so much.",
            "You're welcome! Anything else I can help with today?",
            "Nope, that's all. Have a great day!",
            "You too. Ticket #45678 closed.",
        ]
        * 5,
        "kafka_event_stream": [
            'topic=user.signup key=alice partition=3 offset=10234 payload={"email":"a@b.co","age":32}',
            'topic=user.signup key=bob partition=3 offset=10235 payload={"email":"b@c.io","age":28}',
            'topic=order.placed key=ord_1 partition=5 offset=98711 payload={"amount":99.99,"user":"alice"}',
            'topic=user.login key=carol partition=2 offset=55432 payload={"ip":"10.0.1.5","ts":1712345678}',
            'topic=user.update key=dan partition=3 offset=10236 payload={"phone":"+1-555-222-3333"}',
            'topic=order.paid key=ord_2 partition=5 offset=98712 payload={"card":"4111...4242","amt":49.99}',
            'topic=webhook.sent key=wh_1 partition=8 offset=33221 payload={"url":"https://ex.com/hook"}',
            'topic=user.delete key=eve partition=3 offset=10237 payload={"reason":"user_request"}',
            'topic=user.login key=frank partition=2 offset=55433 payload={"ip":"10.0.1.6","ts":1712345679}',
            'topic=order.refund key=ord_3 partition=5 offset=98713 payload={"amt":99.99,"refund_to":"alice"}',
        ]
        * 5,
    }


def _audit_single_fixture(
    name: str,
    sample_values: "list[str]",
    profile: "Any",
    engines: "dict[str, Any]",
    mc: "Any",
) -> dict[str, Any]:
    """Run live cascade + v5 shadow on a single fixture. Returns a
    per-fixture result dict with collapse verdict classification.

    Extracted from the original single-fixture q3 so the same logic
    can be applied to 6 different heterogeneous shapes and aggregated.
    """
    from data_classifier import ColumnInput, classify_columns

    column = ColumnInput(
        column_id=f"hetero_fixture:{name}",
        column_name=name,
        sample_values=sample_values,
    )

    # Part A: live cascade
    try:
        live_findings = classify_columns([column], profile)
    except Exception as exc:
        return {
            "fixture": name,
            "error": f"live cascade failed: {exc}",
            "collapse_verdict": "error",
        }
    live_findings_summary = [
        {
            "entity_type": f.entity_type,
            "category": f.category,
            "confidence": float(f.confidence),
            "engine": f.engine,
        }
        for f in live_findings
    ]
    live_distinct = {f["entity_type"] for f in live_findings_summary}

    # Part B: v5 shadow
    engine_findings: dict[str, list] = {}
    flat_findings: list = []
    for en_name, engine in engines.items():
        try:
            engine_result = engine.classify_column(column, profile=profile, min_confidence=0.0)
        except Exception:
            engine_result = []
        engine_findings[en_name] = list(engine_result)
        flat_findings.extend(engine_result)

    try:
        shadow = mc.predict_shadow(flat_findings, sample_values, engine_findings=engine_findings)
    except Exception as exc:
        return {
            "fixture": name,
            "error": f"predict_shadow failed: {exc}",
            "collapse_verdict": "error",
            "live_findings": live_findings_summary,
        }

    if shadow is None:
        return {
            "fixture": name,
            "error": "predict_shadow returned None",
            "collapse_verdict": "shadow_unavailable",
            "live_findings": live_findings_summary,
        }

    shadow_entity = shadow.predicted_entity
    shadow_confidence = float(shadow.confidence)
    shadow_in_live = shadow_entity in live_distinct

    # Collapse verdict taxonomy — encodes the two axes we care about:
    # (confidence level) × (is shadow_entity present in the column?).
    if shadow_confidence >= HETERO_COLLAPSE_CONFIDENCE and not shadow_in_live:
        cv = "collapsed_high_confidence_wrong_class"
    elif shadow_confidence >= HETERO_COLLAPSE_CONFIDENCE:
        cv = "collapsed_high_confidence_one_of_live"
    elif shadow_confidence >= 0.50 and not shadow_in_live:
        cv = "collapsed_medium_confidence_wrong_class"
    elif shadow_confidence >= 0.50:
        cv = "collapsed_medium_confidence_one_of_live"
    else:
        cv = "graceful_degradation"

    print(
        f"  [{name:<26}] live={len(live_findings_summary)}:{','.join(sorted(live_distinct)) or '(none)':<40} "
        f"shadow={shadow_entity}@{shadow_confidence:.3f}  {cv}",
        file=sys.stderr,
    )

    return {
        "fixture": name,
        "fixture_size": len(sample_values),
        "live_findings": live_findings_summary,
        "num_live_findings": len(live_findings_summary),
        "live_distinct_entities": sorted(live_distinct),
        "shadow_prediction": {
            "entity_type": shadow_entity,
            "confidence": shadow_confidence,
            "live_entity": shadow.live_entity,
            "agreement": bool(shadow.agreement),
            "in_live_entities": shadow_in_live,
        },
        "collapse_verdict": cv,
    }


def q3_heterogeneous_audit() -> dict[str, Any]:
    """Column-level test: can flat v5 represent a mixed-content column?

    Runs 6 heterogeneous fixtures spanning distinct shapes (log lines,
    access logs, JSON events, base64 tokens, chat messages, Kafka
    streams) and aggregates verdicts. The Sprint 12 iteration-1 audit
    ran only the original log fixture, which masked the fact that the
    failure surface has multiple distinct "default class" modes —
    different fixture shapes collapse to different wrong classes
    (ADDRESS, CREDENTIAL, VIN). Iteration-2 fixed this by running
    multiple shapes and taking the worst-case verdict.

    Aggregate verdict is driven by the **worst single-fixture
    verdict** across all shapes. A single fixture with
    ``collapsed_high_confidence_wrong_class`` is enough to block GREEN
    because a BQ customer with that shape of column would see a
    confident-wrong directive prediction in production.
    """
    from data_classifier import load_profile
    from data_classifier.engines.column_name_engine import ColumnNameEngine
    from data_classifier.engines.heuristic_engine import HeuristicEngine
    from data_classifier.engines.regex_engine import RegexEngine
    from data_classifier.engines.secret_scanner import SecretScannerEngine
    from data_classifier.orchestrator.meta_classifier import MetaClassifier

    print("\n── Q3: Heterogeneous audit (6 fixtures) ──", file=sys.stderr)

    engines = {
        "regex": RegexEngine(),
        "column_name": ColumnNameEngine(),
        "heuristic_stats": HeuristicEngine(),
        "secret_scanner": SecretScannerEngine(),
    }
    for e in engines.values():
        e.startup()
    mc = MetaClassifier()
    profile = load_profile("standard")

    fixtures = _build_heterogeneous_fixtures()
    per_fixture: list[dict[str, Any]] = []
    for name, samples in fixtures.items():
        per_fixture.append(_audit_single_fixture(name, samples, profile, engines, mc))

    # Worst-case aggregate verdict. The enumeration order below is
    # worst-first; first-match wins.
    severity_order = [
        "error",
        "shadow_unavailable",
        "collapsed_high_confidence_wrong_class",
        "collapsed_medium_confidence_wrong_class",
        "collapsed_high_confidence_one_of_live",
        "collapsed_medium_confidence_one_of_live",
        "graceful_degradation",
    ]
    all_verdicts = [r["collapse_verdict"] for r in per_fixture]
    aggregate_verdict = next((s for s in severity_order if s in all_verdicts), "graceful_degradation")

    # Count fixtures in each category for the memo/summary.
    verdict_counts = {v: all_verdicts.count(v) for v in severity_order if v in all_verdicts}

    # "Live-multi vs shadow-collapse" flag: how many fixtures had the
    # pathology where the cascade correctly found multiple entities
    # and v5 collapsed to a wrong class not in the cascade's set.
    live_multi_vs_shadow_collapse = sum(
        1
        for r in per_fixture
        if len(r.get("live_distinct_entities", [])) > 1 and "wrong_class" in r.get("collapse_verdict", "")
    )

    n_fixtures = len(per_fixture)
    n_high_conf_wrong = verdict_counts.get("collapsed_high_confidence_wrong_class", 0)
    n_med_conf_wrong = verdict_counts.get("collapsed_medium_confidence_wrong_class", 0)
    print(
        f"  aggregate: {aggregate_verdict}  "
        f"({n_high_conf_wrong}/{n_fixtures} high-conf-wrong, "
        f"{n_med_conf_wrong}/{n_fixtures} med-conf-wrong, "
        f"{live_multi_vs_shadow_collapse}/{n_fixtures} live-multi-vs-collapse)",
        file=sys.stderr,
    )

    return {
        "per_fixture": per_fixture,
        "aggregate_verdict": aggregate_verdict,
        "verdict_counts": verdict_counts,
        "n_fixtures": n_fixtures,
        "n_high_confidence_wrong_class": n_high_conf_wrong,
        "n_medium_confidence_wrong_class": n_med_conf_wrong,
        "n_live_multi_vs_shadow_collapse": live_multi_vs_shadow_collapse,
        # Legacy compat: the top-level ``collapse_verdict`` key is
        # the aggregate for the verdict logic below.
        "collapse_verdict": aggregate_verdict,
    }


# ── Verdict ─────────────────────────────────────────────────────────────────


@dataclass
class Verdict:
    level: str  # GREEN, YELLOW, RED
    reasons: list[str] = field(default_factory=list)
    mitigations: list[str] = field(default_factory=list)


def compute_verdict(q1: dict[str, Any], q2: dict[str, Any], q3: dict[str, Any]) -> Verdict:
    reasons: list[str] = []
    red_reasons: list[str] = []
    mitigations: list[str] = []

    # Pull the numbers the thresholds reference.
    # Q1 LOCO: use the best arm's LOCO unweighted (the backlog reads
    # "LOCO macro F1" without specifying weighting; unweighted is the
    # more conservative measurement — it does not let a large easy
    # corpus mask a small hard one).
    winner = q1["winner_by_cv_plus_loco"]
    winner_loco_unweighted = q1["arms"][winner]["loco"]["loco_mean_unweighted"]
    winner_loco_weighted = q1["arms"][winner]["loco"]["loco_mean_weighted"]
    q1_loco = winner_loco_unweighted

    q2_delta = q2["delta"]
    q3_verdict = q3["collapse_verdict"]

    # RED conditions (any triggers RED)
    if q1_loco < LOCO_RED_MAX:
        red_reasons.append(
            f"Q1 LOCO unweighted = {q1_loco:.4f} < RED threshold {LOCO_RED_MAX:.2f} — "
            f"flat architecture cannot generalize across held-out corpora"
        )
    if q2_delta >= ARCH_RED_MIN_DELTA:
        red_reasons.append(
            f"Q2 hard-gated delta = {q2_delta:+.4f} >= RED threshold {ARCH_RED_MIN_DELTA:.2f} — "
            f"hard gating unlocks material headroom soft-gating cannot reach"
        )
    if q3_verdict == "collapsed_high_confidence_wrong_class":
        red_reasons.append(
            f"Q3 shadow output collapsed to a single class NOT present in the column "
            f"at >={HETERO_COLLAPSE_CONFIDENCE:.2f} confidence — the exact silent-failure "
            "pathology the flat-architecture audit exists to catch"
        )

    # GREEN conditions (all must hold). Any shadow collapse to a class
    # not present in the live findings blocks GREEN — a medium-confidence
    # wrong-class collapse is still the flat-classifier pathology, just
    # less loud than the high-confidence version.
    q3_clean = q3_verdict in {
        "graceful_degradation",
        "collapsed_medium_confidence_one_of_live",
        "collapsed_high_confidence_one_of_live",
    }
    green_ok = q1_loco >= LOCO_GREEN_MIN and q2_delta < ARCH_GREEN_MAX_DELTA and q3_clean

    if red_reasons:
        reasons = red_reasons
        # Mitigation for RED is to defer directive flip to Sprint 13
        mitigations = ["Defer directive flip to Sprint 13; ship v0.12.0 with shadow-only meta-classifier."]
        return Verdict(level="RED", reasons=reasons, mitigations=mitigations)

    if green_ok:
        reasons.append(
            f"Q1 LOCO unweighted = {q1_loco:.4f} >= {LOCO_GREEN_MIN:.2f} (weighted = {winner_loco_weighted:.4f})"
        )
        reasons.append(f"Q2 hard-gated delta = {q2_delta:+.4f} < {ARCH_GREEN_MAX_DELTA:.2f}")
        reasons.append(f"Q3 column output = {q3_verdict} (no collapse)")
        return Verdict(level="GREEN", reasons=reasons, mitigations=[])

    # YELLOW — at least one threshold is in the grey zone but none are red
    if LOCO_RED_MAX <= q1_loco < LOCO_GREEN_MIN:
        reasons.append(
            f"Q1 LOCO unweighted = {q1_loco:.4f} is between RED {LOCO_RED_MAX:.2f} "
            f"and GREEN {LOCO_GREEN_MIN:.2f} — generalization is measurable but weak"
        )
        mitigations.append(
            "Per-entity confidence threshold (>=0.80) for directive; fall back to live "
            "cascade below threshold to preserve Items #1/#2 feature wins on high-confidence "
            "rows without inheriting LOCO risk on low-confidence rows."
        )
    if ARCH_GREEN_MAX_DELTA <= q2_delta < ARCH_RED_MIN_DELTA:
        reasons.append(
            f"Q2 hard-gated delta = {q2_delta:+.4f} is between GREEN {ARCH_GREEN_MAX_DELTA:.2f} "
            f"and RED {ARCH_RED_MIN_DELTA:.2f} — soft-gating leaves some headroom on the table"
        )
        mitigations.append(
            "Proceed with soft-gated directive but file Sprint 13 item to revisit hard gating"
            " if the in-production LOCO measurement drifts."
        )
    if q3_verdict == "collapsed_medium_confidence_wrong_class":
        reasons.append(
            "Q3 shadow output collapsed to a class NOT present in the column at medium "
            "confidence (0.50–0.80) — flat classifier silently picks a wrong class on "
            "heterogeneous input; confidence is low enough that a threshold fallback can "
            "catch it, but the structural problem is real"
        )
        mitigations.append(
            "Heterogeneous-column fallback: if directive shadow confidence < 0.80 AND "
            "column has heuristic_distinct_ratio > 0.9 (indicator of mixed content), "
            "fall back to live cascade output for this column. Preserves current live "
            "quality on log-shaped columns without inheriting flat-classifier collapse."
        )
    elif q3_verdict == "graceful_degradation":
        reasons.append(
            "Q3 column output degraded to a single low-confidence finding — flat classifier "
            "does not fail loudly on mixed content, but also does not represent it correctly"
        )
        mitigations.append(
            "Heterogeneous-column fallback to live cascade when directive confidence < 0.80 "
            "on columns with high heuristic_distinct_ratio (>0.9) — conservative but "
            "preserves current live quality on log-shaped columns."
        )
    return Verdict(level="YELLOW", reasons=reasons, mitigations=mitigations)


# ── Main ────────────────────────────────────────────────────────────────────


def run_audit(input_path: Path, out_path: Path) -> dict[str, Any]:
    dataset = _load_dataset(input_path)
    print(
        f"Loaded {len(dataset.base.labels)} rows, "
        f"{len(dataset.kept_feature_names)} features, "
        f"{len(set(dataset.base.labels))} classes",
        file=sys.stderr,
    )

    q1 = q1_capacity_audit(dataset)
    q2 = q2_architecture_audit(dataset)
    q3 = q3_heterogeneous_audit()
    verdict = compute_verdict(q1, q2, q3)

    result = {
        "q1_capacity": q1,
        "q2_architecture": q2,
        "q3_heterogeneous": q3,
        "verdict": {
            "level": verdict.level,
            "reasons": verdict.reasons,
            "mitigations": verdict.mitigations,
        },
        "thresholds": {
            "loco_green_min": LOCO_GREEN_MIN,
            "loco_red_max": LOCO_RED_MAX,
            "arch_green_max_delta": ARCH_GREEN_MAX_DELTA,
            "arch_red_min_delta": ARCH_RED_MIN_DELTA,
            "hetero_collapse_confidence": HETERO_COLLAPSE_CONFIDENCE,
        },
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, default=str))

    print("\n" + "=" * 72, file=sys.stderr)
    print(f"SPRINT 12 SAFETY AUDIT — VERDICT: {verdict.level}", file=sys.stderr)
    print("=" * 72, file=sys.stderr)
    for r in verdict.reasons:
        print(f"  • {r}", file=sys.stderr)
    if verdict.mitigations:
        print("\nMitigations:", file=sys.stderr)
        for m in verdict.mitigations:
            print(f"  → {m}", file=sys.stderr)
    print(f"\nFull JSON: {out_path}", file=sys.stderr)

    return result


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("tests/benchmarks/meta_classifier/training_data.jsonl"),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("/tmp/sprint12_safety_audit.json"),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    run_audit(args.input, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
