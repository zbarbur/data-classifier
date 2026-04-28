"""Tests for NegativeFilter — FP suppression signals."""

from docs.experiments.prompt_analysis.s4_zone_detection.v2.config import load_zone_patterns
from docs.experiments.prompt_analysis.s4_zone_detection.v2.negative import NegativeFilter


def _make_filter():
    return NegativeFilter(load_zone_patterns())


class TestErrorOutput:
    def test_python_traceback(self):
        nf = _make_filter()
        assert nf.check_line("Traceback (most recent call last):") == "error_output"

    def test_python_file_line(self):
        nf = _make_filter()
        assert nf.check_line('  File "/app/server.py", line 42, in handle_request') == "error_output"

    def test_java_stack_frame(self):
        nf = _make_filter()
        assert nf.check_line("    at com.foo.Bar.process(Bar.java:42)") == "error_output"

    def test_npm_error(self):
        nf = _make_filter()
        assert nf.check_line("npm ERR! code ERESOLVE") == "error_output"

    def test_rust_compiler_error(self):
        nf = _make_filter()
        assert nf.check_line("error[E0382]: borrow of moved value") == "error_output"

    def test_timestamp_log(self):
        nf = _make_filter()
        assert nf.check_line("2024-01-15T10:30:00 ERROR connection refused") == "error_output"

    def test_code_line_not_error(self):
        nf = _make_filter()
        assert nf.check_line("result = process(data)") is None


class TestDialogPatterns:
    def test_dialog_line(self):
        nf = _make_filter()
        assert nf.check_line('Monika: "I know, I know. But I thought it would be nice..."') == "suppress"

    def test_dialog_without_quotes(self):
        nf = _make_filter()
        assert nf.check_line("Natsuki: I don't know what you mean by that.") == "suppress"


class TestMathPatterns:
    def test_latex(self):
        nf = _make_filter()
        assert nf.check_line("\\frac{1}{2} + \\int_0^1 x dx") == "suppress"

    def test_probability_notation(self):
        nf = _make_filter()
        assert nf.check_line("Prob[X > 0] = 0.5") == "suppress"


class TestRatioPatterns:
    def test_aspect_ratio(self):
        nf = _make_filter()
        assert nf.check_line("4:3 is best for portrait images") == "suppress"

    def test_time_ratio(self):
        nf = _make_filter()
        assert nf.check_line("10:30 AM meeting tomorrow") == "suppress"


class TestProsePattern:
    def test_prose_sentence(self):
        nf = _make_filter()
        assert nf.check_line("The algorithm processes each element in the list.") == "suppress"

    def test_code_not_prose(self):
        nf = _make_filter()
        assert nf.check_line("    result = algorithm.process(elements)") is None


class TestListPrefix:
    def test_list_detected(self):
        nf = _make_filter()
        lines = [
            "1. First item in the list",
            "2. Second item here",
            "3. Third item here",
            "4. Fourth item",
        ]
        assert nf.check_list_prefix(lines) is True

    def test_code_not_list(self):
        nf = _make_filter()
        lines = [
            "def foo():",
            "    x = 1",
            "    return x",
        ]
        assert nf.check_list_prefix(lines) is False
