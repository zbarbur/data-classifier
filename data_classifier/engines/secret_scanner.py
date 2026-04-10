"""Structured Secret Scanner Engine — detects secrets in structured content.

Finds credentials embedded in JSON, YAML, env files, and code string literals
by combining key-name scoring with Shannon entropy analysis.  Catches secrets
that regex engines cannot detect — values with no known prefix or format,
identified only by their key name and high entropy.

Example detections:
  - ``"db_password": "kJ#9xMp$2wLq!"`` — key name + high entropy
  - ``export API_TOKEN=a8f3b2c1d4e5`` — env var name + entropy
  - ``password = "SuperSecret123!"`` — code literal assignment

Order 4 in the engine cascade (after heuristic_stats).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from data_classifier.config import load_engine_config
from data_classifier.core.types import (
    ClassificationFinding,
    ClassificationProfile,
    ColumnInput,
    SampleAnalysis,
)
from data_classifier.engines.heuristic_engine import compute_shannon_entropy
from data_classifier.engines.interface import ClassificationEngine
from data_classifier.engines.parsers import parse_key_values

logger = logging.getLogger(__name__)

_SECRET_KEY_NAMES_FILE = Path(__file__).parent.parent / "patterns" / "secret_key_names.json"

# Known example/placeholder values that should never be flagged
_KNOWN_EXAMPLES: frozenset[str] = frozenset(
    {
        "akiaiosfodnn7example",
        "changeme",
        "password123",
        "password",
        "passw0rd",
        "p@ssw0rd",
        "admin",
        "root",
        "default",
        "12345678",
        "123456789",
        "1234567890",
        "abcdefgh",
        "qwerty123",
        "letmein",
        "welcome1",
        "abc12345",
        "your_api_key_here",
        "your_secret_here",
        "xxx",
        "xxxxxxxx",
        "todo",
        "fixme",
        "replace_me",
        "insert_here",
        "put_your_key_here",
    }
)


def _detect_charset(value: str) -> str:
    """Detect the character set of a value for entropy threshold selection.

    Args:
        value: The string to analyze.

    Returns:
        One of ``"hex"``, ``"base64"``, or ``"alphanumeric"``.
    """
    # Check hex: 0-9, a-f (case-insensitive)
    if re.fullmatch(r"[0-9a-fA-F]+", value):
        return "hex"
    # Check base64: A-Za-z0-9+/= (with optional padding)
    if re.fullmatch(r"[A-Za-z0-9+/=]+", value):
        return "base64"
    return "alphanumeric"


def _score_value_entropy(value: str, thresholds: dict) -> float:
    """Score a value based on Shannon entropy relative to its character set.

    Values below the charset-specific threshold score 0.0.  Values above
    scale linearly from 0.5 to 1.0 based on how far they exceed the threshold.

    Args:
        value: The value string to score.
        thresholds: Dict mapping charset names to entropy thresholds.

    Returns:
        Score between 0.0 and 1.0.
    """
    entropy = compute_shannon_entropy(value)
    charset = _detect_charset(value)
    threshold = thresholds.get(charset, 4.0)
    if entropy < threshold:
        return 0.0
    # Scale 0.0-1.0 based on how far above threshold
    return min(1.0, 0.5 + 0.5 * (entropy - threshold) / 2.0)


def _score_key_name(key: str, key_entries: list[dict]) -> float:
    """Score a key name against the secret key-name dictionary.

    Performs case-insensitive substring matching: if any pattern appears
    as a substring of the key (after lowering), its score is used.
    Returns the highest matching score.

    Args:
        key: The key name to score (e.g. ``"DB_PASSWORD"``).
        key_entries: List of dicts with ``pattern`` and ``score`` keys.

    Returns:
        Score between 0.0 and 1.0.  0.0 if no pattern matches.
    """
    key_lower = key.lower()
    best_score = 0.0
    for entry in key_entries:
        pattern = entry["pattern"]
        if pattern in key_lower:
            if entry["score"] > best_score:
                best_score = entry["score"]
    return best_score


class SecretScannerEngine(ClassificationEngine):
    """Structured secret scanner — order 4 in the cascade.

    Detects credentials embedded in structured content (JSON, YAML, env
    files, code literals) by combining key-name scoring with Shannon
    entropy analysis.  Catches secrets that regex cannot detect.
    """

    name = "secret_scanner"
    order = 4
    min_confidence = 0.0
    supported_modes = frozenset({"structured", "unstructured"})

    def __init__(self) -> None:
        self._config: dict | None = None
        self._key_entries: list[dict] | None = None

    def startup(self) -> None:
        """Load engine configuration and key-name dictionary."""
        full_config = load_engine_config()
        self._config = full_config.get("secret_scanner", {})
        self._key_entries = _load_key_names()
        logger.info("SecretScannerEngine: loaded %d key-name patterns", len(self._key_entries))

    def _ensure_config(self) -> None:
        """Lazily load config if startup() was not called."""
        if self._config is None or self._key_entries is None:
            self.startup()

    def classify_column(
        self,
        column: ColumnInput,
        *,
        profile: ClassificationProfile | None = None,
        min_confidence: float = 0.5,
        mask_samples: bool = False,
        max_evidence_samples: int = 5,
    ) -> list[ClassificationFinding]:
        """Classify a column by scanning sample values for embedded secrets.

        For each sample value, parses key-value pairs and scores them
        using key-name matching and Shannon entropy analysis.

        Returns findings for columns where embedded credentials are detected.
        """
        self._ensure_config()

        if not column.sample_values:
            return []

        thresholds = self._config.get("entropy_thresholds", {})
        min_value_length = self._config.get("min_value_length", 8)
        anti_indicators = self._config.get("anti_indicators", [])

        matched_samples: list[str] = []
        best_confidence = 0.0
        best_evidence = ""
        samples_scanned = 0

        for sample in column.sample_values:
            if not sample:
                continue
            samples_scanned += 1

            kv_pairs = parse_key_values(sample)
            if not kv_pairs:
                continue

            for key, value in kv_pairs:
                # Skip short values
                if len(value) < min_value_length:
                    continue

                # Anti-indicator suppression on key and value
                if self._has_anti_indicator(key, value, anti_indicators):
                    continue

                # Known example suppression
                if value.lower() in _KNOWN_EXAMPLES:
                    continue

                # Score the key name
                key_score = _score_key_name(key, self._key_entries)
                if key_score <= 0.0:
                    continue

                # Score the value entropy
                entropy_score = _score_value_entropy(value, thresholds)
                if entropy_score <= 0.0:
                    continue

                # Composite score
                composite = key_score * entropy_score
                if composite >= min_confidence:
                    if composite > best_confidence:
                        best_confidence = composite
                        entropy = compute_shannon_entropy(value)
                        charset = _detect_charset(value)
                        best_evidence = (
                            f"Secret scanner: key '{key}' (score={key_score:.2f}) "
                            f"with {charset} entropy={entropy:.2f} bits/char "
                            f"(score={entropy_score:.2f}), composite={composite:.2f}"
                        )
                    if len(matched_samples) < max_evidence_samples:
                        display_value = _mask_value(value) if mask_samples else value
                        matched_samples.append(f"{key}={display_value}")

        if best_confidence < min_confidence:
            return []

        sample_analysis = SampleAnalysis(
            samples_scanned=samples_scanned,
            samples_matched=len(matched_samples),
            samples_validated=len(matched_samples),
            match_ratio=len(matched_samples) / max(samples_scanned, 1),
            sample_matches=matched_samples,
        )

        return [
            ClassificationFinding(
                column_id=column.column_id,
                entity_type="CREDENTIAL",
                category="Credential",
                sensitivity="CRITICAL",
                confidence=round(best_confidence, 4),
                regulatory=["SOC2", "ISO27001"],
                engine=self.name,
                evidence=best_evidence,
                sample_analysis=sample_analysis,
            )
        ]

    @staticmethod
    def _has_anti_indicator(key: str, value: str, anti_indicators: list[str]) -> bool:
        """Check if key or value contains any anti-indicator substring.

        Args:
            key: The key name.
            value: The value string.
            anti_indicators: List of substrings that suppress findings.

        Returns:
            True if any anti-indicator is found in key or value.
        """
        key_lower = key.lower()
        value_lower = value.lower()
        for indicator in anti_indicators:
            indicator_lower = indicator.lower()
            if indicator_lower in key_lower or indicator_lower in value_lower:
                return True
        return False


def _mask_value(value: str) -> str:
    """Mask a value for evidence display, showing only first/last 2 chars.

    Args:
        value: The value to mask.

    Returns:
        Masked string like ``"kJ***q!"``.
    """
    if len(value) <= 4:
        return "***"
    return value[:2] + "***" + value[-2:]


def _load_key_names() -> list[dict]:
    """Load secret key-name patterns from JSON file.

    Returns:
        List of dicts with ``pattern``, ``score``, and ``category`` keys.
    """
    with open(_SECRET_KEY_NAMES_FILE) as fh:
        raw = json.load(fh)
    return raw["key_names"]
