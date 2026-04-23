"""Tests for zone pattern configuration loading."""

from docs.experiments.prompt_analysis.s4_zone_detection.v2.config import apply_preset, load_zone_patterns


def test_load_zone_patterns_returns_dict():
    patterns = load_zone_patterns()
    assert isinstance(patterns, dict)
    assert patterns["version"] == "2.0.0"


def test_patterns_has_required_sections():
    patterns = load_zone_patterns()
    for section in ("pre_screen", "lang_tag_map", "structural", "format", "syntax", "negative", "assembly"):
        assert section in patterns, f"Missing section: {section}"


def test_syntax_has_code_keywords():
    patterns = load_zone_patterns()
    keywords = patterns["syntax"]["code_keywords"]
    assert "import" in keywords
    assert "def" in keywords
    assert "function" in keywords
    assert "defer" in keywords  # Go keyword
    assert len(keywords) >= 60


def test_syntax_has_fragment_patterns():
    patterns = load_zone_patterns()
    fragments = patterns["syntax"]["fragment_patterns"]
    assert "c_family" in fragments
    assert "python" in fragments
    assert "markup" in fragments
    assert "sql" in fragments
    assert "shell" in fragments
    assert "assembly" in fragments
    assert "rust" in fragments


def test_negative_has_all_signal_types():
    patterns = load_zone_patterns()
    neg = patterns["negative"]
    for signal in ("error_output", "dialog", "list_prefix", "math", "ratio", "prose"):
        assert signal in neg, f"Missing negative signal: {signal}"


def test_apply_preset_high_recall():
    from docs.experiments.prompt_analysis.s4_zone_detection.v2.types import ZoneConfig

    cfg = ZoneConfig(sensitivity="high_recall")
    cfg = apply_preset(cfg)
    assert cfg.min_block_lines == 3
    assert cfg.min_confidence == 0.40


def test_apply_preset_balanced():
    from docs.experiments.prompt_analysis.s4_zone_detection.v2.types import ZoneConfig

    cfg = ZoneConfig(sensitivity="balanced")
    cfg = apply_preset(cfg)
    assert cfg.min_block_lines == 8
    assert cfg.min_confidence == 0.50


def test_apply_preset_high_precision():
    from docs.experiments.prompt_analysis.s4_zone_detection.v2.types import ZoneConfig

    cfg = ZoneConfig(sensitivity="high_precision")
    cfg = apply_preset(cfg)
    assert cfg.min_block_lines == 10
    assert cfg.min_confidence == 0.65
