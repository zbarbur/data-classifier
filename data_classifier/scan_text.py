"""Text-level scanning — credential detection in free text (prompts, logs, configs).

Unlike :func:`classify_columns` which operates on database columns (column name +
sample values), :func:`scan_text` scans a string for credential patterns at the
substring level.  This is the Python equivalent of the JS browser scanner's
``scanText``.

Detection flow:
  1. **Regex pass** — iterate all non-column-gated credential patterns via RE2,
     apply validators and stopwords.
  2. **Secret scanner pass** — parse KV structures from the text, score key names
     against the dictionary with tiered entropy gating.  Uses regex findings from
     step 1 to enrich KV-extracted values (unified detection).
  3. **Opaque token pass** — scan whitespace-delimited tokens for standalone
     high-entropy opaque secrets (JWTs, hex hashes, random API keys).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import re2

from data_classifier.engines.heuristic_engine import compute_char_class_diversity
from data_classifier.engines.parsers import parse_key_values_with_spans
from data_classifier.engines.regex_engine import _get_global_stopwords
from data_classifier.engines.secret_scanner import (
    SecretScannerEngine,
    _compute_relative_entropy,
    _is_compound_non_secret,
    _is_placeholder_value,
    _score_key_name,
    _value_is_obviously_not_secret,
)
from data_classifier.engines.validators import VALIDATORS
from data_classifier.patterns import ContentPattern, load_default_patterns

logger = logging.getLogger(__name__)

# ── Opaque token pass constants (mirrors JS scanner-core.js opaqueTokenPass) ─
_OPAQUE_MIN_LENGTH = 16
_OPAQUE_ENTROPY_THRESHOLD = 0.7
_OPAQUE_DIVERSITY_THRESHOLD = 3
_OPAQUE_BASE_CONFIDENCE = 0.65
_OPAQUE_MAX_CONFIDENCE = 0.85
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_TOKEN_RE = re.compile(r"\S+")
_STRIP_RE = re.compile(r'^["\'`]+|["\'`,.;:!?)\]]+$')


@dataclass
class TextScanResult:
    """Result of scanning free text for credentials."""

    findings: list[TextFinding]
    """All credential findings in the text."""

    scanned_length: int
    """Length of the input text."""


@dataclass
class TextFinding:
    """A single credential match within text."""

    entity_type: str
    detection_type: str
    display_name: str
    category: str
    confidence: float
    engine: str
    start: int
    end: int
    value_masked: str
    evidence: str = ""


def _mask_value(value: str) -> str:
    """Mask a matched value for safe display."""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


class TextScanner:
    """Reusable text scanner — call :meth:`startup` once, then :meth:`scan` per text."""

    def __init__(self) -> None:
        self._patterns: list[ContentPattern] = []
        self._stopwords: set[str] = set()
        self._ss: SecretScannerEngine | None = None
        self._started = False

    def startup(self) -> None:
        self._patterns = load_default_patterns()
        self._stopwords = _get_global_stopwords()
        self._ss = SecretScannerEngine()
        self._ss.startup()
        self._started = True

    def scan(self, text: str, *, min_confidence: float = 0.3) -> TextScanResult:
        """Scan free text for credential patterns.

        Runs regex pass then secret scanner KV pass, deduplicates overlapping
        spans, returns findings sorted by position.
        """
        if not self._started:
            self.startup()

        raw: list[TextFinding] = []
        raw.extend(self._regex_pass(text))
        raw.extend(self._secret_scanner_pass(text, raw))
        raw.extend(self._opaque_token_pass(text))

        # Dedup: keep highest confidence per overlapping span
        deduped = self._dedup(raw)
        deduped = [f for f in deduped if f.confidence >= min_confidence]

        return TextScanResult(findings=deduped, scanned_length=len(text))

    def _regex_pass(self, text: str) -> list[TextFinding]:
        out: list[TextFinding] = []
        for p in self._patterns:
            if p.category != "Credential":
                continue
            if p.requires_column_hint:
                continue
            try:
                for m in re2.finditer(p.regex, text):
                    value = m.group(0)
                    lower = value.lower().strip()
                    if p.stopwords and lower in {s.lower() for s in p.stopwords}:
                        continue
                    if lower in self._stopwords:
                        continue
                    vfn = VALIDATORS.get(p.validator)
                    if vfn and not vfn(value):
                        continue
                    # FP filters — match JS scanner-core.js behavior
                    if _value_is_obviously_not_secret(value):
                        continue
                    if _is_placeholder_value(value):
                        continue
                    out.append(
                        TextFinding(
                            entity_type=p.entity_type,
                            detection_type=p.name,
                            display_name=p.display_name or p.name,
                            category=p.category,
                            confidence=p.confidence,
                            engine="regex",
                            start=m.start(),
                            end=m.end(),
                            value_masked=_mask_value(value),
                            evidence=f"Regex: {p.display_name or p.name} matched",
                        )
                    )
            except Exception:
                pass  # (?i) patterns fail in RE2, same as JS
        return out

    def _secret_scanner_pass(self, text: str, regex_findings: list[TextFinding]) -> list[TextFinding]:
        """Run KV parsing on text — calls parse_key_values directly for accurate spans.

        Mirrors the JS ``secretScannerPass`` which calls ``parseKeyValues(text)``
        and scores each (key, value) pair against the secret key-name dictionary.
        Unlike the old approach (routing through SecretScannerEngine.classify_column),
        this gives accurate value spans instead of whole-text spans.
        """
        pairs = parse_key_values_with_spans(text)
        if not pairs:
            return []

        ss_config = self._ss._config if self._ss else {}
        key_entries = self._ss._key_entries if self._ss else []
        anti_indicators = ss_config.get("anti_indicators", [])
        min_value_len = ss_config.get("min_value_length", 6)
        placeholder_values = self._ss._placeholder_values if self._ss else set()

        out: list[TextFinding] = []
        for key, value, value_start, value_end in pairs:
            if len(value) < min_value_len:
                continue
            if len(value) > 500:
                continue

            # Anti-indicators
            kv_lower = (key + value).lower()
            if any(ai.lower() in kv_lower for ai in anti_indicators):
                continue

            # Placeholder values
            if value.lower() in placeholder_values:
                continue
            if _is_placeholder_value(value):
                continue

            # Compound non-secret keys (e.g. "token_address", "key_type")
            if _is_compound_non_secret(key):
                continue

            # Score key name
            key_score, tier, subtype = _score_key_name(key, key_entries)
            if key_score <= 0:
                continue

            # Score value with tiered logic
            composite = self._ss._compute_tiered_score(key_score, tier, value)
            if composite <= 0:
                continue

            entity_type = subtype or "OPAQUE_SECRET"
            out.append(
                TextFinding(
                    entity_type=entity_type,
                    detection_type="",
                    display_name=entity_type,
                    category="Credential",
                    confidence=round(composite, 4),
                    engine="secret_scanner",
                    start=value_start,
                    end=value_end,
                    value_masked=_mask_value(value),
                    evidence=(f'secret_scanner: key "{key}" score={key_score:.2f} tier={tier}'),
                )
            )
        return out

    def _opaque_token_pass(self, text: str) -> list[TextFinding]:
        """Scan whitespace-delimited tokens for standalone high-entropy opaque secrets.

        Mirrors JS scanner-core.js ``opaqueTokenPass``.  Tokens must pass entropy
        and char-class diversity gates, and must not be UUIDs, placeholders, or
        obviously not secret.
        """
        out: list[TextFinding] = []
        ss_config = self._ss._config if self._ss else {}
        anti_indicators = ss_config.get("anti_indicators", [])

        for m in _TOKEN_RE.finditer(text):
            token = m.group(0)
            start = m.start()
            cleaned = _STRIP_RE.sub("", token)

            if len(cleaned) < _OPAQUE_MIN_LENGTH:
                continue
            # Real tokens/secrets are short — skip absurdly long tokens
            # (e.g. concatenated base64 blobs, minified code chunks)
            if len(cleaned) > 512:
                continue
            if _value_is_obviously_not_secret(cleaned):
                continue
            if _UUID_RE.match(cleaned):
                continue
            if _is_placeholder_value(cleaned):
                continue
            lower = cleaned.lower()
            if any(ai.lower() in lower for ai in anti_indicators):
                continue

            rel = _compute_relative_entropy(cleaned)
            if rel < _OPAQUE_ENTROPY_THRESHOLD:
                continue
            diversity = compute_char_class_diversity(cleaned)
            if diversity < _OPAQUE_DIVERSITY_THRESHOLD:
                continue

            confidence = _OPAQUE_BASE_CONFIDENCE
            if rel > 0.85:
                confidence += 0.10
            if len(cleaned) > 24:
                confidence += 0.05
            confidence = min(confidence, _OPAQUE_MAX_CONFIDENCE)

            out.append(
                TextFinding(
                    entity_type="OPAQUE_SECRET",
                    detection_type="opaque_token",
                    display_name="Opaque Token",
                    category="Credential",
                    confidence=confidence,
                    engine="secret_scanner",
                    start=start,
                    end=start + len(token),
                    value_masked=_mask_value(cleaned),
                    evidence=(
                        f"secret_scanner: opaque token — rel_entropy={rel:.2f} diversity={diversity} len={len(cleaned)}"
                    ),
                )
            )
        return out

    @staticmethod
    def _dedup(findings: list[TextFinding]) -> list[TextFinding]:
        """Keep highest confidence per overlapping span."""
        sorted_f = sorted(findings, key=lambda f: -f.confidence)
        kept: list[TextFinding] = []
        for f in sorted_f:
            overlaps = any(f.start < k.end and f.end > k.start for k in kept)
            if not overlaps:
                kept.append(f)
        return sorted(kept, key=lambda f: f.start)


# Module-level singleton for convenience
_scanner: TextScanner | None = None


def scan_text(text: str, *, min_confidence: float = 0.3) -> TextScanResult:
    """Scan free text for credentials — convenience wrapper.

    Uses a module-level :class:`TextScanner` singleton (initialized on first call).
    For batch usage, create a :class:`TextScanner` directly to control lifecycle.
    """
    global _scanner
    if _scanner is None:
        _scanner = TextScanner()
        _scanner.startup()
    return _scanner.scan(text, min_confidence=min_confidence)
