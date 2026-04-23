"""Zone Detector v2 — multi-detector cascade architecture."""

from __future__ import annotations

from docs.experiments.prompt_analysis.s4_zone_detection.v2.types import (
    ZONE_TYPES,
    PromptZones,
    ZoneBlock,
    ZoneConfig,
)

__all__ = ["ZONE_TYPES", "ZoneBlock", "PromptZones", "ZoneConfig", "detect_zones"]

from docs.experiments.prompt_analysis.s4_zone_detection.v2.orchestrator import ZoneOrchestrator

_orchestrator: ZoneOrchestrator | None = None


def detect_zones(text: str, prompt_id: str = "", config: ZoneConfig | None = None) -> PromptZones:
    """Detect zones in text -- convenience wrapper with singleton orchestrator."""
    global _orchestrator
    if _orchestrator is None or config is not None:
        _orchestrator = ZoneOrchestrator(config)
    return _orchestrator.detect_zones(text, prompt_id=prompt_id)
