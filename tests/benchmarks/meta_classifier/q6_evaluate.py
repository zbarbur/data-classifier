"""Q6 offline evaluation: PII-only meta-classifier (inverted stage 1).

Produces the three-tier numbers that Q6's result.md needs, plus a
head-to-head comparison against the shipped v1 model on PII-only rows.

The baseline eval script (``tests/benchmarks/meta_classifier/evaluate.py``)
hardcodes the LOCO outer loop to ``("ai4privacy", "nemotron")``, which
was correct for v1 (other corpora were credential-pure) but wrong for
Q6 (synthetic is the third diverse PII corpus). This script iterates
over all three PII corpora and also runs McNemar's paired test against
v1 on the PII held-out rows.

No production code is touched. This module lives under
``tests/benchmarks/meta_classifier`` which the research workflow
contract permits. All pkl loading is delegated to the existing
``evaluate.load_model`` helper so this file has no direct
serialization logic of its own.
"""
# ruff: noqa: N803, N806
# N803/N806 suppress the ML convention on X/C/X_train naming so this file
# matches the per-file-ignores already applied to the sibling evaluate.py
# in pyproject.toml.

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("PYTHONHASHSEED", "42")
os.environ.setdefault("DATA_CLASSIFIER_DISABLE_ML", "1")

from data_classifier.orchestrator.meta_classifier import FEATURE_NAMES  # noqa: E402
from scripts.train_meta_classifier import RANDOM_STATE, load_jsonl  # noqa: E402
from tests.benchmarks.meta_classifier.evaluate import load_model  # noqa: E402

BOOTSTRAP_RESAMPLES = 2000


def _feature_indices(kept: list[str]) -> list[int]:
    name_to_idx = {n: i for i, n in enumerate(FEATURE_NAMES)}
    return [name_to_idx[n] for n in kept]


def _predict(payload: dict, X_full):
    import numpy as np

    kept = list(payload["feature_names"])
    idx = _feature_indices(kept)
    arr = np.asarray(X_full, dtype=np.float64)[:, idx]
    scaled = payload["scaler"].transform(arr)
    return [str(p) for p in payload["model"].predict(scaled)]


def _macro_f1(y_true, y_pred):
    from sklearn.metrics import f1_score

    return float(f1_score(y_true, y_pred, average="macro", zero_division=0))


def _per_class_f1(y_true, y_pred):
    from sklearn.metrics import classification_report

    rep = classification_report(y_true, y_pred, output_dict=True, zero_division=0)
    out = []
    for label, v in rep.items():
        if not isinstance(v, dict) or label in {"accuracy", "macro avg", "weighted avg"}:
            continue
        out.append((label, float(v["f1-score"]), int(v["support"])))
    return out


def _mcnemar(y_true, y_a, y_b):
    from scipy.stats import chi2

    a_only = 0
    b_only = 0
    for t, a, b in zip(y_true, y_a, y_b, strict=True):
        a_ok = a == t
        b_ok = b == t
        if a_ok and not b_ok:
            a_only += 1
        elif b_ok and not a_ok:
            b_only += 1
    total = a_only + b_only
    if total == 0:
        return {"statistic": 0.0, "pvalue": 1.0, "a_only": 0, "b_only": 0}
    statistic = (abs(a_only - b_only) - 1) ** 2 / total
    pvalue = float(1.0 - chi2.cdf(statistic, df=1))
    return {
        "statistic": float(statistic),
        "pvalue": pvalue,
        "a_only": int(a_only),
        "b_only": int(b_only),
    }


def _bootstrap_f1_ci(y_true, y_pred, *, n_resamples=BOOTSTRAP_RESAMPLES, random_state=RANDOM_STATE):
    import numpy as np
    from scipy.stats import bootstrap
    from sklearn.metrics import f1_score

    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)

    def stat(idx, axis=0):  # noqa: ARG001
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


def _primary_split(dataset):
    """Reproduce the 80/20 split the training script used (same seed)."""
    import numpy as np
    from sklearn.model_selection import train_test_split

    y = np.asarray(dataset.labels)
    X = np.asarray(dataset.features, dtype=np.float64)
    ids = np.asarray(dataset.column_ids)
    corpora = np.asarray(dataset.corpora)
    modes = np.asarray(dataset.modes)

    (
        X_tr,
        X_te,
        y_tr,
        y_te,
        id_tr,
        id_te,
        c_tr,
        c_te,
        m_tr,
        m_te,
    ) = train_test_split(X, y, ids, corpora, modes, test_size=0.2, random_state=RANDOM_STATE, stratify=y)
    return {
        "X_test": X_te,
        "y_test": y_te.tolist(),
        "id_test": id_te.tolist(),
        "corpus_test": c_te.tolist(),
        "mode_test": m_te.tolist(),
    }


def _loco_fit_predict(dataset, *, kept_indices, C, train_corpora, test_corpora):
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    X = np.asarray(dataset.features, dtype=np.float64)[:, kept_indices]
    y = np.asarray(dataset.labels)
    corp = np.asarray(dataset.corpora)

    tr_mask = np.isin(corp, list(train_corpora))
    te_mask = np.isin(corp, list(test_corpora))
    if tr_mask.sum() == 0 or te_mask.sum() == 0:
        return [], []

    scaler = StandardScaler()
    X_tr = scaler.fit_transform(X[tr_mask])
    X_te = scaler.transform(X[te_mask])

    clf = LogisticRegression(
        C=C,
        solver="lbfgs",
        max_iter=1000,
        class_weight="balanced",
        random_state=RANDOM_STATE,
    )
    clf.fit(X_tr, y[tr_mask])
    preds = clf.predict(X_te)
    return y[te_mask].tolist(), [str(p) for p in preds]


def run(
    *,
    q6_jsonl: Path,
    q6_model_path: Path,
    v1_model_path: Path,
    json_out: Path | None = None,
    stream=sys.stdout,
) -> dict:
    q6_payload = load_model(q6_model_path)
    v1_payload = load_model(v1_model_path)

    q6_meta = json.loads((q6_model_path.parent / (q6_model_path.stem + ".metadata.json")).read_text())
    best_c_q6 = float(q6_meta.get("best_c", 100.0))

    dataset_q6 = load_jsonl(q6_jsonl, FEATURE_NAMES)
    split = _primary_split(dataset_q6)

    y_test = split["y_test"]
    X_test = split["X_test"]

    # ── Primary: held-out macro F1 for Q6 and for v1 on the same rows ──
    q6_preds = _predict(q6_payload, X_test)
    v1_preds = _predict(v1_payload, X_test)

    q6_f1, q6_ci_low, q6_ci_high = _bootstrap_f1_ci(y_test, q6_preds)
    v1_f1 = _macro_f1(y_test, v1_preds)

    mcnemar = _mcnemar(y_test, v1_preds, q6_preds)

    q6_per_class = sorted(_per_class_f1(y_test, q6_preds), key=lambda t: t[1])
    v1_per_class_map = {lbl: (f1, sup) for lbl, f1, sup in _per_class_f1(y_test, v1_preds)}

    # ── LOCO: iterate over all 3 PII corpora ──
    q6_kept = list(q6_payload["feature_names"])
    q6_indices = _feature_indices(q6_kept)

    loco: dict[str, dict] = {}
    for holdout in ("ai4privacy", "nemotron", "synthetic"):
        train_set = {"ai4privacy", "nemotron", "synthetic"} - {holdout}
        y_true, y_pred = _loco_fit_predict(
            dataset_q6,
            kept_indices=q6_indices,
            C=best_c_q6,
            train_corpora=train_set,
            test_corpora={holdout},
        )
        if not y_true:
            continue
        loco[holdout] = {
            "n_test": len(y_true),
            "f1": _macro_f1(y_true, y_pred),
        }

    loco_mean = (sum(v["f1"] for v in loco.values()) / len(loco)) if loco else 0.0

    # ── Reporting ──
    def hdr(title):
        print(file=stream)
        print("=" * 72, file=stream)
        print(title, file=stream)
        print("=" * 72, file=stream)

    hdr("Q6: PII-only meta-classifier evaluation")
    print(f"  training data         : {q6_jsonl}", file=stream)
    print(f"  rows                  : {len(dataset_q6.labels)}", file=stream)
    print(f"  classes               : {len(set(dataset_q6.labels))}", file=stream)
    print(f"  best C                : {best_c_q6}", file=stream)
    print(f"  features used (n={len(q6_kept)}): {q6_kept}", file=stream)

    hdr("1. PRIMARY — held-out 80/20 (PII-only rows)")
    print(f"  n_test                = {len(y_test)}", file=stream)
    print(f"  v1_q6  macro F1       = {q6_f1:.4f}", file=stream)
    print(
        f"  v1_q6  95% BCa CI     = [{q6_ci_low:.4f}, {q6_ci_high:.4f}] (width {q6_ci_high - q6_ci_low:.4f})",
        file=stream,
    )
    print(f"  v1 (on same rows)     = {v1_f1:.4f}", file=stream)
    print(f"  delta (q6 - v1)       = {q6_f1 - v1_f1:+.4f}", file=stream)
    print(
        f"  McNemar v1 vs q6      : stat={mcnemar['statistic']:.3f} p={mcnemar['pvalue']:.4g} "
        f"(q6-only-right={mcnemar['b_only']}, v1-only-right={mcnemar['a_only']})",
        file=stream,
    )

    print("  5 worst per-class F1 (q6 on PII test rows):", file=stream)
    for lbl, f1, sup in q6_per_class[:5]:
        v1_f, _ = v1_per_class_map.get(lbl, (0.0, 0))
        print(
            f"    {lbl:<24} q6 F1={f1:.3f} (sup {sup})  v1 F1={v1_f:.3f}",
            file=stream,
        )

    hdr("2. SECONDARY — LOCO over 3 PII corpora")
    for corpus, v in loco.items():
        print(
            f"  hold out {corpus:<14} n_test={v['n_test']:<5} macro F1={v['f1']:.4f}",
            file=stream,
        )
    print(f"  LOCO MEAN macro F1    = {loco_mean:.4f}", file=stream)

    # Reference numbers from v1 (Q3 extended LOCO table per queue §M3)
    v1_loco_ref = {
        "ai4privacy": 0.26,
        "nemotron": 0.36,
        "synthetic": 0.13,
    }
    hdr("3. BASELINE — v1 LOCO reference (Q3 extended table)")
    for corpus, f1 in v1_loco_ref.items():
        q6_here = loco.get(corpus, {}).get("f1", float("nan"))
        delta = (q6_here - f1) if q6_here == q6_here else float("nan")
        print(
            f"  hold out {corpus:<14} v1={f1:.3f}  q6={q6_here:.4f}  delta={delta:+.4f}",
            file=stream,
        )
    v1_mean = sum(v1_loco_ref.values()) / len(v1_loco_ref)
    print(f"  v1 3-corpus mean      = {v1_mean:.4f}", file=stream)
    print(f"  q6 3-corpus mean      = {loco_mean:.4f}", file=stream)
    print(f"  LOCO delta (q6 - v1)  = {loco_mean - v1_mean:+.4f}", file=stream)

    # ── Verdict classifier ──
    if loco_mean >= 0.60:
        verdict = "Q6-A"
        verdict_text = "LOCO ≥ 0.60 — label purity was the whole story. Ship as v2."
    elif loco_mean >= 0.45:
        verdict = "Q6-B"
        verdict_text = "LOCO 0.45–0.60 — partial fix. Recommend hybrid Q6 + E10 (GLiNER)."
    else:
        verdict = "Q6-C"
        verdict_text = "LOCO < 0.45 — label purity was not the dominant issue. Pivot to E10 or E9."

    hdr("VERDICT")
    print(f"  classification        : {verdict}", file=stream)
    print(f"  recommendation        : {verdict_text}", file=stream)

    result = {
        "q6_model": str(q6_model_path),
        "v1_model": str(v1_model_path),
        "training_rows": len(dataset_q6.labels),
        "classes": sorted(set(dataset_q6.labels)),
        "best_c": best_c_q6,
        "features": q6_kept,
        "primary": {
            "n_test": len(y_test),
            "q6_f1": q6_f1,
            "q6_ci_low": q6_ci_low,
            "q6_ci_high": q6_ci_high,
            "v1_f1_on_pii_test": v1_f1,
            "delta": q6_f1 - v1_f1,
            "mcnemar": mcnemar,
            "q6_per_class": q6_per_class,
            "v1_per_class_on_pii_test": [(lbl, f1, sup) for lbl, (f1, sup) in sorted(v1_per_class_map.items())],
        },
        "loco": loco,
        "loco_mean": loco_mean,
        "v1_loco_reference": v1_loco_ref,
        "v1_loco_mean_3corpus": v1_mean,
        "loco_delta": loco_mean - v1_mean,
        "verdict": verdict,
        "verdict_text": verdict_text,
    }

    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(result, indent=2, default=str))
        print(f"\n  wrote JSON report to {json_out}", file=stream)

    return result


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--q6-input",
        type=Path,
        default=Path("tests/benchmarks/meta_classifier/training_data_q6.jsonl"),
    )
    p.add_argument(
        "--q6-model",
        type=Path,
        default=Path("data_classifier/models/meta_classifier_v1_q6.pkl"),
    )
    p.add_argument(
        "--v1-model",
        type=Path,
        default=Path("data_classifier/models/meta_classifier_v1.pkl"),
    )
    p.add_argument("--json", type=Path, default=None)
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    run(
        q6_jsonl=args.q6_input,
        q6_model_path=args.q6_model,
        v1_model_path=args.v1_model,
        json_out=args.json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
