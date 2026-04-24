"""ScopeTracker — bracket continuation and indentation-based scope tracking.

Runs after SyntaxDetector to adjust scores for lines that belong to an
open scope or are continuations of a multi-line statement.  Only promotes
zero-scored lines; never suppresses scored lines.

Two passes:
  1. Bracket continuation — unclosed ``(``, ``[``, ``{`` propagate the
     parent line's score to subsequent zero-scored lines.
  2. Indentation scope — lines ending with ``:`` or ``{`` open a scope;
     more-indented zero-scored lines inherit the opener's score.
"""

from __future__ import annotations


class ScopeTracker:
    """Adjust per-line scores based on scope context."""

    def __init__(self, patterns: dict) -> None:
        scope_cfg = patterns.get("scope", {})
        self._inherit_factor: float = scope_cfg.get("scope_inherit_factor", 0.5)
        self._continuation_factor: float = scope_cfg.get("continuation_inherit_factor", 0.9)
        self._min_parent_score: float = scope_cfg.get("min_parent_score", 0.3)

    def adjust_scores(
        self,
        lines: list[str],
        scores: list[float],
        claimed_ranges: set[int],
    ) -> list[float]:
        """Return a new score list with scope/continuation adjustments.

        Only promotes zero-scored lines.  Claimed lines (score < 0) and
        already-scored lines are never changed.
        """
        result = list(scores)
        n = len(lines)

        # --- Pass 1: Bracket continuation ---
        open_count = 0
        parent_score = 0.0

        for i in range(n):
            if i in claimed_ranges or result[i] < 0:
                open_count = 0
                parent_score = 0.0
                continue

            # Inherit from parent if in continuation and current is zero
            if open_count > 0 and result[i] == 0.0 and parent_score >= self._min_parent_score:
                result[i] = parent_score * self._continuation_factor

            # Update bracket tracking
            delta = self._net_brackets(lines[i])
            open_count = max(0, open_count + delta)

            # Track parent score (most recent scored line)
            if result[i] >= self._min_parent_score:
                parent_score = result[i]

        # --- Pass 2: Indentation scope ---
        scope_indent = -1
        scope_score = 0.0

        for i in range(n):
            if i in claimed_ranges or result[i] < 0:
                scope_indent = -1
                scope_score = 0.0
                continue

            stripped = lines[i].strip()
            if not stripped:
                continue  # skip blanks, preserve scope

            indent = len(lines[i]) - len(lines[i].lstrip())

            # Check if we've exited the scope (back to opener indent or less)
            if scope_indent >= 0 and indent <= scope_indent:
                scope_indent = -1
                scope_score = 0.0

            # Inherit scope score for zero-scored lines inside scope
            if scope_indent >= 0 and result[i] == 0.0 and scope_score >= self._min_parent_score:
                result[i] = scope_score * self._inherit_factor

            # Open new scope: scored line ending with ':' or '{'
            if result[i] >= self._min_parent_score and (stripped.endswith(":") or stripped.endswith("{")):
                scope_indent = indent
                scope_score = result[i]

        return result

    @staticmethod
    def _net_brackets(line: str) -> int:
        """Count net unclosed brackets (openers minus closers).

        Skips brackets inside quoted strings.
        """
        in_string: str | None = None
        net = 0
        prev = ""
        for ch in line:
            if ch in ('"', "'"):
                if in_string is None:
                    in_string = ch
                elif in_string == ch and prev != "\\":
                    in_string = None
                prev = ch
                continue
            if in_string:
                prev = ch
                continue
            if ch in "([{":
                net += 1
            elif ch in ")]}":
                net -= 1
            prev = ch
        return net
