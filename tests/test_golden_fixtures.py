"""Golden fixture tests — behavioral contract for Sprint 27 migration.

These tests load fixtures ported from BigQuery-connector's test suite
and verify the new library produces identical results on identical inputs.
If these pass, the Sprint 27 migration cannot regress.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from data_classifier import (
    ClassificationFinding,
    ColumnInput,
    classify_columns,
    compute_rollups,
    rollup_from_rollups,
)

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ── Column name matching fixtures ────────────────────────────────────────────


def _load_column_name_fixtures():
    """Load golden column name test cases."""
    with open(_FIXTURES_DIR / "golden_column_name.yaml") as f:
        data = yaml.safe_load(f)
    return data["cases"]


_COLUMN_NAME_CASES = _load_column_name_fixtures()


@pytest.mark.parametrize(
    "case",
    _COLUMN_NAME_CASES,
    ids=[c["column_name"] for c in _COLUMN_NAME_CASES],
)
def test_column_name_classification(case, standard_profile):
    """Verify column name produces expected entity_type and sensitivity."""
    column = ColumnInput(
        column_name=case["column_name"],
        column_id=f"test:{case['column_name']}",
    )
    findings = classify_columns([column], standard_profile, min_confidence=0.0)

    expected_type = case["expected_entity_type"]

    if expected_type is None:
        assert len(findings) == 0, (
            f"Column '{case['column_name']}' should have no findings, got: {[f.entity_type for f in findings]}"
        )
    else:
        assert len(findings) >= 1, f"Column '{case['column_name']}' should match {expected_type}, got no findings"
        finding = findings[0]
        assert finding.entity_type == expected_type
        if "expected_sensitivity" in case:
            assert finding.sensitivity == case["expected_sensitivity"]
        if "expected_category" in case:
            assert finding.category == case["expected_category"]


# ── Rollup computation fixtures ──────────────────────────────────────────────


def _load_rollup_fixtures():
    with open(_FIXTURES_DIR / "golden_rollups.yaml") as f:
        data = yaml.safe_load(f)
    return data["cases"]


_ROLLUP_CASES = _load_rollup_fixtures()


def _make_finding(d: dict) -> ClassificationFinding:
    """Create a ClassificationFinding from a fixture dict."""
    return ClassificationFinding(
        column_id=d["column_id"],
        entity_type=d["entity_type"],
        category=d.get("category", ""),
        sensitivity=d["sensitivity"],
        confidence=d["confidence"],
        regulatory=d.get("regulatory", []),
        engine="test",
    )


@pytest.mark.parametrize(
    "case",
    [c for c in _ROLLUP_CASES if "parent_map" in c],
    ids=[c["name"] for c in _ROLLUP_CASES if "parent_map" in c],
)
def test_compute_rollups(case):
    """Verify rollup computation matches expected output."""
    findings = [_make_finding(f) for f in case["findings"]]
    rollups = compute_rollups(findings, case["parent_map"])

    for parent_id, expected in case["expected"].items():
        assert parent_id in rollups, f"Missing rollup for {parent_id}"
        rollup = rollups[parent_id]

        if "sensitivity" in expected:
            assert rollup.sensitivity == expected["sensitivity"]
        if "findings_count" in expected:
            assert rollup.findings_count == expected["findings_count"]
        if "classifications" in expected:
            assert rollup.classifications == expected["classifications"]
        if "frameworks" in expected:
            assert sorted(rollup.frameworks) == sorted(expected["frameworks"])


@pytest.mark.parametrize(
    "case",
    [c for c in _ROLLUP_CASES if "table_to_dataset" in c],
    ids=[c["name"] for c in _ROLLUP_CASES if "table_to_dataset" in c],
)
def test_dataset_rollups(case):
    """Verify two-pass rollup (columns→tables→datasets)."""
    findings = [_make_finding(f) for f in case["findings"]]
    table_rollups = compute_rollups(findings, case["col_to_table"])
    dataset_rollups = rollup_from_rollups(table_rollups, case["table_to_dataset"])

    for ds_id, expected in case["expected_dataset"].items():
        assert ds_id in dataset_rollups, f"Missing dataset rollup for {ds_id}"
        rollup = dataset_rollups[ds_id]

        if "sensitivity" in expected:
            assert rollup.sensitivity == expected["sensitivity"]
        if "findings_count" in expected:
            assert rollup.findings_count == expected["findings_count"]


def test_empty_rollups():
    """Empty findings produce empty rollups."""
    assert compute_rollups([], {}) == {}
    assert rollup_from_rollups({}, {}) == {}
