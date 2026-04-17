"""Vague column name corpus tests — validates classification when column names are uninformative.

Real BigQuery tables often have generic column names (field_1, data, value, col1, etc.)
that provide zero signal to the column_name_engine. These tests ensure the classifier
still detects PII through content analysis alone, and that the column-shape router
assigns the correct branch.

Corpus: tests/fixtures/vague_column_corpus.json
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from data_classifier import ColumnInput
from data_classifier.engines.column_name_engine import ColumnNameEngine
from data_classifier.engines.heuristic_engine import HeuristicEngine
from data_classifier.engines.regex_engine import RegexEngine
from data_classifier.engines.secret_scanner import SecretScannerEngine
from data_classifier.orchestrator.orchestrator import Orchestrator
from data_classifier.orchestrator.shape_detector import detect_column_shape


def _classify_no_ml(columns, profile, **kwargs):
    """Classify columns WITHOUT GLiNER — tests cascade/router behavior only.

    Uses an explicit engine list to avoid the module-level _DEFAULT_ENGINES
    cache which may already include GLiNER from other tests in the session.
    """
    engines = [ColumnNameEngine(), RegexEngine(), HeuristicEngine(), SecretScannerEngine()]
    orch = Orchestrator(engines=engines, mode="structured")
    results = []
    for col in columns:
        results.extend(orch.classify_column(col, profile, **kwargs))
    return results


logger = logging.getLogger(__name__)

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_corpus() -> list[dict]:
    with open(_FIXTURES_DIR / "vague_column_corpus.json") as f:
        data = json.load(f)
    return data["columns"]


_CORPUS = _load_corpus()

# ── Partition columns by test type ──────────────────────────────────────────

_STRUCTURED_CASES = [
    c
    for c in _CORPUS
    if c["expected_router_branch"] == "structured_single"
    and not c.get("expected_no_finding")
    and c.get("expected_entity_type") is not None
]
_HETERO_CASES = [
    c for c in _CORPUS if c["expected_router_branch"] == "free_text_heterogeneous" and not c.get("expected_no_finding")
]
# Non-structured cases with a specific expected entity type (opaque tokens, URLs, BTC, etc.)
_SPECIFIC_NONSTRUCTURED_CASES = [
    c
    for c in _CORPUS
    if c["expected_router_branch"] != "structured_single"
    and not c.get("expected_no_finding")
    and c.get("expected_entity_type") is not None
    and c.get("expected_entity_types_any") is None
]
_NEGATIVE_CASES = [c for c in _CORPUS if c.get("expected_no_finding")]
_ALL_CASES = _CORPUS


# ── Helper ──────────────────────────────────────────────────────────────────


def _make_column(case: dict) -> ColumnInput:
    return ColumnInput(
        column_name=case["column_name"],
        column_id=case["id"],
        sample_values=case["sample_values"],
    )


# ── Router branch assignment tests ──────────────────────────────────────────


@pytest.mark.parametrize("case", _ALL_CASES, ids=[c["id"] for c in _ALL_CASES])
def test_router_branch_assignment(case, standard_profile):
    """Verify the column-shape router assigns the expected branch."""
    column = _make_column(case)
    findings = _classify_no_ml([column], standard_profile, min_confidence=0.0)
    shape = detect_column_shape(column, findings)
    assert shape.shape == case["expected_router_branch"], (
        f"Column '{case['column_name']}' (id={case['id']}): "
        f"expected branch '{case['expected_router_branch']}', got '{shape.shape}' "
        f"(avg_len={shape.avg_len_normalized:.3f}, dict_ratio={shape.dict_word_ratio:.3f}, "
        f"n_entities={shape.n_cascade_entities})"
    )


# ── Structured single: exact entity type ────────────────────────────────────


@pytest.mark.parametrize("case", _STRUCTURED_CASES, ids=[c["id"] for c in _STRUCTURED_CASES])
def test_structured_single_entity_detection(case, standard_profile):
    """Vague-named structured columns must detect the correct entity type from content alone."""
    column = _make_column(case)
    findings = _classify_no_ml([column], standard_profile, min_confidence=0.0)

    expected = case["expected_entity_type"]
    entity_types = [f.entity_type for f in findings]

    assert expected in entity_types, (
        f"Column '{case['column_name']}' (id={case['id']}): expected {expected} in findings, got {entity_types}"
    )

    # The expected type should be the primary (highest-confidence) finding
    top_finding = max(findings, key=lambda f: f.confidence)
    assert top_finding.entity_type == expected, (
        f"Column '{case['column_name']}' (id={case['id']}): "
        f"expected {expected} as primary finding, got {top_finding.entity_type} "
        f"(confidence={top_finding.confidence:.3f})"
    )


@pytest.mark.parametrize("case", _STRUCTURED_CASES, ids=[c["id"] for c in _STRUCTURED_CASES])
def test_structured_single_match_ratio(case, standard_profile):
    """Structured single-entity columns should have high match_ratio from content."""
    column = _make_column(case)
    findings = _classify_no_ml([column], standard_profile, min_confidence=0.0)

    expected = case["expected_entity_type"]
    matching = [f for f in findings if f.entity_type == expected]
    assert matching, f"No finding for {expected} on column {case['id']}"

    finding = matching[0]
    if finding.sample_analysis is not None:
        # With vague column names, match_ratio is pure content prevalence.
        # Structured single columns should have most values matching.
        non_empty = [v for v in case["sample_values"] if v.strip()]
        if len(non_empty) >= 5:
            assert finding.sample_analysis.match_ratio >= 0.3, (
                f"Column '{case['column_name']}' (id={case['id']}): "
                f"match_ratio {finding.sample_analysis.match_ratio:.3f} too low for "
                f"structured single column with {len(non_empty)} non-empty values"
            )


# ── Free-text heterogeneous: multi-entity detection ─────────────────────────


@pytest.mark.parametrize("case", _HETERO_CASES, ids=[c["id"] for c in _HETERO_CASES])
def test_heterogeneous_detects_pii(case, standard_profile):
    """Free-text columns with embedded PII must detect at least one expected entity type."""
    column = _make_column(case)
    findings = _classify_no_ml([column], standard_profile, min_confidence=0.0)

    expected_any = case.get("expected_entity_types_any", [])
    entity_types = {f.entity_type for f in findings}

    if expected_any:
        found = entity_types & set(expected_any)
        assert found, (
            f"Column '{case['column_name']}' (id={case['id']}): "
            f"expected at least one of {expected_any}, got {sorted(entity_types)}"
        )


# ── Non-structured: specific entity type detection ──────────────────────────


@pytest.mark.parametrize("case", _SPECIFIC_NONSTRUCTURED_CASES, ids=[c["id"] for c in _SPECIFIC_NONSTRUCTURED_CASES])
def test_nonstructured_entity_detection(case, standard_profile):
    """Non-structured columns (opaque tokens, URLs, BTC) must detect the expected entity type."""
    column = _make_column(case)
    findings = _classify_no_ml([column], standard_profile, min_confidence=0.0)

    expected = case["expected_entity_type"]
    entity_types = [f.entity_type for f in findings]

    assert expected in entity_types, (
        f"Column '{case['column_name']}' (id={case['id']}): expected {expected} in findings, got {entity_types}"
    )


# ── Negative controls ──────────────────────────────────────────────────────


@pytest.mark.parametrize("case", _NEGATIVE_CASES, ids=[c["id"] for c in _NEGATIVE_CASES])
def test_negative_no_pii_detected(case, standard_profile):
    """Vague-named columns with no PII content should produce no findings."""
    column = _make_column(case)
    threshold = 0.5
    findings = _classify_no_ml([column], standard_profile, min_confidence=0.0)

    high_confidence = [f for f in findings if f.confidence >= threshold]
    assert not high_confidence, (
        f"Column '{case['column_name']}' (id={case['id']}): "
        f"expected no findings above {threshold}, got {[(f.entity_type, f.confidence) for f in high_confidence]}"
    )


# ── Column name engine provides no signal ───────────────────────────────────


def test_column_name_engine_gives_no_signal(standard_profile):
    """Verify that vague column names produce no column_name_engine findings."""
    from data_classifier.engines.column_name_engine import ColumnNameEngine

    engine = ColumnNameEngine()
    vague_names = [
        "field_1",
        "data",
        "value",
        "col1",
        "info",
        "column_a",
        "misc",
        "description",
        "notes",
        "content",
        "comments",
        "field_2",
        "value_hash",
        "session",
        "field_3",
        "col2",
        "memo",
        "col_x",
        "val",
        "code",
        "identifier",
        "ref",
        "col_b",
        "token_data",
        "field_4",
    ]
    for name in vague_names:
        column = ColumnInput(column_name=name, column_id=f"test:{name}")
        findings = engine.classify_column(column, profile=standard_profile)
        assert not findings, (
            f"Column name '{name}' should not trigger column_name_engine, got {[f.entity_type for f in findings]}"
        )


# ── Edge case: empty sample values ──────────────────────────────────────────


def test_empty_samples_no_crash(standard_profile):
    """Vague column name + empty sample_values should not crash."""
    column = ColumnInput(
        column_name="field_1",
        column_id="vague:edge:empty",
        sample_values=[],
    )
    findings = _classify_no_ml([column], standard_profile, min_confidence=0.5)
    assert isinstance(findings, list)


def test_all_empty_strings_no_crash(standard_profile):
    """Vague column name + all-empty strings should not crash."""
    column = ColumnInput(
        column_name="data",
        column_id="vague:edge:all_empty",
        sample_values=["", "", "", "", ""],
    )
    findings = _classify_no_ml([column], standard_profile, min_confidence=0.5)
    assert isinstance(findings, list)


# ── Batch classification: multiple vague columns together ───────────────────


def test_batch_vague_columns(standard_profile):
    """Multiple vague-named columns classified together should not interfere."""
    columns = [
        ColumnInput(
            column_name="field_1",
            column_id="batch:emails",
            sample_values=[
                "alice@example.com",
                "bob@company.org",
                "charlie@university.edu",
                "diana@webmail.net",
                "eve@startup.io",
            ],
        ),
        ColumnInput(
            column_name="data",
            column_id="batch:phones",
            sample_values=[
                "(212) 555-0101",
                "(312) 555-0202",
                "(415) 555-0303",
                "(617) 555-0404",
                "(713) 555-0505",
            ],
        ),
        ColumnInput(
            column_name="col1",
            column_id="batch:no_pii",
            sample_values=[
                "Widget A",
                "Widget B",
                "Widget C",
                "Widget D",
                "Widget E",
            ],
        ),
    ]
    findings = _classify_no_ml(columns, standard_profile, min_confidence=0.0)

    # Group by column
    by_col = {}
    for f in findings:
        by_col.setdefault(f.column_id, []).append(f)

    # Email column should detect EMAIL
    email_findings = by_col.get("batch:emails", [])
    assert any(f.entity_type == "EMAIL" for f in email_findings), (
        f"batch:emails should detect EMAIL, got {[f.entity_type for f in email_findings]}"
    )

    # Phone column should detect PHONE
    phone_findings = by_col.get("batch:phones", [])
    assert any(f.entity_type == "PHONE" for f in phone_findings), (
        f"batch:phones should detect PHONE, got {[f.entity_type for f in phone_findings]}"
    )
