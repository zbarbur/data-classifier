"""Tests for the M4c gold-set schema validator.

Two flavors of test:

- **Unit tests** on ``validate_row()`` with hand-constructed rows
  covering each failure mode (missing field, unknown entity type,
  family inconsistency, enum violations, ...).
- **Contract test** on the committed gold set — runs the full
  validator on ``heterogeneous_gold_set.jsonl`` and asserts zero
  errors. This is what keeps the committed set honest as labels
  get edited by the CLI labeler.

Contract-test skip logic: if the JSONL file is missing (fresh clone
before the builder has run), skip with a clear message instead of
failing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.benchmarks.meta_classifier.gold_set_schema import (
    load_gold_set,
    validate_gold_set,
    validate_row,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
GOLD_SET_PATH = REPO_ROOT / "tests/benchmarks/meta_classifier/heterogeneous_gold_set.jsonl"


def _valid_row(**overrides) -> dict:
    """Build a minimal valid row. Override any field to trigger failures."""
    base = {
        "column_id": "test_col",
        "source": "test.source",
        "source_reference": "test.table.column",
        "encoding": "plaintext",
        "values": ["value_0", "value_1"],
        "true_shape": "structured_single",
        "true_labels": ["EMAIL"],
        "true_labels_family": ["CONTACT"],
        "true_labels_prevalence": {"EMAIL": 0.9},
        "review_status": "prefilled",
        "annotator": "test",
        "annotated_on": "2026-04-16",
        "notes": "",
    }
    base.update(overrides)
    return base


class TestValidRow:
    def test_baseline_passes(self):
        issues = validate_row(_valid_row(), row_idx=0)
        errors = [i for i in issues if i.level == "error"]
        assert errors == []


class TestStructuralFailures:
    def test_non_dict_row(self):
        issues = validate_row("not a dict", row_idx=0)
        assert any(i.level == "error" and i.field == "<row>" for i in issues)

    def test_missing_required_field(self):
        row = _valid_row()
        del row["true_labels"]
        issues = validate_row(row, row_idx=0)
        assert any(i.field == "true_labels" and "missing" in i.message for i in issues)

    def test_wrong_type(self):
        row = _valid_row(values="not a list")
        issues = validate_row(row, row_idx=0)
        assert any(i.field == "values" and i.level == "error" for i in issues)


class TestEnumFailures:
    def test_invalid_shape(self):
        issues = validate_row(_valid_row(true_shape="gibberish"), row_idx=0)
        assert any(i.field == "true_shape" and i.level == "error" for i in issues)

    def test_invalid_encoding(self):
        issues = validate_row(_valid_row(encoding="rot13"), row_idx=0)
        assert any(i.field == "encoding" and i.level == "error" for i in issues)

    def test_invalid_review_status(self):
        issues = validate_row(_valid_row(review_status="done"), row_idx=0)
        assert any(i.field == "review_status" and i.level == "error" for i in issues)


class TestLabelFailures:
    def test_unknown_entity_type(self):
        row = _valid_row(true_labels=["EMAIL", "MADE_UP"], true_labels_family=["CONTACT"])
        issues = validate_row(row, row_idx=0)
        assert any(i.field == "true_labels" and "MADE_UP" in i.message and i.level == "error" for i in issues)

    def test_family_inconsistency(self):
        """Stored families don't match what true_labels derives."""
        row = _valid_row(true_labels=["EMAIL"], true_labels_family=["CREDENTIAL"])
        issues = validate_row(row, row_idx=0)
        assert any(i.field == "true_labels_family" and i.level == "error" for i in issues)

    def test_empty_labels_empty_families_ok(self):
        """A column with no PII labels is valid (negative control)."""
        row = _valid_row(
            true_labels=[],
            true_labels_family=[],
            true_labels_prevalence={},
        )
        issues = validate_row(row, row_idx=0)
        errors = [i for i in issues if i.level == "error"]
        assert errors == []


class TestPrevalenceFailures:
    def test_prevalence_out_of_range(self):
        row = _valid_row(
            true_labels=["EMAIL"],
            true_labels_family=["CONTACT"],
            true_labels_prevalence={"EMAIL": 1.5},
        )
        issues = validate_row(row, row_idx=0)
        assert any(i.field == "true_labels_prevalence" and i.level == "error" for i in issues)

    def test_prevalence_unknown_key(self):
        """Warning (not error): prevalence key not in true_labels."""
        row = _valid_row(
            true_labels=["EMAIL"],
            true_labels_family=["CONTACT"],
            true_labels_prevalence={"EMAIL": 0.9, "STALE": 0.5},
        )
        issues = validate_row(row, row_idx=0)
        assert any(i.field == "true_labels_prevalence" and i.level == "warning" for i in issues)

    def test_empty_values_violates_floor(self):
        issues = validate_row(_valid_row(values=[]), row_idx=0)
        assert any(i.field == "values" and "prevalence floor" in i.message and i.level == "error" for i in issues)


class TestXorRoundtrip:
    def test_malformed_xor_value(self):
        row = _valid_row(
            encoding="xor",
            values=["xor:not-valid-base64!!!"],
        )
        issues = validate_row(row, row_idx=0)
        assert any(i.field == "values" and i.level == "error" for i in issues)


class TestCrossRow:
    def test_duplicate_column_id(self):
        rows = [_valid_row(column_id="dup"), _valid_row(column_id="dup")]
        issues = validate_gold_set(rows)
        assert any(i.field == "column_id" and "duplicate" in i.message for i in issues)

    def test_unique_column_ids_pass(self):
        rows = [_valid_row(column_id="a"), _valid_row(column_id="b")]
        issues = validate_gold_set(rows)
        errors = [i for i in issues if i.level == "error"]
        assert errors == []


# --------------------------------------------------------------------------- #
# Contract test against the actual committed gold set
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    not GOLD_SET_PATH.exists(),
    reason=f"gold set not built yet ({GOLD_SET_PATH}); run scripts.m4c_build_gold_set first",
)
class TestCommittedGoldSet:
    def test_zero_errors(self):
        """The committed gold set must be schema-clean at all times."""
        rows = load_gold_set(GOLD_SET_PATH)
        issues = validate_gold_set(rows)
        errors = [i for i in issues if i.level == "error"]
        assert errors == [], f"Schema validation failed with {len(errors)} errors:\n" + "\n".join(
            str(e) for e in errors[:20]
        )

    def test_fifty_rows_or_close(self):
        """Sprint target is 50 rows; allow some slack for source-drift."""
        rows = load_gold_set(GOLD_SET_PATH)
        assert 40 <= len(rows) <= 60, f"unexpected row count: {len(rows)}"

    def test_all_three_shapes_present(self):
        """Gold set must cover all three Sprint 13 router branches."""
        rows = load_gold_set(GOLD_SET_PATH)
        shapes = {r["true_shape"] for r in rows}
        assert "structured_single" in shapes
        assert "free_text_heterogeneous" in shapes
        assert "opaque_tokens" in shapes

    def test_both_encodings_used(self):
        rows = load_gold_set(GOLD_SET_PATH)
        encodings = {r["encoding"] for r in rows}
        assert encodings == {"plaintext", "xor"}

    def test_xor_rows_decode(self):
        """Spot-check every XOR row's first value decodes."""
        from data_classifier.patterns._decoder import decode_encoded_strings

        rows = load_gold_set(GOLD_SET_PATH)
        for row in rows:
            if row["encoding"] != "xor" or not row["values"]:
                continue
            decoded = decode_encoded_strings([row["values"][0]])[0]
            assert decoded, f"{row['column_id']}: first XOR value decoded to empty"

    def test_gold_set_file_is_valid_jsonl(self):
        """Each line is parseable JSON. Catches trailing-write corruption."""
        with GOLD_SET_PATH.open() as f:
            for lineno, raw in enumerate(f, start=1):
                if not raw.strip():
                    continue
                try:
                    json.loads(raw)
                except json.JSONDecodeError as exc:
                    pytest.fail(f"line {lineno}: invalid JSON — {exc}")
