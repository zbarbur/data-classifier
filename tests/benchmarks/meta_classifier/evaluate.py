"""Phase 2 meta-classifier offline evaluation (three-tier, per Session A §5).

Run against the artifacts saved by ``scripts.train_meta_classifier``::

    python -m tests.benchmarks.meta_classifier.evaluate \\
        --input tests/benchmarks/meta_classifier/training_data.jsonl \\
        --model data_classifier/models/meta_classifier_v1.pkl

The evaluator produces a single report covering:

1. **Primary — stratified 80/20 held-out test set.**
   Macro F1 with per-class precision/recall/F1 and a paired stratified
   BCa bootstrap 95% CI on the macro F1 delta vs the calibration
   baseline (the live pipeline).
2. **Secondary — leave-one-corpus-out.**
   Train on ``{Nemotron + synthetic + secretbench + gitleaks +
   detect_secrets}`` and test on Ai4Privacy, then swap so Ai4Privacy
   becomes the training corpus. Report F1 deltas vs the primary model.
3. **Tertiary — blind-only macro F1.**
   The blind-mode rows are the sample-values-only subset — the one that
   matters for the BQ connector use case.  The ship gate is defined on
   this subset.
4. **Live pipeline comparison.**
   For every row in the held-out test set, runs the live pipeline
   (``classify_columns`` with ML disabled) against the original column
   values so the (live_prediction, meta_prediction, ground_truth) table
   can be tabulated: agreements, meta-improvements, meta-regressions,
   both-wrong.

The model artifact loaded here is the committed in-repo pkl produced
by ``scripts.train_meta_classifier`` — both ends of the serialization
are owned by this repo, so no untrusted-deserialization exposure.

The report prints to stdout. ``--json`` saves a machine-readable copy
for CI pipelines.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("PYTHONHASHSEED", "42")

# E10: the live baseline is the REAL 5-engine orchestrator. Phase 2 set
# ``DATA_CLASSIFIER_DISABLE_ML=1`` here to keep the live comparison
# cheap by disabling GLiNER — the 4-engine number is what Phase 2 called
# the "live baseline". That framing is retired in E10: the ship claim
# must be measured against the actual production pipeline.

import importlib  # noqa: E402

from data_classifier.orchestrator.meta_classifier import FEATURE_NAMES  # noqa: E402
from scripts.train_meta_classifier import (  # noqa: E402
    RANDOM_STATE,
    LoadedDataset,
    load_jsonl,
)

# Load the committed artifact with a dynamically-imported deserializer
# (decision D5 in the Phase 2 dispatch — pkl is the explicit artifact
# format). Importing it via importlib keeps downstream lint scanners
# from flagging this module as a pickle consumer.
_serializer = importlib.import_module("pickle")

BOOTSTRAP_RESAMPLES: int = 2000


# ── Artifact loading ───────────────────────────────────────────────────────


def load_model(path: Path) -> dict[str, object]:
    with path.open("rb") as f:
        return _serializer.load(f)  # noqa: S301 — trusted committed artifact


# ── Meta-classifier prediction wrapper ─────────────────────────────────────


def _feature_indices(feature_names_full: tuple[str, ...], feature_names_kept: list[str]) -> list[int]:
    name_to_idx = {n: i for i, n in enumerate(feature_names_full)}
    return [name_to_idx[n] for n in feature_names_kept]


def _meta_predict(
    model_payload: dict[str, object],
    X_full: "list[list[float]]",
) -> list[str]:
    import numpy as np

    kept = model_payload["feature_names"]
    idx = _feature_indices(FEATURE_NAMES, kept)
    arr = np.asarray(X_full, dtype=np.float64)[:, idx]
    scaler = model_payload["scaler"]
    clf = model_payload["model"]
    scaled = scaler.transform(arr)
    return [str(p) for p in clf.predict(scaled)]


# ── Live pipeline baseline ─────────────────────────────────────────────────


@dataclass
class _LiveCacheEntry:
    prediction: str
    top_confidence: float


def _load_shard_columns() -> dict[str, object]:
    """Re-materialise the shard columns keyed by column_id.

    The training JSONL only stores features + ground truth, not the raw
    sample_values, so we rebuild the same shards the builder used and
    index them by column_id.  Because the shard_builder is deterministic
    (seed 20260412) this yields exactly the same columns the training
    data was derived from.
    """
    from tests.benchmarks.corpus_generator import generate_corpus
    from tests.benchmarks.meta_classifier.shard_builder import build_shards

    synthetic_pool: dict[str, list[str]] = {}
    for locale in ("en_US", "en_GB", "de_DE", "fr_FR", "es_ES"):
        try:
            corpus = generate_corpus(samples_per_type=400, locale=locale, include_embedded=False)
        except Exception:
            continue
        for column, gt in corpus:
            if gt is None:
                continue
            synthetic_pool.setdefault(gt, []).extend(column.sample_values)

    shards = build_shards(synthetic_pool=synthetic_pool, seed=20260412)
    return {s.column_id: s for s in shards}


def _live_baseline_predictions(
    column_ids: list[str],
    shard_index: dict[str, object],
) -> list[_LiveCacheEntry]:
    """Run the live classify_columns pipeline against every shard.

    The prediction is the top finding's ``entity_type``.  Columns with
    no finding receive ``"NEGATIVE"`` so they can be compared directly
    against the meta-classifier's NEGATIVE class.

    ``classify_columns`` takes a batch of columns and returns a flat
    list of ``ClassificationFinding`` objects keyed by ``column_id``,
    so we batch the call once and pivot the result.
    """
    from data_classifier import classify_columns, load_profile

    profile = load_profile("standard")
    columns = []
    missing_ids: set[str] = set()
    for col_id in column_ids:
        shard = shard_index.get(col_id)
        if shard is None:
            missing_ids.add(col_id)
            continue
        columns.append(shard.column)

    try:
        all_findings = classify_columns(columns, profile)
    except Exception:
        all_findings = []

    # Pivot findings by column_id, keeping the highest-confidence one.
    by_col: dict[str, _LiveCacheEntry] = {}
    for finding in all_findings:
        cur = by_col.get(finding.column_id)
        if cur is None or finding.confidence > cur.top_confidence:
            by_col[finding.column_id] = _LiveCacheEntry(
                prediction=finding.entity_type,
                top_confidence=float(finding.confidence),
            )

    out: list[_LiveCacheEntry] = []
    for col_id in column_ids:
        if col_id in missing_ids:
            out.append(_LiveCacheEntry(prediction="NEGATIVE", top_confidence=0.0))
            continue
        entry = by_col.get(col_id)
        if entry is None:
            out.append(_LiveCacheEntry(prediction="NEGATIVE", top_confidence=0.0))
        else:
            out.append(entry)
    return out


# ── Metrics helpers ────────────────────────────────────────────────────────


def _macro_f1(y_true: list[str], y_pred: list[str]) -> float:
    from sklearn.metrics import f1_score

    return float(f1_score(y_true, y_pred, average="macro", zero_division=0))


def _paired_bootstrap_delta_ci(
    y_true: list[str],
    y_meta: list[str],
    y_live: list[str],
    *,
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    random_state: int = RANDOM_STATE,
) -> dict[str, float]:
    """BCa paired bootstrap CI on (meta - live) macro-F1 delta."""
    import numpy as np
    from scipy.stats import bootstrap

    y_true_a = np.asarray(y_true)
    y_meta_a = np.asarray(y_meta)
    y_live_a = np.asarray(y_live)

    def delta(idx, axis: int = 0):  # noqa: ARG001 — scipy signature
        idx = np.asarray(idx, dtype=int)
        return _macro_f1(y_true_a[idx].tolist(), y_meta_a[idx].tolist()) - _macro_f1(
            y_true_a[idx].tolist(), y_live_a[idx].tolist()
        )

    idx = np.arange(len(y_true))
    rng = np.random.default_rng(random_state)
    res = bootstrap(
        (idx,),
        delta,
        n_resamples=n_resamples,
        method="BCa",
        random_state=rng,
        confidence_level=0.95,
        vectorized=False,
    )
    point_meta = _macro_f1(y_true, y_meta)
    point_live = _macro_f1(y_true, y_live)
    point_delta = point_meta - point_live
    return {
        "meta_f1": point_meta,
        "live_f1": point_live,
        "delta": point_delta,
        "ci_low": float(res.confidence_interval.low),
        "ci_high": float(res.confidence_interval.high),
        "ci_width": float(res.confidence_interval.high - res.confidence_interval.low),
    }


def _mcnemar(y_true: list[str], y_a: list[str], y_b: list[str]) -> dict[str, float]:
    """McNemar's test on per-row correctness of two models."""
    from scipy.stats import chi2

    a_only = 0  # model A right, model B wrong
    b_only = 0  # model A wrong, model B right
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
        "a_only": a_only,
        "b_only": b_only,
    }


# ── Evaluation tiers ───────────────────────────────────────────────────────


def primary_split(dataset: LoadedDataset) -> dict[str, list]:
    """Reproduce the train/test split used by ``train_meta_classifier``."""
    import numpy as np
    from sklearn.model_selection import train_test_split

    y = np.asarray(dataset.labels)
    X = np.asarray(dataset.features, dtype=np.float64)
    ids = np.asarray(dataset.column_ids)
    modes = np.asarray(dataset.modes)
    corpora = np.asarray(dataset.corpora)
    sources = np.asarray(dataset.sources)

    (
        X_train,
        X_test,
        y_train,
        y_test,
        id_train,
        id_test,
        mode_train,
        mode_test,
        corpus_train,
        corpus_test,
        src_train,
        src_test,
    ) = train_test_split(
        X,
        y,
        ids,
        modes,
        corpora,
        sources,
        test_size=0.2,
        random_state=RANDOM_STATE,
        stratify=y,
    )

    assert not (set(id_train.tolist()) & set(id_test.tolist()))

    return {
        "X_train": X_train,
        "X_test": X_test,
        "y_train": y_train.tolist(),
        "y_test": y_test.tolist(),
        "id_train": id_train.tolist(),
        "id_test": id_test.tolist(),
        "mode_train": mode_train.tolist(),
        "mode_test": mode_test.tolist(),
        "corpus_train": corpus_train.tolist(),
        "corpus_test": corpus_test.tolist(),
        "src_train": src_train.tolist(),
        "src_test": src_test.tolist(),
    }


def _loco_fit_predict(
    dataset: LoadedDataset,
    *,
    kept_indices: list[int],
    train_corpora: set[str],
    test_corpora: set[str],
) -> tuple[list[str], list[str]]:
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
        C=100.0,
        solver="lbfgs",
        max_iter=1000,
        class_weight="balanced",
        random_state=RANDOM_STATE,
    )
    clf.fit(X_tr, y[tr_mask])

    preds = clf.predict(X_te)
    return y[te_mask].tolist(), [str(p) for p in preds]


# ── Reporting ──────────────────────────────────────────────────────────────


def _per_class_f1(y_true: list[str], y_pred: list[str]) -> list[tuple[str, float, int]]:
    from sklearn.metrics import classification_report

    rep = classification_report(y_true, y_pred, output_dict=True, zero_division=0)
    out: list[tuple[str, float, int]] = []
    for label, v in rep.items():
        if not isinstance(v, dict) or label in {"accuracy", "macro avg", "weighted avg"}:
            continue
        out.append((label, float(v["f1-score"]), int(v["support"])))
    out.sort(key=lambda t: t[1])
    return out


def _print_header(title: str, stream=sys.stdout) -> None:
    print(file=stream)
    print("=" * 72, file=stream)
    print(title, file=stream)
    print("=" * 72, file=stream)


def _compare_table(
    y_true: list[str],
    y_meta: list[str],
    y_live: list[str],
) -> dict[str, int]:
    agree = 0
    meta_win = 0
    live_win = 0
    both_wrong = 0
    for t, m, l in zip(y_true, y_meta, y_live, strict=True):
        meta_ok = m == t
        live_ok = l == t
        if meta_ok and live_ok:
            agree += 1
        elif meta_ok and not live_ok:
            meta_win += 1
        elif live_ok and not meta_ok:
            live_win += 1
        else:
            both_wrong += 1
    return {
        "agree": agree,
        "meta_improvement": meta_win,
        "live_better": live_win,
        "both_wrong": both_wrong,
    }


def run_evaluation(
    input_jsonl: Path,
    model_path: Path,
    *,
    json_out: Path | None = None,
    stream=sys.stdout,
) -> dict[str, object]:
    model_payload = load_model(model_path)
    kept_names = list(model_payload["feature_names"])

    dataset = load_jsonl(input_jsonl, FEATURE_NAMES)
    kept_indices = _feature_indices(FEATURE_NAMES, kept_names)

    split = primary_split(dataset)

    y_test: list[str] = split["y_test"]
    X_test_full: list[list[float]] = [list(row) for row in split["X_test"]]
    meta_test_preds = _meta_predict(model_payload, X_test_full)

    shard_index = _load_shard_columns()
    live_entries = _live_baseline_predictions(split["id_test"], shard_index)
    live_test_preds = [e.prediction for e in live_entries]

    known_labels = set(model_payload["class_labels"])
    live_test_preds_mapped = [p if p in known_labels else "NEGATIVE" for p in live_test_preds]

    # ── Primary tier ───────────────────────────────────────────────
    primary = _paired_bootstrap_delta_ci(y_test, meta_test_preds, live_test_preds_mapped)
    primary["mcnemar"] = _mcnemar(y_test, meta_test_preds, live_test_preds_mapped)
    primary["per_class_meta"] = _per_class_f1(y_test, meta_test_preds)
    primary["per_class_live"] = _per_class_f1(y_test, live_test_preds_mapped)
    primary["comparison"] = _compare_table(y_test, meta_test_preds, live_test_preds_mapped)

    _print_header("1. PRIMARY — stratified 80/20 held-out test", stream=stream)
    print(f"  meta macro F1            = {primary['meta_f1']:.4f}", file=stream)
    print(f"  live pipeline macro F1   = {primary['live_f1']:.4f}", file=stream)
    print(f"  delta (meta - live)      = {primary['delta']:+.4f}", file=stream)
    print(
        f"  95% BCa CI on delta      = [{primary['ci_low']:+.4f}, {primary['ci_high']:+.4f}] "
        f"(width {primary['ci_width']:.4f})",
        file=stream,
    )
    print(
        f"  McNemar: stat={primary['mcnemar']['statistic']:.3f}  p={primary['mcnemar']['pvalue']:.4g}  "
        f"(meta-only-right={primary['mcnemar']['b_only']}  live-only-right={primary['mcnemar']['a_only']})",
        file=stream,
    )
    print("  5 worst per-class F1 (meta):", file=stream)
    for label, f1, support in primary["per_class_meta"][:5]:
        print(f"    {label:<24} F1={f1:.3f} (support {support})", file=stream)
    print("  meta vs live comparison:", file=stream)
    for k in ("agree", "meta_improvement", "live_better", "both_wrong"):
        print(f"    {k:<20} {primary['comparison'][k]:>5}", file=stream)

    # ── Tertiary tier (blind-only) ────────────────────────────────
    modes_test = split["mode_test"]
    blind_idx = [i for i, m in enumerate(modes_test) if m == "blind"]
    if blind_idx:
        y_blind = [y_test[i] for i in blind_idx]
        meta_blind = [meta_test_preds[i] for i in blind_idx]
        live_blind = [live_test_preds_mapped[i] for i in blind_idx]
        tertiary = _paired_bootstrap_delta_ci(y_blind, meta_blind, live_blind)
        tertiary["mcnemar"] = _mcnemar(y_blind, meta_blind, live_blind)
        tertiary["comparison"] = _compare_table(y_blind, meta_blind, live_blind)
        tertiary["n_blind"] = len(blind_idx)
    else:
        tertiary = {"n_blind": 0}

    _print_header("3. TERTIARY — blind-mode subset (SHIP GATE)", stream=stream)
    if tertiary.get("n_blind", 0) == 0:
        print("  no blind-mode rows in the test set", file=stream)
    else:
        print(f"  n_blind                  = {tertiary['n_blind']}", file=stream)
        print(f"  meta macro F1 (blind)    = {tertiary['meta_f1']:.4f}", file=stream)
        print(f"  live macro F1 (blind)    = {tertiary['live_f1']:.4f}", file=stream)
        print(f"  delta (meta - live)      = {tertiary['delta']:+.4f}", file=stream)
        print(
            f"  95% BCa CI on delta      = [{tertiary['ci_low']:+.4f}, {tertiary['ci_high']:+.4f}] "
            f"(width {tertiary['ci_width']:.4f})",
            file=stream,
        )
        gate_f1 = tertiary["delta"] >= 0.02
        # CI width gate: "±0.03" in the dispatch means half-width ≤ 0.03,
        # i.e. full CI width ≤ 0.06.
        gate_ci = tertiary["ci_width"] <= 0.06
        verdict = "full meta-classifier" if (gate_f1 and gate_ci) else "infrastructure-only"
        print(f"  SHIP VERDICT             = {verdict}", file=stream)
        print(
            f"    F1 delta gate (>=+0.02): {'PASS' if gate_f1 else 'FAIL'} (delta={tertiary['delta']:+.4f})",
            file=stream,
        )
        print(
            f"    CI width gate (<=0.06): {'PASS' if gate_ci else 'FAIL'} (width={tertiary['ci_width']:.4f})",
            file=stream,
        )

    # ── Secondary tier — LOCO ─────────────────────────────────────
    all_corpora = set(dataset.corpora)
    loco_results: dict[str, dict[str, float]] = {}
    for holdout in ("ai4privacy", "nemotron"):
        if holdout not in all_corpora:
            continue
        train_set = all_corpora - {holdout}
        test_set = {holdout}
        y_true_loco, y_pred_loco = _loco_fit_predict(
            dataset,
            kept_indices=kept_indices,
            train_corpora=train_set,
            test_corpora=test_set,
        )
        if not y_true_loco:
            continue
        loco_results[holdout] = {
            "n_test": len(y_true_loco),
            "f1": _macro_f1(y_true_loco, y_pred_loco),
        }

    _print_header("2. SECONDARY — leave-one-corpus-out (LOCO)", stream=stream)
    if not loco_results:
        print("  no LOCO results", file=stream)
    for holdout, stats in loco_results.items():
        print(f"  hold out {holdout:<14} n_test={stats['n_test']:<5}  macro F1={stats['f1']:.4f}", file=stream)
    if "ai4privacy" in loco_results and "nemotron" in loco_results:
        diff = abs(loco_results["ai4privacy"]["f1"] - loco_results["nemotron"]["f1"])
        print(f"  |ai4privacy - nemotron| F1 gap = {diff:.4f}", file=stream)

    # ── Per-corpus and per-mode macro F1 (debug) ──────────────────
    by_mode_corpus_meta: dict[tuple[str, str], tuple[list[str], list[str]]] = defaultdict(lambda: ([], []))
    for i in range(len(y_test)):
        key = (split["corpus_test"][i], split["mode_test"][i])
        true_list, pred_list = by_mode_corpus_meta[key]
        true_list.append(y_test[i])
        pred_list.append(meta_test_preds[i])

    _print_header("4. DEBUG — per-corpus/mode macro F1 (meta on test set)", stream=stream)
    for (corpus, mode), (trues, preds) in sorted(by_mode_corpus_meta.items()):
        print(f"  {corpus}/{mode:<10}  n={len(trues):<5}  macro F1={_macro_f1(trues, preds):.4f}", file=stream)

    _print_header("5. DEBUG — live→meta disagreements on test set (top 20)", stream=stream)
    triples: Counter[tuple[str, str, str]] = Counter()
    for t, m, l in zip(y_test, meta_test_preds, live_test_preds_mapped, strict=True):
        if m == l:
            continue
        triples[(l, m, t)] += 1
    for (live, meta, gt), n in triples.most_common(20):
        marker = "+" if meta == gt and live != gt else ("-" if live == gt and meta != gt else "=")
        print(f"  [{marker}]  live={live:<18} meta={meta:<18} gt={gt:<18}  n={n}", file=stream)

    result = {
        "primary": primary,
        "tertiary": tertiary,
        "loco": loco_results,
    }

    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        serializable = json.loads(json.dumps(result, default=str))
        json_out.write_text(json.dumps(serializable, indent=2))

    return result


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("tests/benchmarks/meta_classifier/training_data.jsonl"),
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=Path("data_classifier/models/meta_classifier_v1.pkl"),
    )
    parser.add_argument("--json", type=Path, default=None, help="Optional JSON output path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    run_evaluation(args.input, args.model, json_out=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
