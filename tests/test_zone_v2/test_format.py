"""Tests for FormatDetector — structured format detection."""
from docs.experiments.prompt_analysis.s4_zone_detection.v2.format_detector import FormatDetector
from docs.experiments.prompt_analysis.s4_zone_detection.v2.config import load_zone_patterns


def _make_detector():
    return FormatDetector(load_zone_patterns())


class TestJsonDetection:
    def test_valid_json_object(self):
        lines = ['', '  {', '    "name": "test",', '    "value": 42,', '    "active": true', '  }', '']
        det = _make_detector()
        blocks, claimed = det.detect(lines, claimed_ranges=set())
        assert len(blocks) == 1
        assert blocks[0].zone_type == "config"
        assert blocks[0].language_hint == "json"
        assert blocks[0].confidence == 0.90

    def test_invalid_json_not_detected(self):
        lines = ['{partial json', 'not closed']
        det = _make_detector()
        blocks, _ = det.detect(lines, claimed_ranges=set())
        assert len(blocks) == 0


class TestXmlDetection:
    def test_html_with_matched_tags(self):
        lines = ['<div class="app">', '  <h1>Title</h1>', '  <p>Content</p>', '</div>']
        det = _make_detector()
        blocks, _ = det.detect(lines, claimed_ranges=set())
        assert len(blocks) == 1
        assert blocks[0].zone_type == "markup"

    def test_angle_brackets_without_matched_tags_rejected(self):
        """v2 fix: NL instructions with <CLAIM> should NOT trigger XML detection."""
        lines = [
            'Format your output as: <CLAIM> followed by <MEASURE>',
            'Make sure each claim is backed by evidence.',
            'Use the format <CLAIM>: <MEASURE> for each point.',
        ]
        det = _make_detector()
        blocks, _ = det.detect(lines, claimed_ranges=set())
        assert len(blocks) == 0


class TestYamlDetection:
    def test_yaml_key_value_pairs(self):
        lines = ['name: test-app', 'version: 1.0.0', 'port: 8080', 'debug: true', 'timeout: 30']
        det = _make_detector()
        blocks, _ = det.detect(lines, claimed_ranges=set())
        assert len(blocks) == 1
        assert blocks[0].zone_type == "config"
        assert blocks[0].language_hint == "yaml"

    def test_bullet_list_not_yaml(self):
        """Bullet-only lists are markdown, not YAML."""
        lines = ['- First item in the list', '- Second item here', '- Third item here']
        det = _make_detector()
        blocks, _ = det.detect(lines, claimed_ranges=set())
        assert len(blocks) == 0


class TestEnvDetection:
    def test_env_file(self):
        lines = ['DATABASE_URL=postgres://localhost/db', 'API_KEY=sk_test_12345', 'DEBUG=true']
        det = _make_detector()
        blocks, _ = det.detect(lines, claimed_ranges=set())
        assert len(blocks) == 1
        assert blocks[0].zone_type == "config"
        assert blocks[0].language_hint == "env"


class TestClaimedRangesRespected:
    def test_skips_claimed_lines(self):
        lines = ['  {', '    "key": "value"', '  }']
        det = _make_detector()
        blocks, _ = det.detect(lines, claimed_ranges={0, 1, 2})
        assert len(blocks) == 0
