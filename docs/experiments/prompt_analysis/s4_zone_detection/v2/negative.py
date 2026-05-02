"""NegativeFilter — FP suppression signals.

Runs after SyntaxDetector to suppress false positives. Operates on a
per-line basis (check_line) and on full blocks (check_list_prefix).

The 35 known FP categories from WildChat reviews that this filter handles:
  - 7 aspect ratios / time expressions  → ratio patterns
  - 6 structured lists                   → list prefix detection
  - 4 error messages                     → error_output patterns
  - 3 dialog lines                       → dialog patterns
  - 3 math notation                      → math patterns
  - remainder                            → prose pattern + confidence threshold
"""

from __future__ import annotations

import re


def _alpha_ratio(line: str) -> float:
    """Fraction of non-empty characters that are alphabetic or whitespace."""
    stripped = line.strip()
    if not stripped:
        return 0.0
    return sum(c.isalpha() or c.isspace() for c in stripped) / len(stripped)


class NegativeFilter:
    """Suppress false-positive zone detections using known non-code signal patterns."""

    def __init__(self, patterns: dict) -> None:
        neg = patterns.get("negative", {})

        # --- error output ---
        self._error_output: list[re.Pattern[str]] = [re.compile(p) for p in neg.get("error_output", [])]

        # --- dialog ---
        dialog_cfg = neg.get("dialog", {})
        self._dialog_pats: list[re.Pattern[str]] = [re.compile(p) for p in dialog_cfg.get("patterns", [])]
        self._dialog_min_alpha: float = dialog_cfg.get("min_alpha_ratio", 0.70)

        # --- math ---
        self._math_pats: list[re.Pattern[str]] = [re.compile(p) for p in neg.get("math", [])]

        # --- ratio ---
        self._ratio_pats: list[re.Pattern[str]] = [re.compile(p) for p in neg.get("ratio", [])]

        # --- prose ---
        prose_cfg = neg.get("prose", {})
        self._prose_re: re.Pattern[str] = re.compile(prose_cfg.get("pattern", r"^[A-Z][a-z].+[.!?]$"))
        self._prose_min_alpha: float = prose_cfg.get("min_alpha_ratio", 0.75)

        # --- list prefix ---
        list_cfg = neg.get("list_prefix", {})
        self._list_prefix_re: re.Pattern[str] = re.compile(
            list_cfg.get("pattern", r"^\s*(?:\d+[.):]?\s+|[-\u2022*]\s+|[a-z][.)]\s+)")
        )
        self._list_threshold: float = list_cfg.get("threshold", 0.70)

    # ------------------------------------------------------------------
    # check_line
    # ------------------------------------------------------------------

    def check_line(self, line: str) -> str | None:
        """Check a single line against negative signals.

        Returns:
            "error_output" — line matches an error output pattern
            "suppress"     — line matches math, prose, dialog, or ratio patterns
            None           — no negative signal detected
        """
        # 1. Math patterns → "suppress"
        for pat in self._math_pats:
            if pat.search(line):
                return "suppress"

        # 2. Error output patterns → "error_output"
        for pat in self._error_output:
            if pat.search(line):
                return "error_output"

        # 3. Prose pattern → "suppress"
        if self._prose_re.search(line) and _alpha_ratio(line) > self._prose_min_alpha:
            return "suppress"

        # 4. Dialog patterns → "suppress"
        for pat in self._dialog_pats:
            if pat.search(line) and _alpha_ratio(line) > self._dialog_min_alpha:
                return "suppress"

        # 5. Ratio patterns → "suppress"
        for pat in self._ratio_pats:
            if pat.search(line):
                return "suppress"

        return None

    # ------------------------------------------------------------------
    # check_list_prefix
    # ------------------------------------------------------------------

    def check_list_prefix(self, lines: list[str]) -> bool:
        """Return True if >threshold of non-empty lines match the list prefix pattern.

        Used by BlockAssembler at the block level (not per-line).
        """
        non_empty = [ln for ln in lines if ln.strip()]
        if not non_empty:
            return False
        matched = sum(1 for ln in non_empty if self._list_prefix_re.search(ln))
        return (matched / len(non_empty)) > self._list_threshold
