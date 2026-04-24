"""Zone Detector v2 — Rust-backed detection via data_classifier_core.

All detection logic lives in the Rust crate `data_classifier_core`.
This module provides the Python-facing API with the same types.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from docs.experiments.prompt_analysis.s4_zone_detection.v2.types import (
    ZONE_TYPES,
    PromptZones,
    ZoneBlock,
    ZoneConfig,
)

__all__ = ["ZONE_TYPES", "ZoneBlock", "PromptZones", "ZoneConfig", "detect_zones"]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load patterns and initialize the Rust detector once on import
# ---------------------------------------------------------------------------

_PATTERNS_PATH = Path(__file__).parent / "patterns" / "zone_patterns.json"

try:
    from data_classifier_core import ZoneDetector as _RustDetector

    with open(_PATTERNS_PATH) as _f:
        _patterns_json = _f.read()
    _rust_detector = _RustDetector(_patterns_json)
    _USE_RUST = True
    logger.debug("zone_detector: using Rust backend (data_classifier_core)")
except ImportError:
    _rust_detector = None
    _USE_RUST = False
    logger.warning(
        "zone_detector: Rust backend not available, falling back to Python. "
        "Install with: cd data_classifier_core && maturin develop --release"
    )


def detect_zones(text: str, prompt_id: str = "", config: ZoneConfig | None = None) -> PromptZones:
    """Detect zones in text. Uses Rust backend when available."""
    if _USE_RUST and config is None:
        return _detect_rust(text, prompt_id)
    return _detect_python(text, prompt_id, config)


def _detect_rust(text: str, prompt_id: str) -> PromptZones:
    """Route through the Rust detector."""
    result = _rust_detector.detect_zones(text, prompt_id)
    return PromptZones(
        prompt_id=result.prompt_id,
        total_lines=result.total_lines,
        blocks=[
            ZoneBlock(
                start_line=b.start_line,
                end_line=b.end_line,
                zone_type=b.zone_type,
                confidence=b.confidence,
                method=b.method,
                language_hint=b.language_hint,
                language_confidence=b.language_confidence,
                text=b.text,
            )
            for b in result.blocks
        ],
    )


def _detect_python(text: str, prompt_id: str, config: ZoneConfig | None) -> PromptZones:
    """Fallback: use the Python orchestrator (for custom configs or when Rust is unavailable)."""
    from docs.experiments.prompt_analysis.s4_zone_detection.v2.orchestrator import ZoneOrchestrator

    orchestrator = ZoneOrchestrator(config)
    return orchestrator.detect_zones(text, prompt_id=prompt_id)
