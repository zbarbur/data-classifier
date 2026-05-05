"""Unit tests for null-aware family benchmark metrics (Sprint 13 Option C).

These tests verify the three critical behaviors added in Sprint 13 Item A:
  1. Legacy cross_family_rate still counts suppressed columns as errors
     (audit-trail continuity for Sprint 12 comparisons).
  2. cross_family_rate_emitted excludes router-suppressed columns from
     both numerator and denominator.
  3. suppressed_by_shape breakdown counts per shape value.
"""


def test_compute_family_metrics_legacy_counts_suppressed_as_errors():
    """Legacy cross_family_rate counts router-suppressed columns as errors.

    Preserved for audit-trail continuity when comparing against Sprint 12.
    """
    from tests.benchmarks.family_accuracy_benchmark import _compute_family_metrics

    predictions = [
        {
            "ground_truth": "EMAIL",
            "shadow_predicted": "EMAIL",
            "shadow_suppressed_by_router": False,
            "shape": "structured_single",
        },
        {
            "ground_truth": "EMAIL",
            "shadow_predicted": None,
            "shadow_suppressed_by_router": True,
            "shape": "opaque_tokens",
        },
    ]
    result = _compute_family_metrics(predictions, "shadow_predicted")
    assert result["n_shards"] == 2
    assert result["cross_family_errors"] == 1  # the suppressed one counts as an error in legacy
    assert result["cross_family_rate"] == 0.5


def test_compute_family_metrics_null_aware_excludes_suppressed():
    """cross_family_rate_emitted excludes router-suppressed columns."""
    from tests.benchmarks.family_accuracy_benchmark import _compute_family_metrics

    predictions = [
        {
            "ground_truth": "EMAIL",
            "shadow_predicted": "EMAIL",
            "shadow_suppressed_by_router": False,
            "shape": "structured_single",
        },
        {
            "ground_truth": "EMAIL",
            "shadow_predicted": None,
            "shadow_suppressed_by_router": True,
            "shape": "opaque_tokens",
        },
    ]
    result = _compute_family_metrics(predictions, "shadow_predicted")
    assert result["n_shards_emitted"] == 1
    assert result["cross_family_rate_emitted"] == 0.0  # emitted prediction was correct
    assert result["router_suppressed_count"] == 1
    assert result["router_suppression_rate"] == 0.5


def test_compute_family_metrics_suppression_by_shape_breakdown():
    """suppressed_by_shape counts by shape value."""
    from tests.benchmarks.family_accuracy_benchmark import _compute_family_metrics

    predictions = [
        {
            "ground_truth": "EMAIL",
            "shadow_predicted": None,
            "shadow_suppressed_by_router": True,
            "shape": "opaque_tokens",
        },
        {
            "ground_truth": "EMAIL",
            "shadow_predicted": None,
            "shadow_suppressed_by_router": True,
            "shape": "opaque_tokens",
        },
        {
            "ground_truth": "EMAIL",
            "shadow_predicted": None,
            "shadow_suppressed_by_router": True,
            "shape": "free_text_heterogeneous",
        },
    ]
    result = _compute_family_metrics(predictions, "shadow_predicted")
    assert result["suppressed_by_shape"] == {"opaque_tokens": 2, "free_text_heterogeneous": 1}


# ── Sprint 17 system-level joint miss metric ──────────────────────────────


def test_joint_miss_excludes_negative_from_denominator():
    """NEGATIVE ground truth is excluded from joint miss numerator AND denominator.

    Per Sprint 17 memo §5: 'predict nothing' is the correct answer for NEGATIVE,
    so symmetric metric treats no-prediction as wrong but joint miss excludes.
    """
    from tests.benchmarks.family_accuracy_benchmark import _compute_joint_miss_metrics

    predictions = [
        {
            "ground_truth": "EMAIL",
            "ground_truth_families": ["CONTACT"],
            "predicted": "EMAIL",
            "shadow_predicted": "EMAIL",
            "shadow_suppressed_by_router": False,
        },
        {
            "ground_truth": "NEGATIVE",
            "ground_truth_families": ["NEGATIVE"],
            "predicted": None,
            "shadow_predicted": None,
            "shadow_suppressed_by_router": True,
        },
    ]
    result = _compute_joint_miss_metrics(predictions)
    assert result["n_negative_excluded"] == 1
    assert result["n_shards_excluding_negative"] == 1
    assert result["joint_miss_count"] == 0
    assert result["joint_miss_rate"] == 0.0


def test_joint_miss_router_suppressed_shadow_counts_as_wrong():
    """Router-suppressed shadow is treated as 'no prediction' — wrong on its own.

    A shard where router suppressed AND LIVE missed is a joint miss.
    A shard where router suppressed BUT LIVE caught it is shadow_only_miss.
    """
    from tests.benchmarks.family_accuracy_benchmark import _compute_joint_miss_metrics

    predictions = [
        # joint miss: shadow suppressed, live wrong (API_KEY is CREDENTIAL, gt is CONTACT)
        {
            "ground_truth": "EMAIL",
            "ground_truth_families": ["CONTACT"],
            "predicted": "API_KEY",
            "shadow_predicted": None,
            "shadow_suppressed_by_router": True,
        },
        # shadow_only_miss: shadow suppressed, live correct
        {
            "ground_truth": "EMAIL",
            "ground_truth_families": ["CONTACT"],
            "predicted": "EMAIL",
            "shadow_predicted": None,
            "shadow_suppressed_by_router": True,
        },
    ]
    result = _compute_joint_miss_metrics(predictions)
    assert result["joint_miss_count"] == 1
    assert result["shadow_only_miss_count"] == 1
    assert result["live_only_miss_count"] == 0
    assert result["both_correct_count"] == 0


def test_joint_miss_multilabel_ground_truth():
    """Multi-label GT: shard right if ANY GT family is predicted.

    A CREDENTIAL+URL shard where shadow predicts URL is correct, not a miss.
    """
    from tests.benchmarks.family_accuracy_benchmark import _compute_joint_miss_metrics

    predictions = [
        {
            "ground_truth": "API_KEY",
            "ground_truth_families": ["CREDENTIAL", "URL"],
            "predicted": None,
            "shadow_predicted": "URL",
            "shadow_suppressed_by_router": False,
        },
    ]
    result = _compute_joint_miss_metrics(predictions)
    assert result["joint_miss_count"] == 0
    assert result["live_only_miss_count"] == 1


class TestSprint18MLActiveBenchmarkVariant:
    """Sprint 18 item: --ml-active produces a joint_miss_rate_ml_active
    field instead of joint_miss_rate so the merged sprint baseline can
    carry both metrics unambiguously.  Runs the benchmark CLI as a
    subprocess (env-var contract requires fresh import).
    """

    def _run(self, *flags: str, limit: int = 30) -> dict:
        import json
        import subprocess
        import sys
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            preds = tmp_path / "preds.jsonl"
            summary = tmp_path / "summary.json"
            cmd = [
                sys.executable,
                "-m",
                "tests.benchmarks.family_accuracy_benchmark",
                "--out",
                str(preds),
                "--summary",
                str(summary),
                "--limit",
                str(limit),
                *flags,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            assert result.returncode == 0, f"benchmark CLI failed: {result.stderr}"
            return json.loads(summary.read_text())

    def test_default_run_emits_joint_miss_rate(self) -> None:
        summary = self._run()
        assert summary["ml_active"] is False
        sysov = summary["system"]["overall"]
        assert "joint_miss_rate" in sysov
        assert "joint_miss_rate_ml_active" not in sysov
        assert isinstance(sysov["joint_miss_rate"], float)

    def test_ml_active_run_emits_joint_miss_rate_ml_active(self) -> None:
        summary = self._run("--ml-active")
        assert summary["ml_active"] is True
        sysov = summary["system"]["overall"]
        assert "joint_miss_rate_ml_active" in sysov
        assert "joint_miss_rate" not in sysov
        # Field must be a populated number — never None or missing.
        assert isinstance(sysov["joint_miss_rate_ml_active"], (int, float))
        assert 0.0 <= sysov["joint_miss_rate_ml_active"] <= 1.0

    def test_ml_active_summary_preserves_other_joint_miss_fields(self) -> None:
        """Renaming joint_miss_rate must not lose the count, n, or decomposition fields."""
        summary = self._run("--ml-active")
        sysov = summary["system"]["overall"]
        for required in (
            "joint_miss_count",
            "n_shards_excluding_negative",
            "live_only_miss_count",
            "shadow_only_miss_count",
            "both_correct_count",
        ):
            assert required in sysov, f"ML-active summary missing field: {required}"


def test_joint_miss_decomposition_by_family_and_shape():
    """joint_miss_by_family and joint_miss_by_shape decompose the misses."""
    from tests.benchmarks.family_accuracy_benchmark import _compute_joint_miss_metrics

    predictions = [
        # joint miss CONTACT in free_text_heterogeneous
        {
            "ground_truth": "EMAIL",
            "ground_truth_families": ["CONTACT"],
            "predicted": None,
            "shadow_predicted": None,
            "shadow_suppressed_by_router": True,
            "shape": "free_text_heterogeneous",
        },
        # joint miss CREDENTIAL in opaque_tokens
        {
            "ground_truth": "API_KEY",
            "ground_truth_families": ["CREDENTIAL"],
            "predicted": None,
            "shadow_predicted": None,
            "shadow_suppressed_by_router": True,
            "shape": "opaque_tokens",
        },
    ]
    result = _compute_joint_miss_metrics(predictions)
    assert result["joint_miss_count"] == 2
    assert result["joint_miss_by_family"] == {"CONTACT": 1, "CREDENTIAL": 1}
    assert result["joint_miss_by_shape"] == {"free_text_heterogeneous": 1, "opaque_tokens": 1}
