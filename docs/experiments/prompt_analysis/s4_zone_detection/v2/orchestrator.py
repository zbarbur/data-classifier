"""ZoneOrchestrator — wires all detectors into a cascade pipeline.

This is the single entry point for zone detection. External consumers
interact only with this class (or the convenience wrapper ``detect_zones``
in ``__init__.py``).

Pipeline order:
    1. Empty / pre-screen fast path
    2. StructuralDetector   → fenced blocks, delimiter pairs  → claimed_ranges
    3. FormatDetector        → JSON/XML/YAML/ENV on unclaimed → claimed_ranges
    4. SyntaxDetector        → per-line scores (unclaimed)
    4.5 ScopeTracker          → bracket continuation + indentation scope
    5. NegativeFilter        → per-line suppression / retype   → filtered scores
    6. BlockAssembler        → group scored lines into blocks
    7. LanguageDetector      → enrich blocks with language info
    8. Merge, sort, filter by min_confidence
"""

from __future__ import annotations

from docs.experiments.prompt_analysis.s4_zone_detection.v2.assembler import BlockAssembler
from docs.experiments.prompt_analysis.s4_zone_detection.v2.config import apply_preset, load_zone_patterns
from docs.experiments.prompt_analysis.s4_zone_detection.v2.format_detector import FormatDetector
from docs.experiments.prompt_analysis.s4_zone_detection.v2.language import LanguageDetector
from docs.experiments.prompt_analysis.s4_zone_detection.v2.negative import NegativeFilter
from docs.experiments.prompt_analysis.s4_zone_detection.v2.pre_screen import pre_screen
from docs.experiments.prompt_analysis.s4_zone_detection.v2.scope import ScopeTracker
from docs.experiments.prompt_analysis.s4_zone_detection.v2.structural import StructuralDetector
from docs.experiments.prompt_analysis.s4_zone_detection.v2.syntax import SyntaxDetector
from docs.experiments.prompt_analysis.s4_zone_detection.v2.types import PromptZones, ZoneBlock, ZoneConfig


class ZoneOrchestrator:
    """Cascade pipeline that wires all zone detectors together."""

    def __init__(self, config: ZoneConfig | None = None) -> None:
        self._config = config if config is not None else ZoneConfig()

        # Snapshot fields that the caller may have set explicitly.
        # apply_preset unconditionally overwrites min_block_lines,
        # min_confidence, and parse_validation_enabled — we need to
        # restore any caller-provided values afterward.
        defaults = ZoneConfig()
        caller_overrides: dict[str, object] = {}
        for field_name in ("min_block_lines", "min_confidence", "parse_validation_enabled"):
            user_val = getattr(self._config, field_name)
            if user_val != getattr(defaults, field_name):
                caller_overrides[field_name] = user_val

        apply_preset(self._config)

        # Restore explicit caller overrides that the preset would have clobbered.
        for k, v in caller_overrides.items():
            setattr(self._config, k, v)

        patterns = load_zone_patterns()
        self._structural = StructuralDetector(patterns)
        self._format = FormatDetector(patterns)
        self._syntax = SyntaxDetector(patterns)
        self._negative = NegativeFilter(patterns)
        self._assembler = BlockAssembler(patterns, self._config)
        self._language = LanguageDetector(patterns)
        self._scope = ScopeTracker(patterns)

    def detect_zones(self, text: str, prompt_id: str = "") -> PromptZones:
        """Run the full detection pipeline on *text*.

        Returns a PromptZones result with all detected blocks sorted by
        start_line and filtered by min_confidence.
        """
        # 1. Handle empty input
        if not text or not text.strip():
            return PromptZones(prompt_id=prompt_id, total_lines=0)

        lines = text.split("\n")
        total_lines = len(lines)

        # 2. Pre-screen fast path
        if self._config.pre_screen_enabled and not pre_screen(text):
            return PromptZones(prompt_id=prompt_id, total_lines=total_lines)

        # 3. Structural detection (fenced blocks + delimiter pairs)
        struct_blocks: list[ZoneBlock] = []
        claimed_ranges: set[int] = set()
        if self._config.structural_enabled:
            struct_blocks, claimed_ranges = self._structural.detect(lines)

        # 4. Format detection on unclaimed lines
        format_blocks: list[ZoneBlock] = []
        if self._config.format_enabled:
            format_blocks, claimed_ranges = self._format.detect(lines, claimed_ranges)

        # 5. Syntax scoring (claimed lines get -1.0)
        scores = self._syntax.score_lines(lines, claimed_ranges) if self._config.syntax_enabled else [0.0] * total_lines

        # 5.5. Scope tracking (bracket continuation + indentation scope)
        scores = self._scope.adjust_scores(lines, scores, claimed_ranges)

        # 6. Negative filter on unclaimed lines
        line_types: list[str | None] = [None] * total_lines
        if self._config.negative_filter_enabled:
            for i in range(total_lines):
                if i in claimed_ranges:
                    continue
                result = self._negative.check_line(lines[i])
                if result == "error_output":
                    line_types[i] = "error_output"
                    scores[i] = 0.0
                elif result == "suppress":
                    scores[i] = 0.0

            # Absorb lines sandwiched between error_output lines into the
            # error block.  Tracebacks interleave "File ..." (error_output)
            # with indented context lines (scored as code); without this
            # pass the assembler sees rapid type transitions and fragments
            # the block below min_block_lines.
            self._absorb_error_interior(line_types, scores, claimed_ranges, total_lines)

            # List prefix check on all unclaimed lines
            unclaimed_lines = [lines[i] for i in range(total_lines) if i not in claimed_ranges]
            if self._negative.check_list_prefix(unclaimed_lines):
                for i in range(total_lines):
                    if i not in claimed_ranges and scores[i] > 0:
                        scores[i] = 0.0

        # 7. Block assembly from scores + line_types
        syntax_blocks = self._assembler.assemble(lines, scores, line_types) if self._config.syntax_enabled else []

        # 8. Language detection enrichment
        if self._config.language_detection_enabled:
            for block in syntax_blocks:
                block_lines = lines[block.start_line : block.end_line]
                hits = self._syntax.fragment_hits_for_block(block_lines)
                lang, lang_conf, _dist = self._language.detect_language(block_lines, hits)
                block.language_hint = lang
                block.language_confidence = lang_conf

        # 9. Merge all blocks, sort, filter
        all_blocks = struct_blocks + format_blocks + syntax_blocks
        all_blocks.sort(key=lambda b: b.start_line)
        all_blocks = [b for b in all_blocks if b.confidence >= self._config.min_confidence]

        # 10. Merge adjacent compatible blocks.
        # Adjacent code + error_output is one zone (error output
        # accompanies code — stack traces, compilation errors).
        # Adjacent same-type blocks with small gaps are one zone.
        all_blocks = self._merge_adjacent(all_blocks, lines)

        return PromptZones(
            prompt_id=prompt_id,
            total_lines=total_lines,
            blocks=all_blocks,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    _COMPATIBLE_TYPES = {
        frozenset({"code", "error_output"}),  # error output accompanies code
    }

    @staticmethod
    def _merge_adjacent(blocks: list[ZoneBlock], lines: list[str]) -> list[ZoneBlock]:
        """Merge adjacent blocks of compatible types.

        Two blocks are merged when they are the same type, or when
        their types form a compatible pair (e.g. code + error_output).
        """
        if len(blocks) < 2:
            return blocks

        merged: list[ZoneBlock] = [blocks[0]]
        for b in blocks[1:]:
            prev = merged[-1]
            same = prev.zone_type == b.zone_type
            compatible = frozenset({prev.zone_type, b.zone_type}) in ZoneOrchestrator._COMPATIBLE_TYPES
            adjacent = b.start_line <= prev.end_line + 1

            if adjacent and (same or compatible):
                prev.end_line = max(prev.end_line, b.end_line)
                prev.confidence = max(prev.confidence, b.confidence)
                prev.text = "\n".join(lines[prev.start_line : prev.end_line])
            else:
                merged.append(b)

        return merged

    @staticmethod
    def _absorb_error_interior(
        line_types: list[str | None],
        scores: list[float],
        claimed_ranges: set[int],
        total_lines: int,
    ) -> None:
        """Reclassify unclaimed lines between error_output lines as error_output.

        Tracebacks alternate between ``File "..."`` lines (tagged
        error_output by NegativeFilter) and indented context lines that
        look like code.  Without this pass, the assembler sees rapid
        code/error_output transitions that fragment the block below
        min_block_lines.
        """
        for i in range(total_lines):
            if i in claimed_ranges or line_types[i] is not None:
                continue
            # Look for an error_output neighbour above and below
            has_error_above = False
            for j in range(i - 1, -1, -1):
                if j in claimed_ranges:
                    break
                if line_types[j] == "error_output":
                    has_error_above = True
                    break
                if line_types[j] is None and scores[j] <= 0:
                    break  # gap — stop looking
            has_error_below = False
            for j in range(i + 1, total_lines):
                if j in claimed_ranges:
                    break
                if line_types[j] == "error_output":
                    has_error_below = True
                    break
                if line_types[j] is None and scores[j] <= 0:
                    break
            if has_error_above and has_error_below:
                line_types[i] = "error_output"
                scores[i] = 0.0
