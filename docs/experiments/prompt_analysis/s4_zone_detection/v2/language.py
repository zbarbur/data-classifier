"""LanguageDetector — language probability from fragment hits.

Called per-block by the Orchestrator (Task 10). Receives fragment_hits
from SyntaxDetector.fragment_hits_for_block() (Task 6). Enriches
ZoneBlocks with language_hint and language_confidence.

This is an optional enrichment step — the Orchestrator can skip it if
config.language_detection_enabled is False.
"""

from __future__ import annotations

import re


class LanguageDetector:
    """Detect programming language from fragment family hits and disambiguation markers."""

    def __init__(self, patterns: dict) -> None:
        lang_cfg = patterns.get("language", {})
        raw_markers: dict[str, list[str]] = lang_cfg.get("c_family_markers", {})

        # Pre-compile all disambiguation patterns per language
        self._c_family_markers: dict[str, list[re.Pattern[str]]] = {
            lang: [re.compile(p) for p in pat_list]
            for lang, pat_list in raw_markers.items()
        }

    # ------------------------------------------------------------------
    # detect_language
    # ------------------------------------------------------------------

    def detect_language(
        self,
        block_lines: list[str],
        fragment_hits: dict[str, int],
    ) -> tuple[str, float, dict]:
        """Compute language from fragment family hit counts.

        Args:
            block_lines: Lines in the block (used for c_family disambiguation).
            fragment_hits: Mapping of family name → hit count from
                SyntaxDetector.fragment_hits_for_block().

        Returns:
            (top_language, confidence, full_distribution)
            - top_language: detected language name, or "" if no hits
            - confidence: probability of top language (0.0–1.0)
            - full_distribution: normalized probability dict over all families
        """
        if not fragment_hits:
            return ("", 0.0, {})

        # Normalize to probability distribution
        total = sum(fragment_hits.values())
        distribution: dict[str, float] = {family: count / total for family, count in fragment_hits.items()}

        # Find top family
        top_family = max(distribution, key=lambda f: distribution[f])
        top_conf = distribution[top_family]

        # C-family disambiguation when dominant and lines are available
        if top_family == "c_family" and top_conf > 0.5 and block_lines:
            specific = self._disambiguate_c_family(block_lines)
            if specific is not None:
                # Replace "c_family" entry with the specific language
                distribution[specific] = distribution.pop("c_family")
                return (specific, top_conf, distribution)

        return (top_family, top_conf, distribution)

    # ------------------------------------------------------------------
    # _disambiguate_c_family
    # ------------------------------------------------------------------

    def _disambiguate_c_family(self, lines: list[str]) -> str | None:
        """Identify the specific C-family language from marker patterns.

        For each language, counts how many of its marker patterns match
        across the block lines.  Returns the language with the most
        matches, or None if no markers matched at all.
        """
        scores: dict[str, int] = {}
        joined = "\n".join(lines)

        for lang, compiled_pats in self._c_family_markers.items():
            count = sum(1 for pat in compiled_pats if pat.search(joined))
            if count > 0:
                scores[lang] = count

        if not scores:
            return None

        return max(scores, key=lambda lang: scores[lang])
