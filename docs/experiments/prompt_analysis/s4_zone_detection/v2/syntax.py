"""SyntaxDetector — line scoring, fragment matching, context window.

Runs after StructuralDetector and FormatDetector. Operates only on unclaimed
lines (those not already claimed by structural or format detectors).  Produces
per-line syntax scores consumed by the BlockAssembler.

Responsible for ~88 % of detected blocks in WildChat.
"""

from __future__ import annotations

import re


class SyntaxDetector:
    """Score lines for code-likeness using syntactic features and fragment patterns."""

    def __init__(self, patterns: dict) -> None:
        syntax = patterns.get("syntax", {})

        # --- syntactic character set ---
        self._syntactic_chars: set[str] = set(syntax.get("syntactic_chars", "{}()[];=<>|&!@#$^*/\\~"))
        self._syntactic_endings: set[str] = set(syntax.get("syntactic_endings", "{;)],:" ))

        # --- keyword regex ---
        keywords = syntax.get("code_keywords", [])
        kw_alt = "|".join(re.escape(k) for k in keywords)
        self._keyword_re: re.Pattern[str] = re.compile(rf"\b(?:{kw_alt})\b")

        # --- assignment pattern ---
        self._assignment_re: re.Pattern[str] = re.compile(syntax.get("assignment_pattern", r"^\s*[a-z_]\w*\s*[:=]"))

        # --- scoring weights ---
        sw = syntax.get("scoring_weights", {})
        self._syn_density_high: float = sw.get("syn_density_high", 0.15)
        self._syn_density_high_weight: float = sw.get("syn_density_high_weight", 0.30)
        self._syn_density_med: float = sw.get("syn_density_med", 0.08)
        self._syn_density_med_weight: float = sw.get("syn_density_med_weight", 0.15)
        self._keyword_multi_weight: float = sw.get("keyword_multi_weight", 0.30)
        self._keyword_single_weight: float = sw.get("keyword_single_weight", 0.15)
        self._line_ending_weight: float = sw.get("line_ending_weight", 0.10)
        self._assignment_weight: float = sw.get("assignment_weight", 0.10)
        self._indentation_weight: float = sw.get("indentation_weight", 0.05)
        self._fragment_match_boost: float = sw.get("fragment_match_boost", 0.25)

        # --- fragment patterns (compiled per-family) ---
        raw_fragments: dict[str, list[str]] = syntax.get("fragment_patterns", {})
        self._fragment_families: dict[str, list[re.Pattern[str]]] = {}
        for family, pat_list in raw_fragments.items():
            self._fragment_families[family] = [re.compile(p) for p in pat_list]

        # --- context weights ---
        ctx = syntax.get("context", {})
        self._self_weight: float = ctx.get("self_weight", 0.70)
        self._neighbor_weight: float = ctx.get("neighbor_weight", 0.20)
        self._transition_colon_boost: float = ctx.get("transition_colon_boost", 0.10)
        self._transition_phrase_boost: float = ctx.get("transition_phrase_boost", 0.15)
        self._comment_bridge_factor: float = ctx.get("comment_bridge_factor", 0.80)

        # --- intro phrase and comment marker ---
        self._intro_phrase_re: re.Pattern[str] = re.compile(
            syntax.get(
                "intro_phrase_pattern",
                r"(?:example|code|output|command|result|script|snippet|run this|here is|as follows|shown below|see below).*:?\s*$",
            ),
            re.IGNORECASE,
        )
        self._comment_marker_re: re.Pattern[str] = re.compile(
            syntax.get(
                "comment_marker_pattern",
                r"^\s*(?:#(?!include|define|ifdef|ifndef|endif|pragma)|//|--|/\*|\*(?!/)| \*\s|%|REM\s)",
            )
        )

    # ------------------------------------------------------------------
    # line_syntax_score
    # ------------------------------------------------------------------

    def line_syntax_score(self, line: str) -> float:
        """Compute a 0.0-1.0 syntax score for a single line."""
        stripped = line.strip()
        if not stripped:
            return 0.0

        score = 0.0

        # 1. syntactic char density
        syn_count = sum(1 for c in stripped if c in self._syntactic_chars)
        density = syn_count / len(stripped)
        if density > self._syn_density_high:
            score += self._syn_density_high_weight
        elif density > self._syn_density_med:
            score += self._syn_density_med_weight

        # 2. keyword matches
        kw_hits = len(self._keyword_re.findall(stripped))
        if kw_hits >= 2:
            score += self._keyword_multi_weight
        elif kw_hits >= 1:
            score += self._keyword_single_weight

        # 3. syntactic line ending
        if stripped and stripped[-1] in self._syntactic_endings:
            score += self._line_ending_weight

        # 4. assignment pattern
        if self._assignment_re.search(stripped):
            score += self._assignment_weight

        # 5. indentation (>= 2 spaces or tabs)
        leading = len(line) - len(line.lstrip())
        if leading >= 2:
            score += self._indentation_weight

        return min(score, 1.0)

    # ------------------------------------------------------------------
    # score_with_fragments
    # ------------------------------------------------------------------

    def score_with_fragments(self, line: str) -> tuple[float, str | None]:
        """Score a line and identify which fragment family matches (if any).

        Returns:
            (score, family_name) — family_name is None when no fragment matches.
        """
        score = self.line_syntax_score(line)

        for family, compiled_pats in self._fragment_families.items():
            for pat in compiled_pats:
                if pat.search(line):
                    return (min(score + self._fragment_match_boost, 1.0), family)

        return (score, None)

    # ------------------------------------------------------------------
    # score_lines (context window)
    # ------------------------------------------------------------------

    def score_lines(self, lines: list[str], claimed_ranges: set[int]) -> list[float]:
        """Score every line, applying context window smoothing.

        Claimed lines receive -1.0 so downstream consumers can skip them.

        Args:
            lines: All prompt lines.
            claimed_ranges: Line indices already owned by earlier detectors.

        Returns:
            List of float scores, one per line.
        """
        n = len(lines)

        # --- pass 1: raw scores ---
        raw: list[float] = []
        for i in range(n):
            if i in claimed_ranges:
                raw.append(-1.0)
            else:
                raw.append(self.line_syntax_score(lines[i]))

        # --- pass 2: context-aware smoothing ---
        result: list[float] = list(raw)

        for i in range(n):
            if raw[i] < 0:
                # Claimed — keep -1.0
                continue

            # neighbor average (skip negatives / out-of-range)
            neighbors: list[float] = []
            if i > 0 and raw[i - 1] >= 0:
                neighbors.append(raw[i - 1])
            if i < n - 1 and raw[i + 1] >= 0:
                neighbors.append(raw[i + 1])
            neighbor_avg = sum(neighbors) / len(neighbors) if neighbors else 0.0

            # transition boost
            transition_boost = 0.0
            if i > 0 and raw[i - 1] >= 0:
                prev_stripped = lines[i - 1].rstrip()
                if prev_stripped and prev_stripped[-1] in (":", "{") and raw[i - 1] > 0.2:
                    transition_boost = self._transition_colon_boost
                if self._intro_phrase_re.search(lines[i - 1]):
                    transition_boost = max(transition_boost, self._transition_phrase_boost)

            # comment bridge
            comment_bridge = 0.0
            if raw[i] == 0.0 and neighbor_avg > 0.3 and self._comment_marker_re.match(lines[i]):
                comment_bridge = neighbor_avg * self._comment_bridge_factor

            blended = raw[i] * self._self_weight + neighbor_avg * self._neighbor_weight + transition_boost + comment_bridge
            result[i] = blended

        return result

    # ------------------------------------------------------------------
    # fragment_hits_for_block
    # ------------------------------------------------------------------

    def fragment_hits_for_block(self, lines: list[str]) -> dict[str, int]:
        """Count how many lines match each fragment family.

        Used by LanguageDetector (Task 9) to identify the dominant
        language family in a block.
        """
        hits: dict[str, int] = {}
        for line in lines:
            for family, compiled_pats in self._fragment_families.items():
                for pat in compiled_pats:
                    if pat.search(line):
                        hits[family] = hits.get(family, 0) + 1
                        break  # one hit per family per line is enough
        return hits
