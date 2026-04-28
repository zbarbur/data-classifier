"""Tests for the pre-screen fast path."""

from docs.experiments.prompt_analysis.s4_zone_detection.v2.pre_screen import pre_screen


class TestPreScreenPasses:
    """These should return True — text might contain code."""

    def test_fenced_block(self):
        assert pre_screen("Hello\n```python\nprint('hi')\n```\n") is True

    def test_tilde_fence(self):
        assert pre_screen("~~~\ncode\n~~~") is True

    def test_high_syntax_density(self):
        assert pre_screen("if (x > 0) { return x; }") is True

    def test_indentation_spaces(self):
        assert pre_screen("line 1\n    indented code\nline 3") is True

    def test_indentation_tab(self):
        assert pre_screen("line 1\n\tindented code\nline 3") is True

    def test_closing_tag(self):
        assert pre_screen("<div>hello</div>") is True

    def test_braces_in_code(self):
        assert pre_screen("function foo() { return 1; }") is True


class TestPreScreenRejects:
    """These should return False — pure prose, skip pipeline."""

    def test_empty_string(self):
        assert pre_screen("") is False

    def test_pure_prose(self):
        assert pre_screen("The quick brown fox jumps over the lazy dog.") is False

    def test_prose_with_question(self):
        assert pre_screen("How do I sort a list in Python?") is False

    def test_short_prose_with_comma(self):
        assert pre_screen("Hello, world. Nice to meet you.") is False

    def test_cjk_text(self):
        assert pre_screen("今日は天気がいいですね。散歩に行きましょう。") is False

    def test_cyrillic_text(self):
        assert pre_screen("Привет, как дела? Хорошо, спасибо.") is False

    def test_whitespace_only(self):
        assert pre_screen("   \n\n   \n") is False
