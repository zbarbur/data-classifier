"""Tests for the heuristic statistics engine.

Covers:
- Pure signal computation functions (unit tests)
- SSN-like column detection (high cardinality, 9-digit uniform)
- ABA routing number detection (low cardinality, 9-digit uniform)
- High-entropy values are NOT flagged as CREDENTIAL (secret scanner owns that)
- Below min_samples guard
- Non-matching columns
- Engine registration in orchestrator
- Config loading
"""

from __future__ import annotations

import random
import string

import pytest

from data_classifier.config import load_engine_config
from data_classifier.core.types import ClassificationFinding, ClassificationProfile, ColumnInput, ColumnStats
from data_classifier.engines.heuristic_engine import (
    HeuristicEngine,
    compute_avg_entropy,
    compute_cardinality_ratio,
    compute_char_class_ratios,
    compute_length_stats,
    compute_shannon_entropy,
)
from data_classifier.orchestrator.orchestrator import Orchestrator

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def engine() -> HeuristicEngine:
    """Create and start a HeuristicEngine."""
    e = HeuristicEngine()
    e.startup()
    return e


@pytest.fixture
def empty_profile() -> ClassificationProfile:
    """Minimal profile — heuristic engine doesn't use profile rules."""
    return ClassificationProfile(name="test", description="test profile", rules=[])


def _make_ssn_samples(n: int = 60) -> list[str]:
    """Generate n unique 9-digit SSN-like strings."""
    rng = random.Random(42)
    values = set()
    while len(values) < n:
        values.add(f"{rng.randint(100000000, 999999999)}")
    return list(values)


def _make_aba_samples(n: int = 60) -> list[str]:
    """Generate n samples with very low cardinality (3 unique ABA routing numbers repeated)."""
    routing_numbers = ["021000021", "121042882", "021200339"]
    rng = random.Random(42)
    return [rng.choice(routing_numbers) for _ in range(n)]


def _make_high_entropy_samples(n: int = 60) -> list[str]:
    """Generate n random hex+special strings with high entropy."""
    rng = random.Random(42)
    chars = string.ascii_letters + string.digits + "!@#$%^&*()-_=+[]{}|;:',.<>?/"
    return ["".join(rng.choices(chars, k=32)) for _ in range(n)]


def _make_text_samples(n: int = 60) -> list[str]:
    """Generate n generic text values — should not trigger any rule."""
    words = ["hello", "world", "foo", "bar", "baz", "testing", "data", "value", "record", "item"]
    rng = random.Random(42)
    return [" ".join(rng.choices(words, k=rng.randint(2, 5))) for _ in range(n)]


# ── Signal computation unit tests ──────────────────────────────────────────


class TestComputeCardinalityRatio:
    def test_empty(self):
        assert compute_cardinality_ratio([]) == 0.0

    def test_all_unique(self):
        assert compute_cardinality_ratio(["a", "b", "c", "d"]) == 1.0

    def test_all_same(self):
        assert compute_cardinality_ratio(["x", "x", "x", "x"]) == 0.25

    def test_mixed(self):
        # 3 unique out of 6
        ratio = compute_cardinality_ratio(["a", "b", "c", "a", "b", "c"])
        assert ratio == pytest.approx(0.5)


class TestComputeShannonEntropy:
    def test_empty_string(self):
        assert compute_shannon_entropy("") == 0.0

    def test_single_char(self):
        assert compute_shannon_entropy("aaaa") == 0.0

    def test_two_chars_equal(self):
        # "ab" → each char prob 0.5, entropy = 1.0 bit/char
        assert compute_shannon_entropy("ab") == pytest.approx(1.0)

    def test_higher_entropy(self):
        # More distinct chars → higher entropy
        e1 = compute_shannon_entropy("aabb")
        e2 = compute_shannon_entropy("abcd")
        assert e2 > e1

    def test_known_value(self):
        # "aab": a=2/3, b=1/3 → -(2/3*log2(2/3) + 1/3*log2(1/3)) ≈ 0.918
        assert compute_shannon_entropy("aab") == pytest.approx(0.9183, abs=0.001)


class TestComputeAvgEntropy:
    def test_empty(self):
        assert compute_avg_entropy([]) == 0.0

    def test_single_value(self):
        assert compute_avg_entropy(["abcd"]) == pytest.approx(compute_shannon_entropy("abcd"))

    def test_average(self):
        values = ["aaaa", "abcd"]
        avg = compute_avg_entropy(values)
        expected = (compute_shannon_entropy("aaaa") + compute_shannon_entropy("abcd")) / 2
        assert avg == pytest.approx(expected)


class TestComputeLengthStats:
    def test_empty(self):
        stats = compute_length_stats([])
        assert stats["uniform"] is True
        assert stats["mean"] == 0.0

    def test_uniform_lengths(self):
        stats = compute_length_stats(["abc", "def", "ghi"])
        assert stats["uniform"] is True
        assert stats["mean"] == 3.0
        assert stats["stddev"] == 0.0
        assert stats["min"] == 3
        assert stats["max"] == 3

    def test_variable_lengths(self):
        stats = compute_length_stats(["a", "ab", "abc"])
        assert stats["uniform"] is False
        assert stats["min"] == 1
        assert stats["max"] == 3
        assert stats["mean"] == pytest.approx(2.0)
        assert stats["stddev"] > 0


class TestComputeCharClassRatios:
    def test_empty(self):
        ratios = compute_char_class_ratios([])
        assert ratios["digit_ratio"] == 0.0

    def test_all_digits(self):
        ratios = compute_char_class_ratios(["123", "456", "789"])
        assert ratios["digit_ratio"] == pytest.approx(1.0)
        assert ratios["alpha_ratio"] == 0.0

    def test_all_alpha(self):
        ratios = compute_char_class_ratios(["abc", "def", "ghi"])
        assert ratios["alpha_ratio"] == pytest.approx(1.0)
        assert ratios["digit_ratio"] == 0.0

    def test_mixed_alnum(self):
        ratios = compute_char_class_ratios(["abc123", "def456"])
        assert ratios["alnum_ratio"] == pytest.approx(1.0)

    def test_special_chars(self):
        ratios = compute_char_class_ratios(["abc@123", "def#456"])
        assert ratios["special_ratio"] == pytest.approx(1.0)


# ── Engine classification tests ────────────────────────────────────────────


class TestSSNDetection:
    """High cardinality + all-digits + uniform length 9 → SSN."""

    def test_ssn_like_column(self, engine: HeuristicEngine, empty_profile: ClassificationProfile):
        samples = _make_ssn_samples(60)
        column = ColumnInput(column_name="some_id", column_id="col1", sample_values=samples)

        findings = engine.classify_column(column, profile=empty_profile)

        ssn_findings = [f for f in findings if f.entity_type == "SSN"]
        assert len(ssn_findings) == 1
        assert ssn_findings[0].confidence >= 0.80
        assert ssn_findings[0].engine == "heuristic_stats"
        assert ssn_findings[0].category == "PII"
        assert ssn_findings[0].sensitivity == "CRITICAL"

    def test_ssn_with_column_stats(self, engine: HeuristicEngine, empty_profile: ClassificationProfile):
        """When ColumnStats is provided, use its cardinality over sample-computed."""
        samples = _make_ssn_samples(60)
        stats = ColumnStats(distinct_count=9500, total_count=10000)
        column = ColumnInput(column_name="identifier", column_id="col2", sample_values=samples, stats=stats)

        findings = engine.classify_column(column, profile=empty_profile)

        ssn_findings = [f for f in findings if f.entity_type == "SSN"]
        assert len(ssn_findings) == 1
        assert ssn_findings[0].confidence >= 0.80


class TestABARoutingDetection:
    """Low cardinality + all-digits + uniform length 9 → ABA_ROUTING."""

    def test_aba_like_column(self, engine: HeuristicEngine, empty_profile: ClassificationProfile):
        samples = _make_aba_samples(60)
        column = ColumnInput(column_name="routing", column_id="col3", sample_values=samples)

        findings = engine.classify_column(column, profile=empty_profile)

        aba_findings = [f for f in findings if f.entity_type == "ABA_ROUTING"]
        assert len(aba_findings) == 1
        assert aba_findings[0].confidence >= 0.75
        assert aba_findings[0].engine == "heuristic_stats"
        assert aba_findings[0].category == "Financial"
        assert aba_findings[0].sensitivity == "HIGH"

    def test_aba_does_not_produce_ssn(self, engine: HeuristicEngine, empty_profile: ClassificationProfile):
        """Low cardinality should NOT trigger SSN rule."""
        samples = _make_aba_samples(60)
        column = ColumnInput(column_name="routing", column_id="col4", sample_values=samples)

        findings = engine.classify_column(column, profile=empty_profile)

        ssn_findings = [f for f in findings if f.entity_type == "SSN"]
        assert len(ssn_findings) == 0


class TestNoCredentialFromHeuristic:
    """Heuristic engine does NOT produce CREDENTIAL findings — secret scanner owns that."""

    def test_high_entropy_column_no_credential(self, engine: HeuristicEngine, empty_profile: ClassificationProfile):
        """High-entropy column should NOT be flagged as CREDENTIAL by heuristic engine."""
        samples = _make_high_entropy_samples(60)
        column = ColumnInput(column_name="token_value", column_id="col5", sample_values=samples)

        findings = engine.classify_column(column, profile=empty_profile)

        cred_findings = [f for f in findings if f.entity_type == "CREDENTIAL"]
        assert len(cred_findings) == 0


class TestEdgeCases:
    """Edge cases and guard rails."""

    def test_below_min_samples(self, engine: HeuristicEngine, empty_profile: ClassificationProfile):
        """Fewer than min_samples → empty results."""
        samples = _make_ssn_samples(5)[:5]
        column = ColumnInput(column_name="ssn", column_id="col6", sample_values=samples)

        findings = engine.classify_column(column, profile=empty_profile)
        assert findings == []

    def test_empty_samples(self, engine: HeuristicEngine, empty_profile: ClassificationProfile):
        column = ColumnInput(column_name="ssn", column_id="col7", sample_values=[])

        findings = engine.classify_column(column, profile=empty_profile)
        assert findings == []

    def test_non_matching_text(self, engine: HeuristicEngine, empty_profile: ClassificationProfile):
        """Generic text values should not trigger any rule."""
        samples = _make_text_samples(60)
        column = ColumnInput(column_name="notes", column_id="col8", sample_values=samples)

        findings = engine.classify_column(column, profile=empty_profile)
        assert findings == []

    def test_min_confidence_filter(self, engine: HeuristicEngine, empty_profile: ClassificationProfile):
        """Findings below min_confidence are not returned."""
        samples = _make_ssn_samples(60)
        column = ColumnInput(column_name="id", column_id="col9", sample_values=samples)

        findings = engine.classify_column(column, profile=empty_profile, min_confidence=0.99)
        assert findings == []


# ── Engine registration and config ─────────────────────────────────────────


class TestEngineRegistration:
    def test_engine_in_default_engines(self):
        """HeuristicEngine should be in the default engine list."""
        from data_classifier import _DEFAULT_ENGINES

        engine_names = [e.name for e in _DEFAULT_ENGINES]
        assert "heuristic_stats" in engine_names

    def test_engine_order(self):
        """HeuristicEngine should have order=3 (after column_name=1, regex=2)."""
        e = HeuristicEngine()
        assert e.order == 3

    def test_supported_modes(self):
        e = HeuristicEngine()
        assert "structured" in e.supported_modes


class TestConfigLoading:
    def test_load_engine_config(self):
        config = load_engine_config()
        assert "heuristic_engine" in config
        assert "min_samples" in config["heuristic_engine"]
        assert "signals" in config["heuristic_engine"]

    def test_config_thresholds(self):
        config = load_engine_config()
        signals = config["heuristic_engine"]["signals"]
        assert signals["cardinality"]["low_threshold"] == 0.05
        assert signals["cardinality"]["high_threshold"] == 0.80
        assert signals["entropy"]["high_threshold"] == 4.0
        assert signals["length"]["consistency_threshold"] == 0.95

    def test_secret_scanner_placeholder(self):
        config = load_engine_config()
        assert "secret_scanner" in config


# ── Collision resolution tests ─────────────────────────────────────────────


class TestCollisionResolution:
    """Orchestrator _resolve_collisions suppresses the weaker of SSN/ABA_ROUTING.

    These tests exercise the method in isolation by constructing ``findings``
    dicts directly — no engines need to run.
    """

    def _make_finding(self, entity_type: str, confidence: float) -> ClassificationFinding:
        return ClassificationFinding(
            column_id="col_test",
            entity_type=entity_type,
            category="Test",
            sensitivity="HIGH",
            confidence=confidence,
            regulatory=[],
            engine="test",
        )

    @pytest.fixture
    def orchestrator(self) -> Orchestrator:
        return Orchestrator(engines=[])

    def test_ssn_wins_over_aba(self, orchestrator):
        """SSN=0.85 + ABA=0.60 → gap 0.25 ≥ 0.15, ABA suppressed."""
        findings = {
            "SSN": self._make_finding("SSN", 0.85),
            "ABA_ROUTING": self._make_finding("ABA_ROUTING", 0.60),
        }
        result = orchestrator._resolve_collisions(findings)
        assert "SSN" in result
        assert "ABA_ROUTING" not in result

    def test_aba_wins_over_ssn(self, orchestrator):
        """ABA=0.85 + SSN=0.60 → gap 0.25 ≥ 0.15, SSN suppressed."""
        findings = {
            "SSN": self._make_finding("SSN", 0.60),
            "ABA_ROUTING": self._make_finding("ABA_ROUTING", 0.85),
        }
        result = orchestrator._resolve_collisions(findings)
        assert "ABA_ROUTING" in result
        assert "SSN" not in result

    def test_small_gap_keeps_both(self, orchestrator):
        """SSN=0.65 + ABA=0.60 → gap 0.05 < 0.15, both kept (ambiguous)."""
        findings = {
            "SSN": self._make_finding("SSN", 0.65),
            "ABA_ROUTING": self._make_finding("ABA_ROUTING", 0.60),
        }
        result = orchestrator._resolve_collisions(findings)
        assert "SSN" in result
        assert "ABA_ROUTING" in result

    def test_exact_threshold_gap_suppresses(self, orchestrator):
        """Gap exactly equal to threshold (0.15) triggers suppression."""
        findings = {
            "SSN": self._make_finding("SSN", 0.75),
            "ABA_ROUTING": self._make_finding("ABA_ROUTING", 0.60),
        }
        result = orchestrator._resolve_collisions(findings)
        assert "SSN" in result
        assert "ABA_ROUTING" not in result

    def test_only_ssn_no_change(self, orchestrator):
        """Only SSN present → no collision pair, no change."""
        findings = {"SSN": self._make_finding("SSN", 0.85)}
        result = orchestrator._resolve_collisions(findings)
        assert result == {"SSN": findings["SSN"]}

    def test_only_aba_no_change(self, orchestrator):
        """Only ABA_ROUTING present → no collision pair, no change."""
        findings = {"ABA_ROUTING": self._make_finding("ABA_ROUTING", 0.80)}
        result = orchestrator._resolve_collisions(findings)
        assert result == {"ABA_ROUTING": findings["ABA_ROUTING"]}

    def test_neither_ssn_nor_aba_no_change(self, orchestrator):
        """Unrelated entity types → no collision pair, unchanged."""
        findings = {
            "EMAIL": self._make_finding("EMAIL", 0.90),
            "PHONE": self._make_finding("PHONE", 0.70),
        }
        result = orchestrator._resolve_collisions(findings)
        assert set(result.keys()) == {"EMAIL", "PHONE"}
