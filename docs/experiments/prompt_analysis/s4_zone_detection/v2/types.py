"""Zone detection data structures."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

ZONE_TYPES = (
    "code",
    "markup",
    "config",
    "query",
    "cli_shell",
    "data",
    "error_output",
    "natural_language",
)


@dataclass
class ZoneBlock:
    """A single detected zone within a prompt."""

    start_line: int  # 0-indexed inclusive
    end_line: int  # 0-indexed exclusive
    zone_type: str  # one of ZONE_TYPES
    confidence: float  # 0.0-1.0
    method: str  # detection method name
    language_hint: str = ""
    language_confidence: float = 0.0
    text: str = ""


@dataclass
class PromptZones:
    """Result of zone detection on a prompt."""

    prompt_id: str
    total_lines: int
    blocks: list[ZoneBlock] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "prompt_id": self.prompt_id,
            "total_lines": self.total_lines,
            "blocks": [asdict(b) for b in self.blocks],
        }
        for b in d["blocks"]:
            del b["text"]
        return d


@dataclass
class ZoneConfig:
    """Configuration for zone detection."""

    sensitivity: str = "balanced"
    enabled_types: list[str] = field(
        default_factory=lambda: ["code", "markup", "config", "query", "cli_shell", "data", "error_output"]
    )
    min_block_lines: int = 8
    min_confidence: float = 0.50
    structural_enabled: bool = True
    format_enabled: bool = True
    syntax_enabled: bool = True
    negative_filter_enabled: bool = True
    parse_validation_enabled: bool = True
    language_detection_enabled: bool = True
    context_window: int = 3
    pre_screen_enabled: bool = True
    max_parse_attempts: int = 10
    weight_overrides: dict = field(default_factory=dict)
