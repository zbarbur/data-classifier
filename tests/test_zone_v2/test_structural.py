"""Tests for StructuralDetector — fenced blocks and delimiter pairs."""
from docs.experiments.prompt_analysis.s4_zone_detection.v2.structural import StructuralDetector
from docs.experiments.prompt_analysis.s4_zone_detection.v2.config import load_zone_patterns


def _make_detector():
    return StructuralDetector(load_zone_patterns())


class TestFencedBlocks:
    def test_python_fenced_block(self):
        text = "Hello\n```python\ndef foo():\n    pass\n```\nBye"
        det = _make_detector()
        blocks, claimed = det.detect(text.split("\n"))
        assert len(blocks) == 1
        assert blocks[0].zone_type == "code"
        assert blocks[0].language_hint == "python"
        assert blocks[0].confidence == 0.95
        assert blocks[0].start_line == 1
        assert blocks[0].end_line == 5

    def test_json_fenced_block(self):
        text = '```json\n{"key": "value"}\n```'
        det = _make_detector()
        blocks, claimed = det.detect(text.split("\n"))
        assert blocks[0].zone_type == "config"
        assert blocks[0].language_hint == "json"

    def test_bash_fenced_block(self):
        text = "```bash\necho hello\n```"
        det = _make_detector()
        blocks, claimed = det.detect(text.split("\n"))
        assert blocks[0].zone_type == "cli_shell"
        assert blocks[0].language_hint == "bash"

    def test_untagged_code_fence(self):
        text = "```\ndef foo():\n    return 1\n```"
        det = _make_detector()
        blocks, claimed = det.detect(text.split("\n"))
        assert blocks[0].zone_type == "code"

    def test_untagged_prose_fence(self):
        text = "```\nThis is just a quoted paragraph of text.\nNothing code-like here at all.\n```"
        det = _make_detector()
        blocks, claimed = det.detect(text.split("\n"))
        assert blocks[0].zone_type == "natural_language"

    def test_tilde_fence(self):
        text = "~~~js\nconsole.log('hi')\n~~~"
        det = _make_detector()
        blocks, claimed = det.detect(text.split("\n"))
        assert len(blocks) == 1
        assert blocks[0].language_hint == "javascript"

    def test_claimed_ranges(self):
        text = "prose\n```\ncode\n```\nprose"
        det = _make_detector()
        _, claimed = det.detect(text.split("\n"))
        assert 1 in claimed
        assert 2 in claimed
        assert 3 in claimed
        assert 0 not in claimed
        assert 4 not in claimed

    def test_multiple_fenced_blocks(self):
        text = "```python\nx=1\n```\ntext\n```js\ny=2\n```"
        det = _make_detector()
        blocks, claimed = det.detect(text.split("\n"))
        assert len(blocks) == 2
        assert blocks[0].language_hint == "python"
        assert blocks[1].language_hint == "javascript"


class TestDelimiterPairs:
    def test_multiline_comment(self):
        text = "code\n/* this is\na comment */\ncode"
        det = _make_detector()
        blocks, claimed = det.detect(text.split("\n"))
        assert 1 in claimed
        assert 2 in claimed

    def test_html_comment(self):
        text = "<!-- this is\na comment -->\n<div>hi</div>"
        det = _make_detector()
        blocks, claimed = det.detect(text.split("\n"))
        assert 0 in claimed
        assert 1 in claimed

    def test_script_tag(self):
        text = "<div>\n<script>\nconst x = 1;\n</script>\n</div>"
        det = _make_detector()
        blocks, claimed = det.detect(text.split("\n"))
        script_blocks = [b for b in blocks if b.language_hint == "javascript"]
        assert len(script_blocks) == 1
        assert script_blocks[0].zone_type == "code"

    def test_unclosed_delimiter_not_claimed(self):
        text = "/* this comment never closes\nso it should not be claimed"
        det = _make_detector()
        _, claimed = det.detect(text.split("\n"))
        assert len(claimed) == 0
