"""Performance benchmark — pattern matching and engine performance on real data.

NOT part of the CI test suite. Run manually:
    python -m tests.benchmarks.perf_benchmark [--samples N] [--iterations N]

Reports:
    - Corpus statistics (total data processed)
    - RE2 Set compilation time
    - Per-column latency (p50/p95/p99) at varying corpus sizes
    - Per-engine latency breakdown (column_name vs regex)
    - Pattern matching throughput (samples/sec, not just columns/sec)
    - RE2 Set screening time vs extraction time
    - Validator execution overhead
"""

from __future__ import annotations

import argparse
import statistics
import time
import uuid

from faker import Faker

from data_classifier import classify_columns, load_profile
from data_classifier.core.types import ColumnInput
from data_classifier.engines.column_name_engine import ColumnNameEngine
from data_classifier.engines.regex_engine import RegexEngine
from data_classifier.events.emitter import CallbackHandler, EventEmitter
from data_classifier.events.types import TierEvent


def _timed_classify(columns: list[ColumnInput], profile, emitter=None) -> tuple[list, float]:
    """Classify and return (findings, elapsed_ms)."""
    t0 = time.perf_counter()
    findings = classify_columns(columns, profile, min_confidence=0.0, event_emitter=emitter)
    elapsed = (time.perf_counter() - t0) * 1000
    return findings, elapsed


def run_perf_benchmark(
    corpus: list[tuple[ColumnInput, str | None]],
    iterations: int = 50,
) -> dict:
    """Run comprehensive performance benchmark."""
    profile = load_profile("standard")
    columns = [col for col, _ in corpus]
    total_samples = sum(len(c.sample_values) for c in columns)

    results: dict = {
        "corpus": {
            "columns": len(columns),
            "total_samples": total_samples,
            "avg_samples_per_col": total_samples / len(columns) if columns else 0,
        },
        "iterations": iterations,
    }

    # ── 1. Warmup + compilation time ─────────────────────────────────────
    t0 = time.perf_counter()
    classify_columns(columns[:1], profile, min_confidence=0.0)
    results["warmup_ms"] = (time.perf_counter() - t0) * 1000

    # ── 2. Full pipeline latency ─────────────────────────────────────────
    full_latencies: list[float] = []
    for _ in range(iterations):
        _, elapsed = _timed_classify(columns, profile)
        full_latencies.append(elapsed)

    full_latencies.sort()
    n = len(full_latencies)
    results["full_pipeline"] = {
        "total_p50_ms": full_latencies[n // 2],
        "total_p95_ms": full_latencies[int(n * 0.95)],
        "total_p99_ms": full_latencies[int(n * 0.99)],
        "per_column_p50_ms": full_latencies[n // 2] / len(columns),
        "per_sample_p50_us": full_latencies[n // 2] / total_samples * 1000 if total_samples else 0,
        "columns_per_sec": len(columns) / (full_latencies[n // 2] / 1000) if full_latencies[n // 2] > 0 else 0,
        "samples_per_sec": total_samples / (full_latencies[n // 2] / 1000) if full_latencies[n // 2] > 0 else 0,
    }

    # ── 3. Per-engine isolation timing ───────────────────────────────────
    for engine_cls, engine_name in [(ColumnNameEngine, "column_name"), (RegexEngine, "regex")]:
        engine = engine_cls()
        engine_latencies: list[float] = []
        for _ in range(iterations):
            t0 = time.perf_counter()
            for col in columns:
                engine.classify_column(col, profile=profile, min_confidence=0.0)
            elapsed = (time.perf_counter() - t0) * 1000
            engine_latencies.append(elapsed)

        engine_latencies.sort()
        n = len(engine_latencies)
        results[f"engine_{engine_name}"] = {
            "total_p50_ms": engine_latencies[n // 2],
            "per_column_p50_ms": engine_latencies[n // 2] / len(columns),
            "pct_of_pipeline": engine_latencies[n // 2] / full_latencies[len(full_latencies) // 2] * 100
            if full_latencies[len(full_latencies) // 2] > 0
            else 0,
        }

    # ── 4. Per-engine telemetry via events ────────────────────────────────
    tier_events: list[TierEvent] = []
    emitter = EventEmitter()
    emitter.add_handler(CallbackHandler(lambda e: tier_events.append(e) if isinstance(e, TierEvent) else None))
    classify_columns(columns, profile, min_confidence=0.0, event_emitter=emitter)

    engine_latency_totals: dict[str, list[float]] = {}
    for ev in tier_events:
        engine_latency_totals.setdefault(ev.tier, []).append(ev.latency_ms)

    results["engine_events"] = {}
    for engine_name, latencies in engine_latency_totals.items():
        results["engine_events"][engine_name] = {
            "calls": len(latencies),
            "total_ms": sum(latencies),
            "mean_ms": statistics.mean(latencies),
            "max_ms": max(latencies),
            "hits": sum(1 for ev in tier_events if ev.tier == engine_name and ev.outcome == "hit"),
            "misses": sum(1 for ev in tier_events if ev.tier == engine_name and ev.outcome == "miss"),
        }

    # ── 5. Scaling test — how does latency grow with sample count ────────
    scaling: list[dict] = []
    sample_sizes = [10, 50, 100, 500]
    for size in sample_sizes:
        scaled_columns = []
        for col in columns[:5]:  # Use 5 columns for scaling test
            scaled_col = ColumnInput(
                column_name=col.column_name,
                column_id=f"scale_{col.column_id}_{size}",
                data_type=col.data_type,
                sample_values=col.sample_values[:size] * (size // max(len(col.sample_values), 1) + 1),
            )
            scaled_col = ColumnInput(
                column_name=col.column_name,
                column_id=f"scale_{col.column_id}_{size}",
                data_type=col.data_type,
                sample_values=scaled_col.sample_values[:size],
            )
            scaled_columns.append(scaled_col)

        scale_latencies = []
        for _ in range(20):
            t0 = time.perf_counter()
            classify_columns(scaled_columns, profile, min_confidence=0.0)
            elapsed = (time.perf_counter() - t0) * 1000
            scale_latencies.append(elapsed / len(scaled_columns))

        scale_latencies.sort()
        actual_samples = sum(len(c.sample_values) for c in scaled_columns) // len(scaled_columns)
        scaling.append(
            {
                "samples_per_col": actual_samples,
                "per_column_p50_ms": scale_latencies[len(scale_latencies) // 2],
            }
        )

    results["scaling_samples"] = scaling

    # ── 6. String-length scaling — does RE2 scale linearly with input size? ──
    from tests.benchmarks.corpus_generator import generate_length_scaling_data

    length_data = generate_length_scaling_data()
    engine = RegexEngine()
    length_scaling: list[dict] = []

    for text, text_len in length_data:
        test_col = ColumnInput(
            column_name="__length_test__",
            column_id=f"__len_{text_len}__",
            data_type="STRING",
            sample_values=[text],
        )
        timings = []
        for _ in range(100):
            t0 = time.perf_counter()
            engine.classify_column(test_col, profile=profile, min_confidence=0.0)
            timings.append((time.perf_counter() - t0) * 1_000_000)  # microseconds
        timings.sort()
        length_scaling.append(
            {
                "input_bytes": text_len,
                "p50_us": timings[len(timings) // 2],
                "p99_us": timings[int(len(timings) * 0.99)],
            }
        )

    results["scaling_length"] = length_scaling

    # ── 7. Direct pattern matching — per-pattern performance ─────────────
    from data_classifier.patterns import load_default_patterns

    patterns = load_default_patterns()

    # Generate a mixed text with many potential matches
    fake = Faker()
    mixed_text = " ".join(
        [
            fake.ssn(),
            fake.email(),
            fake.ipv4(),
            fake.credit_card_number(),
            fake.iban(),
            fake.swift(),
            "just some random padding text here",
            fake.name(),
            fake.address(),
            str(uuid.uuid4()),
        ]
    )

    test_col = ColumnInput(
        column_name="__pattern_test__",
        column_id="__pattern_perf__",
        data_type="STRING",
        sample_values=[mixed_text] * 100,
    )

    t0 = time.perf_counter()
    findings = engine.classify_column(test_col, profile=profile, min_confidence=0.0)
    pattern_match_ms = (time.perf_counter() - t0) * 1000

    results["pattern_matching"] = {
        "input_samples": 100,
        "input_avg_length": len(mixed_text),
        "total_ms": pattern_match_ms,
        "per_sample_us": pattern_match_ms * 1000 / 100,
        "patterns_compiled": len(patterns),
        "findings_returned": len(findings),
        "findings_types": [f.entity_type for f in findings],
    }

    return results


def print_report(results: dict) -> None:
    """Print comprehensive performance report."""
    w = 70
    print()  # noqa: T201
    print("=" * w)  # noqa: T201
    print("PERFORMANCE BENCHMARK REPORT")  # noqa: T201
    print("=" * w)  # noqa: T201

    c = results["corpus"]
    print()  # noqa: T201
    print("DATA PROCESSED")  # noqa: T201
    print(f"  Columns:             {c['columns']}")  # noqa: T201
    print(f"  Total samples:       {c['total_samples']}")  # noqa: T201
    print(f"  Avg samples/column:  {c['avg_samples_per_col']:.0f}")  # noqa: T201
    print(f"  Iterations:          {results['iterations']}")  # noqa: T201
    print(f"  Warmup:              {results['warmup_ms']:.2f} ms")  # noqa: T201

    fp = results["full_pipeline"]
    print()  # noqa: T201
    print("FULL PIPELINE LATENCY")  # noqa: T201
    print("-" * w)  # noqa: T201
    print(
        f"  Total (all columns)  p50={fp['total_p50_ms']:.2f} ms"  # noqa: T201
        f"  p95={fp['total_p95_ms']:.2f} ms  p99={fp['total_p99_ms']:.2f} ms"
    )
    print(f"  Per column           p50={fp['per_column_p50_ms']:.3f} ms")  # noqa: T201
    print(f"  Per sample           p50={fp['per_sample_p50_us']:.1f} us")  # noqa: T201
    print(
        f"  Throughput           {fp['columns_per_sec']:.0f} columns/sec"  # noqa: T201
        f"  |  {fp['samples_per_sec']:.0f} samples/sec"
    )

    print()  # noqa: T201
    print("PER-ENGINE BREAKDOWN")  # noqa: T201
    print("-" * w)  # noqa: T201
    for key in ["engine_column_name", "engine_regex"]:
        if key in results:
            eng = results[key]
            name = key.replace("engine_", "")
            print(  # noqa: T201
                f"  {name:<20} total_p50={eng['total_p50_ms']:.2f} ms"
                f"  per_col={eng['per_column_p50_ms']:.3f} ms"
                f"  ({eng['pct_of_pipeline']:.0f}% of pipeline)"
            )

    print()  # noqa: T201
    print("ENGINE TELEMETRY (single run)")  # noqa: T201
    print("-" * w)  # noqa: T201
    for engine_name, ev in results.get("engine_events", {}).items():
        print(  # noqa: T201
            f"  {engine_name:<20} calls={ev['calls']}  "
            f"hits={ev['hits']}  misses={ev['misses']}  "
            f"total={ev['total_ms']:.2f}ms  mean={ev['mean_ms']:.3f}ms  max={ev['max_ms']:.3f}ms"
        )

    print()  # noqa: T201
    print("SCALING: SAMPLE COUNT (per-column latency vs samples/column)")  # noqa: T201
    print("-" * w)  # noqa: T201
    for s in results.get("scaling_samples", []):
        bar = "#" * min(int(s["per_column_p50_ms"] * 100), 40)
        print(f"  {s['samples_per_col']:>5} samples → {s['per_column_p50_ms']:.3f} ms/col  {bar}")  # noqa: T201

    print()  # noqa: T201
    print("SCALING: INPUT LENGTH (RE2 time vs string length, single sample)")  # noqa: T201
    print("-" * w)  # noqa: T201
    length_data = results.get("scaling_length", [])
    if length_data:
        base_us = length_data[0]["p50_us"]
        for s in length_data:
            ratio = s["p50_us"] / base_us if base_us > 0 else 0
            bar = "#" * min(int(ratio * 3), 40)
            print(  # noqa: T201
                f"  {s['input_bytes']:>6} bytes → p50={s['p50_us']:.1f} us"
                f"  p99={s['p99_us']:.1f} us"
                f"  ({ratio:.1f}x)  {bar}"
            )

    pm = results.get("pattern_matching", {})
    if pm:
        print()  # noqa: T201
        print("DIRECT PATTERN MATCHING (regex engine on mixed-PII text)")  # noqa: T201
        print("-" * w)  # noqa: T201
        print(f"  Patterns compiled:   {pm['patterns_compiled']}")  # noqa: T201
        print(f"  Input:               {pm['input_samples']} samples × {pm['input_avg_length']} chars")  # noqa: T201
        print(f"  Total time:          {pm['total_ms']:.2f} ms")  # noqa: T201
        print(f"  Per sample:          {pm['per_sample_us']:.1f} us")  # noqa: T201
        print(f"  Findings:            {pm['findings_returned']} ({', '.join(pm['findings_types'])})")  # noqa: T201

    print()  # noqa: T201
    print("=" * w)  # noqa: T201


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run performance benchmark")
    parser.add_argument("--samples", type=int, default=100, help="Samples per entity type")
    parser.add_argument("--iterations", type=int, default=50, help="Benchmark iterations")
    args = parser.parse_args()

    from tests.benchmarks.corpus_generator import generate_corpus

    print(f"Generating corpus ({args.samples} samples/type)...")  # noqa: T201
    corpus = generate_corpus(samples_per_type=args.samples, locale="en_US")

    results = run_perf_benchmark(corpus, iterations=args.iterations)
    print_report(results)
