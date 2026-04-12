"""Quick performance benchmark — fast enough for every sprint closure.

Measures only the essentials:
- Warmup cost (first call, includes RE2 compile + GLiNER2 model load)
- Full pipeline p50/p95 (full classify_columns call)
- Per-column p50 latency
- Throughput (columns/sec, samples/sec)
- Per-engine contribution (via tier events)

Skips:
- Sample count scaling sweeps
- Input length scaling (RE2 linearity)
- Per-input-type variation
- Direct pattern matching micro-benchmarks

For the deep perf analysis, run: python -m tests.benchmarks.perf_benchmark

Usage:
    python -m tests.benchmarks.perf_quick                    # 5 iterations
    python -m tests.benchmarks.perf_quick --iterations 10    # more stable p95
    python -m tests.benchmarks.perf_quick --corpus nemotron  # use real corpus
"""

from __future__ import annotations

import argparse
import sys
import time

from data_classifier import classify_columns, load_profile
from data_classifier.core.types import ColumnInput
from data_classifier.events.emitter import CallbackHandler, EventEmitter
from data_classifier.events.types import TierEvent


def _build_default_corpus() -> list[ColumnInput]:
    """Small synthetic corpus for quick perf testing (~20 columns, 50 samples)."""
    return [
        ColumnInput(
            column_name="customer_ssn",
            column_id="c1",
            sample_values=[f"{i:03d}-{i:02d}-{1000 + i:04d}" for i in range(50)],
        ),
        ColumnInput(column_name="email", column_id="c2", sample_values=[f"user{i}@example.com" for i in range(50)]),
        ColumnInput(
            column_name="phone", column_id="c3", sample_values=[f"555-{i:03d}-{1000 + i:04d}" for i in range(50)]
        ),
        ColumnInput(
            column_name="full_name", column_id="c4", sample_values=["John Smith", "Maria Garcia", "Wei Zhang"] * 17
        ),
        ColumnInput(column_name="street_address", column_id="c5", sample_values=[f"{i} Main St" for i in range(50)]),
        ColumnInput(
            column_name="credit_card", column_id="c6", sample_values=[f"4532 0151 1283 {i:04d}" for i in range(50)]
        ),
        ColumnInput(column_name="ip_address", column_id="c7", sample_values=[f"192.168.{i}.1" for i in range(50)]),
        ColumnInput(
            column_name="date_of_birth",
            column_id="c8",
            sample_values=[f"1990-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}" for i in range(50)],
        ),
        ColumnInput(column_name="description", column_id="c9", sample_values=["Generic text content"] * 50),
        ColumnInput(column_name="col_1", column_id="c10", sample_values=[f"value_{i}" for i in range(50)]),
    ]


def run_quick_perf(corpus: list[ColumnInput], iterations: int = 5, measure_warmup: bool = False) -> dict:
    """Run a minimal performance benchmark.

    Assumes a warm environment by default — skips warmup measurement.
    Pass ``measure_warmup=True`` only if you care about cold-start cost.
    """
    profile = load_profile("standard")
    total_samples = sum(len(c.sample_values) for c in corpus)

    results: dict = {
        "iterations": iterations,
        "num_columns": len(corpus),
        "total_samples": total_samples,
        "avg_samples_per_col": total_samples / len(corpus),
    }

    # Always run one call first to warm the engines — this is NOT timed
    # and ensures subsequent measurements reflect steady-state latency.
    if measure_warmup:
        t0 = time.perf_counter()
        classify_columns(corpus[:1], profile, min_confidence=0.0)
        results["warmup_ms"] = (time.perf_counter() - t0) * 1000
    else:
        # Still warm, but don't time it
        classify_columns(corpus[:1], profile, min_confidence=0.0)
        results["warmup_ms"] = None

    # Full pipeline latency — N iterations
    latencies_ms: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        classify_columns(corpus, profile, min_confidence=0.0)
        latencies_ms.append((time.perf_counter() - t0) * 1000)

    latencies_ms.sort()
    n = len(latencies_ms)
    p50 = latencies_ms[n // 2]
    p95 = latencies_ms[min(int(n * 0.95), n - 1)]

    results["total_p50_ms"] = p50
    results["total_p95_ms"] = p95
    results["per_column_p50_ms"] = p50 / len(corpus)
    results["per_sample_p50_us"] = (p50 / total_samples * 1000) if total_samples else 0
    results["columns_per_sec"] = len(corpus) / (p50 / 1000) if p50 > 0 else 0
    results["samples_per_sec"] = total_samples / (p50 / 1000) if p50 > 0 else 0

    # Per-engine contribution (single run, via events)
    tier_events: list[TierEvent] = []
    emitter = EventEmitter()
    emitter.add_handler(CallbackHandler(lambda e: tier_events.append(e) if isinstance(e, TierEvent) else None))
    classify_columns(corpus, profile, min_confidence=0.0, event_emitter=emitter)

    engine_totals: dict[str, float] = {}
    engine_calls: dict[str, int] = {}
    for ev in tier_events:
        engine_totals[ev.tier] = engine_totals.get(ev.tier, 0.0) + ev.latency_ms
        engine_calls[ev.tier] = engine_calls.get(ev.tier, 0) + 1

    results["engines"] = {
        name: {
            "total_ms": engine_totals[name],
            "calls": engine_calls[name],
            "avg_ms": engine_totals[name] / engine_calls[name] if engine_calls[name] > 0 else 0.0,
            "pct_of_total": engine_totals[name] / sum(engine_totals.values()) * 100 if engine_totals else 0,
        }
        for name in engine_totals
    }

    return results


def print_report(results: dict) -> None:
    """Pretty-print the quick perf results."""
    print("=" * 60)
    print("QUICK PERFORMANCE BENCHMARK")
    print("=" * 60)
    print(f"  Columns:            {results['num_columns']}")
    print(f"  Samples/col:        {results['avg_samples_per_col']:.0f}")
    print(f"  Iterations:         {results['iterations']}")
    print()
    print("HOT LATENCY (steady-state, warm environment)")
    print("-" * 60)
    if results.get("warmup_ms") is not None:
        print(f"  Cold start (one-time)          {results['warmup_ms']:>10.1f} ms")
    print(f"  Total pipeline p50             {results['total_p50_ms']:>10.1f} ms")
    print(f"  Total pipeline p95             {results['total_p95_ms']:>10.1f} ms")
    print(f"  Per column (p50)               {results['per_column_p50_ms']:>10.2f} ms")
    print(f"  Per sample (p50)               {results['per_sample_p50_us']:>10.1f} us")
    print()
    print("THROUGHPUT")
    print("-" * 60)
    print(f"  Columns/sec         {results['columns_per_sec']:>10,.0f}")
    print(f"  Samples/sec         {results['samples_per_sec']:>10,.0f}")
    print()
    print("PER-ENGINE BREAKDOWN (single run)")
    print("-" * 60)
    print(f"  {'Engine':20s} {'Total':>10s} {'Calls':>8s} {'Avg':>10s} {'%':>8s}")
    for name, data in sorted(results["engines"].items(), key=lambda x: -x[1]["total_ms"]):
        print(
            f"  {name:20s} "
            f"{data['total_ms']:>8.1f}ms "
            f"{data['calls']:>8d} "
            f"{data['avg_ms']:>8.2f}ms "
            f"{data['pct_of_total']:>6.1f}%"
        )
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Quick performance benchmark")
    parser.add_argument("--iterations", type=int, default=5, help="Iterations (default: 5)")
    parser.add_argument(
        "--corpus",
        default="synthetic",
        choices=["synthetic", "nemotron", "ai4privacy"],
        help="Corpus to use (default: built-in synthetic)",
    )
    parser.add_argument(
        "--measure-warmup",
        action="store_true",
        help="Include cold-start warmup measurement (default: warm env assumed)",
    )
    args = parser.parse_args()

    if args.corpus == "synthetic":
        corpus = _build_default_corpus()
    else:
        from tests.benchmarks.corpus_loader import load_corpus

        raw = load_corpus(args.corpus, max_rows=50)
        corpus = [col for col, _ in raw]

    print(f"Running quick perf on {args.corpus} corpus...", file=sys.stderr)
    results = run_quick_perf(corpus, iterations=args.iterations, measure_warmup=args.measure_warmup)
    print_report(results)


if __name__ == "__main__":
    main()
