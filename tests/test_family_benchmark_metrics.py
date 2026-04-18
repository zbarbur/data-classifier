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


# ── M4b gate + per-branch surface tests ──────────────────────────────────────


def test_derive_true_shape_scanner_corpora_are_heterogeneous():
    from tests.benchmarks.family_accuracy_benchmark import _derive_true_shape

    assert _derive_true_shape("secretbench", "CREDENTIAL") == "free_text_heterogeneous"
    assert _derive_true_shape("gitleaks", "NEGATIVE") == "free_text_heterogeneous"
    assert _derive_true_shape("detect_secrets", "CREDENTIAL") == "free_text_heterogeneous"


def test_derive_true_shape_opaque_ground_truths():
    from tests.benchmarks.family_accuracy_benchmark import _derive_true_shape

    assert _derive_true_shape("synthetic", "BITCOIN_ADDRESS") == "opaque_tokens"
    assert _derive_true_shape("synthetic", "ETHEREUM_ADDRESS") == "opaque_tokens"
    assert _derive_true_shape("nemotron", "OPAQUE_SECRET") == "opaque_tokens"


def test_derive_true_shape_default_is_structured_single():
    from tests.benchmarks.family_accuracy_benchmark import _derive_true_shape

    assert _derive_true_shape("gretel_en", "EMAIL") == "structured_single"
    assert _derive_true_shape("nemotron", "PHONE") == "structured_single"
    assert _derive_true_shape("gretel_finance", "CREDENTIAL") == "structured_single"


def test_compute_gate_accuracy_perfect_routing():
    """When router's shape == true_shape on every row, accuracy is 1.0."""
    from tests.benchmarks.family_accuracy_benchmark import _compute_gate_accuracy

    predictions = [
        {"true_shape": "structured_single", "shape": "structured_single"},
        {"true_shape": "structured_single", "shape": "structured_single"},
        {"true_shape": "free_text_heterogeneous", "shape": "free_text_heterogeneous"},
        {"true_shape": "opaque_tokens", "shape": "opaque_tokens"},
    ]
    result = _compute_gate_accuracy(predictions)
    assert result["overall_accuracy"] == 1.0
    assert result["n_rows_scored"] == 4
    assert result["per_shape"]["structured_single"]["tp"] == 2
    assert result["per_shape"]["free_text_heterogeneous"]["tp"] == 1
    assert result["per_shape"]["opaque_tokens"]["tp"] == 1


def test_compute_gate_accuracy_confusion_off_diagonal():
    """Mis-routed rows populate the off-diagonal of the confusion matrix."""
    from tests.benchmarks.family_accuracy_benchmark import _compute_gate_accuracy

    predictions = [
        # Two correctly routed
        {"true_shape": "structured_single", "shape": "structured_single"},
        {"true_shape": "opaque_tokens", "shape": "opaque_tokens"},
        # Router called structured as opaque
        {"true_shape": "structured_single", "shape": "opaque_tokens"},
        # Router emitted no shape (e.g., old event handler unavailable)
        {"true_shape": "structured_single", "shape": None},
    ]
    result = _compute_gate_accuracy(predictions)
    assert result["overall_accuracy"] == 0.5  # 2 of 4 rows correct
    assert result["confusion"]["structured_single"]["opaque_tokens"] == 1
    assert result["confusion"]["structured_single"]["no_shape"] == 1
    assert result["n_rows_no_shape"] == 1
    # structured_single precision: 1 TP / (1 TP + 0 FP) = 1.0
    assert result["per_shape"]["structured_single"]["precision"] == 1.0
    # opaque_tokens precision: 1 TP / (1 TP + 1 FP from structured) = 0.5
    assert result["per_shape"]["opaque_tokens"]["precision"] == 0.5


def test_compute_per_branch_accuracy_emits_note_for_empty_branches():
    """Branches with no shards of that true_shape emit an explicit note."""
    from tests.benchmarks.family_accuracy_benchmark import _compute_per_branch_accuracy

    predictions = [
        {
            "true_shape": "structured_single",
            "ground_truth": "EMAIL",
            "predicted": "EMAIL",
            "shadow_suppressed_by_router": False,
            "shape": "structured_single",
        },
    ]
    result = _compute_per_branch_accuracy(predictions, "predicted")
    assert result["structured_single"]["n_shards"] == 1
    assert result["free_text_heterogeneous"]["n_shards"] == 0
    assert "note" in result["free_text_heterogeneous"]
    assert result["opaque_tokens"]["n_shards"] == 0
    assert "note" in result["opaque_tokens"]


def test_compute_per_branch_accuracy_isolates_by_true_shape():
    """Per-branch metrics only include shards whose true_shape is that branch."""
    from tests.benchmarks.family_accuracy_benchmark import _compute_per_branch_accuracy

    predictions = [
        # structured_single — classified correctly
        {
            "true_shape": "structured_single",
            "ground_truth": "EMAIL",
            "predicted": "EMAIL",
            "shadow_suppressed_by_router": False,
            "shape": "structured_single",
        },
        # opaque_tokens — classified correctly
        {
            "true_shape": "opaque_tokens",
            "ground_truth": "BITCOIN_ADDRESS",
            "predicted": "BITCOIN_ADDRESS",
            "shadow_suppressed_by_router": False,
            "shape": "opaque_tokens",
        },
        # heterogeneous — wrong family
        {
            "true_shape": "free_text_heterogeneous",
            "ground_truth": "CREDENTIAL",
            "predicted": "EMAIL",
            "shadow_suppressed_by_router": False,
            "shape": "free_text_heterogeneous",
        },
    ]
    result = _compute_per_branch_accuracy(predictions, "predicted")
    assert result["structured_single"]["n_shards"] == 1
    assert result["structured_single"]["family"]["cross_family_rate"] == 0.0
    assert result["opaque_tokens"]["n_shards"] == 1
    assert result["opaque_tokens"]["family"]["cross_family_rate"] == 0.0
    assert result["free_text_heterogeneous"]["n_shards"] == 1
    assert result["free_text_heterogeneous"]["family"]["cross_family_rate"] == 1.0
