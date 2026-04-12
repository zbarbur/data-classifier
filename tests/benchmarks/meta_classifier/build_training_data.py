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
        --output tests/benchmarks/meta_classifier/training_data.jsonl

The script disables ML engines before importing the library, so GLiNER2
is never loaded. The Phase 1 feature set is intentionally non-ML — the
whole point of Phase 1 is to measure whether non-ML engine signals alone
carry enough information to learn a useful meta-classifier.
"""

from __future__ import annotations

# NB: set environment BEFORE importing data_classifier — the GLiNER loader
# checks this on module import.
import os

os.environ.setdefault("DATA_CLASSIFIER_DISABLE_ML", "1")

import argparse  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import random  # noqa: E402
import statistics  # noqa: E402
import sys  # noqa: E402
from collections import Counter  # noqa: E402
from dataclasses import replace  # noqa: E402
from pathlib import Path  # noqa: E402

from data_classifier import load_profile  # noqa: E402
from data_classifier.core.types import ColumnInput  # noqa: E402
from tests.benchmarks.corpus_generator import generate_corpus  # noqa: E402
from tests.benchmarks.corpus_loader import (  # noqa: E402
    load_ai4privacy_corpus,
    load_nemotron_corpus,
)
from tests.benchmarks.meta_classifier.extract_features import (  # noqa: E402
    FEATURE_NAMES,
    TrainingRow,
    extract_training_row,
)

# Continuous (non-boolean, non-count) features for the stats report.
_CONTINUOUS_FEATURE_INDICES: tuple[int, ...] = (0, 1, 2, 3, 4, 7, 8, 9, 10)
_ENGINE_NAMES: tuple[str, ...] = (
    "regex",
    "column_name",
    "heuristic_stats",
    "secret_scanner",
)


# ── Row assembly helpers ────────────────────────────────────────────────────


def _rows_from_real_corpus(
    loader_name: str,
    loader_fn,
    mode: str,
    *,
    profile,
    blind: bool,
) -> list[TrainingRow]:
    corpus = loader_fn(blind=blind)
    rows: list[TrainingRow] = []
    for idx, (column, ground_truth) in enumerate(corpus):
        if ground_truth is None:
            continue
        row = extract_training_row(
            column,
            ground_truth,
            profile=profile,
            column_id=f"{loader_name}_{mode}_col_{idx}",
            corpus=loader_name,
            mode=mode,
            source="real",
        )
        rows.append(row)
    return rows


_SYNTHETIC_LOCALES: tuple[str, ...] = ("en_US", "en_GB", "de_DE", "fr_FR", "es_ES")

# Column-name variants used when augmenting synthetic rows. Each synthetic
# column is re-emitted once with a generic name (like a "blind" run) and
# once with a semantically obvious name — so the meta-classifier sees both
# column_name-engine-hit and column_name-engine-miss cases for every type.
_SYNTHETIC_NAME_VARIANTS: tuple[str, ...] = ("named", "blind")


def _rows_from_synthetic(
    target_count: int,
    *,
    profile,
) -> list[TrainingRow]:
    """Produce ``target_count`` synthetic training rows.

    Strategy: call :func:`generate_corpus` once per locale to get a base
    set of labeled columns (~27 per locale), then repeatedly derive new
    rows by (a) sub-sampling the sample_values and (b) alternating
    between the generator's natural column_name and a generic blind name.
    Continues until ``target_count`` rows have been produced or the
    locale pool is exhausted.
    """
    rng = random.Random(20260412)
    rows: list[TrainingRow] = []

    # Build a pool of (column, ground_truth, base_name) across all locales.
    pool: list[tuple[ColumnInput, str, str]] = []
    for locale in _SYNTHETIC_LOCALES:
        try:
            corpus = generate_corpus(samples_per_type=400, locale=locale, include_embedded=False)
        except Exception:
            # Some Faker locales may not have every provider.
            continue
        for column, ground_truth in corpus:
            if ground_truth is None:
                continue
            pool.append((column, ground_truth, column.column_name))

    if not pool:
        return rows

    col_idx = 0
    attempts = 0
    max_attempts = target_count * 4  # bail-out safety
    while len(rows) < target_count and attempts < max_attempts:
        attempts += 1
        base_column, ground_truth, base_name = pool[col_idx % len(pool)]
        col_idx += 1
        variant = _SYNTHETIC_NAME_VARIANTS[col_idx % len(_SYNTHETIC_NAME_VARIANTS)]

        # Subsample the sample values so every derived column is unique.
        values = base_column.sample_values
        if len(values) > 60:
            sample_size = rng.randint(40, min(150, len(values)))
            subset = rng.sample(values, sample_size)
        else:
            subset = list(values)

        if variant == "blind":
            new_name = f"col_{len(rows)}"
        else:
            new_name = base_name

        derived = replace(
            base_column,
            column_name=new_name,
            column_id=f"synthetic_col_{len(rows)}",
            sample_values=subset,
        )

        row = extract_training_row(
            derived,
            ground_truth,
            profile=profile,
            column_id=f"synthetic_col_{len(rows)}",
            corpus="synthetic",
            mode="synthetic",
            source="synthetic",
        )
        rows.append(row)

    return rows


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
            "Target number of synthetic training rows. The builder "
            "cycles through multiple Faker locales and alternates between "
            "named/blind column names, subsampling values to keep every "
            "row unique."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    profile = load_profile("standard")

    rows: list[TrainingRow] = []

    # Real corpora — both named and blind modes.
    for mode, blind in (("named", False), ("blind", True)):
        rows.extend(
            _rows_from_real_corpus(
                "nemotron",
                lambda *, blind=blind: load_nemotron_corpus(blind=blind),
                mode,
                profile=profile,
                blind=blind,
            )
        )
        rows.extend(
            _rows_from_real_corpus(
                "ai4privacy",
                lambda *, blind=blind: load_ai4privacy_corpus(blind=blind),
                mode,
                profile=profile,
                blind=blind,
            )
        )

    # Synthetic augmentation (Faker-backed).
    rows.extend(_rows_from_synthetic(args.synthetic_count, profile=profile))

    # Write JSONL.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row.to_json_dict()) + "\n")

    _print_report(rows, output=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
