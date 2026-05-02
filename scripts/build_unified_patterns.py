#!/usr/bin/env python3
"""Build unified_patterns.json -- merges zone + secret + scoring config.

Reads:
  - Zone patterns from s4_zone_detection v2 patterns
  - Secret patterns from Python source (data_classifier.patterns)
  - Secret key names from data_classifier/patterns/secret_key_names.json
  - Secret scanner config from data_classifier/config/engine_defaults.yaml
  - Stopwords from data_classifier/patterns/stopwords.json
  - Placeholder values from data_classifier/patterns/known_placeholder_values.json
  - Zone scoring rules (default config)

Outputs:
  data_classifier_core/patterns/unified_patterns.json
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

# Ensure the in-repo ``data_classifier`` package is importable.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ZONE_PATTERNS_PATH = (
    REPO_ROOT
    / "docs"
    / "experiments"
    / "prompt_analysis"
    / "s4_zone_detection"
    / "v2"
    / "patterns"
    / "zone_patterns.json"
)
OUTPUT_DIR = REPO_ROOT / "data_classifier_core" / "patterns"
OUTPUT_PATH = OUTPUT_DIR / "unified_patterns.json"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("build_unified_patterns")


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def load_zone_patterns() -> dict:
    """Load the zone detection patterns JSON."""
    return json.loads(ZONE_PATTERNS_PATH.read_text())


def load_secret_patterns() -> list[dict]:
    """Load secret patterns from Python source (same as generate_browser_patterns.py)."""
    from data_classifier.patterns import load_default_patterns

    patterns = load_default_patterns()
    out = []
    for p in patterns:
        out.append(
            {
                "name": p.name,
                "regex": p.regex,
                "entity_type": p.entity_type,
                "category": p.category,
                "sensitivity": p.sensitivity,
                "confidence": p.confidence,
                "validator": p.validator,
                "description": p.description,
                "context_words_boost": list(p.context_words_boost),
                "context_words_suppress": list(p.context_words_suppress),
                "stopwords": list(p.stopwords),
                "allowlist_patterns": list(p.allowlist_patterns),
                "display_name": p.display_name or p.name,
                "requires_column_hint": p.requires_column_hint,
                "column_hint_keywords": list(p.column_hint_keywords),
            }
        )
    return out


def load_secret_key_names() -> list[dict]:
    """Load secret key names from the curated JSON source."""
    src = REPO_ROOT / "data_classifier" / "patterns" / "secret_key_names.json"
    data = json.loads(src.read_text())
    return data["key_names"]


def load_secret_scanner_config() -> dict:
    """Load secret scanner thresholds from engine_defaults.yaml + Python constants."""
    yaml_path = REPO_ROOT / "data_classifier" / "config" / "engine_defaults.yaml"
    data = yaml.safe_load(yaml_path.read_text())
    cfg = data.get("secret_scanner", {})
    scoring = cfg.get("scoring", {})
    rel = scoring.get("relative_entropy_thresholds", {})
    tiers = scoring.get("tier_boundaries", {})
    opaque = cfg.get("opaque_token", {})

    return {
        "min_value_length": cfg.get("min_value_length", 8),
        "max_value_length": 500,
        "anti_indicators": cfg.get("anti_indicators", ["example", "test", "placeholder", "changeme"]),
        "definitive_multiplier": scoring.get("definitive_multiplier", 0.95),
        "strong_min_entropy_score": scoring.get("strong_min_entropy_score", 0.6),
        "relative_entropy_strong": rel.get("strong", 0.5),
        "relative_entropy_contextual": rel.get("contextual", 0.7),
        "diversity_threshold": scoring.get("diversity_threshold", 3),
        "evenness_weight": 0.15,
        "diversity_bonus_weight": 0.05,
        "prose_alpha_threshold": scoring.get("prose_alpha_threshold", 0.6),
        "tier_boundary_definitive": tiers.get("definitive", 0.9),
        "tier_boundary_strong": tiers.get("strong", 0.7),
        "opaque_token": {
            "min_length": opaque.get("min_length", 16),
            "max_length": 512,
            "entropy_threshold": opaque.get("entropy_threshold", 0.7),
            "diversity_threshold": opaque.get("diversity_threshold", 3),
            "base_confidence": opaque.get("base_confidence", 0.65),
            "max_confidence": opaque.get("max_confidence", 0.85),
            "high_entropy_bonus": 0.10,
            "high_entropy_gate": 0.85,
            "length_bonus": 0.05,
            "length_gate": 24,
            "diversity_bonus_weight": 0.05,
        },
        "non_secret_suffixes": [
            "_address",
            "_count",
            "_dir",
            "_endpoint",
            "_field",
            "_file",
            "_format",
            "_id",
            "_input",
            "_label",
            "_length",
            "_mode",
            "_name",
            "_path",
            "_placeholder",
            "_prefix",
            "_size",
            "_status",
            "_suffix",
            "_type",
            "_url",
        ],
        "non_secret_allowlist": ["auth_id", "client_id", "session_id"],
    }


def load_stopwords() -> list[str]:
    """Load stopwords from the curated JSON source (decoded)."""
    from data_classifier.patterns._decoder import decode_encoded_strings

    src = REPO_ROOT / "data_classifier" / "patterns" / "stopwords.json"
    raw = json.loads(src.read_text()).get("stopwords", [])
    decoded = decode_encoded_strings(raw)
    return sorted({s.lower() for s in decoded})


def load_placeholder_values() -> list[str]:
    """Load placeholder values from the curated JSON source."""
    src = REPO_ROOT / "data_classifier" / "patterns" / "known_placeholder_values.json"
    raw = json.loads(src.read_text()).get("placeholder_values", [])
    return sorted({s.lower() for s in raw})


def default_zone_scoring() -> dict:
    """Default zone scoring rules."""
    return {
        "enabled": True,
        "suppression_threshold": 0.30,
        "max_confidence": 0.99,
        "rules": [
            {"name": "code_literal_boost", "zone_type": "code", "value_context": "literal", "delta": 0.05},
            {"name": "code_expression_suppress", "zone_type": "code", "value_context": "expression", "delta": -0.20},
            {"name": "config_boost", "zone_type": "config", "value_context": "any", "delta": 0.05},
            {"name": "error_output_reduce", "zone_type": "error_output", "value_context": "any", "delta": -0.15},
            {"name": "cli_literal_keep", "zone_type": "cli_shell", "value_context": "literal", "delta": 0.0},
            {"name": "cli_reference_suppress", "zone_type": "cli_shell", "value_context": "expression", "delta": -0.25},
            {"name": "markup_reduce", "zone_type": "markup", "value_context": "any", "delta": -0.10},
            {"name": "query_reduce", "zone_type": "query", "value_context": "any", "delta": -0.05},
            {
                "name": "natural_language_reduce",
                "zone_type": "natural_language",
                "value_context": "any",
                "delta": -0.10,
            },
        ],
        "value_context_detection": {
            "literal_patterns": ["=[\\s]*[\"']", ":[\\s]*[\"']", "\\([\"']", ">[\"']"],
            "expression_patterns": [
                "^[a-zA-Z_]\\w*(?:\\.[a-zA-Z_]\\w*)+$",
                "^\\$[\\w{]",
                "^[a-zA-Z_]\\w*\\(",
                "^[a-zA-Z_]\\w*\\[",
                "^\\{\\{.*\\}\\}$",
            ],
        },
        "tier_overrides": {
            "definitive_min_confidence": 0.50,
            "strong_min_confidence": 0.35,
            "contextual_min_confidence": 0.30,
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load all sources
    log.info("Loading zone patterns from %s", ZONE_PATTERNS_PATH)
    zone = load_zone_patterns()

    log.info("Loading secret patterns from Python source")
    secret_patterns = load_secret_patterns()

    log.info("Loading secret key names")
    key_names = load_secret_key_names()

    log.info("Loading secret scanner config")
    scanner_config = load_secret_scanner_config()

    log.info("Loading stopwords")
    stopwords = load_stopwords()

    log.info("Loading placeholder values")
    placeholder_values = load_placeholder_values()

    zone_scoring = default_zone_scoring()

    # Build unified JSON: zone config as base, add secret sections
    unified = dict(zone)
    unified["secret_scanner"] = scanner_config
    unified["secret_patterns"] = secret_patterns
    unified["secret_key_names"] = key_names
    unified["stopwords"] = stopwords
    unified["placeholder_values"] = placeholder_values
    unified["zone_scoring"] = zone_scoring

    # Write output
    OUTPUT_PATH.write_text(json.dumps(unified, indent=2, ensure_ascii=False) + "\n")

    # Report
    log.info("Unified patterns written to %s", OUTPUT_PATH)
    log.info("  Zone config sections: %d", len(zone))
    log.info("  Secret patterns: %d", len(secret_patterns))
    log.info("  Secret key names: %d", len(key_names))
    log.info("  Stopwords: %d", len(stopwords))
    log.info("  Placeholder values: %d", len(placeholder_values))
    log.info("  Zone scoring rules: %d", len(zone_scoring["rules"]))

    # Validate: round-trip the output and check required keys
    reloaded = json.loads(OUTPUT_PATH.read_text())
    assert "secret_patterns" in reloaded, "missing secret_patterns"
    assert "secret_key_names" in reloaded, "missing secret_key_names"
    assert "zone_scoring" in reloaded, "missing zone_scoring"
    assert "pre_screen" in reloaded, "missing pre_screen (zone section)"
    assert "stopwords" in reloaded, "missing stopwords"
    assert "placeholder_values" in reloaded, "missing placeholder_values"
    assert "secret_scanner" in reloaded, "missing secret_scanner"
    log.info("Validation: OK")


if __name__ == "__main__":
    main()
