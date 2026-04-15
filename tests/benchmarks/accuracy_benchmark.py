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


@dataclass
class BenchmarkResult:
    """Complete benchmark result including all metrics."""

    column_results: list[ColumnResult]
    entity_metrics: dict[str, EntityMetrics]
    micro_f1: float = 0.0
    macro_f1: float = 0.0
    primary_label_accuracy: float = 0.0
    corpus_source: str = "synthetic"


def run_benchmark(
    corpus: list[tuple[ColumnInput, str | None]],
    *,
    verbose: bool = False,
    corpus_source: str = "synthetic",
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

    # ── Step 5: Compute aggregate metrics ──────────────────────────────────
    total_tp = sum(m.tp for m in metrics.values())
    total_fp = sum(m.fp for m in metrics.values())
    total_fn = sum(m.fn for m in metrics.values())

    # Micro F1
    micro_p = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    micro_r = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    micro_f1 = 2 * micro_p * micro_r / (micro_p + micro_r) if (micro_p + micro_r) > 0 else 0.0

    # Macro F1 — average of per-entity F1
    entity_f1s = [m.f1 for m in metrics.values() if (m.tp + m.fn) > 0]
    macro_f1 = sum(entity_f1s) / len(entity_f1s) if entity_f1s else 0.0

    # Primary-label accuracy — is the TOP prediction (highest confidence) correct?
    # predicted_entity_types comes from findings which are merged by highest confidence,
    # so we need to find the actual highest-confidence prediction.
    primary_correct = 0
    primary_total = 0
    for cr in column_results:
        if cr.expected_entity_type is not None:
            primary_total += 1
            # Find the highest-confidence finding from the pipeline results
            col_findings = findings_by_col.get(cr.column_id, [])
            if col_findings:
                top_prediction = max(col_findings, key=lambda f: f.confidence)
                if top_prediction.entity_type == cr.expected_entity_type:
                    primary_correct += 1

    primary_label_accuracy = primary_correct / primary_total if primary_total > 0 else 0.0

    # Attach aggregate metrics to a module-level cache for report access
    run_benchmark._last_result = BenchmarkResult(  # type: ignore[attr-defined]
        column_results=column_results,
        entity_metrics=metrics,
        micro_f1=micro_f1,
        macro_f1=macro_f1,
        primary_label_accuracy=primary_label_accuracy,
        corpus_source=corpus_source,
    )

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

    # Retrieve aggregate metrics from last run
    last_result: BenchmarkResult | None = getattr(run_benchmark, "_last_result", None)
    macro_f1 = last_result.macro_f1 if last_result else 0.0
    micro_f1 = last_result.micro_f1 if last_result else 0.0
    primary_label_acc = last_result.primary_label_accuracy if last_result else 0.0
    corpus_source = last_result.corpus_source if last_result else "synthetic"

    print("=" * 70)  # noqa: T201
    print("ACCURACY BENCHMARK REPORT")  # noqa: T201
    print("=" * 70)  # noqa: T201
    print()  # noqa: T201

    print("KEY METRICS")  # noqa: T201
    print("-" * 70)  # noqa: T201
    print(f"  Macro F1:                {macro_f1:.3f}")  # noqa: T201
    print(f"  Micro F1:                {micro_f1:.3f}")  # noqa: T201
    print(f"  Primary-Label Accuracy:  {primary_label_acc:.1%}")  # noqa: T201
    print(f"  Corpus Source:           {corpus_source}")  # noqa: T201
    print()  # noqa: T201

    print("CORPUS STATISTICS")  # noqa: T201
    print(f"  Total columns:      {total_columns}")  # noqa: T201
    print(f"  Positive columns:   {positive_columns} ({entity_types_tested} entity types)")  # noqa: T201
    print(f"  Negative columns:   {negative_columns}")  # noqa: T201
    print(f"  Total samples:      {total_samples}")  # noqa: T201
    print(f"  Avg samples/column: {avg_samples:.0f}")  # noqa: T201
    print()  # noqa: T201

    # ── Sample-level aggregate ─────────────────────────────────────────────
    w = 70
    profile = load_profile("standard")
    total_samples_matched = 0
    total_samples_scanned = 0
    total_samples_validated = 0
    sample_rows: list[tuple[str, int, int, int, float, str]] = []

    for cr in column_results:
        if cr.expected_entity_type is None:
            continue
        col = next(c for c, _ in corpus if c.column_id == cr.column_id)
        col_findings = {f.entity_type: f for f in classify_columns([col], profile, min_confidence=0.0)}
        expected_f = col_findings.get(cr.expected_entity_type)
        n_samples = len(col.sample_values)

        if expected_f and expected_f.sample_analysis:
            sa = expected_f.sample_analysis
            total_samples_scanned += sa.samples_scanned
            total_samples_matched += sa.samples_matched
            total_samples_validated += sa.samples_validated
            sample_rows.append(
                (
                    cr.expected_entity_type,
                    sa.samples_matched,
                    sa.samples_scanned,
                    sa.samples_validated,
                    expected_f.confidence,
                    "regex",
                )
            )
        elif expected_f:
            # Detected via column name only — all samples "covered" by name match
            total_samples_scanned += n_samples
            total_samples_matched += n_samples
            total_samples_validated += n_samples
            sample_rows.append(
                (
                    cr.expected_entity_type,
                    n_samples,
                    n_samples,
                    n_samples,
                    expected_f.confidence,
                    "column_name",
                )
            )
        else:
            total_samples_scanned += n_samples
            sample_rows.append((cr.expected_entity_type, 0, n_samples, 0, 0.0, "MISSED"))

    positive_samples = sum(len(c.sample_values) for c, e in corpus if e is not None)
    negative_samples = total_samples - positive_samples
    sample_match_rate = total_samples_matched / total_samples_scanned if total_samples_scanned > 0 else 0
    sample_valid_rate = total_samples_validated / total_samples_matched if total_samples_matched > 0 else 0

    print("SAMPLE-LEVEL SUMMARY")  # noqa: T201
    print("-" * w)  # noqa: T201
    print(f"  Positive samples:     {positive_samples:,}")  # noqa: T201
    print(f"  Negative samples:     {negative_samples:,}")  # noqa: T201
    print(f"  Samples scanned:      {total_samples_scanned:,}")  # noqa: T201
    print(f"  Samples matched:      {total_samples_matched:,} ({sample_match_rate:.1%})")  # noqa: T201
    print(f"  Samples validated:    {total_samples_validated:,} ({sample_valid_rate:.1%} of matched)")  # noqa: T201
    print()  # noqa: T201

    print(
        f"  {'Entity Type':<22} {'Matched':>10} {'Scanned':>10} {'Valid':>10} {'Conf':>8} {'Via':>12}"  # noqa: T201
    )
    print(f"  {'-' * 22} {'-' * 10} {'-' * 10} {'-' * 10} {'-' * 8} {'-' * 12}")  # noqa: T201
    for entity_type, matched, scanned, validated, conf, via in sample_rows:
        pct = f"({matched / scanned:.0%})" if scanned > 0 else ""
        print(  # noqa: T201
            f"  {entity_type:<22} {matched:>7}{pct:>3} {scanned:>10} {validated:>10} {conf:>8.3f} {via:>12}"
        )
    print()  # noqa: T201

    # ── Per-column detection accuracy ─────────────────────────────────────
    header = f"{'Entity Type':<22} {'TP':>4} {'FP':>4} {'FN':>4} {'Prec':>8} {'Recall':>8} {'F1':>8}"
    print("COLUMN-LEVEL ACCURACY (did the column get the correct entity label?)")  # noqa: T201
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


def _build_parser() -> argparse.ArgumentParser:
    """Construct the accuracy_benchmark CLI argparser.

    Exposed as a helper so tests can inspect the ``--corpus`` choices
    without invoking the full benchmark pipeline (which loads ML models).
    """
    parser = argparse.ArgumentParser(description="Run accuracy benchmark")
    parser.add_argument("--samples", type=int, default=100, help="Samples per entity type")
    parser.add_argument("--verbose", action="store_true", help="Include per-sample analysis")
    parser.add_argument(
        "--corpus",
        type=str,
        default="synthetic",
        choices=["synthetic", "nemotron", "gretel_en", "gretel_finance", "all"],
        help="Corpus source to use (default: synthetic)",
    )
    parser.add_argument("--max-rows", type=int, default=500, help="Max rows for real-world corpora")
    parser.add_argument(
        "--blind",
        action="store_true",
        help="Use generic column names (col_0, col_1, ...) to test sample-value-only classification",
    )
    return parser


if __name__ == "__main__":
    args = _build_parser().parse_args()

    corpus_source = args.corpus

    if corpus_source == "synthetic":
        from tests.benchmarks.corpus_generator import generate_corpus

        print(f"Generating synthetic corpus ({args.samples} samples/type)...")  # noqa: T201
        corpus = generate_corpus(samples_per_type=args.samples, locale="en_US")
    else:
        from tests.benchmarks.corpus_loader import load_corpus

        label = f"{corpus_source} corpus"
        if args.blind:
            label += " (BLIND — generic column names)"
        print(f"Loading {label} (max {args.max_rows} rows)...")  # noqa: T201
        corpus = load_corpus(corpus_source, max_rows=args.max_rows, blind=args.blind)

    results, metrics = run_benchmark(corpus, verbose=args.verbose, corpus_source=corpus_source)
    print_report(corpus, results, metrics, verbose=args.verbose)
