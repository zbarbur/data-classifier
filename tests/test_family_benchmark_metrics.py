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
