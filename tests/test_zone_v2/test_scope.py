"""Tests for ScopeTracker — bracket continuation and indentation scope."""

from docs.experiments.prompt_analysis.s4_zone_detection.v2.config import load_zone_patterns
from docs.experiments.prompt_analysis.s4_zone_detection.v2.scope import ScopeTracker


def _make_tracker():
    return ScopeTracker(load_zone_patterns())


class TestBracketContinuation:
    def test_multiline_function_call(self):
        """Lines inside unclosed parens should inherit parent score."""
        lines = [
            "result = process(",
            "    data,",
            "    timeout=30,",
            "    retries=3,",
            ")",
        ]
        scores = [0.5, 0.0, 0.0, 0.0, 0.3]
        tracker = _make_tracker()
        adjusted = tracker.adjust_scores(lines, scores, claimed_ranges=set())
        assert adjusted[1] > 0.0
        assert adjusted[2] > 0.0
        assert adjusted[3] > 0.0

    def test_no_continuation_without_open_bracket(self):
        """Zero-scored lines without open brackets should stay zero."""
        lines = ["x = 1", "hello world", "y = 2"]
        scores = [0.5, 0.0, 0.5]
        tracker = _make_tracker()
        adjusted = tracker.adjust_scores(lines, scores, claimed_ranges=set())
        assert adjusted[1] == 0.0

    def test_brackets_in_strings_ignored(self):
        """Brackets inside quotes should not count."""
        lines = [
            'msg = "no open paren here ("',
            "next_line",
        ]
        scores = [0.5, 0.0]
        tracker = _make_tracker()
        adjusted = tracker.adjust_scores(lines, scores, claimed_ranges=set())
        assert adjusted[1] == 0.0

    def test_claimed_ranges_reset_continuation(self):
        """Continuation should not cross claimed range boundaries."""
        lines = ["func(", "claimed_line", "orphan"]
        scores = [0.5, -1.0, 0.0]
        tracker = _make_tracker()
        adjusted = tracker.adjust_scores(lines, scores, claimed_ranges={1})
        assert adjusted[2] == 0.0


class TestIndentationScope:
    def test_python_function_body(self):
        """Lines inside a Python function (after ':') should inherit."""
        lines = [
            "def process(data):",
            "    # just a comment",
            "    return data",
        ]
        scores = [0.6, 0.0, 0.4]
        tracker = _make_tracker()
        adjusted = tracker.adjust_scores(lines, scores, claimed_ranges=set())
        assert adjusted[1] > 0.0

    def test_scope_closes_at_dedent(self):
        """When indentation returns to opener level, scope closes."""
        lines = [
            "def foo():",
            "    body_line",
            "outside",
        ]
        scores = [0.6, 0.4, 0.0]
        tracker = _make_tracker()
        adjusted = tracker.adjust_scores(lines, scores, claimed_ranges=set())
        assert adjusted[2] == 0.0

    def test_brace_scope_opener(self):
        """Lines after '{' should inherit scope."""
        lines = [
            "if (x > 0) {",
            "    // comment",
            "    return x;",
            "}",
        ]
        scores = [0.6, 0.0, 0.5, 0.3]
        tracker = _make_tracker()
        adjusted = tracker.adjust_scores(lines, scores, claimed_ranges=set())
        assert adjusted[1] > 0.0

    def test_low_parent_score_no_inherit(self):
        """Scope opener with score below threshold should not propagate."""
        lines = [
            "maybe code:",
            "    next line",
        ]
        scores = [0.15, 0.0]
        tracker = _make_tracker()
        adjusted = tracker.adjust_scores(lines, scores, claimed_ranges=set())
        assert adjusted[1] == 0.0
