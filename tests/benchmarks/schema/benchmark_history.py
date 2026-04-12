"""Versioned schema for per-sprint benchmark history artifacts.

This module defines the dataclasses that are serialized to
``docs/benchmarks/history/sprint_{N}.json``. The ``schema_version`` field
lets us migrate older snapshots forward without breaking the consolidated
report.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

BENCHMARK_HISTORY_SCHEMA_VERSION = 1


@dataclass
class CorpusResult:
    """Accuracy metrics for one (corpus, mode) benchmark run."""

    corpus: str  # "nemotron" | "ai4privacy"
    mode: str  # "named" | "blind"
    macro_f1: float
    micro_f1: float | None = None
    precision: float = 0.0
    recall: float = 0.0
    tp_count: int = 0
    fp_count: int = 0
    fn_count: int = 0
    primary_label_pct: float | None = None


@dataclass
class PerfResult:
    """Performance metrics from the quick perf benchmark."""

    total_p50_ms: float
    total_p95_ms: float | None = None
    per_column_p50_ms: float = 0.0
    per_sample_p50_ms: float | None = None
    throughput_cols_per_sec: float | None = None
    per_engine_times_ms: dict[str, float] = field(default_factory=dict)


@dataclass
class SprintBenchmark:
    """Full per-sprint benchmark snapshot."""

    sprint: int
    date: str  # ISO-8601
    git_sha: str
    accuracy: list[CorpusResult]
    perf: PerfResult | None = None
    schema_version: int = BENCHMARK_HISTORY_SCHEMA_VERSION
    note: str | None = None  # optional, e.g. "stubbed — benchmark infra unavailable"


def to_dict(sb: SprintBenchmark) -> dict:
    """Serialize a SprintBenchmark to a plain dict for JSON encoding."""
    return asdict(sb)


def from_dict(data: dict) -> SprintBenchmark:
    """Load a benchmark snapshot from dict, validating schema version."""
    version = data.get("schema_version", 0)
    if version != BENCHMARK_HISTORY_SCHEMA_VERSION:
        raise ValueError(
            f"benchmark history schema version mismatch: got {version}, expected {BENCHMARK_HISTORY_SCHEMA_VERSION}"
        )
    return SprintBenchmark(
        sprint=data["sprint"],
        date=data["date"],
        git_sha=data["git_sha"],
        accuracy=[CorpusResult(**r) for r in data.get("accuracy", [])],
        perf=PerfResult(**data["perf"]) if data.get("perf") else None,
        note=data.get("note"),
    )
