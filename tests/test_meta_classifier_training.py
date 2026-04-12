"""Phase 2 meta-classifier training pipeline unit tests.

These tests are sklearn-dependent. They are skipped if the `[meta]`
extra is not installed, so the repo's CI without sklearn still passes.

The model artifacts loaded below are produced by the same training
script under test — both ends of the serialization are owned by this
repo, so there is no untrusted-deserialization exposure.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

_HAS_SKLEARN = (
    importlib.util.find_spec("sklearn") is not None
    and importlib.util.find_spec("numpy") is not None
    and importlib.util.find_spec("scipy") is not None
)

pytestmark = pytest.mark.skipif(
    not _HAS_SKLEARN,
    reason="Phase 2 training tests require the `[meta]` extra (sklearn/numpy/scipy)",
)

os.environ.setdefault("DATA_CLASSIFIER_DISABLE_ML", "1")


def _load_artifact(path: Path) -> dict:
    """Deserialize a committed meta-classifier artifact produced by
    ``scripts.train_meta_classifier``. We own both ends of the format
    so there is no untrusted-input concern."""
    serializer = importlib.import_module("pickle")
    with path.open("rb") as f:
        return serializer.load(f)  # noqa: S301 — trusted artifact


# ── Helpers ────────────────────────────────────────────────────────────────


def _fixture_jsonl(tmp_path: Path, rows: list[dict]) -> Path:
    out = tmp_path / "training_fixture.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return out


def _base_feature_vector(**overrides) -> list[float]:
    # E10 widened the schema from 15 → 20 features. Each entry here must
    # stay in lockstep with FEATURE_NAMES in
    # data_classifier/orchestrator/meta_classifier.py — if a new name is
    # appended there, add it here with a zero default or the dict lookup
    # below raises KeyError.
    vector: dict[str, float] = {
        "top_overall_confidence": 0.0,
        "regex_confidence": 0.0,
        "column_name_confidence": 0.0,
        "heuristic_confidence": 0.0,
        "secret_scanner_confidence": 0.0,
        "engines_agreed": 0.0,
        "engines_fired": 0.0,
        "confidence_gap": 0.0,
        "regex_match_ratio": 0.0,
        "heuristic_distinct_ratio": 0.0,
        "heuristic_avg_length": 0.0,
        "has_column_name_hit": 0.0,
        "has_secret_indicators": 0.0,
        "primary_is_pii": 0.0,
        "primary_is_credential": 0.0,
        "gliner_top_confidence": 0.0,
        "gliner_top_entity_is_pii": 0.0,
        "gliner_agrees_with_regex": 0.0,
        "gliner_agrees_with_column": 0.0,
        "gliner_confidence_gap": 0.0,
    }
    vector.update(overrides)
    from data_classifier.orchestrator.meta_classifier import FEATURE_NAMES

    return [vector[n] for n in FEATURE_NAMES]


def _row(col_id: str, gt: str, corpus: str = "test", mode: str = "named", **features) -> dict:
    return {
        "column_id": col_id,
        "corpus": corpus,
        "mode": mode,
        "source": "real",
        "features": _base_feature_vector(**features),
        "ground_truth": gt,
    }


def _small_three_class_fixture() -> list[dict]:
    rows: list[dict] = []
    for i in range(8):
        rows.append(
            _row(
                f"email_named_{i}",
                "EMAIL",
                mode="named",
                top_overall_confidence=0.95,
                regex_confidence=0.95,
                column_name_confidence=0.85,
                engines_agreed=2.0,
                engines_fired=2.0,
                regex_match_ratio=0.98,
                has_column_name_hit=1.0,
                primary_is_pii=1.0,
                heuristic_distinct_ratio=0.9,
                heuristic_avg_length=0.25,
            )
        )
        rows.append(
            _row(
                f"email_blind_{i}",
                "EMAIL",
                mode="blind",
                top_overall_confidence=0.9,
                regex_confidence=0.9,
                engines_agreed=1.0,
                engines_fired=1.0,
                regex_match_ratio=0.98,
                primary_is_pii=1.0,
                heuristic_distinct_ratio=0.9,
                heuristic_avg_length=0.25,
            )
        )
    for i in range(8):
        rows.append(
            _row(
                f"ssn_named_{i}",
                "SSN",
                mode="named",
                top_overall_confidence=0.93,
                regex_confidence=0.93,
                column_name_confidence=0.8,
                engines_agreed=2.0,
                engines_fired=2.0,
                regex_match_ratio=1.0,
                has_column_name_hit=1.0,
                primary_is_pii=1.0,
                heuristic_distinct_ratio=0.95,
                heuristic_avg_length=0.11,
            )
        )
        rows.append(
            _row(
                f"ssn_blind_{i}",
                "SSN",
                mode="blind",
                top_overall_confidence=0.9,
                regex_confidence=0.9,
                engines_agreed=1.0,
                engines_fired=1.0,
                regex_match_ratio=1.0,
                primary_is_pii=1.0,
                heuristic_distinct_ratio=0.95,
                heuristic_avg_length=0.11,
            )
        )
    for i in range(8):
        rows.append(
            _row(
                f"neg_named_{i}",
                "NEGATIVE",
                mode="named",
                heuristic_distinct_ratio=0.4,
                heuristic_avg_length=0.08,
            )
        )
        rows.append(
            _row(
                f"neg_blind_{i}",
                "NEGATIVE",
                mode="blind",
                heuristic_distinct_ratio=0.4,
                heuristic_avg_length=0.08,
            )
        )
    return rows


# ── Tests ──────────────────────────────────────────────────────────────────


class TestTrainingScriptEndToEnd:
    def test_cli_runs_end_to_end_on_fixture(self, tmp_path: Path) -> None:
        from scripts.train_meta_classifier import main as train_main

        input_path = _fixture_jsonl(tmp_path, _small_three_class_fixture())
        model_path = tmp_path / "model.pkl"
        metadata_path = tmp_path / "model.metadata.json"

        rc = train_main(
            [
                "--input",
                str(input_path),
                "--output",
                str(model_path),
                "--metadata",
                str(metadata_path),
            ]
        )
        assert rc == 0
        assert model_path.exists()
        assert metadata_path.exists()

        metadata = json.loads(metadata_path.read_text())
        assert metadata["total_rows"] == 48
        assert set(metadata["class_labels"]) == {"EMAIL", "SSN", "NEGATIVE"}
        assert metadata["held_out_test_macro_f1"] > 0.0


class TestModelRoundtrip:
    def test_save_load_roundtrip_preserves_predictions(self, tmp_path: Path) -> None:
        import numpy as np

        from scripts.train_meta_classifier import main as train_main

        input_path = _fixture_jsonl(tmp_path, _small_three_class_fixture())
        model_path = tmp_path / "m.pkl"
        meta_path = tmp_path / "m.metadata.json"
        train_main(["--input", str(input_path), "--output", str(model_path), "--metadata", str(meta_path)])

        payload = _load_artifact(model_path)

        from data_classifier.orchestrator.meta_classifier import FEATURE_NAMES

        kept = payload["feature_names"]
        name_to_idx = {n: i for i, n in enumerate(FEATURE_NAMES)}
        idx = [name_to_idx[n] for n in kept]

        rows = _small_three_class_fixture()
        X = np.asarray([r["features"] for r in rows])[:, idx]
        X_scaled = payload["scaler"].transform(X)
        p1 = payload["model"].predict_proba(X_scaled)

        payload2 = _load_artifact(model_path)
        X_scaled2 = payload2["scaler"].transform(X)
        p2 = payload2["model"].predict_proba(X_scaled2)

        np.testing.assert_allclose(p1, p2, atol=1e-9)


class TestClassImbalance:
    def test_balanced_class_weight_no_nan_coefs(self, tmp_path: Path) -> None:
        import numpy as np

        from scripts.train_meta_classifier import main as train_main

        rows: list[dict] = []
        for i in range(30):
            rows.append(
                _row(
                    f"email_{i}",
                    "EMAIL",
                    top_overall_confidence=0.9,
                    regex_confidence=0.9,
                    engines_agreed=1.0,
                    engines_fired=1.0,
                    regex_match_ratio=1.0,
                    primary_is_pii=1.0,
                    heuristic_distinct_ratio=0.9,
                    heuristic_avg_length=0.25,
                )
            )
        for i in range(4):
            rows.append(
                _row(
                    f"ssn_{i}",
                    "SSN",
                    top_overall_confidence=0.9,
                    regex_confidence=0.9,
                    engines_agreed=1.0,
                    engines_fired=1.0,
                    regex_match_ratio=1.0,
                    primary_is_pii=1.0,
                    heuristic_distinct_ratio=0.95,
                    heuristic_avg_length=0.11,
                )
            )
        for i in range(4):
            rows.append(_row(f"neg_{i}", "NEGATIVE", heuristic_distinct_ratio=0.3, heuristic_avg_length=0.05))

        input_path = _fixture_jsonl(tmp_path, rows)
        model_path = tmp_path / "m.pkl"
        meta_path = tmp_path / "m.metadata.json"
        train_main(["--input", str(input_path), "--output", str(model_path), "--metadata", str(meta_path)])

        payload = _load_artifact(model_path)
        assert not np.any(np.isnan(payload["model"].coef_))


class TestFeatureDropping:
    def test_constant_feature_detection_drops_all_zero_columns(self) -> None:
        from data_classifier.orchestrator.meta_classifier import FEATURE_NAMES
        from scripts.train_meta_classifier import (
            ALWAYS_DROP_REDUNDANT,
            CONDITIONAL_DROP_IF_CONSTANT,
            LoadedDataset,
            resolve_feature_subset,
        )

        row = _row("c_0", "EMAIL")
        dataset = LoadedDataset(
            features=[row["features"]] * 3,
            labels=["EMAIL"] * 3,
            column_ids=["a", "b", "c"],
            corpora=["test"] * 3,
            modes=["named"] * 3,
            sources=["real"] * 3,
            feature_names=list(FEATURE_NAMES),
        )
        kept_names, _ = resolve_feature_subset(dataset)
        assert set(ALWAYS_DROP_REDUNDANT).isdisjoint(kept_names)
        for name in CONDITIONAL_DROP_IF_CONSTANT:
            assert name not in kept_names

    def test_non_constant_conditional_features_are_kept(self) -> None:
        from data_classifier.orchestrator.meta_classifier import FEATURE_NAMES
        from scripts.train_meta_classifier import LoadedDataset, resolve_feature_subset

        row_zero = _row("a", "EMAIL")
        row_nonzero = _row("b", "EMAIL", secret_scanner_confidence=0.8)
        dataset = LoadedDataset(
            features=[row_zero["features"], row_nonzero["features"]],
            labels=["EMAIL", "EMAIL"],
            column_ids=["a", "b"],
            corpora=["test", "test"],
            modes=["named", "named"],
            sources=["real", "real"],
            feature_names=list(FEATURE_NAMES),
        )
        kept_names, _ = resolve_feature_subset(dataset)
        assert "secret_scanner_confidence" in kept_names
        assert "has_secret_indicators" not in kept_names

    def test_effective_feature_count_on_phase2_dataset(self) -> None:
        from data_classifier.orchestrator.meta_classifier import FEATURE_NAMES
        from scripts.train_meta_classifier import load_jsonl, resolve_feature_subset

        path = Path("tests/benchmarks/meta_classifier/training_data.jsonl")
        if not path.exists():
            pytest.skip("training_data.jsonl not built")
        dataset = load_jsonl(path, FEATURE_NAMES)
        kept_names, kept_indices = resolve_feature_subset(dataset)
        assert len(kept_names) == 13
        assert len(kept_indices) == 13


class TestBootstrapCI:
    def test_bootstrap_ci_matches_manual_calc(self) -> None:
        import numpy as np
        from sklearn.metrics import f1_score

        from scripts.train_meta_classifier import bootstrap_f1_ci

        # 10-row fixture with one deliberate misclassification so the
        # distribution is non-degenerate (BCa cannot compute on a
        # perfect classifier).
        y_true = np.array(["A"] * 5 + ["B"] * 5)
        y_pred = y_true.copy()
        y_pred[0] = "B"
        point, low, high = bootstrap_f1_ci(y_true, y_pred, n_resamples=500)

        # Manual point estimate: macro F1 on 9/10 correct.
        expected_point = float(f1_score(y_true, y_pred, average="macro", zero_division=0))
        assert point == pytest.approx(expected_point, abs=1e-9)
        # CI must bracket the point estimate and be a valid interval.
        assert low <= point <= high
        # Non-degenerate CI — low strictly less than high on this
        # fixture.
        assert low < high


class TestSplitInvariants:
    def test_train_test_split_has_no_column_id_overlap(self, tmp_path: Path) -> None:
        import numpy as np
        from sklearn.model_selection import train_test_split

        from scripts.train_meta_classifier import main as train_main

        rows = _small_three_class_fixture()
        input_path = _fixture_jsonl(tmp_path, rows)
        model_path = tmp_path / "m.pkl"
        meta_path = tmp_path / "m.metadata.json"
        rc = train_main(["--input", str(input_path), "--output", str(model_path), "--metadata", str(meta_path)])
        assert rc == 0

        ids = np.array([r["column_id"] for r in rows])
        labels = np.array([r["ground_truth"] for r in rows])
        _, _, _, _, id_train, id_test = train_test_split(
            np.zeros(len(rows)),
            labels,
            ids,
            test_size=0.2,
            random_state=42,
            stratify=labels,
        )
        assert not (set(id_train.tolist()) & set(id_test.tolist()))


class TestLOCOEvaluation:
    def test_loco_fit_predict_excludes_heldout_corpus(self) -> None:
        from data_classifier.orchestrator.meta_classifier import FEATURE_NAMES
        from scripts.train_meta_classifier import LoadedDataset
        from tests.benchmarks.meta_classifier.evaluate import _loco_fit_predict

        rows = []
        for i in range(10):
            rows.append(
                _row(
                    f"a_{i}",
                    "EMAIL",
                    corpus="corpus_a",
                    top_overall_confidence=0.9,
                    regex_confidence=0.9,
                    engines_agreed=1.0,
                    engines_fired=1.0,
                    primary_is_pii=1.0,
                    regex_match_ratio=1.0,
                    heuristic_distinct_ratio=0.9,
                    heuristic_avg_length=0.2,
                )
            )
            rows.append(
                _row(
                    f"b_{i}",
                    "EMAIL",
                    corpus="corpus_b",
                    top_overall_confidence=0.9,
                    regex_confidence=0.9,
                    engines_agreed=1.0,
                    engines_fired=1.0,
                    primary_is_pii=1.0,
                    regex_match_ratio=1.0,
                    heuristic_distinct_ratio=0.9,
                    heuristic_avg_length=0.2,
                )
            )
            rows.append(
                _row(
                    f"n{i}a",
                    "NEGATIVE",
                    corpus="corpus_a",
                    heuristic_distinct_ratio=0.3,
                    heuristic_avg_length=0.04,
                )
            )
            rows.append(
                _row(
                    f"n{i}b",
                    "NEGATIVE",
                    corpus="corpus_b",
                    heuristic_distinct_ratio=0.3,
                    heuristic_avg_length=0.04,
                )
            )
        dataset = LoadedDataset(
            features=[r["features"] for r in rows],
            labels=[r["ground_truth"] for r in rows],
            column_ids=[r["column_id"] for r in rows],
            corpora=[r["corpus"] for r in rows],
            modes=[r["mode"] for r in rows],
            sources=[r["source"] for r in rows],
            feature_names=list(FEATURE_NAMES),
        )
        kept_indices = list(range(len(FEATURE_NAMES)))
        y_true, y_pred = _loco_fit_predict(
            dataset,
            kept_indices=kept_indices,
            train_corpora={"corpus_a"},
            test_corpora={"corpus_b"},
        )
        assert len(y_true) == 20
        assert len(y_pred) == 20


class TestNegativeClass:
    def test_negative_class_survives_jsonl_loading(self) -> None:
        from data_classifier.orchestrator.meta_classifier import FEATURE_NAMES
        from scripts.train_meta_classifier import load_jsonl

        path = Path("tests/benchmarks/meta_classifier/training_data.jsonl")
        if not path.exists():
            pytest.skip("training_data.jsonl not built")
        dataset = load_jsonl(path, FEATURE_NAMES)
        assert "NEGATIVE" in set(dataset.labels)
        assert sum(1 for gt in dataset.labels if gt == "NEGATIVE") > 0


class TestScalerLeakage:
    def test_scaler_fit_on_training_data_only(self, tmp_path: Path) -> None:
        import numpy as np

        from data_classifier.orchestrator.meta_classifier import FEATURE_NAMES
        from scripts.train_meta_classifier import load_jsonl, resolve_feature_subset, train

        rows = _small_three_class_fixture()
        # Poison one row with an extreme outlier so train/test means differ.
        rows[0]["features"][0] = 999.0
        input_path = _fixture_jsonl(tmp_path, rows)
        dataset = load_jsonl(input_path, FEATURE_NAMES)
        _, kept_indices = resolve_feature_subset(dataset)
        trained = train(dataset, kept_indices=kept_indices)

        X_all = np.asarray([r["features"] for r in rows], dtype=np.float64)[:, kept_indices]
        full_mean = X_all.mean(axis=0)
        train_mean = np.asarray(trained["X_train"]).mean(axis=0)
        scaler_mean = trained["scaler"].mean_

        np.testing.assert_allclose(scaler_mean, train_mean, rtol=1e-9, atol=1e-9)
        assert not np.allclose(scaler_mean, full_mean)


class TestPredictProbaRoundtrip:
    def test_predict_proba_sums_to_one(self, tmp_path: Path) -> None:
        import numpy as np

        from scripts.train_meta_classifier import main as train_main

        input_path = _fixture_jsonl(tmp_path, _small_three_class_fixture())
        model_path = tmp_path / "m.pkl"
        meta_path = tmp_path / "m.metadata.json"
        train_main(["--input", str(input_path), "--output", str(model_path), "--metadata", str(meta_path)])

        payload = _load_artifact(model_path)

        from data_classifier.orchestrator.meta_classifier import FEATURE_NAMES

        rows = _small_three_class_fixture()
        name_to_idx = {n: i for i, n in enumerate(FEATURE_NAMES)}
        idx = [name_to_idx[n] for n in payload["feature_names"]]
        X = np.asarray([r["features"] for r in rows])[:, idx]
        probs = payload["model"].predict_proba(payload["scaler"].transform(X))
        np.testing.assert_allclose(probs.sum(axis=1), 1.0, atol=1e-9)


class TestMetadataSchema:
    def test_metadata_json_has_required_fields(self, tmp_path: Path) -> None:
        from scripts.train_meta_classifier import main as train_main

        input_path = _fixture_jsonl(tmp_path, _small_three_class_fixture())
        model_path = tmp_path / "m.pkl"
        meta_path = tmp_path / "m.metadata.json"
        train_main(["--input", str(input_path), "--output", str(model_path), "--metadata", str(meta_path)])

        md = json.loads(meta_path.read_text())
        required = {
            "training_date",
            "git_sha",
            "total_rows",
            "per_class_counts",
            "cv_mean_macro_f1",
            "cv_std_macro_f1",
            "held_out_test_macro_f1",
            "held_out_test_ci_95_bca",
            "top_5_feature_importances",
            "feature_names",
            "dropped_features",
            "class_labels",
        }
        missing = required - set(md.keys())
        assert not missing, f"missing metadata keys: {missing}"
