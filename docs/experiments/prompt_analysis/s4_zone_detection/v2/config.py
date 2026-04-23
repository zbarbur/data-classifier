"""Load zone detection patterns and configuration."""

from __future__ import annotations

import json
from pathlib import Path

from docs.experiments.prompt_analysis.s4_zone_detection.v2.types import ZoneConfig

_PATTERNS_PATH = Path(__file__).parent / "patterns" / "zone_patterns.json"
_cached_patterns: dict | None = None


def load_zone_patterns() -> dict:
    """Load the shared zone patterns configuration."""
    global _cached_patterns
    if _cached_patterns is None:
        with open(_PATTERNS_PATH) as f:
            _cached_patterns = json.load(f)
    return _cached_patterns


def apply_preset(config: ZoneConfig) -> ZoneConfig:
    """Apply sensitivity preset to config thresholds."""
    presets = {
        "high_recall": {"min_block_lines": 3, "min_confidence": 0.40, "parse_validation_enabled": False},
        "balanced": {"min_block_lines": 8, "min_confidence": 0.50, "parse_validation_enabled": True},
        "high_precision": {"min_block_lines": 10, "min_confidence": 0.65, "parse_validation_enabled": True},
    }
    preset = presets.get(config.sensitivity, presets["balanced"])
    for k, v in preset.items():
        setattr(config, k, v)
    return config
