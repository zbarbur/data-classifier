"""Pattern matching benchmark — tests regex engine directly on raw data.

Bypasses the column/profile layer entirely. Tests: given a string value,
does the regex engine find the correct entity type?

NOT part of the CI test suite. Run manually:
    python -m tests.benchmarks.pattern_benchmark [--samples N]

Reports:
    - Sample-level TP/FP/FN per entity type (not column-level)
    - Per-pattern match rate and validation rate
    - Cross-pattern collision matrix at the sample level
    - Missed samples (values that should match but didn't)
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, field

import re2

from data_classifier.engines.validators import VALIDATORS
from data_classifier.patterns import ContentPattern, load_default_patterns

# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class PatternStats:
    """Stats for one pattern across all samples."""

    name: str
    entity_type: str
    regex: str
    total_tested: int = 0
    matched: int = 0
    validated: int = 0
    validation_failed: int = 0

    @property
    def match_rate(self) -> float:
        return self.matched / self.total_tested if self.total_tested > 0 else 0.0

    @property
    def validation_rate(self) -> float:
        return self.validated / self.matched if self.matched > 0 else 0.0


@dataclass
class EntityResult:
    """Sample-level TP/FP/FN for one entity type."""

    tp: int = 0
    fp: int = 0
    fn: int = 0
    missed_samples: list[str] = field(default_factory=list)
    fp_samples: list[tuple[str, str]] = field(default_factory=list)  # (value, expected)

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


# ── Direct pattern matcher ───────────────────────────────────────────────────


def _match_value(value: str, patterns: list[ContentPattern], compiled: list, validators: list) -> list[str]:
    """Match a single value against all patterns. Returns list of entity types found."""
    found: dict[str, float] = {}  # entity_type -> best confidence

    for i, pattern in enumerate(patterns):
        m = compiled[i].search(value)
        if m:
            # Run validator
            validator_fn = validators[i]
            if validator_fn is not None:
                try:
                    if not validator_fn(value):
                        continue  # Validation failed, skip
                except Exception:
                    continue

            if pattern.entity_type not in found or pattern.confidence > found[pattern.entity_type]:
                found[pattern.entity_type] = pattern.confidence

    return list(found.keys())


def run_pattern_benchmark(
    samples: list[tuple[str, str | None]],
) -> tuple[dict[str, EntityResult], dict[str, PatternStats], dict[str, dict[str, int]]]:
    """Run pattern matching benchmark on raw (value, expected_type) pairs.

    Returns:
        - entity_results: per-entity-type TP/FP/FN at sample level
        - pattern_stats: per-pattern match/validation rates
        - collision_matrix: entity_type_a -> entity_type_b -> count
    """
    patterns = load_default_patterns()
    compiled = [re2.compile(p.regex) for p in patterns]
    validators = [VALIDATORS.get(p.validator) if p.validator else None for p in patterns]

    # Initialize stats
    pattern_stats: dict[str, PatternStats] = {}
    for p in patterns:
        pattern_stats[p.name] = PatternStats(name=p.name, entity_type=p.entity_type, regex=p.regex)

    entity_results: dict[str, EntityResult] = defaultdict(EntityResult)
    collision_matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for value, expected in samples:
        # Match against all patterns
        matched_types = _match_value(value, patterns, compiled, validators)

        # Track per-pattern stats for this value's expected type
        if expected is not None:
            for i, p in enumerate(patterns):
                if p.entity_type == expected:
                    pattern_stats[p.name].total_tested += 1
                    m = compiled[i].search(value)
                    if m:
                        pattern_stats[p.name].matched += 1
                        vfn = validators[i]
                        if vfn is not None:
                            try:
                                if vfn(value):
                                    pattern_stats[p.name].validated += 1
                                else:
                                    pattern_stats[p.name].validation_failed += 1
                            except Exception:
                                pattern_stats[p.name].validation_failed += 1
                        else:
                            pattern_stats[p.name].validated += 1

        # Compute TP/FP/FN
        if expected is not None:
            if expected in matched_types:
                entity_results[expected].tp += 1
            else:
                entity_results[expected].fn += 1
                if len(entity_results[expected].missed_samples) < 10:
                    entity_results[expected].missed_samples.append(value)

        # FPs: anything matched that wasn't expected
        for mt in matched_types:
            if mt != expected:
                entity_results[mt].fp += 1
                if len(entity_results[mt].fp_samples) < 10:
                    entity_results[mt].fp_samples.append((value, expected))

        # Collisions
        if len(matched_types) > 1:
            for a in matched_types:
                for b in matched_types:
                    if a != b:
                        collision_matrix[a][b] += 1

    return dict(entity_results), pattern_stats, dict(collision_matrix)


def print_report(
    samples: list[tuple[str, str | None]],
    entity_results: dict[str, EntityResult],
    pattern_stats: dict[str, PatternStats],
    collision_matrix: dict[str, dict[str, int]],
) -> None:
    """Print comprehensive pattern matching report."""
    w = 78

    # Count corpus
    positive = sum(1 for _, e in samples if e is not None)
    negative = sum(1 for _, e in samples if e is None)
    entity_types = len({e for _, e in samples if e is not None})

    print()  # noqa: T201
    print("=" * w)  # noqa: T201
    print("PATTERN MATCHING BENCHMARK (regex engine, per-sample)")  # noqa: T201
    print("=" * w)  # noqa: T201
    print()  # noqa: T201
    print("CORPUS")  # noqa: T201
    print(f"  Total samples:      {len(samples):,}")  # noqa: T201
    print(f"  Positive samples:   {positive:,} ({entity_types} entity types)")  # noqa: T201
    print(f"  Negative samples:   {negative:,}")  # noqa: T201
    print()  # noqa: T201

    # ── Sample-level accuracy ─────────────────────────────────────────────
    print("SAMPLE-LEVEL DETECTION ACCURACY")  # noqa: T201
    print("-" * w)  # noqa: T201
    header = f"{'Entity Type':<22} {'TP':>6} {'FP':>6} {'FN':>6} {'Prec':>8} {'Recall':>8} {'F1':>8}"
    print(header)  # noqa: T201
    print("-" * w)  # noqa: T201

    total_tp = total_fp = total_fn = 0
    for et in sorted(entity_results.keys()):
        r = entity_results[et]
        total_tp += r.tp
        total_fp += r.fp
        total_fn += r.fn
        print(  # noqa: T201
            f"{et:<22} {r.tp:>6} {r.fp:>6} {r.fn:>6} {r.precision:>8.3f} {r.recall:>8.3f} {r.f1:>8.3f}"
        )

    overall_p = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    overall_r = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    overall_f1 = 2 * overall_p * overall_r / (overall_p + overall_r) if (overall_p + overall_r) > 0 else 0.0

    print("-" * w)  # noqa: T201
    print(  # noqa: T201
        f"{'OVERALL':<22} {total_tp:>6} {total_fp:>6} {total_fn:>6}"
        f" {overall_p:>8.3f} {overall_r:>8.3f} {overall_f1:>8.3f}"
    )
    print()  # noqa: T201

    # ── Per-pattern stats ─────────────────────────────────────────────────
    active_patterns = {name: ps for name, ps in pattern_stats.items() if ps.total_tested > 0}
    if active_patterns:
        print("PER-PATTERN MATCH RATES (patterns with test data)")  # noqa: T201
        print("-" * w)  # noqa: T201
        print(  # noqa: T201
            f"  {'Pattern':<30} {'Entity':<18} {'Matched':>10} {'Valid':>10} {'ValFail':>10}"
        )
        print(f"  {'-' * 30} {'-' * 18} {'-' * 10} {'-' * 10} {'-' * 10}")  # noqa: T201
        for name in sorted(active_patterns.keys()):
            ps = active_patterns[name]
            pct = f"({ps.match_rate:.0%})" if ps.total_tested > 0 else ""
            print(  # noqa: T201
                f"  {ps.name:<30} {ps.entity_type:<18}"
                f" {ps.matched:>6}{pct:>4}"
                f" {ps.validated:>10} {ps.validation_failed:>10}"
            )
        print()  # noqa: T201

    # ── Collisions ────────────────────────────────────────────────────────
    if collision_matrix:
        print("CROSS-PATTERN COLLISIONS (same value triggers multiple entity types)")  # noqa: T201
        print("-" * w)  # noqa: T201
        for a in sorted(collision_matrix.keys()):
            for b in sorted(collision_matrix[a].keys()):
                count = collision_matrix[a][b]
                print(f"  {a:<22} also triggers {b:<22} ({count:,} samples)")  # noqa: T201
        print()  # noqa: T201

    # ── Missed samples (FN examples) ──────────────────────────────────────
    missed_types = {et: r for et, r in entity_results.items() if r.fn > 0}
    if missed_types:
        print("MISSED SAMPLES (expected match, got nothing — up to 10 per type)")  # noqa: T201
        print("-" * w)  # noqa: T201
        for et in sorted(missed_types.keys()):
            r = missed_types[et]
            print(f"  {et} ({r.fn:,} missed):")  # noqa: T201
            for v in r.missed_samples[:5]:
                display = v[:60] + "..." if len(v) > 60 else v
                print(f"    {display!r}")  # noqa: T201
        print()  # noqa: T201

    # ── FP examples ───────────────────────────────────────────────────────
    fp_types = {et: r for et, r in entity_results.items() if r.fp > 0}
    if fp_types:
        print("FALSE POSITIVE EXAMPLES (up to 5 per type)")  # noqa: T201
        print("-" * w)  # noqa: T201
        for et in sorted(fp_types.keys()):
            r = fp_types[et]
            print(f"  {et} ({r.fp:,} FPs):")  # noqa: T201
            for v, expected in r.fp_samples[:5]:
                display = v[:50] + "..." if len(v) > 50 else v
                print(f"    {display!r} (expected={expected})")  # noqa: T201
        print()  # noqa: T201

    print("=" * w)  # noqa: T201


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run pattern matching benchmark")
    parser.add_argument("--samples", type=int, default=500, help="Samples per entity type")
    args = parser.parse_args()

    from tests.benchmarks.corpus_generator import generate_raw_samples

    print(f"Generating {args.samples} samples per entity type...")  # noqa: T201
    samples = generate_raw_samples(count_per_type=args.samples)
    print(f"Total samples: {len(samples):,}")  # noqa: T201

    entity_results, pattern_stats, collision_matrix = run_pattern_benchmark(samples)
    print_report(samples, entity_results, pattern_stats, collision_matrix)
