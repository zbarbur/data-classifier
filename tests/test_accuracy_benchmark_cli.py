"""Smoke tests for the accuracy_benchmark CLI argparse surface.

Guards against Sprint 11 regressions where newly-added corpora
(Gretel-finance in particular) ship as loader code but never get wired
into the CLI ``--corpus`` choices list.
"""

from __future__ import annotations

import pytest


def test_corpus_flag_accepts_gretel_finance() -> None:
    """``gretel_finance`` must be a discrete ``--corpus`` choice."""
    from tests.benchmarks.accuracy_benchmark import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["--corpus", "gretel_finance", "--samples", "1"])
    assert args.corpus == "gretel_finance"


def test_corpus_flag_rejects_unknown_source() -> None:
    """Sanity: unknown corpus source still fails at parse time."""
    from tests.benchmarks.accuracy_benchmark import _build_parser

    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--corpus", "definitely_not_a_real_corpus"])


def test_corpus_flag_preserves_sprint10_choices() -> None:
    """Invariant: pre-existing corpus choices don't silently disappear."""
    from tests.benchmarks.accuracy_benchmark import _build_parser

    parser = _build_parser()
    corpus_action = next(action for action in parser._actions if getattr(action, "dest", None) == "corpus")
    assert corpus_action.choices is not None
    assert set(corpus_action.choices) >= {
        "synthetic",
        "nemotron",
        "gretel_en",
        "gretel_finance",
        "all",
    }
