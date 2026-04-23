"""Tests for BlockAssembler — block grouping, gap bridging, bracket validation."""

from docs.experiments.prompt_analysis.s4_zone_detection.v2.assembler import BlockAssembler
from docs.experiments.prompt_analysis.s4_zone_detection.v2.config import load_zone_patterns
from docs.experiments.prompt_analysis.s4_zone_detection.v2.types import ZoneConfig


def _make_assembler(**cfg_kwargs):
    return BlockAssembler(load_zone_patterns(), ZoneConfig(**cfg_kwargs))


class TestGapBridging:
    def test_bridge_single_blank_line(self):
        lines = ["def foo():", "    x = 1", "", "    return x"]
        scores = [0.5, 0.5, 0.0, 0.5]
        line_types = [None, None, None, None]
        asm = _make_assembler(min_block_lines=3)
        blocks = asm.assemble(lines, scores, line_types)
        assert len(blocks) == 1
        assert blocks[0].start_line == 0
        assert blocks[0].end_line == 4

    def test_break_on_three_blank_lines(self):
        lines = ["x = 1", "y = 2", "", "", "", "z = 3", "w = 4"]
        scores = [0.5, 0.5, 0.0, 0.0, 0.0, 0.5, 0.5]
        line_types = [None] * 7
        asm = _make_assembler(min_block_lines=2)
        blocks = asm.assemble(lines, scores, line_types)
        assert len(blocks) == 2


class TestMinBlockLines:
    def test_small_block_discarded(self):
        lines = ["x = 1", "y = 2", "z = 3"]
        scores = [0.5, 0.5, 0.5]
        line_types = [None, None, None]
        asm = _make_assembler(min_block_lines=8)
        blocks = asm.assemble(lines, scores, line_types)
        assert len(blocks) == 0

    def test_large_block_kept(self):
        lines = [f"x_{i} = {i}" for i in range(10)]
        scores = [0.5] * 10
        line_types = [None] * 10
        asm = _make_assembler(min_block_lines=8)
        blocks = asm.assemble(lines, scores, line_types)
        assert len(blocks) == 1


class TestBracketValidation:
    def test_balanced_brackets(self):
        lines = ["config = {", '    "host": "localhost",', '    "port": 8080', "}"]
        scores = [0.5, 0.3, 0.3, 0.3]
        line_types = [None, None, None, None]
        asm = _make_assembler(min_block_lines=3)
        blocks = asm.assemble(lines, scores, line_types)
        assert len(blocks) == 1


class TestRepetitiveStructure:
    def test_repetitive_prefix_detected(self):
        asm = _make_assembler()
        lines = [
            "npm ERR! code ERESOLVE",
            "npm ERR! ERESOLVE unable to resolve",
            "npm ERR! Found: react@18.2.0",
            "npm ERR! Could not resolve dependency",
        ]
        prefix = asm.detect_repetitive_structure(lines)
        assert prefix is not None
        assert "npm" in prefix.lower()

    def test_no_repetition_in_code(self):
        asm = _make_assembler()
        lines = [
            "def foo():",
            "    x = bar(1)",
            "    y = baz(x)",
            "    return x + y",
        ]
        prefix = asm.detect_repetitive_structure(lines)
        assert prefix is None


class TestErrorOutputRetype:
    def test_error_lines_become_error_output_block(self):
        lines = [
            "Traceback (most recent call last):",
            '  File "app.py", line 5, in <module>',
            "    result = process(data)",
            "TypeError: unsupported operand type",
        ]
        scores = [0.0, 0.0, 0.0, 0.0]
        line_types = ["error_output", "error_output", "error_output", "error_output"]
        asm = _make_assembler(min_block_lines=3)
        blocks = asm.assemble(lines, scores, line_types)
        error_blocks = [b for b in blocks if b.zone_type == "error_output"]
        assert len(error_blocks) == 1
