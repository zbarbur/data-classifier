"""StructuralDetector — fenced blocks and delimiter pairs.

Runs first in the pipeline. Claims line ranges for ``` / ~~~ fenced blocks
and delimiter pairs (/* */, <!-- -->, <script>, <style>).  Claimed ranges
are passed to FormatDetector and SyntaxDetector so they skip already-handled
lines.
"""

from __future__ import annotations

import re

from docs.experiments.prompt_analysis.s4_zone_detection.v2.types import ZoneBlock

# ---------------------------------------------------------------------------
# Interior-classification helpers (used for untagged fences)
# ---------------------------------------------------------------------------

_CODE_KEYWORDS = re.compile(
    r"\b(?:import|from|def|class|function|return|if|else|for|while|try|except|catch|"
    r"var|let|const|public|private|static|void|int|struct|enum|fn|match)\b"
)

_SYNTACTIC_CHARS = re.compile(r"[{}()\[\];=<>|&!@#$^*/\\~]")

# Open-fence pattern: ```, ~~~, optional language tag at end of line
_FENCE_OPEN = re.compile(r"^(`{3,}|~{3,})\s*(\w[\w.-]*)?\s*$")
# Close-fence pattern: only the fence chars (no tag)
_FENCE_CLOSE = re.compile(r"^(`{3,}|~{3,})\s*$")


def _classify_interior(inner_lines: list[str]) -> str:
    """Classify untagged fence interior as 'natural_language' or 'code'."""
    non_empty = [l for l in inner_lines if l.strip()]
    if not non_empty:
        return "code"

    alpha_ratios = [
        sum(c.isalpha() or c.isspace() for c in l) / max(len(l), 1)
        for l in non_empty
    ]
    avg_alpha = sum(alpha_ratios) / len(alpha_ratios)

    kw_hits = sum(1 for l in non_empty if _CODE_KEYWORDS.search(l))
    syn_hits = sum(
        1 for l in non_empty
        if len(_SYNTACTIC_CHARS.findall(l)) / max(len(l), 1) > 0.05
    )

    if avg_alpha > 0.80 and kw_hits == 0 and syn_hits < len(non_empty) * 0.2:
        return "natural_language"
    return "code"


class StructuralDetector:
    """Detect ``` / ~~~ fenced blocks and delimiter pairs (/* */, <!-- -->, <script>, <style>)."""

    def __init__(self, patterns: dict) -> None:
        self._lang_tag_map: dict[str, dict] = patterns.get("lang_tag_map", {})
        structural = patterns.get("structural", {})
        self._fenced_confidence: float = structural.get("fenced_confidence", 0.95)
        self._delimiter_confidence: float = structural.get("delimiter_confidence", 0.90)
        self._delimiter_pairs: list[dict] = structural.get("delimiter_pairs", [])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, lines: list[str]) -> tuple[list[ZoneBlock], set[int]]:
        """Detect structural zones in *lines*.

        Returns:
            blocks   — list of ZoneBlock (fenced + delimiter pair blocks)
            claimed  — set of 0-indexed line numbers covered by any block
        """
        blocks: list[ZoneBlock] = []
        claimed: set[int] = set()

        fenced_blocks = self._detect_fenced(lines)
        blocks.extend(fenced_blocks)
        fenced_ranges: set[int] = set()
        for b in fenced_blocks:
            for idx in range(b.start_line, b.end_line):
                fenced_ranges.add(idx)
        claimed.update(fenced_ranges)

        delim_blocks = self._detect_delimiters(lines, fenced_ranges)
        blocks.extend(delim_blocks)
        for b in delim_blocks:
            for idx in range(b.start_line, b.end_line):
                claimed.add(idx)

        return blocks, claimed

    # ------------------------------------------------------------------
    # Fenced block detection
    # ------------------------------------------------------------------

    def _detect_fenced(self, lines: list[str]) -> list[ZoneBlock]:
        """Detect ``` and ~~~ fenced blocks."""
        blocks: list[ZoneBlock] = []
        i = 0
        while i < len(lines):
            m = _FENCE_OPEN.match(lines[i].strip())
            if not m:
                i += 1
                continue

            fence_char = m.group(1)[0]       # '`' or '~'
            fence_len = len(m.group(1))
            raw_tag = (m.group(2) or "").lower()
            start = i

            # Find matching closing fence (same char type, >= same length)
            j = i + 1
            while j < len(lines):
                cm = _FENCE_CLOSE.match(lines[j].strip())
                if cm and cm.group(1)[0] == fence_char and len(cm.group(1)) >= fence_len:
                    break
                j += 1
            # j points to closing fence or end-of-lines
            end = min(j + 1, len(lines))

            # Determine zone type and language hint
            if raw_tag:
                entry = self._lang_tag_map.get(raw_tag)
                if entry:
                    zone_type = entry["type"]
                    language_hint = entry["lang"] if entry["lang"] else raw_tag
                else:
                    # Unknown tag — treat as code
                    zone_type = "code"
                    language_hint = raw_tag
            else:
                # No tag — classify interior
                interior = lines[start + 1 : end - 1]
                zone_type = _classify_interior(interior)
                language_hint = ""

            blocks.append(
                ZoneBlock(
                    start_line=start,
                    end_line=end,
                    zone_type=zone_type,
                    confidence=self._fenced_confidence,
                    method="structural_fence",
                    language_hint=language_hint,
                )
            )
            i = end

        return blocks

    # ------------------------------------------------------------------
    # Delimiter pair detection
    # ------------------------------------------------------------------

    def _detect_delimiters(self, lines: list[str], fenced_ranges: set[int]) -> list[ZoneBlock]:
        """Scan for delimiter pairs: /* */, <!-- -->, <script>, <style>.

        Unclosed delimiters are NOT claimed.
        Lines already in fenced_ranges are skipped.
        """
        blocks: list[ZoneBlock] = []
        text = "\n".join(lines)

        # Build a map from character offset to line number for cheap lookup
        offset_to_line: list[int] = []
        for lineno, line in enumerate(lines):
            for _ in line:
                offset_to_line.append(lineno)
            offset_to_line.append(lineno)  # account for '\n' separator

        def char_to_line(offset: int) -> int:
            if offset >= len(offset_to_line):
                return len(lines) - 1
            return offset_to_line[offset]

        # ----------------------------------------------------------------
        # /* ... */
        # ----------------------------------------------------------------
        for m_open in re.finditer(r"/\*", text):
            start_off = m_open.start()
            start_line = char_to_line(start_off)
            if start_line in fenced_ranges:
                continue
            m_close = re.search(r"\*/", text[m_open.end():])
            if not m_close:
                continue
            close_off = m_open.end() + m_close.end()
            end_line = char_to_line(close_off - 1) + 1  # exclusive

            # Skip if any interior line is already fenced
            if any(ln in fenced_ranges for ln in range(start_line, end_line)):
                continue

            blocks.append(
                ZoneBlock(
                    start_line=start_line,
                    end_line=end_line,
                    zone_type="natural_language",  # comment interior — no structural re-label
                    confidence=self._delimiter_confidence,
                    method="structural_delimiter",
                    language_hint="",
                )
            )
            # Register the claimed range so later patterns skip it
            claimed_this = set(range(start_line, end_line))
            fenced_ranges = fenced_ranges | claimed_this

        # ----------------------------------------------------------------
        # <!-- ... -->
        # ----------------------------------------------------------------
        for m_open in re.finditer(r"<!--", text):
            start_off = m_open.start()
            start_line = char_to_line(start_off)
            if start_line in fenced_ranges:
                continue
            m_close = re.search(r"-->", text[m_open.end():])
            if not m_close:
                continue
            close_off = m_open.end() + m_close.end()
            end_line = char_to_line(close_off - 1) + 1

            if any(ln in fenced_ranges for ln in range(start_line, end_line)):
                continue

            blocks.append(
                ZoneBlock(
                    start_line=start_line,
                    end_line=end_line,
                    zone_type="markup",
                    confidence=self._delimiter_confidence,
                    method="structural_delimiter",
                    language_hint="",
                )
            )
            fenced_ranges = fenced_ranges | set(range(start_line, end_line))

        # ----------------------------------------------------------------
        # <script ...> ... </script>
        # ----------------------------------------------------------------
        for m_open in re.finditer(r"<script(?:\s[^>]*)?>", text, re.IGNORECASE):
            start_off = m_open.start()
            start_line = char_to_line(start_off)
            if start_line in fenced_ranges:
                continue
            m_close = re.search(r"</script>", text[m_open.end():], re.IGNORECASE)
            if not m_close:
                continue
            close_off = m_open.end() + m_close.end()
            end_line = char_to_line(close_off - 1) + 1

            if any(ln in fenced_ranges for ln in range(start_line, end_line)):
                continue

            blocks.append(
                ZoneBlock(
                    start_line=start_line,
                    end_line=end_line,
                    zone_type="code",
                    confidence=self._delimiter_confidence,
                    method="structural_delimiter",
                    language_hint="javascript",
                )
            )
            fenced_ranges = fenced_ranges | set(range(start_line, end_line))

        # ----------------------------------------------------------------
        # <style ...> ... </style>
        # ----------------------------------------------------------------
        for m_open in re.finditer(r"<style(?:\s[^>]*)?>", text, re.IGNORECASE):
            start_off = m_open.start()
            start_line = char_to_line(start_off)
            if start_line in fenced_ranges:
                continue
            m_close = re.search(r"</style>", text[m_open.end():], re.IGNORECASE)
            if not m_close:
                continue
            close_off = m_open.end() + m_close.end()
            end_line = char_to_line(close_off - 1) + 1

            if any(ln in fenced_ranges for ln in range(start_line, end_line)):
                continue

            blocks.append(
                ZoneBlock(
                    start_line=start_line,
                    end_line=end_line,
                    zone_type="code",
                    confidence=self._delimiter_confidence,
                    method="structural_delimiter",
                    language_hint="css",
                )
            )
            fenced_ranges = fenced_ranges | set(range(start_line, end_line))

        return blocks
