"""Engine configuration — loads default thresholds from YAML."""

from __future__ import annotations

from pathlib import Path

import yaml


def load_engine_config() -> dict:
    """Load engine default configuration from engine_defaults.yaml.

    Returns:
        Parsed configuration dictionary.
    """
    config_path = Path(__file__).parent / "engine_defaults.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)
