"""SyntaxDetector — line scoring, fragment matching, context window.

Runs after StructuralDetector and FormatDetector. Operates only on unclaimed
lines (those not already claimed by structural or format detectors).  Produces
per-line syntax scores consumed by the BlockAssembler.

Responsible for ~88 % of detected blocks in WildChat.
"""

from __future__ import annotations

import re

from docs.experiments.prompt_analysis.s4_zone_detection.v2.tokenizer import tokenize_line


class SyntaxDetector:
    """Score lines for code-likeness using syntactic features and fragment patterns."""

    def __init__(self, patterns: dict) -> None:
        syntax = patterns.get("syntax", {})

        # --- syntactic character set ---
        self._syntactic_chars: set[str] = set(syntax.get("syntactic_chars", "{}()[];=<>|&!@#$^*/\\~"))
        self._syntactic_endings: set[str] = set(syntax.get("syntactic_endings", "{;)],:" ))

        # --- two-tier keyword matching ---
        # Strict keywords: programming jargon that never appears in English
        # prose (def, elif, const, async, await, lambda, ...).
        # Contextual keywords: common English words that need structural
        # validation (for, function, class, if, return, new, ...).
        strict = syntax.get("strict_keywords", [])
        contextual = syntax.get("contextual_keywords", [])
        all_keywords = strict + contextual
        if strict:
            strict_alt = "|".join(re.escape(k) for k in strict)
            self._strict_kw_re: re.Pattern[str] | None = re.compile(rf"\b(?:{strict_alt})\b")
        else:
            self._strict_kw_re = None
        if contextual:
            ctx_alt = "|".join(re.escape(k) for k in contextual)
            self._contextual_kw_re: re.Pattern[str] | None = re.compile(rf"\b(?:{ctx_alt})\b")
        else:
            self._contextual_kw_re = None
        # Combined regex for backward-compat (fragment matching, etc.)
        if all_keywords:
            kw_alt = "|".join(re.escape(k) for k in all_keywords)
            self._keyword_re: re.Pattern[str] = re.compile(rf"\b(?:{kw_alt})\b")
        else:
            self._keyword_re = re.compile(r"(?!)")  # never matches

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

        # --- tokenizer integration ---
        # Tokenizer only knows about strict keywords (contextual ones are
        # validated by structural context, which the tokenizer can't check).
        self._keyword_set: frozenset[str] = frozenset(strict)
        tok_cfg = patterns.get("tokenizer", {}).get("semantic_weights", {})
        self._code_dot_boost: float = tok_cfg.get("code_dot_boost", 1.3)
        self._code_operator_boost: float = tok_cfg.get("code_operator_boost", 1.2)
        self._prose_suppress: float = tok_cfg.get("prose_suppress", 0.3)
        self._data_suppress: float = tok_cfg.get("data_suppress", 0.4)
        self._no_ident_suppress: float = tok_cfg.get("no_ident_suppress", 0.3)
        self._min_ident_for_prose: int = tok_cfg.get("min_ident_for_prose", 4)
        self._max_keyword_for_prose: int = tok_cfg.get("max_keyword_for_prose", 1)
        self._data_string_ratio_threshold: float = tok_cfg.get("data_string_ratio_threshold", 0.4)
        self._expr_call_boost: float = tok_cfg.get("expression_call_boost", 0.10)
        self._expr_data_suppress: float = tok_cfg.get("expression_data_suppress", -0.10)
        # Regex for function call pattern: ident(
        self._func_call_re: re.Pattern[str] = re.compile(r"\b[a-zA-Z_]\w*\s*\(")

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

        # 2. keyword matches (two-tier: strict always count,
        #    contextual only count with structural validation)
        kw_hits = self._count_keywords(stripped)
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

        # --- Semantic modifier (tokenizer-based) ---
        profile = tokenize_line(stripped, keywords=self._keyword_set)
        # Override keyword_count with the structurally-validated count.
        # The tokenizer only knows strict keywords; contextual keywords
        # that passed validation should also count so the modifier's
        # prose_suppress rule doesn't fire on lines like
        # "public static void main(String[] args) {".
        profile.keyword_count = kw_hits
        modifier = self._semantic_modifier(profile)
        score *= modifier

        # --- Expression adjustment (tie-breaker) ---
        score += self._expression_adjustment(profile, stripped)

        return max(min(score, 1.0), 0.0)

    def _count_keywords(self, line: str) -> int:
        """Count keywords with structural validation.

        Strict keywords (``def``, ``async``, ``const``, ...) always count.
        Contextual keywords (``for``, ``function``, ``class``, ...) only
        count when accompanied by code structure — at the start of the
        line, or followed by ``(``, ``{``, ``:``, an identifier + ``=``,
        or an identifier + ``(``.

        This prevents English prose like *"generator for a generative AI"*
        from getting keyword score, while still catching *"for (i = 0"* or
        *"function foo("*.
        """
        count = 0

        # Strict: always count
        if self._strict_kw_re:
            count += len(self._strict_kw_re.findall(line))

        # Contextual: validate structural context.
        # A contextual keyword counts only when it has code structure
        # nearby — at line start, or a structural token within 20 chars.
        if self._contextual_kw_re:
            for m in self._contextual_kw_re.finditer(line):
                pos = m.start()
                after = line[m.end():]
                before = line[:pos]

                # Valid if at start of line (after whitespace)
                if not before.strip():
                    count += 1
                    continue

                # Valid if a structural token appears within 20 chars.
                # Catches: static void main(  /  new MyClass(  /  let x =
                # Rejects: "generator for a generative AI"
                if re.search(r"[\(\{\[:=]", after[:20]):
                    count += 1
                    continue

                # Valid if preceded by dot: obj.this, self.match
                if before.endswith("."):
                    count += 1
                    continue

        return count

    def _semantic_modifier(self, profile) -> float:
        """Score multiplier based on token profile.

        Returns a value in [0.3, 1.3] that scales the raw syntax score.
        Code patterns boost, prose/data patterns suppress.
        """
        # Code: identifiers + dot access (method calls, chaining)
        if profile.dot_access_count >= 1 and profile.identifier_count >= 1:
            return self._code_dot_boost

        # Code: identifiers + operators (assignments, comparisons)
        if profile.identifier_count >= 1 and profile.operator_count >= 1:
            return self._code_operator_boost

        # Prose: many word-like tokens, no code structure
        if (
            profile.identifier_count >= self._min_ident_for_prose
            and profile.operator_count == 0
            and profile.dot_access_count == 0
            and profile.keyword_count <= self._max_keyword_for_prose
        ):
            return self._prose_suppress

        # Data: dominated by string literals (but not if a keyword is present —
        # e.g. #include "file.h" has high string ratio but is code)
        if profile.string_ratio > self._data_string_ratio_threshold and profile.keyword_count == 0:
            return self._data_suppress

        # No identifiers or keywords at all (non-Latin text with parens, etc.)
        if profile.identifier_count == 0 and profile.keyword_count == 0 and profile.total_tokens > 0:
            return self._no_ident_suppress

        return 1.0

    def _expression_adjustment(self, profile, line: str) -> float:
        """Small score adjustment for expression-level signals.

        Returns a value in [-0.10, +0.10] added to the score after
        the semantic modifier.  Catches function calls that lack
        operators (e.g. ``print(data)``) and penalizes pure
        number/string rows.
        """
        # Function call: ident( — boost when there's an identifier and parens
        if self._func_call_re.search(line) and profile.identifier_count >= 1:
            return self._expr_call_boost

        # All numbers/strings with no identifiers or keywords — data row
        if profile.identifier_count == 0 and profile.keyword_count == 0:
            if profile.number_count + profile.string_count > 0:
                return self._expr_data_suppress

        return 0.0

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

        # --- pass 1: raw scores (including fragment boost) ---
        raw: list[float] = []
        for i in range(n):
            if i in claimed_ranges:
                raw.append(-1.0)
            else:
                raw.append(self.score_with_fragments(lines[i])[0])

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

        # --- pass 3: multi-line comment block bridge ---
        # The per-line comment bridge (pass 2) only works for isolated
        # comment lines next to code.  Multi-line comment blocks (/** ... */)
        # have interior lines whose neighbors are also 0-score comments.
        # This pass finds contiguous comment blocks and bridges them all
        # if they're adjacent to code on either side.
        i = 0
        while i < n:
            if result[i] != 0.0 or raw[i] < 0 or not self._comment_marker_re.match(lines[i]):
                i += 1
                continue
            # Found a zero-score comment line — find the full block
            block_start = i
            while i < n and result[i] == 0.0 and raw[i] >= 0 and self._comment_marker_re.match(lines[i]):
                i += 1
            block_end = i  # exclusive

            # Check for code near above or below (scan up to 3 lines
            # past closing */ and blank lines to find the real code)
            above = 0.0
            for j in range(block_start - 1, max(block_start - 4, -1), -1):
                if raw[j] < 0:
                    break
                if result[j] > above:
                    above = result[j]
                if above > 0.2:
                    break

            below = 0.0
            for j in range(block_end, min(block_end + 4, n)):
                if raw[j] < 0:
                    break
                if result[j] > below:
                    below = result[j]
                if below > 0.2:
                    break

            if above > 0.2 or below > 0.2:
                bridge = max(above, below) * self._comment_bridge_factor
                for j in range(block_start, block_end):
                    result[j] = bridge

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
