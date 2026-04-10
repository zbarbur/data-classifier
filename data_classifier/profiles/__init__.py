"""Bundled classification profiles.

The library ships with a ``standard`` profile.  Connectors can load
their own profiles from YAML files or dicts.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from data_classifier.core.types import (
    ClassificationProfile,
    ClassificationRule,
)

_PROFILES_DIR = Path(__file__).parent
_BUNDLED_YAML = _PROFILES_DIR / "standard.yaml"


def _parse_rules(raw_rules: list[dict]) -> list[ClassificationRule]:
    """Parse rule dicts into ClassificationRule objects."""
    return [
        ClassificationRule(
            entity_type=r["entity_type"],
            category=r.get("category", ""),
            sensitivity=r["sensitivity"],
            regulatory=list(r.get("regulatory", [])),
            confidence=float(r["confidence"]),
            patterns=list(r.get("patterns", [])),
        )
        for r in raw_rules
    ]


def load_profile_from_yaml(profile_name: str, yaml_path: str | Path) -> ClassificationProfile:
    """Load a named classification profile from a YAML file.

    Args:
        profile_name: Key under ``profiles:`` in the YAML file.
        yaml_path: Path to the YAML file.

    Raises:
        ValueError: If ``profile_name`` is not found.
        FileNotFoundError: If the YAML file does not exist.
    """
    with open(yaml_path) as fh:
        data = yaml.safe_load(fh)
    return load_profile_from_dict(profile_name, data)


def load_profile_from_dict(profile_name: str, data: dict) -> ClassificationProfile:
    """Load a named classification profile from an already-parsed dict.

    Args:
        profile_name: Key under ``profiles:`` in the data.
        data: Parsed YAML/JSON structure with a ``profiles`` key.

    Raises:
        ValueError: If ``profile_name`` is not found.
    """
    profiles = data.get("profiles", {})
    if profile_name not in profiles:
        available = list(profiles.keys())
        raise ValueError(f"Classification profile '{profile_name}' not found. Available: {available}")

    raw = profiles[profile_name]
    return ClassificationProfile(
        name=profile_name,
        description=raw.get("description", ""),
        rules=_parse_rules(raw.get("rules", [])),
    )


def load_profile(profile_name: str = "standard") -> ClassificationProfile:
    """Load a profile from the library's bundled profiles.

    The library ships with a ``standard`` profile.  This function loads
    it from the package's bundled YAML — no file path needed.

    Connectors that store profiles in a database should implement their
    own ``load_profile()`` that tries DB first, then falls back to this.

    Args:
        profile_name: Name of the bundled profile (default: ``standard``).

    Raises:
        ValueError: If ``profile_name`` is not found in the bundled YAML.
    """
    return load_profile_from_yaml(profile_name, _BUNDLED_YAML)
