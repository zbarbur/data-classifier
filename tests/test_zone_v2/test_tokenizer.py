"""Tests for lightweight tokenizer — token profile extraction."""

from docs.experiments.prompt_analysis.s4_zone_detection.v2.tokenizer import tokenize_line


class TestTokenizeEmpty:
    def test_empty_line(self):
        p = tokenize_line("")
        assert p.total_tokens == 0
        assert p.identifier_ratio == 0.0

    def test_whitespace_only(self):
        p = tokenize_line("   \t  ")
        assert p.total_tokens == 0


class TestCodeProfiles:
    def test_python_assignment(self):
        p = tokenize_line("result = process(data)")
        assert p.identifier_count >= 2
        assert p.operator_count >= 1
        assert p.identifier_ratio > 0.3

    def test_method_call_with_dot(self):
        p = tokenize_line("obj.method(arg, flag=True)")
        assert p.dot_access_count >= 1
        assert p.identifier_count >= 1

    def test_chained_dot_access(self):
        p = tokenize_line("self.data.items.append(val)")
        assert p.dot_access_count >= 2

    def test_keywords_separated(self):
        kws = frozenset(["import", "from"])
        p = tokenize_line("from pathlib import Path", keywords=kws)
        assert p.keyword_count == 2
        assert p.identifier_count >= 1  # pathlib, Path

    def test_string_in_code(self):
        p = tokenize_line('name = "hello"')
        assert p.string_count >= 1
        assert p.operator_count >= 1
        assert p.identifier_count >= 1


class TestProseProfiles:
    def test_english_sentence(self):
        p = tokenize_line("The quick brown fox jumps over the lazy dog")
        assert p.operator_count == 0
        assert p.dot_access_count == 0
        assert p.string_count == 0
        assert p.identifier_count > 0  # English words match as identifiers

    def test_no_operators_in_prose(self):
        p = tokenize_line("This is a completely normal sentence about nothing in particular")
        assert p.operator_count == 0
        assert p.dot_access_count == 0


class TestDataProfiles:
    def test_json_kv_pair(self):
        p = tokenize_line('"host": "localhost",')
        assert p.string_count >= 2
        assert p.string_ratio > 0.4

    def test_number_list(self):
        p = tokenize_line("1.5, 2.3, 4.8, 9.1")
        assert p.number_count >= 3
        assert p.identifier_count == 0

    def test_hex_number(self):
        p = tokenize_line("color = 0xFF00AA")
        assert p.number_count >= 1


class TestEdgeCases:
    def test_escaped_string(self):
        p = tokenize_line(r'path = "C:\\Users\\test"')
        assert p.string_count >= 1

    def test_non_latin_text(self):
        """Non-Latin text should have zero identifiers."""
        p = tokenize_line("Это обычный текст на русском языке")
        assert p.identifier_count == 0
        assert p.keyword_count == 0

    def test_mixed_non_latin_with_code(self):
        """Code identifiers in non-Latin context should still be found."""
        p = tokenize_line("obj.method() を呼び出す")
        assert p.dot_access_count >= 1
        assert p.identifier_count >= 1
