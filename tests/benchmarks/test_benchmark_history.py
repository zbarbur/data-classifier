"""Unit tests for the sprint-over-sprint benchmark history module.

Covers schema versioning, save/load round-trip, and delta computation.
Purely filesystem-unit tests — no subprocess calls into the full
consolidated benchmark.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.benchmarks.benchmark_history_io import (
    compute_delta,
    load_recent_sprints,
    save_sprint_benchmark,
)
from tests.benchmarks.schema.benchmark_history import (
    BENCHMARK_HISTORY_SCHEMA_VERSION,
    CorpusResult,
    PerfResult,
    SprintBenchmark,
    from_dict,
    to_dict,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _sample_snapshot(sprint: int, macro: float = 0.90, fp: int = 3) -> SprintBenchmark:
    return SprintBenchmark(
        sprint=sprint,
        date="2026-04-12",
        git_sha=f"abcd{sprint:03d}",
        accuracy=[
            CorpusResult(
                corpus="nemotron",
                mode="named",
                macro_f1=1.0,
                micro_f1=1.0,
                precision=1.0,
                recall=1.0,
                tp_count=13,
                fp_count=0,
                fn_count=0,
                primary_label_pct=1.0,
            ),
            CorpusResult(
                corpus="nemotron",
                mode="blind",
                macro_f1=macro,
                micro_f1=macro,
                precision=0.80,
                recall=0.92,
                tp_count=12,
                fp_count=fp,
                fn_count=1,
                primary_label_pct=0.92,
            ),
        ],
        perf=PerfResult(
            total_p50_ms=2070.0,
            total_p95_ms=2210.0,
            per_column_p50_ms=207.0,
            per_engine_times_ms={"gliner2": 204.0, "regex": 0.15},
        ),
    )


# ---------------------------------------------------------------------------
# Schema round-trip
# ---------------------------------------------------------------------------


def test_schema_version_is_one() -> None:
    assert BENCHMARK_HISTORY_SCHEMA_VERSION == 1


def test_to_from_dict_roundtrip() -> None:
    sb = _sample_snapshot(5)
    data = to_dict(sb)
    assert data["schema_version"] == 1
    restored = from_dict(data)
    assert restored.sprint == sb.sprint
    assert restored.git_sha == sb.git_sha
    assert len(restored.accuracy) == 2
    assert restored.accuracy[1].macro_f1 == pytest.approx(0.90)
    assert restored.perf is not None
    assert restored.perf.per_column_p50_ms == 207.0


def test_roundtrip_preserves_per_engine_times() -> None:
    sb = _sample_snapshot(5)
    restored = from_dict(to_dict(sb))
    assert restored.perf is not None
    assert restored.perf.per_engine_times_ms == {"gliner2": 204.0, "regex": 0.15}


def test_roundtrip_without_perf() -> None:
    sb = SprintBenchmark(
        sprint=6,
        date="2026-04-12",
        git_sha="deadbee",
        accuracy=[CorpusResult(corpus="nemotron", mode="named", macro_f1=1.0)],
        perf=None,
    )
    restored = from_dict(to_dict(sb))
    assert restored.perf is None
    assert restored.sprint == 6


def test_schema_version_mismatch_raises() -> None:
    bad = {
        "schema_version": 99,
        "sprint": 5,
        "date": "2026-04-10",
        "git_sha": "abc",
        "accuracy": [],
    }
    with pytest.raises(ValueError, match="schema version mismatch"):
        from_dict(bad)


def test_schema_version_missing_treated_as_zero() -> None:
    bad = {"sprint": 5, "date": "2026-04-10", "git_sha": "abc", "accuracy": []}
    with pytest.raises(ValueError, match="schema version mismatch"):
        from_dict(bad)


# ---------------------------------------------------------------------------
# Save / load filesystem
# ---------------------------------------------------------------------------


def test_save_writes_to_correct_path(tmp_path: Path) -> None:
    sb = _sample_snapshot(5)
    dest = save_sprint_benchmark(sb, history_dir=tmp_path)
    assert dest == tmp_path / "sprint_5.json"
    assert dest.exists()


def test_save_creates_missing_dir(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "history"
    save_sprint_benchmark(_sample_snapshot(5), history_dir=target)
    assert (target / "sprint_5.json").exists()


def test_save_produces_valid_json(tmp_path: Path) -> None:
    dest = save_sprint_benchmark(_sample_snapshot(5), history_dir=tmp_path)
    parsed = json.loads(dest.read_text())
    assert parsed["schema_version"] == 1
    assert parsed["sprint"] == 5


def test_load_missing_dir_returns_empty(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist"
    assert load_recent_sprints(history_dir=missing) == []


def test_load_empty_dir_returns_empty(tmp_path: Path) -> None:
    assert load_recent_sprints(history_dir=tmp_path) == []


def test_load_single_sprint(tmp_path: Path) -> None:
    save_sprint_benchmark(_sample_snapshot(5), history_dir=tmp_path)
    loaded = load_recent_sprints(history_dir=tmp_path)
    assert len(loaded) == 1
    assert loaded[0].sprint == 5


def test_load_returns_most_recent_n(tmp_path: Path) -> None:
    for n in range(1, 8):
        save_sprint_benchmark(_sample_snapshot(n), history_dir=tmp_path)
    loaded = load_recent_sprints(max_count=5, history_dir=tmp_path)
    assert [sb.sprint for sb in loaded] == [3, 4, 5, 6, 7]


def test_load_sorted_by_sprint_number_not_lex(tmp_path: Path) -> None:
    # sprint_10 must come after sprint_9 numerically, not lexically
    for n in [1, 2, 9, 10, 11]:
        save_sprint_benchmark(_sample_snapshot(n), history_dir=tmp_path)
    loaded = load_recent_sprints(max_count=10, history_dir=tmp_path)
    assert [sb.sprint for sb in loaded] == [1, 2, 9, 10, 11]


def test_load_skips_corrupt_files(tmp_path: Path) -> None:
    save_sprint_benchmark(_sample_snapshot(5), history_dir=tmp_path)
    (tmp_path / "sprint_6.json").write_text("{not valid json")
    loaded = load_recent_sprints(history_dir=tmp_path)
    assert len(loaded) == 1
    assert loaded[0].sprint == 5


def test_load_skips_wrong_schema_version(tmp_path: Path) -> None:
    save_sprint_benchmark(_sample_snapshot(5), history_dir=tmp_path)
    (tmp_path / "sprint_9.json").write_text(
        json.dumps({"schema_version": 99, "sprint": 9, "date": "x", "git_sha": "y"})
    )
    loaded = load_recent_sprints(history_dir=tmp_path)
    assert [sb.sprint for sb in loaded] == [5]


# ---------------------------------------------------------------------------
# Delta computation
# ---------------------------------------------------------------------------


def test_compute_delta_none_previous_returns_empty() -> None:
    sb = _sample_snapshot(5)
    assert compute_delta(sb, None) == {}


def test_compute_delta_identical_returns_zeros() -> None:
    sb_a = _sample_snapshot(5)
    sb_b = _sample_snapshot(6)
    delta = compute_delta(sb_b, sb_a)
    blind = delta["accuracy"][("nemotron", "blind")]
    assert blind["macro_f1"] == 0.0
    assert blind["precision"] == 0.0
    assert blind["recall"] == 0.0
    assert blind["fp_count"] == 0
    assert blind["fn_count"] == 0


def test_compute_delta_positive_improvement() -> None:
    prev = _sample_snapshot(5, macro=0.80, fp=5)
    cur = _sample_snapshot(6, macro=0.90, fp=2)
    delta = compute_delta(cur, prev)
    d = delta["accuracy"][("nemotron", "blind")]
    assert d["macro_f1"] == pytest.approx(0.10)
    assert d["fp_count"] == -3  # fewer FPs is better


def test_compute_delta_regression() -> None:
    prev = _sample_snapshot(5, macro=0.90, fp=1)
    cur = _sample_snapshot(6, macro=0.85, fp=4)
    delta = compute_delta(cur, prev)
    d = delta["accuracy"][("nemotron", "blind")]
    assert d["macro_f1"] == pytest.approx(-0.05)
    assert d["fp_count"] == 3


def test_compute_delta_skips_missing_previous_key() -> None:
    prev = SprintBenchmark(
        sprint=5,
        date="2026-04-10",
        git_sha="a",
        accuracy=[CorpusResult(corpus="nemotron", mode="named", macro_f1=1.0)],
    )
    cur = _sample_snapshot(6)  # has both named + blind
    delta = compute_delta(cur, prev)
    # blind had no previous — should not appear
    assert ("nemotron", "blind") not in delta["accuracy"]
    assert ("nemotron", "named") in delta["accuracy"]


def test_compute_delta_perf_section() -> None:
    prev = _sample_snapshot(5)
    cur = _sample_snapshot(6)
    assert cur.perf is not None
    cur.perf.per_column_p50_ms = 195.0
    cur.perf.total_p50_ms = 1950.0
    delta = compute_delta(cur, prev)
    assert delta["perf"]["per_column_p50_ms"] == pytest.approx(-12.0)
    assert delta["perf"]["total_p50_ms"] == pytest.approx(-120.0)


def test_compute_delta_no_perf_returns_empty_perf() -> None:
    prev = _sample_snapshot(5)
    prev.perf = None
    cur = _sample_snapshot(6)
    delta = compute_delta(cur, prev)
    assert delta["perf"] == {}


@pytest.mark.parametrize(
    "macro_prev,macro_cur,expected",
    [
        (0.800, 0.900, 0.1),
        (0.900, 0.800, -0.1),
        (0.500, 0.500, 0.0),
        (1.000, 0.999, -0.001),
    ],
)
def test_compute_delta_macro_f1_parameterized(macro_prev: float, macro_cur: float, expected: float) -> None:
    prev = _sample_snapshot(5, macro=macro_prev)
    cur = _sample_snapshot(6, macro=macro_cur)
    d = compute_delta(cur, prev)["accuracy"][("nemotron", "blind")]
    assert d["macro_f1"] == pytest.approx(expected, abs=1e-4)


# ---------------------------------------------------------------------------
# Sprint 5 backfill sanity
# ---------------------------------------------------------------------------


def test_sprint_5_backfill_exists_and_loads() -> None:
    """The hand-written Sprint 5 backfill should parse with the current schema."""
    path = Path(__file__).resolve().parents[2] / "docs" / "benchmarks" / "history" / "sprint_5.json"
    assert path.exists(), "Sprint 5 backfill must be committed"
    data = json.loads(path.read_text())
    sb = from_dict(data)
    assert sb.sprint == 5
    assert sb.schema_version == 1
    assert len(sb.accuracy) == 4
    by_key = {(r.corpus, r.mode): r for r in sb.accuracy}
    assert by_key[("nemotron", "blind")].tp_count == 12
    assert by_key[("ai4privacy", "blind")].fp_count == 2
