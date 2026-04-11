"""Generate a sprint benchmark report in Markdown.

Runs both pattern-level and column-level benchmarks, writes a formatted
Markdown report to docs/sprints/SPRINT{N}_BENCHMARK.md.

Usage:
    python -m tests.benchmarks.generate_report --sprint 2 [--samples 500]
"""

from __future__ import annotations

import argparse
import io
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from tests.benchmarks.accuracy_benchmark import BenchmarkResult, run_benchmark
from tests.benchmarks.corpus_generator import generate_corpus, generate_raw_samples
from tests.benchmarks.pattern_benchmark import run_pattern_benchmark
from tests.benchmarks.perf_benchmark import run_perf_benchmark


def _capture_pattern_report(samples: list[tuple[str, str | None]]) -> tuple[dict, str]:
    """Run pattern benchmark and capture results."""
    from tests.benchmarks.pattern_benchmark import print_report

    entity_results, pattern_stats, collision_matrix = run_pattern_benchmark(samples)

    buf = io.StringIO()
    with redirect_stdout(buf):
        print_report(samples, entity_results, pattern_stats, collision_matrix)

    return {"entity_results": entity_results, "collision_matrix": collision_matrix}, buf.getvalue()


def _capture_column_report(corpus: list[tuple], corpus_source: str = "synthetic") -> tuple[dict, str]:
    """Run column-level benchmark and capture results."""
    from tests.benchmarks.accuracy_benchmark import print_report

    results, metrics = run_benchmark(corpus, corpus_source=corpus_source)

    # Retrieve the BenchmarkResult with aggregate metrics
    last_result: BenchmarkResult | None = getattr(run_benchmark, "_last_result", None)

    buf = io.StringIO()
    with redirect_stdout(buf):
        print_report(corpus, results, metrics)

    return {
        "metrics": metrics,
        "macro_f1": last_result.macro_f1 if last_result else 0.0,
        "micro_f1": last_result.micro_f1 if last_result else 0.0,
        "primary_label_accuracy": last_result.primary_label_accuracy if last_result else 0.0,
        "corpus_source": corpus_source,
    }, buf.getvalue()


def _capture_perf_report(corpus: list[tuple]) -> tuple[dict, str]:
    """Run performance benchmark and capture results."""
    from tests.benchmarks.perf_benchmark import print_report

    perf_results = run_perf_benchmark(corpus, iterations=30)

    buf = io.StringIO()
    with redirect_stdout(buf):
        print_report(perf_results)

    return perf_results, buf.getvalue()


def _capture_secret_report() -> tuple[dict, str]:
    """Run secret detection benchmark and capture results."""
    from tests.benchmarks.secret_benchmark import print_report as secret_print_report
    from tests.benchmarks.secret_benchmark import run_benchmark as secret_run_benchmark

    metrics = secret_run_benchmark()

    buf = io.StringIO()
    with redirect_stdout(buf):
        secret_print_report(metrics)

    # Compute overall metrics
    tp_layers = [layer for layer in metrics if not layer.startswith("tn_")]
    overall_tp = sum(metrics[layer].tp for layer in tp_layers)
    overall_fp = sum(m.fp for m in metrics.values())
    overall_fn = sum(metrics[layer].fn for layer in tp_layers)
    overall_p = overall_tp / (overall_tp + overall_fp) if (overall_tp + overall_fp) > 0 else 0.0
    overall_r = overall_tp / (overall_tp + overall_fn) if (overall_tp + overall_fn) > 0 else 0.0
    overall_f1 = 2 * overall_p * overall_r / (overall_p + overall_r) if (overall_p + overall_r) > 0 else 0.0

    return {
        "metrics": metrics,
        "overall_f1": overall_f1,
        "overall_precision": overall_p,
        "overall_recall": overall_r,
    }, buf.getvalue()


def generate_report(
    sprint: int,
    samples_per_type: int = 500,
    corpus_source: str = "synthetic",
) -> str:
    """Generate the full benchmark report as a Markdown string."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    from data_classifier.patterns import load_default_patterns

    patterns = load_default_patterns()
    pattern_count = len(patterns)
    entity_types_in_patterns = len({p.entity_type for p in patterns})

    lines: list[str] = []

    def w(s: str = "") -> None:
        lines.append(s)

    w(f"# Sprint {sprint} — Benchmark Report")
    w()
    w(f"> **Generated:** {now}")
    w(f"> **Samples per type:** {samples_per_type}")
    w(f"> **Patterns:** {pattern_count}")
    w(f"> **Entity types (patterns):** {entity_types_in_patterns}")
    w(f"> **Corpus source:** {corpus_source}")
    w()

    # ── Pattern-level benchmark ──────────────────────────────────────────
    print(f"Running pattern benchmark ({samples_per_type} samples/type)...", file=sys.stderr)
    raw_samples = generate_raw_samples(count_per_type=samples_per_type)
    pattern_data, pattern_text = _capture_pattern_report(raw_samples)

    positive_samples = sum(1 for _, e in raw_samples if e is not None)
    negative_samples = len(raw_samples) - positive_samples

    entity_results = pattern_data["entity_results"]
    total_tp = sum(r.tp for r in entity_results.values())
    total_fp = sum(r.fp for r in entity_results.values())
    total_fn = sum(r.fn for r in entity_results.values())
    overall_p = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    overall_r = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    overall_f1 = 2 * overall_p * overall_r / (overall_p + overall_r) if (overall_p + overall_r) > 0 else 0.0

    w("## Summary")
    w()
    w("| Metric | Pattern-Level (regex only) | Column-Level (full pipeline) |")
    w("|---|---|---|")

    # ── Column-level benchmark ───────────────────────────────────────────
    print(f"Running column benchmark ({samples_per_type} samples/type)...", file=sys.stderr)
    corpus = generate_corpus(samples_per_type=samples_per_type)
    col_data, col_text = _capture_column_report(corpus, corpus_source=corpus_source)
    total_col_samples = sum(len(c.sample_values) for c, _ in corpus)
    col_metrics = col_data["metrics"]
    col_tp = sum(m.tp for m in col_metrics.values())
    col_fp = sum(m.fp for m in col_metrics.values())
    col_fn = sum(m.fn for m in col_metrics.values())
    col_p = col_tp / (col_tp + col_fp) if (col_tp + col_fp) > 0 else 0.0
    col_r = col_tp / (col_tp + col_fn) if (col_tp + col_fn) > 0 else 0.0
    col_f1 = 2 * col_p * col_r / (col_p + col_r) if (col_p + col_r) > 0 else 0.0
    col_macro_f1 = col_data.get("macro_f1", 0.0)
    col_primary_acc = col_data.get("primary_label_accuracy", 0.0)

    # ── Secret detection benchmark ──────────────────────────────────────
    print("Running secret detection benchmark...", file=sys.stderr)
    secret_data, secret_text = _capture_secret_report()
    secret_f1 = secret_data.get("overall_f1", 0.0)
    secret_p = secret_data.get("overall_precision", 0.0)
    secret_r = secret_data.get("overall_recall", 0.0)

    w(f"| Total samples | {len(raw_samples):,} | {total_col_samples:,} |")
    w(
        f"| Positive / Negative | {positive_samples:,} / {negative_samples:,}"
        f" | {sum(1 for _, e in corpus if e is not None)} cols"
        f" / {sum(1 for _, e in corpus if e is None)} cols |"
    )
    w(f"| Precision | {overall_p:.3f} | {col_p:.3f} |")
    w(f"| Recall | {overall_r:.3f} | {col_r:.3f} |")
    w(f"| **Micro F1** | **{overall_f1:.3f}** | **{col_f1:.3f}** |")
    w(f"| **Macro F1** | — | **{col_macro_f1:.3f}** |")
    w(f"| **Primary-Label Accuracy** | — | **{col_primary_acc:.1%}** |")
    w(f"| TP / FP / FN | {total_tp:,} / {total_fp:,} / {total_fn:,} | {col_tp} / {col_fp} / {col_fn} |")
    w()

    # ── Secret detection summary ────────────────────────────────────────
    w("### Secret Detection")
    w()
    w("| Metric | Value |")
    w("|---|---|")
    w(f"| Precision | {secret_p:.3f} |")
    w(f"| Recall | {secret_r:.3f} |")
    w(f"| **F1** | **{secret_f1:.3f}** |")
    w()

    # ── Per-entity F1 breakdown ─────────────────────────────────────────
    w("### Per-Entity F1 Breakdown (Column-Level)")
    w()
    w("| Entity Type | Precision | Recall | F1 | TP | FP | FN |")
    w("|---|---|---|---|---|---|---|")
    for entity_type in sorted(col_metrics.keys()):
        m = col_metrics[entity_type]
        w(f"| {entity_type} | {m.precision:.3f} | {m.recall:.3f} | {m.f1:.3f} | {m.tp} | {m.fp} | {m.fn} |")
    w()

    # ── Corpus source metadata ──────────────────────────────────────────
    w("### Corpus Metadata")
    w()
    w("| Property | Value |")
    w("|---|---|")
    w(f"| Source | {corpus_source} |")
    w(f"| Pattern samples | {len(raw_samples):,} ({positive_samples:,} positive, {negative_samples:,} negative) |")
    w(f"| Column corpus | {len(corpus)} columns ({total_col_samples:,} total samples) |")
    w(f"| Entity types tested | {len({e for _, e in corpus if e is not None})} |")
    w()

    # ── Performance ──────────────────────────────────────────────────────
    print("Running performance benchmark...", file=sys.stderr)
    perf_data, perf_text = _capture_perf_report(corpus)
    fp = perf_data.get("full_pipeline", {})

    w("## Performance")
    w()
    w("| Metric | Value |")
    w("|---|---|")
    w(
        f"| Throughput | {fp.get('columns_per_sec', 0):,.0f} columns/sec"
        f" \\| {fp.get('samples_per_sec', 0):,.0f} samples/sec |"
    )
    w(f"| Per column (p50) | {fp.get('per_column_p50_ms', 0):.3f} ms |")
    w(f"| Per sample (p50) | {fp.get('per_sample_p50_us', 0):.1f} us |")
    w(f"| Warmup (RE2 compile) | {perf_data.get('warmup_ms', 0):.1f} ms |")
    w()

    # Scaling
    w("### Scaling")
    w()
    scaling_samples = perf_data.get("scaling_samples", [])
    if scaling_samples:
        w("**Sample count scaling (per-column latency):**")
        w()
        w("| Samples/col | Latency (p50) |")
        w("|---|---|")
        for s in scaling_samples:
            w(f"| {s['samples_per_col']} | {s['per_column_p50_ms']:.3f} ms |")
        w()

    scaling_length = perf_data.get("scaling_length", [])
    if scaling_length:
        base_us = scaling_length[0]["p50_us"]
        w("**Input length scaling (RE2 linearity):**")
        w()
        w("| Input bytes | p50 (us) | Ratio |")
        w("|---|---|---|")
        for s in scaling_length:
            ratio = s["p50_us"] / base_us if base_us > 0 else 0
            w(f"| {s['input_bytes']:,} | {s['p50_us']:.1f} | {ratio:.1f}x |")
        w()

    # ── Detailed reports ─────────────────────────────────────────────────
    w("## Pattern-Level Detail")
    w()
    w("```")
    w(pattern_text.strip())
    w("```")
    w()

    w("## Column-Level Detail")
    w()
    w("```")
    w(col_text.strip())
    w("```")
    w()

    w("## Secret Detection Detail")
    w()
    w("```")
    w(secret_text.strip())
    w("```")
    w()

    w("## Performance Detail")
    w()
    w("```")
    w(perf_text.strip())
    w("```")

    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate sprint benchmark report")
    parser.add_argument("--sprint", type=int, required=True, help="Sprint number")
    parser.add_argument("--samples", type=int, default=500, help="Samples per entity type")
    parser.add_argument("--output", type=str, default=None, help="Output file (default: docs/sprints/)")
    parser.add_argument(
        "--corpus",
        type=str,
        default="synthetic",
        choices=["synthetic", "ai4privacy", "nemotron", "all"],
        help="Corpus source (default: synthetic)",
    )
    args = parser.parse_args()

    report = generate_report(sprint=args.sprint, samples_per_type=args.samples, corpus_source=args.corpus)

    output_path = args.output or f"docs/sprints/SPRINT{args.sprint}_BENCHMARK.md"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(report + "\n")

    print(f"Report written to {output_path}", file=sys.stderr)
    print(f"Size: {len(report):,} chars", file=sys.stderr)
