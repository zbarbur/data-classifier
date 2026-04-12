"""Build the meta-classifier training dataset (Phase 1).

Assembles training rows from:
  * Nemotron-PII (named + blind modes)
  * Ai4Privacy pii-masking-300k (named + blind modes)
  * Faker-based synthetic corpus (via tests.benchmarks.corpus_generator)

and writes them as newline-delimited JSON to the ``--output`` path. Also
prints a stats report to stdout — dataset size breakdown, class balance,
engine coverage, feature distributions, and top pairwise correlations.

Usage (from the repo root)::

    python -m tests.benchmarks.meta_classifier.build_training_data \\
        --output tests/benchmarks/meta_classifier/training_data_e10.jsonl

Phase 1/2 disabled ML engines here because the initial meta-classifier
was trained on non-ML signals only. E10 flips that — the training data
is built against the real 5-engine cascade (regex + column_name +
heuristic_stats + secret_scanner + GLiNER2). GLiNER's contribution is
captured in five dedicated feature slots (indices 15..19) by
:mod:`tests.benchmarks.meta_classifier.extract_features`. The kill
switch (``DATA_CLASSIFIER_DISABLE_ML=1``) is still honored by the
feature extractor — if the env var is set or GLiNER fails to load, the
five new slots fall back to zero.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path

from data_classifier import load_profile
from tests.benchmarks.corpus_generator import generate_corpus
from tests.benchmarks.meta_classifier.extract_features import (
    FEATURE_NAMES,
    TrainingRow,
    extract_training_row,
)
from tests.benchmarks.meta_classifier.shard_builder import (
    ShardSpec,
    build_shards,
    summarise_shards,
)

# Continuous (non-boolean, non-count) features for the stats report.
# Indices 15, 19 are GLiNER continuous features; 16, 17, 18 are GLiNER
# booleans and stay out of the continuous summary.
_CONTINUOUS_FEATURE_INDICES: tuple[int, ...] = (0, 1, 2, 3, 4, 7, 8, 9, 10, 15, 19)
_ENGINE_NAMES: tuple[str, ...] = (
    "regex",
    "column_name",
    "heuristic_stats",
    "secret_scanner",
    "gliner2",
)


# ── Row assembly helpers ────────────────────────────────────────────────────


def _rows_from_shards(
    shards: list[ShardSpec],
    *,
    profile,
) -> list[TrainingRow]:
    """Run engines over every shard and produce training rows."""
    rows: list[TrainingRow] = []
    for shard in shards:
        row = extract_training_row(
            shard.column,
            shard.ground_truth,
            profile=profile,
            column_id=shard.column_id,
            corpus=shard.corpus,
            mode=shard.mode,
            source=shard.source,
        )
        rows.append(row)
    return rows


_SYNTHETIC_LOCALES: tuple[str, ...] = ("en_US", "en_GB", "de_DE", "fr_FR", "es_ES")


def _build_synthetic_pool() -> dict[str, list[str]]:
    """Build a Faker-backed pool keyed by ground-truth entity type.

    Walks every locale in :data:`_SYNTHETIC_LOCALES`, concatenates the
    resulting sample values per type.  Locales that lack a provider for
    a given type are skipped silently.  The returned pool is consumed by
    :func:`shard_builder.build_shards`, which handles the actual
    shard/blind-mode/bucketed-M strategy.
    """
    pool: dict[str, list[str]] = {}
    for locale in _SYNTHETIC_LOCALES:
        try:
            corpus = generate_corpus(samples_per_type=400, locale=locale, include_embedded=False)
        except Exception:
            continue
        for column, ground_truth in corpus:
            if ground_truth is None:
                continue
            pool.setdefault(ground_truth, []).extend(column.sample_values)
    return pool


# ── Stats report ────────────────────────────────────────────────────────────


def _format_float(value: float, width: int = 8) -> str:
    if math.isnan(value):
        return "nan".rjust(width)
    return f"{value:>{width}.3f}"


def _per_feature_stats(rows: list[TrainingRow]) -> list[tuple[str, float, float, float, float]]:
    """Return [(name, min, max, mean, std), ...] for all features."""
    out: list[tuple[str, float, float, float, float]] = []
    if not rows:
        return out
    for i, name in enumerate(FEATURE_NAMES):
        column = [row.features[i] for row in rows]
        fmin = min(column)
        fmax = max(column)
        mean = statistics.fmean(column)
        std = statistics.pstdev(column) if len(column) > 1 else 0.0
        out.append((name, fmin, fmax, mean, std))
    return out


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx = statistics.fmean(xs)
    my = statistics.fmean(ys)
    num = 0.0
    dx2 = 0.0
    dy2 = 0.0
    for x, y in zip(xs, ys, strict=True):
        dx = x - mx
        dy = y - my
        num += dx * dy
        dx2 += dx * dx
        dy2 += dy * dy
    denom = math.sqrt(dx2 * dy2)
    if denom == 0.0:
        return 0.0
    return num / denom


def _top_correlations(rows: list[TrainingRow], top_k: int = 5) -> list[tuple[str, str, float]]:
    if len(rows) < 2:
        return []
    columns: list[list[float]] = [[row.features[i] for row in rows] for i in range(len(FEATURE_NAMES))]
    pairs: list[tuple[str, str, float]] = []
    for i in range(len(FEATURE_NAMES)):
        for j in range(i + 1, len(FEATURE_NAMES)):
            r = _pearson(columns[i], columns[j])
            pairs.append((FEATURE_NAMES[i], FEATURE_NAMES[j], r))
    pairs.sort(key=lambda p: abs(p[2]), reverse=True)
    return pairs[:top_k]


def _engine_firing_rates(rows: list[TrainingRow]) -> dict[str, int]:
    counts = dict.fromkeys(_ENGINE_NAMES, 0)
    for row in rows:
        for engine in row.fired_engines:
            if engine in counts:
                counts[engine] += 1
    return counts


def _dataset_breakdown(rows: list[TrainingRow]) -> dict[str, int]:
    """(corpus, mode) → count."""
    counter: Counter[tuple[str, str]] = Counter()
    for row in rows:
        counter[(row.corpus, row.mode)] += 1
    return {f"{c}/{m}": v for (c, m), v in sorted(counter.items())}


def _class_balance(rows: list[TrainingRow]) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for row in rows:
        counter[row.ground_truth] += 1
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))


def _per_feature_nonzero_rate(rows: list[TrainingRow]) -> list[tuple[str, float]]:
    """Return the fraction of rows with a non-zero value per feature."""
    if not rows:
        return [(name, 0.0) for name in FEATURE_NAMES]
    total = len(rows)
    out: list[tuple[str, float]] = []
    for i, name in enumerate(FEATURE_NAMES):
        nonzero = sum(1 for row in rows if row.features[i] != 0.0)
        out.append((name, nonzero / total))
    return out


def _print_report(rows: list[TrainingRow], *, output: Path, stream=sys.stdout) -> None:
    total = len(rows)
    print("=" * 72, file=stream)
    print("Meta-classifier Phase 1 — training data build report", file=stream)
    print("=" * 72, file=stream)
    print(f"Output: {output}", file=stream)
    print(f"Total rows: {total}", file=stream)
    print(file=stream)

    print("Dataset breakdown (corpus/mode → rows):", file=stream)
    for key, count in _dataset_breakdown(rows).items():
        print(f"  {key:<32} {count:>5}", file=stream)
    real = sum(1 for r in rows if r.source == "real")
    synth = sum(1 for r in rows if r.source == "synthetic")
    print(f"  {'real (total)':<32} {real:>5}", file=stream)
    print(f"  {'synthetic (total)':<32} {synth:>5}", file=stream)
    print(file=stream)

    print("Class balance (ground_truth → count):", file=stream)
    underfit: list[str] = []
    for entity, count in _class_balance(rows):
        flag = "  <-- UNDERFIT (<10)" if count < 10 else ""
        print(f"  {entity:<24} {count:>5}{flag}", file=stream)
        if count < 10:
            underfit.append(entity)
    print(file=stream)

    # Coverage
    zero_sig = sum(1 for r in rows if not r.has_any_signal)
    zero_pct = (zero_sig / total * 100.0) if total else 0.0
    print("Coverage stats:", file=stream)
    print(f"  columns with zero engine signals: {zero_sig}/{total} ({zero_pct:.1f}%)", file=stream)
    firing = _engine_firing_rates(rows)
    for engine in _ENGINE_NAMES:
        hits = firing[engine]
        pct = (hits / total * 100.0) if total else 0.0
        print(f"  {engine:<20} fired on {hits}/{total} ({pct:.1f}%)", file=stream)
    print(file=stream)

    # Feature distribution
    print("Feature distribution (continuous features):", file=stream)
    print(f"  {'name':<28} {'min':>8} {'max':>8} {'mean':>8} {'std':>8}", file=stream)
    per_stat = _per_feature_stats(rows)
    for idx in _CONTINUOUS_FEATURE_INDICES:
        name, fmin, fmax, mean, std = per_stat[idx]
        print(
            f"  {name:<28} {_format_float(fmin)} {_format_float(fmax)} {_format_float(mean)} {_format_float(std)}",
            file=stream,
        )
    print(file=stream)

    print("Feature distribution (count/boolean features):", file=stream)
    for idx, (name, fmin, fmax, mean, std) in enumerate(per_stat):
        if idx in _CONTINUOUS_FEATURE_INDICES:
            continue
        print(
            f"  {name:<28} {_format_float(fmin)} {_format_float(fmax)} {_format_float(mean)} {_format_float(std)}",
            file=stream,
        )
    print(file=stream)

    # Per-feature non-zero rate — especially important for Phase 2 to
    # verify secret_scanner_confidence has moved off constant zero.
    print("Per-feature non-zero rate (fraction of rows with feature != 0):", file=stream)
    for name, rate in _per_feature_nonzero_rate(rows):
        flag = "  <-- CONSTANT ZERO" if rate == 0.0 else ""
        print(f"  {name:<28} {rate:>6.1%}{flag}", file=stream)
    print(file=stream)

    # Phase-2-specific signal checks.
    negative_rows = [r for r in rows if r.ground_truth == "NEGATIVE"]
    print("NEGATIVE class coverage (Phase 2 supervision signal):", file=stream)
    print(f"  NEGATIVE rows: {len(negative_rows)}", file=stream)
    if negative_rows:
        neg_corp = Counter(r.corpus for r in negative_rows)
        for corpus, count in sorted(neg_corp.items()):
            print(f"    from {corpus:<20} {count:>5}", file=stream)
    real_total = sum(1 for r in rows if r.source == "real")
    synth_total = sum(1 for r in rows if r.source == "synthetic")
    ratio_denom = real_total + synth_total
    real_pct = (real_total / ratio_denom * 100.0) if ratio_denom else 0.0
    synth_pct = (synth_total / ratio_denom * 100.0) if ratio_denom else 0.0
    print(f"  real:synthetic ratio = {real_total}:{synth_total} ({real_pct:.1f}% / {synth_pct:.1f}%)", file=stream)
    print(file=stream)

    # Correlations
    print("Top 5 pairwise Pearson correlations (|r|):", file=stream)
    for a, b, r in _top_correlations(rows):
        flag = "  <-- REDUNDANT (|r|>0.9)" if abs(r) > 0.9 else ""
        print(f"  {a:<28} {b:<28} {r:+.3f}{flag}", file=stream)
    print(file=stream)

    # Verdict (heuristic)
    print("Phase 1 verdict:", file=stream)
    if total < 100:
        print("  WARNING: dataset is very small — <100 samples.", file=stream)
    if zero_pct > 20.0:
        print(
            f"  WARNING: {zero_pct:.1f}% of columns have zero engine signals — "
            "non-ML-only training may not be viable without GLiNER.",
            file=stream,
        )
    if underfit:
        print(
            f"  WARNING: {len(underfit)} entity type(s) have <10 samples and will be underfit: " + ", ".join(underfit),
            file=stream,
        )
    print("=" * 72, file=stream)


# ── CLI ─────────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("tests/benchmarks/meta_classifier/training_data.jsonl"),
        help="Path to write the JSONL training data.",
    )
    parser.add_argument(
        "--synthetic-count",
        type=int,
        default=300,
        help=(
            "DEPRECATED in Phase 2. The shard builder now sizes synthetic "
            "output using per-type shard counts from "
            "sharding_strategy.md §4.3 (30 shards for real-backed types, "
            "150 for synthetic-only types). Retained for CLI compat."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    profile = load_profile("standard")

    # Sharded training data — real corpora (Ai4Privacy, Nemotron,
    # SecretBench, gitleaks, detect_secrets) plus Faker-backed synthetic
    # augmentation.  The shard_builder handles bucketed M, named/blind
    # doubling, and unique-without-replacement slicing inside each
    # (type, corpus) combo.
    synthetic_pool = _build_synthetic_pool()
    shards = build_shards(synthetic_pool=synthetic_pool, seed=20260412)

    # Print shard-level summary before engine extraction (cheap to compute
    # and handy when feature extraction crashes mid-run).
    shard_summary = summarise_shards(shards)
    print(f"Shard summary: {shard_summary['total']} shards across {len(shard_summary['per_class'])} classes")
    print(f"  resampled shards: {shard_summary['resampled']} (will be tagged in row metadata)")
    print(f"  M range: [{shard_summary['m_min']}, {shard_summary['m_max']}], mean={shard_summary['m_mean']:.1f}")

    # Run engines over every shard.
    rows: list[TrainingRow] = _rows_from_shards(shards, profile=profile)

    # Write JSONL.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row.to_json_dict()) + "\n")

    _print_report(rows, output=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
