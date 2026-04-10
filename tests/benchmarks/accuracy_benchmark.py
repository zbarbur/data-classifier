"""Accuracy benchmark — deep analysis of detection quality.

NOT part of the CI test suite. Run manually:
    python -m tests.benchmarks.accuracy_benchmark [--samples N] [--verbose]

Reports:
    - Corpus statistics (total samples, entity types, coverage)
    - Per-entity-type precision, recall, F1
    - Per-sample match analysis (which samples hit, which missed, why)
    - Cross-pattern collision matrix (which patterns fight each other)
    - Per-engine breakdown (column_name vs regex contributions)
    - False positive and false negative details
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

from data_classifier import classify_columns, load_profile
from data_classifier.core.types import ClassificationFinding, ClassificationProfile, ColumnInput
from data_classifier.engines.column_name_engine import ColumnNameEngine
from data_classifier.engines.regex_engine import RegexEngine
from data_classifier.events.emitter import CallbackHandler, EventEmitter
from data_classifier.events.types import TierEvent

# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class SampleResult:
    """Result of classifying a single sample value."""

    value: str
    expected: str | None
    predicted: list[str]
    is_tp: bool = False
    is_fp: bool = False
    is_fn: bool = False


@dataclass
class ColumnResult:
    """Detailed result for one corpus column."""

    column_id: str
    column_name: str
    expected_entity_type: str | None
    predicted_entity_types: list[str] = field(default_factory=list)
    predicted_by_engine: dict[str, list[str]] = field(default_factory=dict)
    sample_analysis: dict[str, dict] = field(default_factory=dict)
    engine_latencies: dict[str, float] = field(default_factory=dict)
    total_ms: float = 0.0


@dataclass
class EntityMetrics:
    """Precision/recall/F1 for one entity type."""

    tp: int = 0
    fp: int = 0
    fn: int = 0
    tp_columns: list[str] = field(default_factory=list)
    fp_columns: list[str] = field(default_factory=list)
    fn_columns: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) > 0 else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


# ── Per-engine analysis ──────────────────────────────────────────────────────


def _classify_with_single_engine(
    engine_class: type,
    columns: list[ColumnInput],
    profile: ClassificationProfile,
) -> dict[str, list[str]]:
    """Run a single engine on all columns, return column_id -> entity_types."""
    engine = engine_class()
    results: dict[str, list[str]] = {}
    for col in columns:
        findings = engine.classify_column(
            col,
            profile=profile,
            min_confidence=0.0,
        )
        results[col.column_id] = [f.entity_type for f in findings]
    return results


# ── Sample-level analysis ────────────────────────────────────────────────────


def _analyze_samples_for_column(
    column: ColumnInput,
    profile: ClassificationProfile,
) -> dict[str, dict]:
    """Classify each sample value individually and report per-sample matches."""
    engine = RegexEngine()
    per_sample: dict[str, dict] = {}

    for i, value in enumerate(column.sample_values):
        single_col = ColumnInput(
            column_name="__benchmark_sample__",
            column_id=f"__sample_{i}__",
            data_type="STRING",
            sample_values=[value],
        )
        findings = engine.classify_column(
            single_col,
            profile=profile,
            min_confidence=0.0,
        )
        matched_types = [f.entity_type for f in findings]
        confidences = {f.entity_type: f.confidence for f in findings}
        validated = {}
        for f in findings:
            if f.sample_analysis:
                validated[f.entity_type] = f.sample_analysis.samples_validated

        per_sample[value] = {
            "matched_types": matched_types,
            "confidences": confidences,
            "validated": validated,
        }

    return per_sample


# ── Main benchmark ───────────────────────────────────────────────────────────


def run_benchmark(
    corpus: list[tuple[ColumnInput, str | None]],
    *,
    verbose: bool = False,
) -> tuple[list[ColumnResult], dict[str, EntityMetrics]]:
    """Run the full accuracy benchmark with per-engine and per-sample analysis."""
    profile = load_profile("standard")
    columns = [col for col, _ in corpus]
    ground_truth = {col.column_id: expected for col, expected in corpus}

    # ── Step 1: Full pipeline classification with event capture ───────────
    tier_events: list[TierEvent] = []
    emitter = EventEmitter()
    emitter.add_handler(CallbackHandler(lambda e: tier_events.append(e) if isinstance(e, TierEvent) else None))

    all_findings: list[ClassificationFinding] = classify_columns(
        columns, profile, min_confidence=0.0, event_emitter=emitter
    )

    # Build finding lookup
    findings_by_col: dict[str, list[ClassificationFinding]] = {}
    for f in all_findings:
        findings_by_col.setdefault(f.column_id, []).append(f)

    # Build tier event lookup
    events_by_col: dict[str, list[TierEvent]] = {}
    for ev in tier_events:
        events_by_col.setdefault(ev.column_id, []).append(ev)

    # ── Step 2: Per-engine isolation runs ─────────────────────────────────
    column_name_results = _classify_with_single_engine(ColumnNameEngine, columns, profile)
    regex_results = _classify_with_single_engine(RegexEngine, columns, profile)

    # ── Step 3: Build detailed results ────────────────────────────────────
    column_results: list[ColumnResult] = []

    for col, expected in corpus:
        col_findings = findings_by_col.get(col.column_id, [])
        predicted = [f.entity_type for f in col_findings]

        # Per-engine breakdown
        by_engine = {
            "column_name": column_name_results.get(col.column_id, []),
            "regex": regex_results.get(col.column_id, []),
        }

        # Engine latencies from events
        latencies = {}
        for ev in events_by_col.get(col.column_id, []):
            latencies[ev.tier] = ev.latency_ms

        # Sample-level analysis (only for positive columns with samples)
        sample_data = {}
        if col.sample_values and verbose:
            sample_data = _analyze_samples_for_column(col, profile)

        cr = ColumnResult(
            column_id=col.column_id,
            column_name=col.column_name,
            expected_entity_type=expected,
            predicted_entity_types=predicted,
            predicted_by_engine=by_engine,
            sample_analysis=sample_data,
            engine_latencies=latencies,
        )
        column_results.append(cr)

    # ── Step 4: Compute metrics ───────────────────────────────────────────
    all_entity_types: set[str] = set()
    for expected in ground_truth.values():
        if expected is not None:
            all_entity_types.add(expected)
    for cr in column_results:
        all_entity_types.update(cr.predicted_entity_types)

    metrics: dict[str, EntityMetrics] = {et: EntityMetrics() for et in sorted(all_entity_types)}

    for cr in column_results:
        for entity_type in all_entity_types:
            predicted_this = entity_type in cr.predicted_entity_types
            expected_this = cr.expected_entity_type == entity_type

            if predicted_this and expected_this:
                metrics[entity_type].tp += 1
                metrics[entity_type].tp_columns.append(cr.column_id)
            elif predicted_this and not expected_this:
                metrics[entity_type].fp += 1
                metrics[entity_type].fp_columns.append(cr.column_id)
            elif not predicted_this and expected_this:
                metrics[entity_type].fn += 1
                metrics[entity_type].fn_columns.append(cr.column_id)

    return column_results, metrics


# ── Collision matrix ─────────────────────────────────────────────────────────


def compute_collision_matrix(
    column_results: list[ColumnResult],
) -> dict[str, dict[str, int]]:
    """Which entity types co-occur on the same column? Shows pattern conflicts."""
    matrix: dict[str, dict[str, int]] = {}

    for cr in column_results:
        predicted = cr.predicted_entity_types
        if len(predicted) > 1:
            for a in predicted:
                for b in predicted:
                    if a != b:
                        matrix.setdefault(a, {}).setdefault(b, 0)
                        matrix[a][b] += 1

    return matrix


# ── Report printing ──────────────────────────────────────────────────────────


def print_report(
    corpus: list[tuple[ColumnInput, str | None]],
    column_results: list[ColumnResult],
    metrics: dict[str, EntityMetrics],
    *,
    verbose: bool = False,
) -> None:
    """Print comprehensive benchmark report."""
    # ── Corpus statistics ─────────────────────────────────────────────────
    total_columns = len(corpus)
    positive_columns = sum(1 for _, e in corpus if e is not None)
    negative_columns = total_columns - positive_columns
    total_samples = sum(len(col.sample_values) for col, _ in corpus)
    entity_types_tested = len({e for _, e in corpus if e is not None})
    avg_samples = total_samples / total_columns if total_columns > 0 else 0

    print("=" * 70)  # noqa: T201
    print("ACCURACY BENCHMARK REPORT")  # noqa: T201
    print("=" * 70)  # noqa: T201
    print()  # noqa: T201
    print("CORPUS STATISTICS")  # noqa: T201
    print(f"  Total columns:      {total_columns}")  # noqa: T201
    print(f"  Positive columns:   {positive_columns} ({entity_types_tested} entity types)")  # noqa: T201
    print(f"  Negative columns:   {negative_columns}")  # noqa: T201
    print(f"  Total samples:      {total_samples}")  # noqa: T201
    print(f"  Avg samples/column: {avg_samples:.0f}")  # noqa: T201
    print()  # noqa: T201

    # ── Per-entity metrics ────────────────────────────────────────────────
    w = 70
    header = f"{'Entity Type':<22} {'TP':>4} {'FP':>4} {'FN':>4} {'Prec':>8} {'Recall':>8} {'F1':>8}"
    print("DETECTION ACCURACY")  # noqa: T201
    print("-" * w)  # noqa: T201
    print(header)  # noqa: T201
    print("-" * w)  # noqa: T201

    total_tp = total_fp = total_fn = 0
    for entity_type, m in sorted(metrics.items()):
        total_tp += m.tp
        total_fp += m.fp
        total_fn += m.fn
        print(  # noqa: T201
            f"{entity_type:<22} {m.tp:>4} {m.fp:>4} {m.fn:>4} {m.precision:>8.3f} {m.recall:>8.3f} {m.f1:>8.3f}"
        )

    overall_p = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    overall_r = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    overall_f1 = 2 * overall_p * overall_r / (overall_p + overall_r) if (overall_p + overall_r) > 0 else 0.0

    print("-" * w)  # noqa: T201
    print(  # noqa: T201
        f"{'OVERALL':<22} {total_tp:>4} {total_fp:>4} {total_fn:>4}"
        f" {overall_p:>8.3f} {overall_r:>8.3f} {overall_f1:>8.3f}"
    )
    print()  # noqa: T201

    # ── Per-engine contribution ───────────────────────────────────────────
    print("ENGINE CONTRIBUTIONS")  # noqa: T201
    print("-" * w)  # noqa: T201
    print(f"{'Column':<30} {'Column Name Eng':>18} {'Regex Eng':>18}")  # noqa: T201
    print("-" * w)  # noqa: T201

    for cr in column_results:
        if cr.expected_entity_type is None:
            continue
        cn_types = ", ".join(cr.predicted_by_engine.get("column_name", [])) or "-"
        rx_types = ", ".join(cr.predicted_by_engine.get("regex", [])) or "-"
        label = f"{cr.expected_entity_type} ({cr.column_name[:15]})"
        print(f"  {label:<28} {cn_types:>18} {rx_types:>18}")  # noqa: T201
    print()  # noqa: T201

    # ── Sample-level analysis (per positive column) ───────────────────────
    print("SAMPLE-LEVEL DETECTION")  # noqa: T201
    print("-" * w)  # noqa: T201

    for cr in column_results:
        if cr.expected_entity_type is None:
            continue
        col = next(c for c, _ in corpus if c.column_id == cr.column_id)

        # Count how many findings came from regex (have sample_analysis)
        findings_by_col = {
            f.entity_type: f for f in classify_columns([col], load_profile("standard"), min_confidence=0.0)
        }

        expected_finding = findings_by_col.get(cr.expected_entity_type)
        if expected_finding and expected_finding.sample_analysis:
            sa = expected_finding.sample_analysis
            print(  # noqa: T201
                f"  {cr.expected_entity_type:<20} "
                f"matched={sa.samples_matched}/{sa.samples_scanned} "
                f"({sa.match_ratio:.0%})  "
                f"validated={sa.samples_validated}/{sa.samples_matched}  "
                f"confidence={expected_finding.confidence:.3f}"
            )
        elif expected_finding:
            print(  # noqa: T201
                f"  {cr.expected_entity_type:<20} via column name  confidence={expected_finding.confidence:.3f}"
            )
        else:
            print(f"  {cr.expected_entity_type:<20} NOT DETECTED")  # noqa: T201
    print()  # noqa: T201

    # ── Cross-pattern collisions ──────────────────────────────────────────
    matrix = compute_collision_matrix(column_results)
    if matrix:
        print("CROSS-PATTERN COLLISIONS (patterns that fire on the same column)")  # noqa: T201
        print("-" * w)  # noqa: T201
        for entity_a, conflicts in sorted(matrix.items()):
            for entity_b, count in sorted(conflicts.items()):
                print(f"  {entity_a:<20} also triggers {entity_b:<20} ({count} columns)")  # noqa: T201
        print()  # noqa: T201

    # ── False positives detail ────────────────────────────────────────────
    fp_details = []
    fn_details = []
    for entity_type, m in sorted(metrics.items()):
        for col_id in m.fp_columns:
            cr = next(r for r in column_results if r.column_id == col_id)
            fp_details.append(
                f"  {col_id}: predicted={entity_type}, expected={cr.expected_entity_type}, "
                f"engines={cr.predicted_by_engine}"
            )
        for col_id in m.fn_columns:
            cr = next(r for r in column_results if r.column_id == col_id)
            fn_details.append(f"  {col_id}: expected={entity_type}, got={cr.predicted_entity_types}")

    if fp_details:
        print("FALSE POSITIVES")  # noqa: T201
        print("-" * w)  # noqa: T201
        for d in fp_details:
            print(d)  # noqa: T201
        print()  # noqa: T201

    if fn_details:
        print("FALSE NEGATIVES")  # noqa: T201
        print("-" * w)  # noqa: T201
        for d in fn_details:
            print(d)  # noqa: T201
        print()  # noqa: T201


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run accuracy benchmark")
    parser.add_argument("--samples", type=int, default=100, help="Samples per entity type")
    parser.add_argument("--verbose", action="store_true", help="Include per-sample analysis")
    args = parser.parse_args()

    from tests.benchmarks.corpus_generator import generate_corpus

    print(f"Generating synthetic corpus ({args.samples} samples/type)...")  # noqa: T201
    corpus = generate_corpus(samples_per_type=args.samples, locale="en_US")

    results, metrics = run_benchmark(corpus, verbose=args.verbose)
    print_report(corpus, results, metrics, verbose=args.verbose)
