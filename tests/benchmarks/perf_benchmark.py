"""Performance benchmark — latency measurement for classification.

NOT part of the CI test suite. Run manually:
    python -m tests.benchmarks.perf_benchmark

Reports:
    - Per-column classification latency (p50, p95, p99)
    - RE2 Set compilation time
    - Throughput (columns/second)
"""

from __future__ import annotations

import statistics
import time

from data_classifier import classify_columns, load_profile
from data_classifier.core.types import ColumnInput


def run_perf_benchmark(
    columns: list[ColumnInput],
    iterations: int = 100,
) -> dict[str, float]:
    """Run performance benchmark on a set of columns.

    Args:
        columns: Columns to classify.
        iterations: Number of classification iterations.

    Returns:
        Dict with p50, p95, p99 latencies (ms), throughput (cols/sec), and compilation time (ms).
    """
    profile = load_profile("standard")

    # Warm up — first call may trigger lazy initialization
    warmup_start = time.perf_counter()
    classify_columns(columns[:1], profile)
    warmup_ms = (time.perf_counter() - warmup_start) * 1000

    # Run benchmark iterations
    latencies_ms: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        classify_columns(columns, profile)
        elapsed_ms = (time.perf_counter() - start) * 1000
        per_column_ms = elapsed_ms / len(columns) if columns else 0.0
        latencies_ms.append(per_column_ms)

    latencies_ms.sort()
    n = len(latencies_ms)

    p50 = latencies_ms[n // 2]
    p95 = latencies_ms[int(n * 0.95)]
    p99 = latencies_ms[int(n * 0.99)]

    # Throughput: use the median per-column latency
    throughput = 1000.0 / p50 if p50 > 0 else float("inf")

    # Standard deviation
    stddev = statistics.stdev(latencies_ms) if n > 1 else 0.0

    return {
        "warmup_ms": warmup_ms,
        "p50_ms": p50,
        "p95_ms": p95,
        "p99_ms": p99,
        "stddev_ms": stddev,
        "throughput_cols_per_sec": throughput,
        "iterations": iterations,
        "columns_count": len(columns),
    }


def print_report(results: dict[str, float]) -> None:
    """Print a formatted performance report."""
    print("\n" + "=" * 50)  # noqa: T201
    print("PERFORMANCE BENCHMARK REPORT")  # noqa: T201
    print("=" * 50)  # noqa: T201
    print(f"Columns:       {int(results['columns_count'])}")  # noqa: T201
    print(f"Iterations:    {int(results['iterations'])}")  # noqa: T201
    print(f"Warmup:        {results['warmup_ms']:.2f} ms")  # noqa: T201
    print("-" * 50)  # noqa: T201
    print("Per-column latency:")  # noqa: T201
    print(f"  p50:         {results['p50_ms']:.3f} ms")  # noqa: T201
    print(f"  p95:         {results['p95_ms']:.3f} ms")  # noqa: T201
    print(f"  p99:         {results['p99_ms']:.3f} ms")  # noqa: T201
    print(f"  stddev:      {results['stddev_ms']:.3f} ms")  # noqa: T201
    print(f"Throughput:    {results['throughput_cols_per_sec']:.0f} columns/sec")  # noqa: T201
    print("=" * 50)  # noqa: T201


if __name__ == "__main__":
    from tests.benchmarks.corpus_generator import generate_corpus

    print("Generating synthetic corpus...")  # noqa: T201
    corpus = generate_corpus(samples_per_type=20, locale="en_US")
    columns = [col for col, _ in corpus]
    print(f"Corpus size: {len(columns)} columns")  # noqa: T201

    results = run_perf_benchmark(columns, iterations=100)
    print_report(results)
