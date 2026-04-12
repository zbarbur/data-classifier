"""Persistence and delta helpers for sprint benchmark history.

Each sprint run writes a versioned JSON artifact to
``docs/benchmarks/history/sprint_{N}.json``. The consolidated report loads
the most recent N sprints to render trend charts and a delta column
showing ``current - previous`` for key metrics.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.benchmarks.schema.benchmark_history import (
    SprintBenchmark,
    from_dict,
    to_dict,
)

_HISTORY_DIR = Path(__file__).resolve().parents[2] / "docs" / "benchmarks" / "history"


def history_dir() -> Path:
    """Return the default history directory (repo-relative)."""
    return _HISTORY_DIR


def save_sprint_benchmark(sb: SprintBenchmark, *, history_dir: Path | None = None) -> Path:
    """Persist a sprint benchmark snapshot as JSON.

    The filename is ``sprint_{N}.json`` so older sprints sort naturally and
    the artifact can be read back deterministically.
    """
    dest = (history_dir or _HISTORY_DIR) / f"sprint_{sb.sprint}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(to_dict(sb), indent=2, sort_keys=True) + "\n")
    return dest


def load_recent_sprints(max_count: int = 5, *, history_dir: Path | None = None) -> list[SprintBenchmark]:
    """Load the most recent ``max_count`` sprint JSONs, sorted by sprint asc.

    Missing directory or unparseable files are tolerated — the latter are
    skipped so a single corrupt snapshot does not break the report.
    """
    directory = history_dir or _HISTORY_DIR
    if not directory.exists():
        return []
    files = sorted(
        directory.glob("sprint_*.json"),
        key=lambda p: _sprint_num_from_path(p),
    )
    loaded: list[SprintBenchmark] = []
    for f in files[-max_count:]:
        try:
            loaded.append(from_dict(json.loads(f.read_text())))
        except (ValueError, KeyError, json.JSONDecodeError):
            continue
    return loaded


def _sprint_num_from_path(p: Path) -> int:
    """Extract the integer sprint number from ``sprint_{N}.json``."""
    stem = p.stem  # "sprint_5"
    try:
        return int(stem.split("_")[-1])
    except (ValueError, IndexError):
        return -1


def compute_delta(current: SprintBenchmark, previous: SprintBenchmark | None) -> dict:
    """Compute per-(corpus, mode) deltas between current and previous sprint.

    Returns a dict with two keys:
      - ``accuracy``: ``{(corpus, mode): {metric: delta_value, ...}, ...}``
      - ``perf``: ``{metric: delta_value, ...}``

    Both may be empty. When ``previous`` is ``None``, an empty dict is
    returned so the consolidated report can detect "no prior data".
    """
    if previous is None:
        return {}
    prev_by_key = {(r.corpus, r.mode): r for r in previous.accuracy}
    deltas: dict[tuple[str, str], dict[str, float]] = {}
    for cur in current.accuracy:
        prev = prev_by_key.get((cur.corpus, cur.mode))
        if prev is None:
            continue
        deltas[(cur.corpus, cur.mode)] = {
            "macro_f1": round(cur.macro_f1 - prev.macro_f1, 4),
            "precision": round(cur.precision - prev.precision, 4),
            "recall": round(cur.recall - prev.recall, 4),
            "fp_count": cur.fp_count - prev.fp_count,
            "fn_count": cur.fn_count - prev.fn_count,
        }
    perf_delta: dict[str, float] = {}
    if current.perf and previous.perf:
        perf_delta["per_column_p50_ms"] = round(current.perf.per_column_p50_ms - previous.perf.per_column_p50_ms, 2)
        perf_delta["total_p50_ms"] = round(current.perf.total_p50_ms - previous.perf.total_p50_ms, 2)
    return {"accuracy": deltas, "perf": perf_delta}
