# Sprint 13 Item A: Column-Shape Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic column-shape detector to the orchestrator that classifies each column as `structured_single`, `free_text_heterogeneous`, or `opaque_tokens`, emits a `ColumnShapeEvent` telemetry stream on every call, and suppresses the v5 meta-classifier shadow emission on the two non-structured branches (where v5 is documented to collapse).

**Architecture:** Pure side-effect-free detector in a new module, composed from three existing heuristic helpers plus a low-weight column-name tiebreaker. Wired into `Orchestrator.classify_column` after the engine cascade produces `engine_findings` but before the post-processing merges. The structured_single branch preserves Sprint 11 behavior (merge + v5 shadow) bit-for-bit; the heterogeneous and opaque_tokens branches still go through the merges (deterministic dedup is useful everywhere) but skip the v5 `MetaClassifierEvent` emission that collapses on those shapes.

**Tech Stack:** Python 3.11, dataclasses, pytest, ruff. No new dependencies — `compute_dictionary_word_ratio`, `compute_cardinality_ratio`, and `_avg_length_normalized` already exist in the codebase; this item promotes the last one to a public helper and composes all three into the detector.

---

## File Structure

**Created:**
- `data_classifier/orchestrator/shape_detector.py` — pure shape detection (one module, one responsibility)
- `tests/test_column_shape_detector.py` — 12 fixture unit tests for the detector
- `tests/test_orchestrator_column_shape_event.py` — orchestrator-integration tests asserting event emission + v5 shadow suppression

**Modified:**
- `data_classifier/engines/heuristic_engine.py` — add public `compute_avg_length_normalized`
- `data_classifier/orchestrator/meta_classifier.py` — delete private `_avg_length_normalized`, import the public one
- `data_classifier/events/types.py` — add `ColumnShapeEvent` dataclass
- `data_classifier/orchestrator/orchestrator.py` — insert shape detection + event emission + v5 shadow gate

---

## Execution Constraints

1. **Use `.venv/bin/python` explicitly** when running pytest (per `feedback_verify_venv_before_trusting_tests.md`).
2. **TDD: test-first** per project convention. Every task in the plan writes the failing test before the implementation.
3. **No behavior change on structured_single columns.** The v5 shadow emission, the 7-pass merge, and the tier-1 gate all continue to run identically for `structured_single`. Any test touching a structured column that passed before must still pass.
4. **Commit per task.** Small commits, conventional-style messages under `chore(sprint13-a): ...`.

---

## Task 1 — Promote `_avg_length_normalized` to a public helper

**Files:**
- Modify: `data_classifier/engines/heuristic_engine.py` (add new function after `compute_cardinality_ratio` at line 74)
- Modify: `data_classifier/orchestrator/meta_classifier.py` (delete `_avg_length_normalized` at lines 436-446, update call site at line 342)
- Test: `tests/test_heuristic_engine.py` (add test for `compute_avg_length_normalized`)

**Rationale:** The helper already exists in `meta_classifier.py` as a private `_avg_length_normalized`. Item A needs it in `shape_detector.py`. Promoting it keeps `shape_detector.py` dependency-free except for `heuristic_engine` (where its sibling helpers live) and avoids reaching across subpackages.

- [ ] **Step 1.1: Write the failing test**

Add to `tests/test_heuristic_engine.py`:

```python
def test_compute_avg_length_normalized_empty_returns_zero():
    from data_classifier.engines.heuristic_engine import compute_avg_length_normalized
    assert compute_avg_length_normalized([]) == 0.0


def test_compute_avg_length_normalized_short_values_below_half():
    from data_classifier.engines.heuristic_engine import compute_avg_length_normalized
    # Length 15 — typical homogeneous single-entity column (SSN, email prefix)
    result = compute_avg_length_normalized(["alice@ex.com"] * 10)
    assert 0.11 <= result <= 0.16


def test_compute_avg_length_normalized_log_lines_above_half():
    from data_classifier.engines.heuristic_engine import compute_avg_length_normalized
    # Length 80+ — typical log line
    result = compute_avg_length_normalized(["x" * 85] * 10)
    assert result == 0.85


def test_compute_avg_length_normalized_clamps_to_one():
    from data_classifier.engines.heuristic_engine import compute_avg_length_normalized
    # Length 500 — should clamp to 1.0
    result = compute_avg_length_normalized(["x" * 500] * 10)
    assert result == 1.0
```

- [ ] **Step 1.2: Run tests — expect 4 failures (ImportError)**

Run: `.venv/bin/python -m pytest tests/test_heuristic_engine.py -k compute_avg_length_normalized -v`
Expected: 4 FAIL with `ImportError: cannot import name 'compute_avg_length_normalized'`

- [ ] **Step 1.3: Add the public helper to heuristic_engine.py**

Insert after line 74 (after `compute_cardinality_ratio`):

```python
def compute_avg_length_normalized(values: list[str]) -> float:
    """Average character length of sample values, normalized to [0.0, 1.0].

    Divides the mean sample length by a reference of 100 characters and
    clamps to [0.0, 1.0]. Chosen empirically from the Sprint 12 safety
    audit fixture statistics: homogeneous single-entity columns land at
    0.11-0.16 (11-16 chars), log-shaped heterogeneous columns at
    0.51-0.90 (51-90 chars), and longer payloads at 1.0.

    This is the ``avg_len_normalized`` signal consumed by the Sprint 13
    column-shape router and the meta-classifier feature extractor. The
    normalization is NOT per-column; it is a project-wide constant so
    training and inference agree.

    Args:
        values: Sample values from the column.

    Returns:
        Float in [0.0, 1.0].
    """
    if not values:
        return 0.0
    total = sum(len(v) for v in values)
    mean = total / len(values)
    normalized = mean / 100.0
    if normalized < 0.0:
        return 0.0
    if normalized > 1.0:
        return 1.0
    return normalized
```

- [ ] **Step 1.4: Update meta_classifier.py to use the public helper**

In `data_classifier/orchestrator/meta_classifier.py`:
- Delete lines 436-446 (the private `_avg_length_normalized` definition)
- At line 342, replace `avg_len = _avg_length_normalized(values)` with `avg_len = compute_avg_length_normalized(values)`
- Add to the imports near line 430-433 (the existing lazy-import block for `compute_cardinality_ratio`): update to import both `compute_cardinality_ratio` and `compute_avg_length_normalized` from `data_classifier.engines.heuristic_engine`. The existing import block is:

```python
from data_classifier.engines.heuristic_engine import compute_cardinality_ratio

return compute_cardinality_ratio(values)
```

Change to:

```python
from data_classifier.engines.heuristic_engine import (
    compute_avg_length_normalized,  # noqa: F401  (re-exported for Sprint 11 compat)
    compute_cardinality_ratio,
)

return compute_cardinality_ratio(values)
```

And at the top-level import of `_avg_length_normalized` usage (line 342), ensure `compute_avg_length_normalized` is in scope. Since it replaces a module-private helper, add a module-level import at the top of meta_classifier.py:

```python
from data_classifier.engines.heuristic_engine import compute_avg_length_normalized
```

- [ ] **Step 1.5: Run the tests — expect 4 passes + full suite green**

Run: `.venv/bin/python -m pytest tests/test_heuristic_engine.py -k compute_avg_length_normalized -v`
Expected: 4 PASS

Run: `.venv/bin/python -m pytest tests/test_meta_classifier.py tests/test_meta_classifier_features.py -v`
Expected: all existing meta-classifier tests still pass (the rename is transparent because the computation is bit-identical — same formula, just a new public name)

- [ ] **Step 1.6: Commit**

```bash
git add data_classifier/engines/heuristic_engine.py data_classifier/orchestrator/meta_classifier.py tests/test_heuristic_engine.py
git commit -m "chore(sprint13-a): promote _avg_length_normalized to public helper

Move the normalization helper from meta_classifier.py (private) to
heuristic_engine.py (public) alongside compute_cardinality_ratio and
compute_dictionary_word_ratio. Sprint 13 Item A's shape_detector needs
the same signal and composing all three from one module keeps
shape_detector's dependency surface minimal.

Formula is unchanged (mean / 100.0, clamped to [0, 1]); meta-classifier
feature output is bit-identical so no retrain required."
```

---

## Task 2 — Add `ColumnShapeEvent` to events/types.py

**Files:**
- Modify: `data_classifier/events/types.py` (append new dataclass at end)
- Test: `tests/test_event_types.py` (add construction + default test)

**Rationale:** The orchestrator will emit this event per `classify_column` call. Follows the same pattern as `GateRoutingEvent` (Sprint 11 observability-only event).

- [ ] **Step 2.1: Write the failing test**

Add to `tests/test_event_types.py` (create file if it doesn't exist):

```python
def test_column_shape_event_default_construction():
    from data_classifier.events.types import ColumnShapeEvent
    event = ColumnShapeEvent(
        column_id="col_1",
        shape="structured_single",
        avg_len_normalized=0.15,
        dict_word_ratio=0.0,
        cardinality_ratio=0.9,
        n_cascade_entities=1,
        column_name_hint_applied=False,
    )
    assert event.shape == "structured_single"
    assert event.per_value_inference_ms is None
    assert event.sampled_row_count is None
    assert event.run_id == ""
    assert event.timestamp  # ISO timestamp populated by default_factory


def test_column_shape_event_with_item_b_latency_fields():
    from data_classifier.events.types import ColumnShapeEvent
    event = ColumnShapeEvent(
        column_id="col_1",
        shape="free_text_heterogeneous",
        avg_len_normalized=0.72,
        dict_word_ratio=0.45,
        cardinality_ratio=1.0,
        n_cascade_entities=4,
        column_name_hint_applied=True,
        per_value_inference_ms=1280,
        sampled_row_count=60,
    )
    assert event.per_value_inference_ms == 1280
    assert event.sampled_row_count == 60
```

- [ ] **Step 2.2: Run — expect ImportError**

Run: `.venv/bin/python -m pytest tests/test_event_types.py -v`
Expected: FAIL with `ImportError: cannot import name 'ColumnShapeEvent'`

- [ ] **Step 2.3: Add the dataclass**

Append to `data_classifier/events/types.py`:

```python
@dataclass
class ColumnShapeEvent:
    """Emitted by the Sprint 13 column-shape router for every classification.

    The router inspects the engine-cascade output and column-level
    statistics to decide which downstream handler a column should route
    to (``structured_single`` → current v5 shadow + 7-pass merge;
    ``free_text_heterogeneous`` → per-value GLiNER aggregation landing in
    Sprint 13 Item B; ``opaque_tokens`` → tuned secret_scanner landing
    in Sprint 13 Item C). The event carries the detection signals so
    BQ telemetry can measure the real shape distribution in production
    and so Item B's per-value latency shows up in the same stream.

    ``per_value_inference_ms`` and ``sampled_row_count`` are ``None`` on
    the ``structured_single`` and ``opaque_tokens`` branches. They are
    populated by Item B's per-value handler on the
    ``free_text_heterogeneous`` branch once that item lands.
    """

    column_id: str
    shape: str
    """One of ``structured_single``, ``free_text_heterogeneous``, ``opaque_tokens``."""

    avg_len_normalized: float
    dict_word_ratio: float
    cardinality_ratio: float
    n_cascade_entities: int
    column_name_hint_applied: bool
    """True iff the column-name tiebreaker fired to resolve an ambiguous
    middle-band content signal. Always False on unambiguous decisions.
    """

    per_value_inference_ms: int | None = None
    """Populated only on the ``free_text_heterogeneous`` branch (Item B)."""

    sampled_row_count: int | None = None
    """Populated only on the ``free_text_heterogeneous`` branch (Item B)."""

    run_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
```

- [ ] **Step 2.4: Run tests — expect PASS**

Run: `.venv/bin/python -m pytest tests/test_event_types.py -v`
Expected: 2 PASS

- [ ] **Step 2.5: Commit**

```bash
git add data_classifier/events/types.py tests/test_event_types.py
git commit -m "feat(sprint13-a): add ColumnShapeEvent for column-shape router telemetry

Observability event emitted per classify_column call by the Sprint 13
router. Payload includes the three content signals used for routing
(avg_len_normalized, dict_word_ratio, cardinality_ratio), the cascade
entity count, whether the column-name tiebreaker fired, and nullable
fields (per_value_inference_ms, sampled_row_count) that Item B will
populate on the free_text_heterogeneous branch."
```

---

## Task 3 — Create pure `detect_column_shape` (content signals only)

**Files:**
- Create: `data_classifier/orchestrator/shape_detector.py`
- Test: `tests/test_column_shape_detector.py`

**Rationale:** The detector is a pure function over `ColumnInput` + `engine_findings`. Keeping it side-effect-free makes it unit-testable without mocking the orchestrator. The column-name tiebreaker is deferred to Task 4 so Task 3 can lock the content-signal semantics first.

- [ ] **Step 3.1: Write the failing test (content signals only)**

Create `tests/test_column_shape_detector.py`:

```python
from data_classifier.core.types import ClassificationFinding, ColumnInput


def _finding(entity_type: str) -> ClassificationFinding:
    return ClassificationFinding(
        column_id="col_1",
        entity_type=entity_type,
        category="PII",
        sensitivity="medium",
        confidence=0.9,
        regulatory=[],
        engine="regex",
        evidence="test",
    )


def test_structured_single_short_values_one_entity():
    from data_classifier.orchestrator.shape_detector import detect_column_shape
    column = ColumnInput(
        column_id="col_1",
        column_name="email",
        sample_values=["alice@ex.com", "bob@ex.org", "carol@site.co"] * 4,
    )
    engine_findings = {"regex": [_finding("EMAIL")]}
    result = detect_column_shape(column, engine_findings)
    assert result.shape == "structured_single"
    assert result.avg_len_normalized < 0.3
    assert result.n_cascade_entities == 1
    assert result.column_name_hint_applied is False


def test_free_text_heterogeneous_long_values_many_entities():
    from data_classifier.orchestrator.shape_detector import detect_column_shape
    log_line = (
        "2026-04-16T10:15:30 INFO user alice@example.com login from 10.0.1.5"
    )
    column = ColumnInput(
        column_id="col_1",
        column_name="log_line",
        sample_values=[log_line] * 10,
    )
    engine_findings = {
        "regex": [_finding("EMAIL"), _finding("IP_ADDRESS"), _finding("DATE_TIME")],
    }
    result = detect_column_shape(column, engine_findings)
    assert result.shape == "free_text_heterogeneous"
    assert result.avg_len_normalized >= 0.3
    assert result.dict_word_ratio >= 0.1


def test_opaque_tokens_no_dictionary_words():
    from data_classifier.orchestrator.shape_detector import detect_column_shape
    column = ColumnInput(
        column_id="col_1",
        column_name="jwt_token",
        sample_values=[
            "eyJ1c2VyIjoiYWxpY2VAZXhhbXBsZS5jb20iLCJyb2xlIjoiYWRtaW4ifQ==",
            "eyJ1c2VyIjoiYm9iQGV4YW1wbGUub3JnIiwicm9sZSI6InVzZXIifQ==",
        ] * 5,
    )
    engine_findings = {"regex": []}
    result = detect_column_shape(column, engine_findings)
    assert result.shape == "opaque_tokens"
    assert result.dict_word_ratio < 0.1


def test_empty_sample_values_defaults_to_structured_single():
    from data_classifier.orchestrator.shape_detector import detect_column_shape
    column = ColumnInput(column_id="col_1", column_name="unknown", sample_values=[])
    result = detect_column_shape(column, {})
    assert result.shape == "structured_single"
    assert result.avg_len_normalized == 0.0
```

- [ ] **Step 3.2: Run — expect 4 ImportError failures**

Run: `.venv/bin/python -m pytest tests/test_column_shape_detector.py -v`
Expected: 4 FAIL with `ModuleNotFoundError: No module named 'data_classifier.orchestrator.shape_detector'`

- [ ] **Step 3.3: Create shape_detector.py**

Create `data_classifier/orchestrator/shape_detector.py`:

```python
"""Column-shape router — routes each column to one of three handlers.

The router inspects the engine-cascade output and column-level
statistics to decide which downstream handler a column should route
to:

  structured_single       — one entity per column (emails, SSNs, phone numbers).
                            Current v5 shadow + 7-pass merge apply.
  free_text_heterogeneous — log lines, chat, JSON events. Multiple
                            entities per column. Item B handles.
  opaque_tokens           — base64 payloads, JWTs, hashes. No dictionary
                            words. Item C handles.

Routing is deterministic and auditable: three content signals
(``avg_len_normalized``, ``dictionary_word_ratio``,
``cardinality_ratio``) plus the cascade's entity-type count, with a
narrow column-name tiebreaker band for ambiguous middle-ground cases.
Thresholds come from the Sprint 12 safety audit §6 evidence (see
``docs/research/meta_classifier/sprint12_safety_audit.md``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from data_classifier.core.types import ClassificationFinding, ColumnInput
from data_classifier.engines.heuristic_engine import (
    compute_avg_length_normalized,
    compute_cardinality_ratio,
    compute_dictionary_word_ratio,
)

Shape = Literal["structured_single", "free_text_heterogeneous", "opaque_tokens"]

# Thresholds from the Sprint 12 safety audit §6:
#   Homogeneous single-entity columns: avg_len 0.11-0.16
#   Log-shaped columns: avg_len 0.51-0.90
#   Base64 tokens: dict_word_ratio ~0
_AVG_LEN_STRUCTURED_MAX: float = 0.3
_DICT_WORD_HETERO_MIN: float = 0.1


@dataclass(frozen=True)
class ShapeDetection:
    """Result of ``detect_column_shape``. Carries the decision and the
    signals that drove it so a ``ColumnShapeEvent`` can be built
    without recomputing.
    """

    shape: Shape
    avg_len_normalized: float
    dict_word_ratio: float
    cardinality_ratio: float
    n_cascade_entities: int
    column_name_hint_applied: bool


def detect_column_shape(
    column: ColumnInput,
    engine_findings: dict[str, list[ClassificationFinding]],
) -> ShapeDetection:
    """Pure column-shape detector. Returns the routing decision and signals.

    Routing rules (Sprint 12 safety audit §6):

      if avg_len_norm < 0.3 AND n_cascade_entities <= 1:
          structured_single
      elif dict_word_ratio >= 0.1:
          free_text_heterogeneous
      else:
          opaque_tokens

    The column-name tiebreaker (Sprint 13 scoping Q1) is added in Task 4.
    """
    values = column.sample_values
    avg_len = compute_avg_length_normalized(values)
    dict_ratio = compute_dictionary_word_ratio(values)
    cardinality = compute_cardinality_ratio(values)

    distinct_entities: set[str] = set()
    for findings in engine_findings.values():
        for f in findings:
            distinct_entities.add(f.entity_type)
    n_cascade = len(distinct_entities)

    if avg_len < _AVG_LEN_STRUCTURED_MAX and n_cascade <= 1:
        shape: Shape = "structured_single"
    elif dict_ratio >= _DICT_WORD_HETERO_MIN:
        shape = "free_text_heterogeneous"
    else:
        shape = "opaque_tokens"

    return ShapeDetection(
        shape=shape,
        avg_len_normalized=avg_len,
        dict_word_ratio=dict_ratio,
        cardinality_ratio=cardinality,
        n_cascade_entities=n_cascade,
        column_name_hint_applied=False,
    )
```

- [ ] **Step 3.4: Run — expect 4 PASS**

Run: `.venv/bin/python -m pytest tests/test_column_shape_detector.py -v`
Expected: 4 PASS

- [ ] **Step 3.5: Commit**

```bash
git add data_classifier/orchestrator/shape_detector.py tests/test_column_shape_detector.py
git commit -m "feat(sprint13-a): add pure column-shape detector with content-signal routing

New module data_classifier/orchestrator/shape_detector.py exposing
detect_column_shape(column, engine_findings) -> ShapeDetection.
Routing rules follow the Sprint 12 safety audit §6 evidence:
  - structured_single: avg_len_norm < 0.3 AND <= 1 cascade entity
  - free_text_heterogeneous: dict_word_ratio >= 0.1
  - opaque_tokens: otherwise

Column-name tiebreaker (Sprint 13 scoping Q1 amendment) lands in the
next commit — this commit locks the content-signal contract first."
```

---

## Task 4 — Add the column-name tiebreaker (Q1 decision)

**Files:**
- Modify: `data_classifier/orchestrator/shape_detector.py`
- Modify: `tests/test_column_shape_detector.py` (add 3 tiebreaker tests)

**Rationale:** Sprint 13 scoping Q1 decision (see the sprint-start commit message): when content signals land in an ambiguous middle band, consult `ColumnInput.column_name` against the `ColumnNameEngine`'s variant dictionary as a low-weight tiebreaker. Default is still content-first; the tiebreaker only fires on `[0.3, 0.45] × [0.05, 0.15]` middle-band decisions.

**Design decision flagged for the engineer:** The `ColumnNameEngine._lookup` dict is currently private (`_` prefix). Rather than reach into a private attribute from `shape_detector.py`, expose a narrow public accessor on `ColumnNameEngine`. The alternative — duplicating the variant load — would double the memory footprint and break DRY. See Step 4.3.

- [ ] **Step 4.1: Write the failing tiebreaker tests**

Append to `tests/test_column_shape_detector.py`:

```python
def test_ambiguous_middle_band_column_name_points_to_hetero():
    """Column name 'log_line' should tip an ambiguous signal toward heterogeneous."""
    from data_classifier.orchestrator.shape_detector import detect_column_shape
    # Craft values so signals land in the ambiguous middle band:
    # avg_len_norm ~ 0.38 (length 38), dict_word_ratio ~ 0.08 (weak dictionary signal)
    values = [f"token_{i:04d}_trailing_suffix_abc_" + "x" * 5 for i in range(20)]
    column = ColumnInput(
        column_id="col_1",
        column_name="log_line",  # known heterogeneous hint
        sample_values=values,
    )
    result = detect_column_shape(column, {"regex": []})
    assert 0.3 <= result.avg_len_normalized <= 0.45
    assert result.dict_word_ratio <= 0.15
    assert result.shape == "free_text_heterogeneous"
    assert result.column_name_hint_applied is True


def test_ambiguous_middle_band_column_name_points_to_structured():
    """Column name 'email' should tip an ambiguous signal toward structured_single."""
    from data_classifier.orchestrator.shape_detector import detect_column_shape
    values = [f"a_{i:04d}b_{i:04d}_" + "x" * 5 for i in range(20)]
    column = ColumnInput(
        column_id="col_1",
        column_name="email",  # known structured hint
        sample_values=values,
    )
    result = detect_column_shape(column, {"regex": []})
    assert 0.3 <= result.avg_len_normalized <= 0.45
    assert result.shape == "structured_single"
    assert result.column_name_hint_applied is True


def test_unambiguous_signal_ignores_column_name_hint():
    """Even 'log_line' column name should not override strong structured signals."""
    from data_classifier.orchestrator.shape_detector import detect_column_shape
    column = ColumnInput(
        column_id="col_1",
        column_name="log_line",  # misleading column name
        sample_values=["alice@ex.com", "bob@ex.org"] * 5,  # strong structured signal
    )
    engine_findings = {"regex": [_finding("EMAIL")]}
    result = detect_column_shape(column, engine_findings)
    assert result.shape == "structured_single"
    assert result.column_name_hint_applied is False  # content decisive — hint didn't fire
```

- [ ] **Step 4.2: Run — expect 3 FAIL**

Run: `.venv/bin/python -m pytest tests/test_column_shape_detector.py -k "middle_band or unambiguous" -v`
Expected: 2 FAIL (middle-band tests — current code returns `opaque_tokens` or `structured_single` without tiebreaker). 1 PASS (unambiguous test already holds because the current detector ignores column_name).

- [ ] **Step 4.3: Expose a public variant-category accessor on `ColumnNameEngine`**

Add to `data_classifier/engines/column_name_engine.py` (inside the `ColumnNameEngine` class, after `_ensure_started`):

```python
def get_variant_category(self, column_name: str) -> str | None:
    """Return the entity-type category bucket for a known column-name variant.

    Used by the Sprint 13 column-shape router as a low-weight tiebreaker
    when content signals are ambiguous. Returns ``None`` for unknown
    variants. Returns one of the known categories otherwise:
    ``"structured"`` for high-cardinality single-entity columns (email,
    phone, ssn, etc.); ``"heterogeneous"`` for log/event/message/trace
    column names.

    This is a read-only classification of the variant dictionary and
    does NOT run the full matching pipeline (no abbreviation expansion,
    no subsequence matching). The intent is a cheap tiebreaker, not
    full column-name classification.
    """
    self._ensure_started()
    normalized = _normalize(column_name)
    entry = self._lookup.get(normalized)
    if entry is None:
        return None
    # Heterogeneous hints: column names indicating log/event/free-text shapes.
    # List is intentionally narrow — any variant not matching falls through
    # to "structured" as the safe default for named sensitive columns.
    if normalized in _HETEROGENEOUS_VARIANTS:
        return "heterogeneous"
    return "structured"
```

Also add a module-level frozen set at the top of the file (after the imports, before the `_VariantEntry` class):

```python
# Known column-name variants that indicate log/event/free-text shapes.
# Used by the Sprint 13 column-shape router as a low-weight tiebreaker.
# Intentionally narrow — most sensitive-name variants (email, ssn, phone,
# address, etc.) are structured and do not appear here.
_HETEROGENEOUS_VARIANTS: frozenset[str] = frozenset({
    "log_line",
    "log_message",
    "logline",
    "logmessage",
    "message",
    "event_message",
    "event_body",
    "event_payload",
    "eventbody",
    "eventpayload",
    "trace",
    "trace_line",
    "traceline",
    "audit_log",
    "auditlog",
    "raw_event",
    "rawevent",
    "payload",
    "body",
    "description",
})
```

Then add to `tests/test_column_name_engine.py` (new test):

```python
def test_get_variant_category_heterogeneous_hint():
    from data_classifier.engines.column_name_engine import ColumnNameEngine
    engine = ColumnNameEngine()
    # log_line is not in the sensitive-variants dict, so returns None
    assert engine.get_variant_category("log_line") is None


def test_get_variant_category_structured_hint():
    from data_classifier.engines.column_name_engine import ColumnNameEngine
    engine = ColumnNameEngine()
    assert engine.get_variant_category("email") == "structured"


def test_get_variant_category_unknown():
    from data_classifier.engines.column_name_engine import ColumnNameEngine
    engine = ColumnNameEngine()
    assert engine.get_variant_category("some_random_name_xyz") is None
```

**Important correction**: the `_HETEROGENEOUS_VARIANTS` set above will not be reached by `get_variant_category` because those variants are NOT in the sensitive-name dictionary at all (they don't describe PII). So `get_variant_category("log_line")` returns `None` via the `self._lookup.get(normalized)` miss, never reaching the `_HETEROGENEOUS_VARIANTS` check.

The fix: have `get_variant_category` handle the heterogeneous case BEFORE the sensitive-dict lookup:

```python
def get_variant_category(self, column_name: str) -> str | None:
    """..."""
    self._ensure_started()
    normalized = _normalize(column_name)
    if normalized in _HETEROGENEOUS_VARIANTS:
        return "heterogeneous"
    entry = self._lookup.get(normalized)
    if entry is None:
        return None
    return "structured"
```

Update the first test to expect "heterogeneous":

```python
def test_get_variant_category_heterogeneous_hint():
    from data_classifier.engines.column_name_engine import ColumnNameEngine
    engine = ColumnNameEngine()
    assert engine.get_variant_category("log_line") == "heterogeneous"
```

- [ ] **Step 4.4: Wire the tiebreaker into `detect_column_shape`**

In `data_classifier/orchestrator/shape_detector.py`:

Add the middle-band constants near the existing thresholds:

```python
# Sprint 13 scoping Q1 decision: column-name tiebreaker middle-band.
# Only consulted when content signals land in this ambiguous zone.
_TIEBREAKER_AVG_LEN_MIN: float = 0.3
_TIEBREAKER_AVG_LEN_MAX: float = 0.45
_TIEBREAKER_DICT_RATIO_MIN: float = 0.05
_TIEBREAKER_DICT_RATIO_MAX: float = 0.15
```

Replace the body of `detect_column_shape` with:

```python
def detect_column_shape(
    column: ColumnInput,
    engine_findings: dict[str, list[ClassificationFinding]],
) -> ShapeDetection:
    """Pure column-shape detector. Returns the routing decision and signals."""
    values = column.sample_values
    avg_len = compute_avg_length_normalized(values)
    dict_ratio = compute_dictionary_word_ratio(values)
    cardinality = compute_cardinality_ratio(values)

    distinct_entities: set[str] = set()
    for findings in engine_findings.values():
        for f in findings:
            distinct_entities.add(f.entity_type)
    n_cascade = len(distinct_entities)

    # Content-signal routing (authoritative).
    if avg_len < _AVG_LEN_STRUCTURED_MAX and n_cascade <= 1:
        shape: Shape = "structured_single"
        hint_applied = False
    elif dict_ratio >= _DICT_WORD_HETERO_MIN:
        shape = "free_text_heterogeneous"
        hint_applied = False
    else:
        shape = "opaque_tokens"
        hint_applied = False

    # Column-name tiebreaker (Sprint 13 scoping Q1): only when content
    # signal is ambiguous (middle band). Content remains authoritative
    # outside this narrow zone.
    in_middle_band = (
        _TIEBREAKER_AVG_LEN_MIN <= avg_len <= _TIEBREAKER_AVG_LEN_MAX
        and _TIEBREAKER_DICT_RATIO_MIN <= dict_ratio <= _TIEBREAKER_DICT_RATIO_MAX
    )
    if in_middle_band:
        hint = _lookup_column_name_hint(column.column_name)
        if hint == "heterogeneous":
            shape = "free_text_heterogeneous"
            hint_applied = True
        elif hint == "structured":
            shape = "structured_single"
            hint_applied = True

    return ShapeDetection(
        shape=shape,
        avg_len_normalized=avg_len,
        dict_word_ratio=dict_ratio,
        cardinality_ratio=cardinality,
        n_cascade_entities=n_cascade,
        column_name_hint_applied=hint_applied,
    )


# Lazy singleton: column-name engine takes ~5ms to initialize. Creating
# it inside detect_column_shape would add that cost to every call; the
# module-level lazy init amortizes it across the first call.
_COLUMN_NAME_ENGINE: "ColumnNameEngine | None" = None


def _lookup_column_name_hint(column_name: str) -> str | None:
    """Return ``"structured"``, ``"heterogeneous"``, or ``None``.

    Lazy-loads the ColumnNameEngine on first use.
    """
    global _COLUMN_NAME_ENGINE
    if _COLUMN_NAME_ENGINE is None:
        # Local import to avoid a module-load-time circular dependency:
        # engines/column_name_engine.py imports from core.types, and
        # this module imports from engines.heuristic_engine. Importing
        # ColumnNameEngine lazily here keeps the orchestrator layer's
        # import graph clean.
        from data_classifier.engines.column_name_engine import ColumnNameEngine
        _COLUMN_NAME_ENGINE = ColumnNameEngine()
    return _COLUMN_NAME_ENGINE.get_variant_category(column_name)
```

- [ ] **Step 4.5: Run — expect all tests PASS**

Run: `.venv/bin/python -m pytest tests/test_column_shape_detector.py tests/test_column_name_engine.py -v`
Expected: all PASS

- [ ] **Step 4.6: Commit**

```bash
git add data_classifier/engines/column_name_engine.py data_classifier/orchestrator/shape_detector.py tests/test_column_name_engine.py tests/test_column_shape_detector.py
git commit -m "feat(sprint13-a): add column-name tiebreaker to shape detector (Q1 decision)

Sprint 13 scoping Q1 decision: when content signals land in the
ambiguous middle band ([0.3, 0.45] avg_len × [0.05, 0.15]
dict_word_ratio), consult ColumnInput.column_name against the
ColumnNameEngine variant dictionary as a low-weight tiebreaker.
Content remains authoritative outside the middle band.

Also adds a narrow _HETEROGENEOUS_VARIANTS set of log/event/message
column name variants (not in the sensitive-name dict because they
don't describe PII) that the tiebreaker uses to route log-shaped
columns away from the structured_single branch.

Exposed ColumnNameEngine.get_variant_category() as a public accessor
so shape_detector doesn't reach into the engine's private _lookup."
```

---

## Task 5 — Add the 12-fixture unit test suite

**Files:**
- Modify: `tests/test_column_shape_detector.py`

**Rationale:** Sprint 13 Item A AC line 3 requires 12 test cases covering all 3 shapes (6 heterogeneous from safety audit + 4 homogeneous + 2 opaque).

- [ ] **Step 5.1: Add the 12-fixture test suite**

Append to `tests/test_column_shape_detector.py`:

```python
import pytest
from tests.benchmarks.meta_classifier.sprint12_safety_audit import (
    _build_heterogeneous_fixtures,
)


# Acceptance criteria fixture set: 6 heterogeneous from the Sprint 12
# safety audit (the exact fixtures that made Q3 verdict RED), plus
# 4 homogeneous structured, plus 2 opaque-token shapes.


@pytest.mark.parametrize(
    "fixture_name,expected_shape",
    [
        # Heterogeneous fixtures from Sprint 12 safety audit §3:
        ("original_q3_log", "free_text_heterogeneous"),
        ("apache_access_log", "free_text_heterogeneous"),
        ("json_event_log", "free_text_heterogeneous"),
        ("support_chat_messages", "free_text_heterogeneous"),
        ("kafka_event_stream", "free_text_heterogeneous"),
        # base64_encoded_payloads is the opaque case — assert it separately
        # below with the correct expected shape.
    ],
)
def test_q3_heterogeneous_fixtures_route_away_from_structured(
    fixture_name: str, expected_shape: str
) -> None:
    from data_classifier.orchestrator.shape_detector import detect_column_shape
    fixtures = _build_heterogeneous_fixtures()
    samples = fixtures[fixture_name]
    column = ColumnInput(
        column_id=fixture_name,
        column_name=fixture_name,
        sample_values=samples,
    )
    # For this integration-lite test we pass an empty engine_findings
    # dict — the content signals (avg_len + dict_word_ratio) alone must
    # correctly classify heterogeneous shapes away from structured_single.
    # When the full orchestrator path runs, engine_findings will be
    # populated; the test here verifies the detector's robustness under
    # the worst case (no cascade signal).
    result = detect_column_shape(column, {})
    assert result.shape == expected_shape, (
        f"{fixture_name}: expected {expected_shape}, got {result.shape} "
        f"(avg_len={result.avg_len_normalized:.3f}, "
        f"dict_word={result.dict_word_ratio:.3f})"
    )


def test_q3_base64_fixture_routes_to_opaque_tokens():
    from data_classifier.orchestrator.shape_detector import detect_column_shape
    fixtures = _build_heterogeneous_fixtures()
    samples = fixtures["base64_encoded_payloads"]
    column = ColumnInput(
        column_id="base64_encoded_payloads",
        column_name="jwt_payload",
        sample_values=samples,
    )
    result = detect_column_shape(column, {})
    assert result.shape == "opaque_tokens"


@pytest.mark.parametrize(
    "fixture_values,column_name,expected_shape",
    [
        # Homogeneous structured fixtures:
        (
            ["alice@example.com", "bob@example.org", "carol@test.io"] * 4,
            "email",
            "structured_single",
        ),
        (
            ["123-45-6789", "987-65-4321", "555-44-3322"] * 4,
            "ssn",
            "structured_single",
        ),
        (
            ["4111111111111111", "5555555555554444", "3782822463100051"] * 4,
            "credit_card",
            "structured_single",
        ),
        (
            ["+1-555-123-4567", "+44 20 7946 0958", "+1 (415) 555-0199"] * 4,
            "phone",
            "structured_single",
        ),
        # Additional opaque-token fixture: SHA-256 hex hashes (no dictionary
        # words, high entropy, not base64).
        (
            [
                "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
                "fcde2b2edba56bf408601fb721fe9b5c338d10ee429ea04fae5511b68fbf8fb9",
            ] * 4,
            "digest",
            "opaque_tokens",
        ),
    ],
)
def test_homogeneous_and_opaque_fixtures(
    fixture_values: list[str], column_name: str, expected_shape: str
) -> None:
    from data_classifier.orchestrator.shape_detector import detect_column_shape
    column = ColumnInput(
        column_id=column_name,
        column_name=column_name,
        sample_values=fixture_values,
    )
    result = detect_column_shape(column, {})
    assert result.shape == expected_shape, (
        f"{column_name}: expected {expected_shape}, got {result.shape} "
        f"(avg_len={result.avg_len_normalized:.3f}, "
        f"dict_word={result.dict_word_ratio:.3f})"
    )
```

- [ ] **Step 5.2: Run — expect all 12 parameterizations PASS**

Run: `.venv/bin/python -m pytest tests/test_column_shape_detector.py -v`
Expected: 5 (heterogeneous) + 1 (base64) + 5 (homogeneous + hash) + earlier Task 3/4 tests = all PASS

If a fixture fails to route correctly, do not relax the threshold silently. The threshold constants are evidence-backed from the Sprint 12 safety audit §3. Failure here indicates either (a) the fixture is an edge case the threshold didn't anticipate — document and file as a follow-up — or (b) the detector has a real bug.

- [ ] **Step 5.3: Commit**

```bash
git add tests/test_column_shape_detector.py
git commit -m "test(sprint13-a): add 12-fixture suite covering all 3 shapes

Exercises the detector against: the 5 log-shaped fixtures from the
Sprint 12 safety audit Q3 + the base64 opaque fixture + 4 homogeneous
structured fixtures (email/ssn/credit_card/phone) + SHA-256 digest
opaque fixture. Satisfies Item A AC line 3: at least 12 test cases
covering all 3 shapes."
```

---

## Task 6 — Wire shape detection into the orchestrator

**Files:**
- Modify: `data_classifier/orchestrator/orchestrator.py`
- Test: `tests/test_orchestrator_column_shape_event.py` (new)

**Rationale:** The detector runs, and the `ColumnShapeEvent` must be emitted per call. On the two non-structured branches, the v5 meta-classifier shadow emission is suppressed (per the Item A AC: "no more wrong-class collapses on heterogeneous fixtures because they are no longer routed to v5").

- [ ] **Step 6.1: Write the failing integration test**

Create `tests/test_orchestrator_column_shape_event.py`:

```python
from data_classifier import load_profile
from data_classifier.core.types import ColumnInput
from data_classifier.engines.column_name_engine import ColumnNameEngine
from data_classifier.engines.heuristic_engine import HeuristicEngine
from data_classifier.engines.regex_engine import RegexEngine
from data_classifier.engines.secret_scanner import SecretScannerEngine
from data_classifier.events.emitter import CallbackHandler, EventEmitter
from data_classifier.events.types import ColumnShapeEvent, MetaClassifierEvent
from data_classifier.orchestrator.orchestrator import Orchestrator


def _collect_events() -> tuple[EventEmitter, list]:
    events: list = []
    emitter = EventEmitter()
    emitter.add_handler(CallbackHandler(events.append))
    return emitter, events


def _orchestrator(emitter: EventEmitter) -> Orchestrator:
    engines = [
        RegexEngine(),
        ColumnNameEngine(),
        HeuristicEngine(),
        SecretScannerEngine(),
    ]
    for e in engines:
        e.startup()
    return Orchestrator(engines, mode="structured", emitter=emitter)


def test_column_shape_event_emitted_for_structured_single():
    emitter, events = _collect_events()
    orch = _orchestrator(emitter)
    column = ColumnInput(
        column_id="col_email",
        column_name="email",
        sample_values=["alice@ex.com", "bob@ex.org", "carol@test.io"] * 4,
    )
    orch.classify_column(column, load_profile("standard"))
    shape_events = [e for e in events if isinstance(e, ColumnShapeEvent)]
    assert len(shape_events) == 1
    assert shape_events[0].shape == "structured_single"
    assert shape_events[0].per_value_inference_ms is None
    assert shape_events[0].sampled_row_count is None


def test_column_shape_event_emitted_for_heterogeneous():
    emitter, events = _collect_events()
    orch = _orchestrator(emitter)
    log_line = "2026-04-16T10:15:30 INFO user alice@example.com login from 10.0.1.5"
    column = ColumnInput(
        column_id="col_log",
        column_name="log_line",
        sample_values=[log_line] * 10,
    )
    orch.classify_column(column, load_profile("standard"))
    shape_events = [e for e in events if isinstance(e, ColumnShapeEvent)]
    assert len(shape_events) == 1
    assert shape_events[0].shape == "free_text_heterogeneous"


def test_column_shape_event_emitted_for_opaque():
    emitter, events = _collect_events()
    orch = _orchestrator(emitter)
    column = ColumnInput(
        column_id="col_jwt",
        column_name="token",
        sample_values=[
            "eyJ1c2VyIjoiYWxpY2VAZXhhbXBsZS5jb20iLCJyb2xlIjoiYWRtaW4ifQ==",
        ] * 10,
    )
    orch.classify_column(column, load_profile("standard"))
    shape_events = [e for e in events if isinstance(e, ColumnShapeEvent)]
    assert len(shape_events) == 1
    assert shape_events[0].shape == "opaque_tokens"


def test_meta_classifier_shadow_suppressed_on_heterogeneous():
    """Item A AC: heterogeneous columns should no longer be routed to v5 shadow."""
    emitter, events = _collect_events()
    orch = _orchestrator(emitter)
    log_line = "2026-04-16T10:15:30 INFO user alice@example.com login from 10.0.1.5"
    column = ColumnInput(
        column_id="col_log",
        column_name="log_line",
        sample_values=[log_line] * 10,
    )
    orch.classify_column(column, load_profile("standard"))
    meta_events = [e for e in events if isinstance(e, MetaClassifierEvent)]
    assert len(meta_events) == 0, (
        "v5 meta-classifier shadow must not be emitted on "
        "free_text_heterogeneous columns (Sprint 13 Item A AC)."
    )


def test_meta_classifier_shadow_emitted_on_structured_single():
    """Structured single columns preserve Sprint 11 behavior — shadow still fires."""
    import os
    if os.environ.get("DATA_CLASSIFIER_DISABLE_META", "").lower() in ("1", "true", "yes"):
        return  # skip when meta-classifier is disabled in CI matrix
    emitter, events = _collect_events()
    orch = _orchestrator(emitter)
    column = ColumnInput(
        column_id="col_email",
        column_name="email",
        sample_values=["alice@ex.com", "bob@ex.org"] * 5,
    )
    orch.classify_column(column, load_profile("standard"))
    meta_events = [e for e in events if isinstance(e, MetaClassifierEvent)]
    assert len(meta_events) == 1
```

- [ ] **Step 6.2: Run — expect 5 FAIL**

Run: `.venv/bin/python -m pytest tests/test_orchestrator_column_shape_event.py -v`
Expected: FAIL. Either `ColumnShapeEvent` is never emitted, or it's not suppressing v5 shadow.

- [ ] **Step 6.3: Wire shape_detector into Orchestrator.classify_column**

In `data_classifier/orchestrator/orchestrator.py`:

Add to the imports at the top:

```python
from data_classifier.events.types import (
    ClassificationEvent,
    ColumnShapeEvent,  # new
    GateRoutingEvent,
    MetaClassifierEvent,
    TierEvent,
)
from data_classifier.orchestrator.shape_detector import detect_column_shape  # new
```

Modify `Orchestrator.classify_column` — insert the shape-detection block between line 308 (`total_ms = (time.monotonic() - t_start) * 1000`) and line 311 (`all_findings = self._apply_engine_weighting(...)`):

```python
        total_ms = (time.monotonic() - t_start) * 1000

        # ── Sprint 13 Item A: column-shape detection ──────────────────────
        # Deterministic routing on structural shape. Detects BEFORE the
        # post-processing merges so the shape decision can gate downstream
        # behavior (specifically: whether to emit the v5 shadow prediction,
        # which is documented to collapse on non-structured shapes).
        try:
            shape_detection = detect_column_shape(column, engine_findings)
        except Exception:  # pragma: no cover — defensive
            logger.debug("Shape detection failed; defaulting to structured_single", exc_info=True)
            shape_detection = None

        # Apply engine priority weighting, collision resolution, etc. are
        # kept for ALL shapes — deterministic dedup is valuable everywhere.
        all_findings = self._apply_engine_weighting(all_findings, finding_authority, engine_findings)
```

At the end of the method (before the `return result`), wire in `ColumnShapeEvent` emission and use `shape_detection.shape` to gate the v5 shadow. Replace the existing shadow block (lines 343-362) with:

```python
        # ── Sprint 13 Item A: emit ColumnShapeEvent ──────────────────────
        # Observability event carries the routing decision + signals. The
        # per_value_inference_ms and sampled_row_count fields are None on
        # the structured_single and opaque_tokens branches; Item B's
        # per-value handler populates them on free_text_heterogeneous
        # columns once that item lands.
        if shape_detection is not None:
            self.emitter.emit(
                ColumnShapeEvent(
                    column_id=column.column_id,
                    shape=shape_detection.shape,
                    avg_len_normalized=shape_detection.avg_len_normalized,
                    dict_word_ratio=shape_detection.dict_word_ratio,
                    cardinality_ratio=shape_detection.cardinality_ratio,
                    n_cascade_entities=shape_detection.n_cascade_entities,
                    column_name_hint_applied=shape_detection.column_name_hint_applied,
                    run_id=run_id or "",
                )
            )

        # Shadow inference (Sprint 6 Phase 3) — observability only.
        # Sprint 13 Item A: gate on shape detection. v5 is documented to
        # collapse on free_text_heterogeneous and opaque_tokens shapes
        # (see docs/research/meta_classifier/sprint12_safety_audit.md §3).
        # Skip shadow emission on those branches to stop feeding wrong-
        # class predictions into downstream telemetry.
        shape_allows_shadow = shape_detection is None or shape_detection.shape == "structured_single"
        if self._meta_classifier is not None and shape_allows_shadow:
            try:
                shadow = self._meta_classifier.predict_shadow(
                    result,
                    column.sample_values,
                    engine_findings=engine_findings,
                )
                if shadow is not None:
                    self.emitter.emit(
                        MetaClassifierEvent(
                            column_id=shadow.column_id or column.column_id,
                            predicted_entity=shadow.predicted_entity,
                            confidence=shadow.confidence,
                            live_entity=shadow.live_entity,
                            agreement=shadow.agreement,
                            run_id=run_id or "",
                        )
                    )
            except Exception:
                logger.debug("MetaClassifier shadow path failed", exc_info=True)
```

- [ ] **Step 6.4: Run — expect all 5 PASS**

Run: `.venv/bin/python -m pytest tests/test_orchestrator_column_shape_event.py -v`
Expected: 5 PASS

- [ ] **Step 6.5: Run the full suite to check for regressions**

Run: `.venv/bin/python -m pytest tests/ -x --tb=short`
Expected: all existing tests still pass. Pay particular attention to any meta-classifier shadow-related tests — they should all still pass because structured_single columns (which is the existing test distribution) are routed unchanged.

If a meta-classifier test fails on a non-structured-single column, investigate before moving on. The expected behavior per Item A's spec is that those v5 emissions stop, so the test's expectation needs updating. Flag in the commit message if so.

- [ ] **Step 6.6: Commit**

```bash
git add data_classifier/orchestrator/orchestrator.py tests/test_orchestrator_column_shape_event.py
git commit -m "feat(sprint13-a): wire shape detection into orchestrator + gate v5 shadow

Orchestrator.classify_column now:
  1. Runs detect_column_shape after the engine cascade, before merges
  2. Emits ColumnShapeEvent per call with the detection + signals
  3. Skips MetaClassifierEvent emission on non-structured_single shapes
     (v5 is documented to collapse on heterogeneous / opaque_tokens —
     see Sprint 12 safety audit §3)

The 7-pass merge pipeline runs for all shapes (deterministic dedup is
useful everywhere); only the v5 shadow emission is gated. Items B and C
will add branch-specific handlers for the non-structured shapes.

Structured_single path is bit-identical to Sprint 11 behavior."
```

---

## Task 7 — Teach the safety audit about shape routing + re-run Q3 → GREEN

**Files:**
- Modify: `tests/benchmarks/meta_classifier/sprint12_safety_audit.py` (update `_audit_single_fixture` to respect the shape router)

**Rationale:** The safety audit currently calls `mc.predict_shadow()` directly at `sprint12_safety_audit.py:740`, bypassing the orchestrator. So Task 6's orchestrator-level v5-shadow gating does NOT flow through to the audit — we have to teach the audit the same shape-routing rule. This is the minimum change that makes the Q3 verdict reflect production behavior.

Item A AC: "Re-running tests/benchmarks/meta_classifier/sprint12_safety_audit.py with the router in place produces Q3 aggregate verdict = GREEN."

- [ ] **Step 7.1: Add the shape check in `_audit_single_fixture`**

In `tests/benchmarks/meta_classifier/sprint12_safety_audit.py`, at the top of the Part B section (around line 729, before `engine_findings: dict[str, list] = {}`), insert:

```python
    # ── Sprint 13 Item A: router-deflection gate ─────────────────────────
    # Production now routes non-structured shapes away from v5 shadow
    # (Sprint 13 Item A, commit ${commit_hash}). Mirror that here so
    # the Q3 verdict reflects production behavior: when the router
    # deflects a column away from v5, no shadow prediction is made and
    # therefore no collapse pathology is possible.
    from data_classifier.orchestrator.shape_detector import detect_column_shape
    # Build the engine_findings dict first so detect_column_shape has
    # the cascade signal it needs.
```

Then keep the existing `engine_findings` build loop (lines 729-737) but REORDER so that `engine_findings` is populated first, then the shape check runs:

```python
    engine_findings: dict[str, list] = {}
    flat_findings: list = []
    for en_name, engine in engines.items():
        try:
            engine_result = engine.classify_column(column, profile=profile, min_confidence=0.0)
        except Exception:
            engine_result = []
        engine_findings[en_name] = list(engine_result)
        flat_findings.extend(engine_result)

    # Sprint 13 Item A: router check BEFORE v5 shadow call.
    shape_detection = detect_column_shape(column, engine_findings)
    if shape_detection.shape != "structured_single":
        return {
            "fixture": name,
            "fixture_size": len(sample_values),
            "live_findings": live_findings_summary,
            "num_live_findings": len(live_findings_summary),
            "live_distinct_entities": sorted(live_distinct),
            "shadow_prediction": None,
            "collapse_verdict": "router_deflected",
            "router_shape": shape_detection.shape,
        }

    try:
        shadow = mc.predict_shadow(flat_findings, sample_values, engine_findings=engine_findings)
    except Exception as exc:
        ...
```

- [ ] **Step 7.2: Add `router_deflected` to the severity order (maps to GREEN)**

In the `q3_heterogeneous_audit` function (around line 842), update `severity_order` to include `router_deflected` at the graceful end:

```python
    severity_order = [
        "error",
        "shadow_unavailable",
        "collapsed_high_confidence_wrong_class",
        "collapsed_medium_confidence_wrong_class",
        "collapsed_high_confidence_one_of_live",
        "collapsed_medium_confidence_one_of_live",
        "graceful_degradation",
        "router_deflected",  # Sprint 13 Item A: shape router deflected away from v5
    ]
```

The list is ordered worst-first, so `router_deflected` at the end means "most graceful outcome." When all 6 fixtures are router-deflected, `aggregate_verdict` becomes `router_deflected` (GREEN).

- [ ] **Step 7.3: Update `compute_verdict` to accept router_deflected as GREEN**

In `compute_verdict` (around line 900+), find the Q3 condition check and add `router_deflected` to the GREEN-allowed set:

```python
    # The GREEN bucket accepts: graceful_degradation OR router_deflected.
    # Both indicate the flat classifier did not produce a collapse-wrong
    # prediction on a heterogeneous column. router_deflected means the
    # Sprint 13 router stopped the shadow call; graceful_degradation
    # means the shadow ran but produced a low-confidence output.
    q3_green_bucket = {"graceful_degradation", "router_deflected"}
    q3_green = q3_verdict in q3_green_bucket
```

Locate the existing Q3 GREEN check and replace it with the above. The red/yellow logic stays unchanged.

- [ ] **Step 7.4: Run the updated audit**

Run:

```bash
DATA_CLASSIFIER_DISABLE_ML=1 .venv/bin/python -m tests.benchmarks.meta_classifier.sprint12_safety_audit \
    --input tests/benchmarks/meta_classifier/training_data.jsonl \
    --out /tmp/sprint13a_safety_audit.json
```

Then inspect: `cat /tmp/sprint13a_safety_audit.json | python -m json.tool | grep -E '"(aggregate_verdict|verdict_counts|q3_verdict)"'`

Expected: `q3.aggregate_verdict = "router_deflected"`. All 6 fixtures show `collapse_verdict = "router_deflected"`.

- [ ] **Step 7.5: Commit**

```bash
cp /tmp/sprint13a_safety_audit.json docs/research/meta_classifier/sprint13_item_a_safety_audit.json
git add tests/benchmarks/meta_classifier/sprint12_safety_audit.py docs/research/meta_classifier/sprint13_item_a_safety_audit.json
git commit -m "feat(sprint13-a): teach safety audit about shape router, Q3 verdict → GREEN

The Sprint 12 safety audit bypassed the orchestrator and called
MetaClassifier.predict_shadow() directly, which meant Sprint 13
Item A's orchestrator-level v5 gating wasn't reflected in the
audit's Q3 verdict. This commit mirrors the router logic inside
_audit_single_fixture: when the column's detected shape is not
structured_single, skip the shadow call and record router_deflected
(new GREEN-bucket verdict) instead of running predict_shadow and
measuring a collapse that cannot occur in production.

All 6 heterogeneous fixtures now return router_deflected, and
aggregate_verdict rolls up to GREEN — matching production behavior
post-Item-A."
```

---

## Task 8 — Re-run family accuracy benchmark → assert no regression

**Files:** no code changes. This is a verification pass.

**Rationale:** Item A AC: "Family benchmark (tests/benchmarks/family_accuracy_benchmark.py) does not regress on structured_single columns (which is the current test distribution)."

- [ ] **Step 8.1: Run the family benchmark**

Run:

```bash
DATA_CLASSIFIER_DISABLE_ML=1 \
    .venv/bin/python -m tests.benchmarks.family_accuracy_benchmark \
    --out /tmp/sprint13a_family.predictions.jsonl \
    --summary /tmp/sprint13a_family.summary.json \
    --compare-to docs/research/meta_classifier/sprint12_family_benchmark.json
```

- [ ] **Step 8.2: Read the summary and compare**

Run: `cat /tmp/sprint13a_family.summary.json | python -m json.tool | grep -E '(cross_family_rate|family_macro_f1)'`

Expected:
- `shadow.overall.family.cross_family_rate` is `<=` the Sprint 12 baseline (0.0044 per the Sprint 12 completion memory).
- `shadow.overall.family.family_macro_f1` is `>=` the Sprint 12 baseline (0.9945).

The family benchmark's test distribution is structured_single columns. Those columns are routed to `structured_single` and preserve Sprint 11 behavior bit-for-bit, so no regression is expected. If the numbers drift, investigate: did any test column fall into the middle-band tiebreaker zone and get re-routed unexpectedly?

- [ ] **Step 8.3: Commit the benchmark summary**

```bash
cp /tmp/sprint13a_family.summary.json docs/research/meta_classifier/sprint13_item_a_family_benchmark.json
git add docs/research/meta_classifier/sprint13_item_a_family_benchmark.json
git commit -m "docs(sprint13-a): record family benchmark no-regression result

Confirms Item A AC: family_macro_f1 and cross_family_rate on
structured_single columns are unchanged from Sprint 12 baseline.
The router preserves Sprint 11/12 behavior on the structured test
distribution; only heterogeneous + opaque branches change."
```

---

## Task 9 — Run the full CI suite

**Files:** no code changes. This is the definition-of-done lint + test gate.

- [ ] **Step 9.1: Run ruff lint + format check**

Run: `ruff check . --exclude .claude/worktrees && ruff format --check . --exclude .claude/worktrees`
Expected: zero issues.

- [ ] **Step 9.2: Run the full pytest suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: all green. Note the final test count — should be at least 20 higher than the Sprint 12 baseline (1532 tests) due to the new test files.

- [ ] **Step 9.3: Move Item A to phase=review**

Run: `agile-backlog edit sprint13-column-shape-router --phase review`

Verify: `agile-backlog show sprint13-column-shape-router` shows `Phase: review`.

---

## Self-Review Checklist

After completing all 9 tasks, verify against Item A's acceptance criteria:

- [ ] `data_classifier/orchestrator/shape_detector.py` exists with `detect_column_shape` as a public function — **Task 3**
- [ ] Orchestrator wiring calls `detect_column_shape` before the 7-pass merge and branches based on the result — **Task 6** (note: all shapes still run through the merge; only v5 shadow is gated)
- [ ] `tests/test_column_shape_detector.py` has at least 12 test cases (6 heterogeneous + 4 homogeneous + 2 opaque) — **Task 5**
- [ ] `sprint12_safety_audit.py` produces Q3 aggregate verdict = GREEN — **Task 7**
- [ ] Family benchmark does not regress on structured_single columns — **Task 8**
- [ ] `ColumnShapeEvent` plumbed with full payload; integration test on each of the 3 branches — **Task 6** (5 test cases)
- [ ] Lint + format clean, full suite green — **Task 9**

---

## Execution Handoff

**Plan complete and saved to `docs/plans/2026-04-16-sprint13-item-a-column-shape-router.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — Dispatch a fresh general-purpose subagent per task, review diffs between tasks, fast iteration. Chosen for this item because Tasks 1, 3, 4, 6 each touch disjoint files and benefit from focused subagent attention.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for review.

**Which approach?**
