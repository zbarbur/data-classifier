"""Tests for zone detection data structures."""
from docs.experiments.prompt_analysis.s4_zone_detection.v2.types import (
    ZONE_TYPES,
    PromptZones,
    ZoneBlock,
    ZoneConfig,
)


def test_zone_types_has_eight_entries():
    assert len(ZONE_TYPES) == 8
    assert "code" in ZONE_TYPES
    assert "error_output" in ZONE_TYPES
    assert "natural_language" in ZONE_TYPES


def test_zone_block_construction():
    b = ZoneBlock(start_line=0, end_line=10, zone_type="code", confidence=0.85, method="syntax_score")
    assert b.start_line == 0
    assert b.end_line == 10
    assert b.zone_type == "code"
    assert b.language_hint == ""
    assert b.language_confidence == 0.0


def test_prompt_zones_to_dict_strips_text():
    b = ZoneBlock(
        start_line=0, end_line=5, zone_type="code",
        confidence=0.9, method="fenced", text="def foo():\n    pass"
    )
    pz = PromptZones(prompt_id="test1", total_lines=10, blocks=[b])
    d = pz.to_dict()
    assert "text" not in d["blocks"][0]
    assert d["blocks"][0]["zone_type"] == "code"


def test_zone_config_defaults():
    cfg = ZoneConfig()
    assert cfg.sensitivity == "balanced"
    assert cfg.min_block_lines == 8
    assert cfg.min_confidence == 0.50
    assert cfg.context_window == 3
    assert cfg.structural_enabled is True


def test_zone_config_preset_high_precision():
    cfg = ZoneConfig(sensitivity="high_precision")
    assert cfg.min_confidence == 0.50  # preset applied by config loader, not dataclass
