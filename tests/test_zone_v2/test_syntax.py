"""Tests for SyntaxDetector — line scoring, fragment matching, context window."""
from docs.experiments.prompt_analysis.s4_zone_detection.v2.syntax import SyntaxDetector
from docs.experiments.prompt_analysis.s4_zone_detection.v2.config import load_zone_patterns


def _make_detector():
    return SyntaxDetector(load_zone_patterns())


class TestLineSyntaxScore:
    def test_empty_line_scores_zero(self):
        det = _make_detector()
        assert det.line_syntax_score("") == 0.0
        assert det.line_syntax_score("   ") == 0.0

    def test_prose_scores_zero(self):
        det = _make_detector()
        assert det.line_syntax_score("The quick brown fox jumps over the lazy dog.") == 0.0

    def test_code_line_scores_high(self):
        det = _make_detector()
        score = det.line_syntax_score("def process(data, timeout=30):")
        assert score >= 0.4

    def test_import_statement_scores_high(self):
        det = _make_detector()
        score = det.line_syntax_score("import json")
        assert score >= 0.15

    def test_brace_line_scores(self):
        det = _make_detector()
        score = det.line_syntax_score("    if (x > 0) {")
        assert score >= 0.3


class TestFragmentMatching:
    def test_python_fragment_detected(self):
        det = _make_detector()
        score, family = det.score_with_fragments("def process(data):")
        assert score >= 0.4
        assert family == "python"

    def test_c_family_fragment_detected(self):
        det = _make_detector()
        score, family = det.score_with_fragments("public static void main(String[] args) {")
        assert score >= 0.4
        assert family == "c_family"

    def test_sql_fragment_detected(self):
        det = _make_detector()
        _, family = det.score_with_fragments("SELECT * FROM users WHERE active = true")
        assert family == "sql"

    def test_assembly_fragment_detected(self):
        det = _make_detector()
        _, family = det.score_with_fragments("    mov eax, [ebp+8]")
        assert family == "assembly"

    def test_prose_no_fragment(self):
        det = _make_detector()
        _, family = det.score_with_fragments("The weather is nice today.")
        assert family is None


class TestContextWindow:
    def test_comment_bridged_by_code_neighbors(self):
        lines = [
            "def foo():",
            "    x = 1",
            "    # this is a comment",
            "    return x",
        ]
        det = _make_detector()
        scores = det.score_lines(lines, claimed_ranges=set())
        assert scores[2] > 0

    def test_isolated_prose_stays_zero(self):
        lines = [
            "This is a normal paragraph.",
            "Nothing interesting happening.",
            "Just a plain sentence.",
        ]
        det = _make_detector()
        scores = det.score_lines(lines, claimed_ranges=set())
        assert all(s == 0.0 for s in scores)

    def test_claimed_lines_get_negative_score(self):
        lines = ["code here", "more code"]
        det = _make_detector()
        scores = det.score_lines(lines, claimed_ranges={0, 1})
        assert scores[0] < 0
        assert scores[1] < 0
