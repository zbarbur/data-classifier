"""FormatDetector — JSON, XML, YAML, ENV detection in unfenced regions.

Runs after StructuralDetector. Receives claimed_ranges (lines already
handled by structural) and finds contiguous non-empty candidate regions
in unclaimed lines, then tries each format parser in order:
JSON → XML → YAML → ENV. First match wins.
"""

from __future__ import annotations

import json
import re

from docs.experiments.prompt_analysis.s4_zone_detection.v2.types import ZoneBlock

# ---------------------------------------------------------------------------
# Regexes
# ---------------------------------------------------------------------------

# YAML mapping line: indented-or-not key (word chars, dots, dashes) + ": " + value
_KV_PATTERN = re.compile(r"^\s*[\w_.-]+\s*:\s+\S.*$")
# YAML list item
_LIST_PATTERN = re.compile(r"^\s*-\s+.+$")
# ENV variable: UPPER_CASE key followed by =value (no leading whitespace)
_ENV_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]+=.+$")
# XML open tag: <word or <word<space
_XML_OPEN = re.compile(r"<\w+[\s>]")
# XML close tag: </word>
_XML_CLOSE = re.compile(r"</\w+>")
# Extract tag name from open tag
_XML_TAG_NAME = re.compile(r"<(\w+)[\s>]")
# Extract tag name from close tag
_XML_CLOSE_TAG_NAME = re.compile(r"</(\w+)>")


class FormatDetector:
    """Detect structured format blocks (JSON, XML, YAML, ENV) in unclaimed lines."""

    def __init__(self, patterns: dict) -> None:
        fmt = patterns.get("format", {})
        self._min_non_empty_lines: int = fmt.get("min_non_empty_lines", 5)
        self._max_blank_gap: int = fmt.get("max_blank_gap", 2)
        self._json_confidence: float = fmt.get("json_confidence", 0.90)
        self._xml_confidence: float = fmt.get("xml_confidence", 0.80)
        self._yaml_confidence: float = fmt.get("yaml_confidence", 0.80)
        self._env_confidence: float = fmt.get("env_confidence", 0.85)
        self._yaml_min_kv_lines: int = fmt.get("yaml_min_kv_lines", 3)
        self._yaml_max_key_words: int = fmt.get("yaml_max_key_words", 3)
        self._yaml_max_prose_ratio: float = fmt.get("yaml_max_prose_ratio", 0.50)
        self._xml_min_open_tags: int = fmt.get("xml_min_open_tags", 2)
        self._xml_min_close_tags: int = fmt.get("xml_min_close_tags", 1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, lines: list[str], claimed_ranges: set[int]) -> tuple[list[ZoneBlock], set[int]]:
        """Detect format zones in unclaimed lines.

        Args:
            lines: All prompt lines (0-indexed).
            claimed_ranges: Line indices already owned by StructuralDetector.

        Returns:
            blocks   — newly detected format ZoneBlocks
            claimed  — claimed_ranges union new claims from this pass
        """
        blocks: list[ZoneBlock] = []
        new_claimed = set(claimed_ranges)

        regions = self._find_candidate_regions(lines, claimed_ranges)

        for start, end in regions:
            block_lines = lines[start:end]
            block_text = "\n".join(block_lines)
            non_empty = [l for l in block_lines if l.strip()]

            block: ZoneBlock | None = None

            if self._try_json(block_text):
                block = ZoneBlock(
                    start_line=start,
                    end_line=end,
                    zone_type="config",
                    confidence=self._json_confidence,
                    method="format_json",
                    language_hint="json",
                )
            elif self._looks_like_xml(block_text):
                block = ZoneBlock(
                    start_line=start,
                    end_line=end,
                    zone_type="markup",
                    confidence=self._xml_confidence,
                    method="format_xml",
                    language_hint="xml",
                )
            elif self._looks_like_yaml(non_empty):
                block = ZoneBlock(
                    start_line=start,
                    end_line=end,
                    zone_type="config",
                    confidence=self._yaml_confidence,
                    method="format_yaml",
                    language_hint="yaml",
                )
            elif self._looks_like_env(non_empty):
                block = ZoneBlock(
                    start_line=start,
                    end_line=end,
                    zone_type="config",
                    confidence=self._env_confidence,
                    method="format_env",
                    language_hint="env",
                )

            if block is not None:
                blocks.append(block)
                new_claimed.update(range(start, end))

        return blocks, new_claimed

    # ------------------------------------------------------------------
    # Region finding
    # ------------------------------------------------------------------

    def _find_candidate_regions(self, lines: list[str], claimed_ranges: set[int]) -> list[tuple[int, int]]:
        """Find contiguous non-empty regions in unclaimed lines.

        Allows up to max_blank_gap consecutive blank lines within a region.
        Only regions with >= min_non_empty_lines non-empty lines are returned.
        For regions smaller than min_non_empty_lines, still include them if
        they are >= 2 non-empty lines (compact format files like small .env
        or XML fragments are valid targets for format detection).

        Returns list of (start, end) tuples (end is exclusive).
        """
        regions: list[tuple[int, int]] = []
        n = len(lines)
        i = 0

        while i < n:
            # Skip claimed or blank lines to find region start
            if i in claimed_ranges or not lines[i].strip():
                i += 1
                continue

            # We found an unclaimed non-empty line — start a region
            region_start = i
            j = i
            blank_streak = 0

            while j < n:
                if j in claimed_ranges:
                    # Hit a claimed line — stop region
                    break

                if lines[j].strip():
                    blank_streak = 0
                    j += 1
                else:
                    blank_streak += 1
                    if blank_streak > self._max_blank_gap:
                        # Too many blanks in a row — end region before the blanks
                        j = j - blank_streak + 1
                        break
                    j += 1

            # Trim trailing blank lines from region
            region_end = j
            while region_end > region_start and not lines[region_end - 1].strip():
                region_end -= 1

            # Count non-empty lines in region
            non_empty_count = sum(1 for l in lines[region_start:region_end] if l.strip())

            # Include regions with >= 2 non-empty lines; min_non_empty_lines is
            # the preferred threshold for large blocks but compact format files
            # (ENV, XML snippets) may be shorter.
            if non_empty_count >= 2:
                regions.append((region_start, region_end))

            i = j if j > i else i + 1

        return regions

    # ------------------------------------------------------------------
    # Format parsers
    # ------------------------------------------------------------------

    def _try_json(self, text: str) -> bool:
        """Return True if text is valid JSON object or array. Strict."""
        text = text.strip()
        if not text:
            return False
        if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")):
            try:
                json.loads(text)
                return True
            except (json.JSONDecodeError, ValueError):
                return False
        return False

    def _looks_like_xml(self, text: str) -> bool:
        """Return True if text contains matched XML/HTML open+close tag pairs.

        v2 tightening over v1: requires >=xml_min_open_tags open tags AND
        >=xml_min_close_tags close tags AND at least one matching tag name
        (case-insensitive). This prevents NL instructions like
        '<CLAIM> followed by <MEASURE>' from triggering.
        """
        text = text.strip()
        open_tags = _XML_OPEN.findall(text)
        close_tags = _XML_CLOSE.findall(text)

        if len(open_tags) < self._xml_min_open_tags:
            return False
        if len(close_tags) < self._xml_min_close_tags:
            return False

        # Require at least one matched pair (open tag name appears in a close tag)
        open_names = {m.lower() for m in _XML_TAG_NAME.findall(text)}
        close_names = {m.lower() for m in _XML_CLOSE_TAG_NAME.findall(text)}
        return bool(open_names & close_names)

    def _looks_like_yaml(self, lines: list[str]) -> bool:
        """Return True if lines look like YAML (mapping lines, not just bullets).

        Rules:
        - Requires >= yaml_min_kv_lines (3) key: value mapping lines.
        - Rejects if >yaml_max_prose_ratio (50%) of non-empty lines are prose
          (alpha ratio > 0.85).
        - Rejects if >50% of matching key parts have >yaml_max_key_words (3) words.
        - Bullet-only blocks are markdown, not YAML.
        """
        kv_lines = sum(1 for l in lines if _KV_PATTERN.match(l))
        list_lines = sum(1 for l in lines if _LIST_PATTERN.match(l))
        non_empty = [l for l in lines if l.strip()]
        non_empty_count = len(non_empty)

        if kv_lines < self._yaml_min_kv_lines:
            return False

        # Reject blocks that are mostly prose sentences
        prose_lines = sum(
            1 for l in non_empty if sum(c.isalpha() or c.isspace() for c in l.strip()) / max(len(l.strip()), 1) > 0.85
        )
        if prose_lines / max(non_empty_count, 1) > self._yaml_max_prose_ratio:
            return False

        # Reject blocks where most "keys" are long multi-word phrases
        long_key_count = 0
        for l in lines:
            m = re.match(r"^(\s*)(.*?)\s*:\s+\S", l)
            if m:
                key = m.group(2).strip()
                if len(key.split()) > self._yaml_max_key_words:
                    long_key_count += 1
        if long_key_count > kv_lines * 0.5:
            return False

        yaml_lines = kv_lines + list_lines
        return yaml_lines / max(non_empty_count, 1) > 0.5

    def _looks_like_env(self, lines: list[str]) -> bool:
        """Return True if lines look like a .env / KEY=VALUE file.

        Requires: >= 2 matching lines AND > 50% of non-empty lines match.
        """
        non_empty = [l for l in lines if l.strip()]
        env_matches = sum(1 for l in non_empty if _ENV_PATTERN.match(l.strip()))
        return env_matches >= 2 and env_matches / max(len(non_empty), 1) > 0.5
