"""Versioned schema for per-sprint benchmark history artifacts.

This module defines the dataclasses that are serialized to
``docs/benchmarks/history/sprint_{N}.json``. The ``schema_version`` field
lets us migrate older snapshots forward without breaking the consolidated
report.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

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


def _filter_known_fields(dc_type, payload: dict) -> dict:
    """Return a dict containing only keys that match dataclass fields.

    Older/ad-hoc snapshots may carry extra keys (e.g. ``n_columns``,
    ``method``) that the canonical schema doesn't know about. Filtering
    them out keeps the loader resilient across schema drift instead of
    raising ``TypeError: unexpected keyword argument``.
    """
    known = {f.name for f in fields(dc_type)}
    return {k: v for k, v in payload.items() if k in known}


def from_dict(data: dict) -> SprintBenchmark:
    """Load a benchmark snapshot from dict, validating schema version.

    Extra keys not present in the dataclass schema are silently ignored
    so that ad-hoc sprint snapshots (e.g. the Sprint 8 retro-fit) can
    still be consumed by the consolidated report generator.
    """
    version = data.get("schema_version", 0)
    if version != BENCHMARK_HISTORY_SCHEMA_VERSION:
        raise ValueError(
            f"benchmark history schema version mismatch: got {version}, expected {BENCHMARK_HISTORY_SCHEMA_VERSION}"
        )
    perf_payload = data.get("perf")
    perf_obj: PerfResult | None = None
    if perf_payload:
        filtered_perf = _filter_known_fields(PerfResult, perf_payload)
        # ``total_p50_ms`` is the only required perf field; if it's missing
        # (as in the Sprint 8 ad-hoc snapshot which used
        # ``full_cascade_p50_ms``), fall back to a known alternate key so
        # the perf block still loads.
        if "total_p50_ms" not in filtered_perf:
            for alt in ("full_cascade_p50_ms", "total_ms", "p50_ms"):
                if alt in perf_payload:
                    filtered_perf["total_p50_ms"] = perf_payload[alt]
                    break
        if "per_column_p50_ms" not in filtered_perf:
            for alt in ("ms_per_col_p50", "per_col_p50_ms"):
                if alt in perf_payload:
                    filtered_perf["per_column_p50_ms"] = perf_payload[alt]
                    break
        if "total_p50_ms" in filtered_perf:
            perf_obj = PerfResult(**filtered_perf)
    return SprintBenchmark(
        sprint=data["sprint"],
        date=data["date"],
        git_sha=data["git_sha"],
        accuracy=[CorpusResult(**_filter_known_fields(CorpusResult, r)) for r in data.get("accuracy", [])],
        perf=perf_obj,
        note=data.get("note"),
    )
