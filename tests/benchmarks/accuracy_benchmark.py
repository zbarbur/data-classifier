"""Accuracy benchmark — measures precision/recall/F1 per entity type.

NOT part of the CI test suite. Run manually:
    python -m tests.benchmarks.accuracy_benchmark

Reports:
    - Per-entity-type precision, recall, F1
    - Overall weighted precision/recall/F1
    - False positive and false negative details
"""

from __future__ import annotations

from data_classifier import ClassificationFinding, ColumnInput, classify_columns, load_profile


def run_accuracy_benchmark(
    corpus: list[tuple[ColumnInput, str | None]],
) -> dict[str, dict[str, float]]:
    """Run accuracy benchmark on a labeled corpus.

    Args:
        corpus: List of (ColumnInput, expected_entity_type) tuples.

    Returns:
        Dict keyed by entity type with precision, recall, F1, TP, FP, FN counts.
    """
    profile = load_profile("standard")

    # Classify all columns at once
    columns = [col for col, _ in corpus]
    all_findings: list[ClassificationFinding] = classify_columns(columns, profile, min_confidence=0.0)

    # Build lookup: column_id -> list of predicted entity types
    predictions: dict[str, list[str]] = {}
    for finding in all_findings:
        predictions.setdefault(finding.column_id, []).append(finding.entity_type)

    # Build ground truth: column_id -> expected entity type
    ground_truth: dict[str, str | None] = {}
    for col, expected in corpus:
        ground_truth[col.column_id] = expected

    # Collect all entity types from both predictions and ground truth
    all_entity_types: set[str] = set()
    for expected in ground_truth.values():
        if expected is not None:
            all_entity_types.add(expected)
    for pred_list in predictions.values():
        all_entity_types.update(pred_list)

    # Compute per-entity-type metrics
    metrics: dict[str, dict[str, float]] = {}
    fp_details: list[str] = []
    fn_details: list[str] = []

    for entity_type in sorted(all_entity_types):
        tp = 0
        fp = 0
        fn = 0

        for col_id, expected in ground_truth.items():
            predicted_types = predictions.get(col_id, [])
            predicted_this = entity_type in predicted_types
            expected_this = expected == entity_type

            if predicted_this and expected_this:
                tp += 1
            elif predicted_this and not expected_this:
                fp += 1
                fp_details.append(f"  FP: {col_id} predicted={entity_type}, expected={expected}")
            elif not predicted_this and expected_this:
                fn += 1
                fn_details.append(f"  FN: {col_id} expected={entity_type}, got={predicted_types}")

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        metrics[entity_type] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }

    return metrics, fp_details, fn_details  # type: ignore[return-value]


def print_report(
    metrics: dict[str, dict[str, float]],
    fp_details: list[str],
    fn_details: list[str],
) -> None:
    """Print a formatted accuracy report."""
    header = f"{'Entity Type':<20} {'TP':>4} {'FP':>4} {'FN':>4} {'Prec':>8} {'Recall':>8} {'F1':>8}"
    print("\n" + "=" * len(header))  # noqa: T201
    print("ACCURACY BENCHMARK REPORT")  # noqa: T201
    print("=" * len(header))  # noqa: T201
    print(header)  # noqa: T201
    print("-" * len(header))  # noqa: T201

    total_tp = 0
    total_fp = 0
    total_fn = 0

    for entity_type, m in sorted(metrics.items()):
        tp, fp, fn = int(m["tp"]), int(m["fp"]), int(m["fn"])
        total_tp += tp
        total_fp += fp
        total_fn += fn
        print(  # noqa: T201
            f"{entity_type:<20} {tp:>4} {fp:>4} {fn:>4} {m['precision']:>8.3f} {m['recall']:>8.3f} {m['f1']:>8.3f}"
        )

    # Overall weighted metrics
    overall_prec = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    overall_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    overall_f1 = (
        2 * overall_prec * overall_recall / (overall_prec + overall_recall)
        if (overall_prec + overall_recall) > 0
        else 0.0
    )

    print("-" * len(header))  # noqa: T201
    print(  # noqa: T201
        f"{'OVERALL':<20} {total_tp:>4} {total_fp:>4} {total_fn:>4} "
        f"{overall_prec:>8.3f} {overall_recall:>8.3f} {overall_f1:>8.3f}"
    )
    print("=" * len(header))  # noqa: T201

    if fp_details:
        print("\nFalse Positives:")  # noqa: T201
        for detail in fp_details:
            print(detail)  # noqa: T201

    if fn_details:
        print("\nFalse Negatives:")  # noqa: T201
        for detail in fn_details:
            print(detail)  # noqa: T201


if __name__ == "__main__":
    from tests.benchmarks.corpus_generator import generate_corpus

    samples = 50
    print("Generating synthetic corpus...")  # noqa: T201
    corpus = generate_corpus(samples_per_type=samples, locale="en_US")

    total_columns = len(corpus)
    positive_columns = sum(1 for _, expected in corpus if expected is not None)
    negative_columns = total_columns - positive_columns
    total_samples = sum(len(col.sample_values) for col, _ in corpus)
    entity_types_tested = len({expected for _, expected in corpus if expected is not None})

    print("Corpus summary:")  # noqa: T201
    print(f"  Columns:          {total_columns}")  # noqa: T201
    print(f"  Positive columns: {positive_columns} ({entity_types_tested} entity types)")  # noqa: T201
    print(f"  Negative columns: {negative_columns}")  # noqa: T201
    print(f"  Total samples:    {total_samples} ({samples} per column)")  # noqa: T201
    print()  # noqa: T201

    metrics, fp_details, fn_details = run_accuracy_benchmark(corpus)
    print_report(metrics, fp_details, fn_details)
