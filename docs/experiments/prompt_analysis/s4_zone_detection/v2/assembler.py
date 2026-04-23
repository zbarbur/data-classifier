"""BlockAssembler — block grouping, gap bridging, bracket validation, repetitive structure."""

from __future__ import annotations

from collections import Counter

from docs.experiments.prompt_analysis.s4_zone_detection.v2.types import ZoneBlock, ZoneConfig


class BlockAssembler:
    """Converts per-line scores and types into grouped ZoneBlocks.

    Responsibilities:
    - Group consecutive scored/typed lines into candidate runs
    - Bridge small gaps (1-2 blank lines) between same-type runs
    - Detect repetitive structure (catches common FP patterns)
    - Filter blocks below min_block_lines threshold
    - Compute per-block confidence scores
    """

    def __init__(self, patterns: dict, config: ZoneConfig) -> None:
        assembly = patterns.get("assembly", {})
        self._min_block_lines = config.min_block_lines if config.min_block_lines else assembly.get("min_block_lines", 8)
        self._min_confidence = config.min_confidence if config.min_confidence else assembly.get("min_confidence", 0.50)
        self._max_blank_gap = assembly.get("max_blank_gap", 3)
        self._max_comment_gap = assembly.get("max_comment_gap", 2)
        self._repetitive_threshold = assembly.get("repetitive_threshold", 0.50)
        self._max_parse_attempts = (
            config.max_parse_attempts if config.max_parse_attempts else assembly.get("max_parse_attempts", 10)
        )
        self._bracket_extension_limit = assembly.get("bracket_extension_limit", 5)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assemble(
        self,
        lines: list[str],
        scores: list[float],
        line_types: list[str | None],
    ) -> list[ZoneBlock]:
        """Main entry: convert per-line data into ZoneBlocks.

        Steps:
        1. Group consecutive lines into runs based on scores and types
        2. Determine zone_type per run
        3. Bridge gaps between same-type runs
        4. Check repetitive structure and reclassify if needed
        5. Filter by min_block_lines
        6. Compute confidence for each block
        7. Return sorted blocks
        """
        if not lines:
            return []

        runs = self._group_runs(scores, line_types, lines)
        runs = self._bridge_gaps(runs)
        blocks: list[ZoneBlock] = []

        for run in runs:
            start = run["start"]
            end = run["end"]
            block_lines = lines[start:end]
            block_scores = scores[start:end]
            zone_type = run["type"]
            line_count = end - start

            # Filter by min_block_lines
            if line_count < self._min_block_lines:
                continue

            # Check repetitive structure
            rep_prefix = self.detect_repetitive_structure(block_lines)
            if rep_prefix is not None and zone_type == "code":
                # Repetitive prefix suggests error output or log, not code
                zone_type = "error_output"

            # Compute confidence
            non_zero = [s for s in block_scores if s > 0]
            avg_score = sum(non_zero) / len(non_zero) if non_zero else 0.0
            high_ratio = sum(1 for s in block_scores if s >= 0.4) / max(len(block_scores), 1)

            if zone_type == "error_output":
                # Error output blocks are typed by NegativeFilter, not scored
                # by syntax. Give them confidence based on type coverage.
                block_types = line_types[start:end]
                typed_ratio = sum(1 for t in block_types if t == "error_output") / max(len(block_types), 1)
                confidence = self._compute_confidence(typed_ratio * 0.5, typed_ratio, block_lines)
            else:
                confidence = self._compute_confidence(avg_score, high_ratio, block_lines)

            if confidence < self._min_confidence:
                continue

            blocks.append(
                ZoneBlock(
                    start_line=start,
                    end_line=end,
                    zone_type=zone_type,
                    confidence=confidence,
                    method="syntax_score",
                    text="\n".join(block_lines),
                )
            )

        blocks.sort(key=lambda b: b.start_line)
        return blocks

    def detect_repetitive_structure(
        self,
        lines: list[str],
        threshold: float | None = None,
    ) -> str | None:
        """Detect repetitive prefix patterns in a block of lines.

        Returns the common prefix string if repetition exceeds the threshold,
        otherwise None.
        """
        if threshold is None:
            threshold = self._repetitive_threshold

        non_empty = [ln for ln in lines if ln.strip()]
        if len(non_empty) < 3:
            return None

        prefixes: list[str] = []
        for ln in non_empty:
            stripped = ln.strip()
            # Extract first significant token(s) as the prefix fingerprint.
            # Use the first two tokens to avoid false matches on common
            # single-token prefixes like "x" or "return".
            tokens = stripped.split(None, 2)
            if len(tokens) >= 2:
                prefixes.append(f"{tokens[0]} {tokens[1]}")
            elif tokens:
                prefixes.append(tokens[0])

        if not prefixes:
            return None

        counter = Counter(prefixes)
        most_common_prefix, count = counter.most_common(1)[0]
        ratio = count / len(non_empty)

        if ratio >= threshold:
            return most_common_prefix
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _group_runs(
        self,
        scores: list[float],
        line_types: list[str | None],
        lines: list[str],
    ) -> list[dict]:
        """Group consecutive lines into candidate runs.

        Rules:
        - Lines with score > 0: part of a code run
        - Lines with line_type 'error_output': part of an error run
        - Blank lines: bridged if gap <= max_blank_gap consecutive blanks
        - Break on 3+ consecutive zero-score non-blank lines
        - Break on type transitions (code -> error_output)
        """
        n = len(scores)
        if n == 0:
            return []

        runs: list[dict] = []
        current_start: int | None = None
        current_type: str | None = None
        current_scores: list[float] = []
        consecutive_blanks = 0
        consecutive_zero_nonblank = 0

        for i in range(n):
            is_blank = not lines[i].strip()
            has_score = scores[i] > 0
            lt = line_types[i]

            # Determine the type this line wants to belong to
            if lt == "error_output":
                line_want_type = "error_output"
            elif has_score:
                line_want_type = "code"
            elif is_blank:
                line_want_type = None  # blank — inherits from context
            else:
                line_want_type = None  # zero-score non-blank

            # Handle blank lines: potential gap bridging
            if is_blank and not has_score and lt != "error_output":
                consecutive_blanks += 1
                consecutive_zero_nonblank = 0
                if consecutive_blanks >= self._max_blank_gap and current_start is not None:
                    # Too many blanks — close current run
                    end_pos = i - consecutive_blanks + 1
                    runs.append(
                        {
                            "start": current_start,
                            "end": end_pos,
                            "type": current_type,
                            "scores": current_scores[:],
                        }
                    )
                    current_start = None
                    current_type = None
                    current_scores = []
                continue

            # Non-blank line
            if not is_blank and not has_score and lt != "error_output":
                consecutive_zero_nonblank += 1
                consecutive_blanks = 0
                if consecutive_zero_nonblank >= 3 and current_start is not None:
                    end_pos = i - consecutive_zero_nonblank + 1
                    if end_pos > current_start:
                        runs.append(
                            {
                                "start": current_start,
                                "end": end_pos,
                                "type": current_type,
                                "scores": current_scores[:],
                            }
                        )
                    current_start = None
                    current_type = None
                    current_scores = []
                continue

            # Active line (has score or is error_output)
            consecutive_blanks = 0
            consecutive_zero_nonblank = 0

            if current_start is None:
                # Start a new run
                current_start = i
                current_type = line_want_type
                current_scores = [scores[i]]
            elif line_want_type != current_type and line_want_type is not None and current_type is not None:
                # Type transition — close current, start new
                runs.append({"start": current_start, "end": i, "type": current_type, "scores": current_scores[:]})
                current_start = i
                current_type = line_want_type
                current_scores = [scores[i]]
            else:
                # Continue current run, extending through any bridged blanks
                current_scores.append(scores[i])
                if line_want_type is not None:
                    current_type = line_want_type

        # Close final run
        if current_start is not None:
            runs.append(
                {
                    "start": current_start,
                    "end": len(lines),
                    "type": current_type or "code",
                    "scores": current_scores[:],
                }
            )

        return runs

    def _bridge_gaps(self, runs: list[dict]) -> list[dict]:
        """Bridge gaps between same-type runs separated by small empty space."""
        if len(runs) <= 1:
            return runs

        merged: list[dict] = [runs[0]]
        for run in runs[1:]:
            prev = merged[-1]
            gap = run["start"] - prev["end"]
            same_type = prev["type"] == run["type"]

            if same_type and gap <= self._max_comment_gap:
                # Merge: extend previous run to cover the gap and the new run
                prev["end"] = run["end"]
                prev["scores"].extend(run["scores"])
            else:
                merged.append(run)

        return merged

    def _brackets_balanced(self, block_lines: list[str]) -> tuple[bool, dict]:
        """Check bracket balance with basic string awareness.

        Tracks counts for (, [, { and their closers.
        Skips characters inside quoted strings (toggles on " or ').

        Returns (is_balanced, {bracket_char: imbalance_count}).
        """
        openers = {"(": ")", "[": "]", "{": "}"}
        closers = {v: k for k, v in openers.items()}
        counts: dict[str, int] = {b: 0 for b in openers}

        for line in block_lines:
            in_string: str | None = None
            for ch in line:
                # String toggling
                if ch in ('"', "'"):
                    if in_string is None:
                        in_string = ch
                    elif in_string == ch:
                        in_string = None
                    continue

                if in_string is not None:
                    continue

                if ch in openers:
                    counts[ch] += 1
                elif ch in closers:
                    opener = closers[ch]
                    counts[opener] -= 1

        imbalances = {k: abs(v) for k, v in counts.items() if v != 0}
        return (len(imbalances) == 0, imbalances)

    def _compute_confidence(
        self,
        avg_score: float,
        high_ratio: float,
        block_lines: list[str],
        method: str = "syntax_score",
    ) -> float:
        """Compute confidence score for a block.

        - Base: 0.40 + avg_score
        - Size bonus: +0.05 if >=20 lines, +0.10 if >=50 lines
        - High-ratio bonus: +0.05 if high_ratio >= 0.70
        - Cap at 0.95
        """
        conf = 0.40 + avg_score
        n = len(block_lines)

        if n >= 50:
            conf += 0.10
        elif n >= 20:
            conf += 0.05

        if high_ratio >= 0.70:
            conf += 0.05

        return min(conf, 0.95)
