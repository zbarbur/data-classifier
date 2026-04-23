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


class TestSemanticModifier:
    """Test that tokenizer-based semantic modifier adjusts scores correctly."""

    def test_prose_suppressed(self):
        """Midjourney template: indented prose with 'for' keyword should score low."""
        det = _make_detector()
        score = det.line_syntax_score(
            "                            As a prompt generator for a generative AI called Midjourney you will create image prompts"
        )
        assert score < 0.15, f"Prose with indentation should be suppressed, got {score}"

    def test_code_with_operators_preserved(self):
        """Real code line should not be suppressed by modifier."""
        det = _make_detector()
        score = det.line_syntax_score("result = process(data, timeout=30)")
        assert score >= 0.3, f"Code with assignment+operators should score high, got {score}"

    def test_dot_access_boosted(self):
        """Method calls with dot access should get boosted."""
        det = _make_detector()
        score = det.line_syntax_score("self.data.items.append(val)")
        assert score >= 0.3, f"Dot access chain should score high, got {score}"

    def test_json_data_suppressed(self):
        """JSON key-value pairs should be suppressed."""
        det = _make_detector()
        score = det.line_syntax_score('"host": "localhost",')
        assert score < 0.15, f"JSON data should be suppressed, got {score}"

    def test_non_latin_parens_suppressed(self):
        """Non-Latin text with parens (Japanese glossary pattern) should be suppressed."""
        det = _make_detector()
        score = det.line_syntax_score("乍ら (ながら)")
        assert score < 0.15, f"Non-Latin with parens should be suppressed, got {score}"

    def test_number_list_suppressed(self):
        """Pure number lists should not score as code."""
        det = _make_detector()
        score = det.line_syntax_score("1.5, 2.3, 4.8, 9.1")
        assert score < 0.15, f"Number list should be suppressed, got {score}"


class TestExpressionAdjustment:
    def test_function_call_gets_boost(self):
        """Bare function call (ident + parens, no operator) should still score."""
        det = _make_detector()
        score = det.line_syntax_score("print(data)")
        assert score >= 0.15, f"Function call should get expression boost, got {score}"


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
