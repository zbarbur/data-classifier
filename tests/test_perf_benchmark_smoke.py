"""Smoke test for ``tests.benchmarks.perf_benchmark --quick``.

The legacy perf_benchmark.py had hardcoded inner loops (``range(50)`` on
phase 2, ``range(20)`` on phase 5) that ignored the ``--iterations``
CLI flag, so even ``--samples 5 --iterations 2`` stalled past 10 CPU
minutes. Sprint 9's retro-fit gated those loops on ``--iterations`` and
added a ``--quick`` mode that drops phases 6 + 7.

This smoke test runs ``--quick`` as a subprocess and asserts the wall
time stays under 90 seconds. It is explicitly NOT a performance
benchmark — it only guards against the previous pathological regression
where a flag change silently fell back to a 10-minute run.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

PERF_SMOKE_WALL_CLOCK_BUDGET_SECONDS = 90.0

REPO_ROOT = Path(__file__).resolve().parents[1]


def _resolve_python() -> str:
    """Prefer the worktree/repo venv when present, otherwise fall back.

    The CLAUDE.md rule ``feedback_verify_venv_before_trusting_tests``
    reminds us to pin to ``.venv/bin/python`` — but this smoke test also
    needs to work under the GitHub Actions runner where the venv lives
    elsewhere. ``sys.executable`` is a safe fallback because the test
    process is itself already pinned by pytest's launcher.
    """
    local_venv = REPO_ROOT / ".venv" / "bin" / "python"
    if local_venv.exists():
        return str(local_venv)
    return sys.executable


def test_perf_benchmark_quick_mode_finishes_under_budget() -> None:
    """``perf_benchmark --quick`` must finish in <90s with small flags.

    The command under test is the one documented in the Sprint 9 backlog
    item's DoD gates:

        python -m tests.benchmarks.perf_benchmark \
            --iterations 2 --samples 5 --quick

    Pre-Sprint-9 this would hit the hardcoded phase-2/phase-5 loops and
    stall for >10 minutes. Post-Sprint-9 it should finish in ~20-30s on
    a warm laptop, comfortably under the 90s budget.
    """
    python_exe = _resolve_python()
    env = os.environ.copy()
    # Propagate HF cache if set so the test doesn't re-download ~250MB.
    env.setdefault("HF_HOME", os.path.expanduser("~/.cache/huggingface"))

    cmd = [
        python_exe,
        "-m",
        "tests.benchmarks.perf_benchmark",
        "--iterations",
        "2",
        "--samples",
        "5",
        "--quick",
    ]

    start = time.perf_counter()
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=PERF_SMOKE_WALL_CLOCK_BUDGET_SECONDS + 30,
            cwd=str(REPO_ROOT),
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(
            f"perf_benchmark --quick hung past "
            f"{PERF_SMOKE_WALL_CLOCK_BUDGET_SECONDS + 30:.0f}s — the "
            f"Sprint 8 regression (hardcoded phase-2/5 loops) may have "
            f"returned. stdout tail: {exc.stdout[-500:] if exc.stdout else '(empty)'}"
        )
    elapsed = time.perf_counter() - start

    if completed.returncode != 0:
        pytest.fail(
            f"perf_benchmark --quick exited with code {completed.returncode}.\n"
            f"stdout tail: {completed.stdout[-1000:]}\n"
            f"stderr tail: {completed.stderr[-1000:]}"
        )

    # Report a line for humans reading pytest -v output.
    print(f"perf_benchmark --quick wall time: {elapsed:.2f}s")

    assert elapsed < PERF_SMOKE_WALL_CLOCK_BUDGET_SECONDS, (
        f"perf_benchmark --quick took {elapsed:.2f}s "
        f"(budget: {PERF_SMOKE_WALL_CLOCK_BUDGET_SECONDS:.0f}s). "
        f"Check for a new hardcoded loop that ignores --iterations."
    )

    # Sanity-check the report text actually made it out — catches the
    # case where the process exits 0 but emits nothing.
    assert "PERFORMANCE BENCHMARK REPORT" in completed.stdout, (
        f"perf_benchmark --quick completed without emitting its report header; stdout tail: {completed.stdout[-500:]}"
    )
