"""Heuristic statistics engine — classifies columns by value distribution signals.

Analyzes sample value distributions (cardinality, entropy, length consistency,
character class ratios) to produce classification findings.  Key use case:
disambiguating SSN vs ABA routing numbers — high cardinality implies SSN
(unique per person), low cardinality implies ABA (few bank routing numbers
reused across rows).

This engine produces standalone findings.  The orchestrator's "highest
confidence wins" deduplication handles disambiguation naturally when
combined with regex engine findings.
"""

from __future__ import annotations

import logging
import math
from collections import Counter

from data_classifier.config import load_engine_config
from data_classifier.core.types import (
    ClassificationFinding,
    ClassificationProfile,
    ColumnInput,
)
from data_classifier.engines.interface import ClassificationEngine

logger = logging.getLogger(__name__)


# ── Pure signal computation functions ───────────────────────────────────────


def compute_cardinality_ratio(values: list[str]) -> float:
    """Compute ratio of unique values to total values.

    Args:
        values: Sample values from the column.

    Returns:
        Float between 0.0 and 1.0.  1.0 means every value is unique.
    """
    if not values:
        return 0.0
    return len(set(values)) / len(values)


def compute_shannon_entropy(value: str) -> float:
    """Compute Shannon entropy in bits per character for a single value.

    Args:
        value: A single string value.

    Returns:
        Entropy in bits/char.  Higher means more random/uniform distribution.
    """
    if not value:
        return 0.0
    counts = Counter(value)
    length = len(value)
    entropy = 0.0
    for count in counts.values():
        prob = count / length
        if prob > 0:
            entropy -= prob * math.log2(prob)
    return entropy


def compute_avg_entropy(values: list[str]) -> float:
    """Compute average Shannon entropy across all values.

    Args:
        values: Sample values from the column.

    Returns:
        Average entropy in bits/char.
    """
    if not values:
        return 0.0
    entropies = [compute_shannon_entropy(v) for v in values if v]
    if not entropies:
        return 0.0
    return sum(entropies) / len(entropies)


def compute_length_stats(values: list[str]) -> dict:
    """Compute length distribution statistics.

    Args:
        values: Sample values from the column.

    Returns:
        Dict with keys: mean, stddev, min, max, uniform (bool).
        ``uniform`` is True when all values have the same length.
    """
    if not values:
        return {"mean": 0.0, "stddev": 0.0, "min": 0, "max": 0, "uniform": True}

    lengths = [len(v) for v in values]
    n = len(lengths)
    mean = sum(lengths) / n
    variance = sum((ln - mean) ** 2 for ln in lengths) / n
    stddev = math.sqrt(variance)
    min_len = min(lengths)
    max_len = max(lengths)
    uniform = min_len == max_len

    return {
        "mean": mean,
        "stddev": stddev,
        "min": min_len,
        "max": max_len,
        "uniform": uniform,
    }


def compute_char_class_ratios(values: list[str]) -> dict:
    """Compute character class ratios across all values.

    For each value, determine its dominant character class, then compute the
    fraction of values in each class.

    Args:
        values: Sample values from the column.

    Returns:
        Dict with keys: digit_ratio, alpha_ratio, alnum_ratio, special_ratio.
        Each is the fraction of values that are purely that class.
    """
    if not values:
        return {"digit_ratio": 0.0, "alpha_ratio": 0.0, "alnum_ratio": 0.0, "special_ratio": 0.0}

    n = len(values)
    digit_count = 0
    alpha_count = 0
    alnum_count = 0
    special_count = 0

    for v in values:
        if not v:
            continue
        if v.isdigit():
            digit_count += 1
        elif v.isalpha():
            alpha_count += 1
        elif v.isalnum():
            alnum_count += 1
        else:
            special_count += 1

    return {
        "digit_ratio": digit_count / n,
        "alpha_ratio": alpha_count / n,
        "alnum_ratio": alnum_count / n,
        "special_ratio": special_count / n,
    }


# ── Engine ──────────────────────────────────────────────────────────────────


class HeuristicEngine(ClassificationEngine):
    """Heuristic statistics engine — order 3 in the cascade.

    Analyzes column sample value distributions to produce classification
    findings based on cardinality, entropy, length consistency, and
    character class ratios.
    """

    name = "heuristic_stats"
    order = 3
    min_confidence = 0.0
    supported_modes = frozenset({"structured"})

    def __init__(self) -> None:
        self._config: dict | None = None

    def startup(self) -> None:
        """Load engine configuration from engine_defaults.yaml."""
        full_config = load_engine_config()
        self._config = full_config.get("heuristic_engine", {})

    def _ensure_config(self) -> None:
        """Lazily load config if startup() was not called."""
        if self._config is None:
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
        """Classify a column using heuristic statistical signals.

        Returns findings based on cardinality, entropy, length, and
        character class analysis of sample values.
        """
        self._ensure_config()

        min_samples = self._config["min_samples"]
        signals_config = self._config["signals"]
        cardinality_config = signals_config["cardinality"]
        entropy_config = signals_config["entropy"]
        char_class_config = signals_config["char_class"]

        # Thresholds from config — no hardcoded fallbacks
        low_cardinality = cardinality_config["low_threshold"]
        high_cardinality = cardinality_config["high_threshold"]
        high_entropy = entropy_config["high_threshold"]
        digit_purity = char_class_config["digit_purity_threshold"]
        mixed_char_threshold = char_class_config["mixed_char_threshold"]

        values = column.sample_values

        # Check minimum sample count
        if len(values) < min_samples:
            return []

        # Compute signals
        cardinality = compute_cardinality_ratio(values)
        avg_entropy = compute_avg_entropy(values)
        length_stats = compute_length_stats(values)
        char_ratios = compute_char_class_ratios(values)

        # Use ColumnStats if available for cardinality (connector pre-computed)
        if column.stats and column.stats.total_count > 0 and column.stats.distinct_count > 0:
            cardinality = column.stats.distinct_count / column.stats.total_count

        findings: list[ClassificationFinding] = []

        # ── Rule: High cardinality + all-digits + uniform length 9 → SSN ──
        if (
            cardinality >= high_cardinality
            and char_ratios["digit_ratio"] >= digit_purity
            and length_stats["uniform"]
            and length_stats["mean"] == 9
        ):
            confidence = 0.70 + 0.15 * cardinality  # 0.82-0.85 for high cardinality
            confidence = min(confidence, 0.95)
            if confidence >= min_confidence:
                findings.append(
                    ClassificationFinding(
                        column_id=column.column_id,
                        entity_type="SSN",
                        category="PII",
                        sensitivity="CRITICAL",
                        confidence=round(confidence, 4),
                        regulatory=["HIPAA", "CCPA", "GDPR"],
                        engine=self.name,
                        evidence=(
                            f"Heuristic: cardinality={cardinality:.2f} (high), "
                            f"uniform length=9, digit_ratio={char_ratios['digit_ratio']:.2f}"
                        ),
                    )
                )

        # ── Rule: Low cardinality + all-digits + uniform length 9 → ABA_ROUTING ──
        if (
            cardinality <= low_cardinality
            and char_ratios["digit_ratio"] >= digit_purity
            and length_stats["uniform"]
            and length_stats["mean"] == 9
        ):
            confidence = 0.75 + 0.10 * (1.0 - cardinality)  # higher when more repeated
            confidence = min(confidence, 0.90)
            if confidence >= min_confidence:
                findings.append(
                    ClassificationFinding(
                        column_id=column.column_id,
                        entity_type="ABA_ROUTING",
                        category="Financial",
                        sensitivity="HIGH",
                        confidence=round(confidence, 4),
                        regulatory=["GLBA", "PCI-DSS"],
                        engine=self.name,
                        evidence=(
                            f"Heuristic: cardinality={cardinality:.2f} (low), "
                            f"uniform length=9, digit_ratio={char_ratios['digit_ratio']:.2f}"
                        ),
                    )
                )

        # ── Rule: High entropy + mixed chars → CREDENTIAL ──
        if (
            avg_entropy >= high_entropy
            and char_ratios["special_ratio"] + char_ratios["alnum_ratio"] >= mixed_char_threshold
        ):
            confidence = 0.60 + 0.08 * (avg_entropy - high_entropy)
            confidence = min(confidence, 0.90)
            if confidence >= min_confidence:
                findings.append(
                    ClassificationFinding(
                        column_id=column.column_id,
                        entity_type="CREDENTIAL",
                        category="Credential",
                        sensitivity="CRITICAL",
                        confidence=round(confidence, 4),
                        regulatory=["SOC2", "ISO27001"],
                        engine=self.name,
                        evidence=(
                            f"Heuristic: avg_entropy={avg_entropy:.2f} bits/char (high), "
                            f"mixed chars (alnum={char_ratios['alnum_ratio']:.2f}, "
                            f"special={char_ratios['special_ratio']:.2f})"
                        ),
                    )
                )

        return findings
