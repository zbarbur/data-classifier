# Sprint 13 Item B — Per-Value GLiNER Aggregation (Union Design) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On the `free_text_heterogeneous` branch from Item A, run GLiNER per-value on a deterministic N=60 subsample, aggregate the spans into column-level `ClassificationFinding` objects, and **union them with the 7-pass cascade output** (preserving the regex floor, adding GLiNER coverage).

**Architecture:** Per-value GLiNER is a new inference method on `GLiNER2Engine` that runs the ONNX span model on each value individually (instead of the concatenated single-call mode used by the `classify_column` path). A new pure helper in `data_classifier/orchestrator/per_value_aggregator.py` takes the `list[list[SpanDetection]]` output and emits `ClassificationFinding` instances at `confidence = coverage × max_span_confidence`. The orchestrator's `classify_column` calls the per-value handler on the heterogeneous branch, concatenates the aggregated findings with the post-merge cascade result, and re-runs the existing merge + suppression passes so duplicate `entity_type`s are resolved by authority/confidence. `ColumnShapeEvent` gains two populated fields (`per_value_inference_ms`, `sampled_row_count`) on this branch for latency telemetry. On total GLiNER failure, the cascade output is returned unchanged — never block a column on per-value inference.

**Tech Stack:** Python 3.11, GLiNER v1 (urchade/gliner_multi_pii-v1 via ONNX), pytest, ruff, existing `data_classifier` dataclasses.

---

## File Structure

### New files
- `data_classifier/orchestrator/per_value_aggregator.py` — pure `aggregate_per_value_spans` helper
- `tests/engines/test_gliner_per_value.py` — unit tests for the new inference method
- `tests/orchestrator/test_per_value_aggregator.py` — unit tests for the aggregator
- `tests/orchestrator/test_heterogeneous_branch_integration.py` — end-to-end tests for the orchestrator branch

### Modified files
- `data_classifier/core/types.py` — add `SpanDetection` dataclass
- `data_classifier/engines/gliner_engine.py` — add `classify_per_value()` method + `_stable_subsample()` helper; read sample size from config
- `data_classifier/config/engine_defaults.yaml` — new `gliner_engine:` section with `per_value_sample_size: 60`
- `data_classifier/orchestrator/orchestrator.py` — heterogeneous-branch integration after `detect_column_shape`; populate `ColumnShapeEvent` latency fields
- `tests/benchmarks/meta_classifier/sprint12_safety_audit.py` — extend Q3 to capture union output; new verdict value `per_value_multilabel`
- `docs/sprints/SPRINT13_HANDOVER.md` — latency characterization section (Task 9)

### Untouched (confirming boundaries)
- `data_classifier/orchestrator/shape_detector.py` — no changes; routing decision is upstream
- `data_classifier/events/types.py` — `ColumnShapeEvent` fields already exist per Item A; no schema change
- `data_classifier/orchestrator/meta_classifier.py` — shadow emission is already gated on `structured_single` by Item A; unchanged

---

## Task 1: `SpanDetection` dataclass

**Files:**
- Modify: `data_classifier/core/types.py` (add dataclass, re-export in `__init__.py` if other types follow that pattern)
- Test: `tests/test_core_types.py` (append)

**Why:** GLiNER's per-value output needs a strongly-typed return so the aggregator is not coupled to a dict schema. Keep it lightweight — positional info (`start`, `end`) is carried even though the aggregator doesn't use it today; downstream callers may want it for value masking.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_core_types.py`:

```python
from data_classifier.core.types import SpanDetection


def test_span_detection_is_frozen_dataclass():
    span = SpanDetection(
        text="alice@example.com",
        entity_type="EMAIL",
        confidence=0.95,
        start=12,
        end=29,
    )
    assert span.text == "alice@example.com"
    assert span.entity_type == "EMAIL"
    assert span.confidence == 0.95
    assert span.start == 12
    assert span.end == 29

    # Frozen — mutating must raise FrozenInstanceError (dataclasses.FrozenInstanceError).
    import dataclasses
    with pytest.raises(dataclasses.FrozenInstanceError):
        span.confidence = 0.5  # type: ignore[misc]


def test_span_detection_equality_enables_set_dedup():
    a = SpanDetection(text="x", entity_type="EMAIL", confidence=0.9, start=0, end=1)
    b = SpanDetection(text="x", entity_type="EMAIL", confidence=0.9, start=0, end=1)
    assert a == b
    assert hash(a) == hash(b)
```

Make sure the file has `import pytest` at the top; append if missing.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_core_types.py::test_span_detection_is_frozen_dataclass -v`
Expected: FAIL with `ImportError: cannot import name 'SpanDetection' from 'data_classifier.core.types'`.

- [ ] **Step 3: Add the dataclass**

In `data_classifier/core/types.py`, after the `ColumnInput` dataclass and before the `ClassificationFinding` dataclass, add:

```python
@dataclass(frozen=True)
class SpanDetection:
    """One entity span detected by a per-value NER call.

    Produced by ``GLiNER2Engine.classify_per_value`` and consumed by
    ``aggregate_per_value_spans``. Frozen so instances are safe to use in
    sets or as dict keys during aggregation.
    """

    text: str
    """The substring the model identified (verbatim from the sample value)."""

    entity_type: str
    """Normalized to our taxonomy (EMAIL, PHONE, PERSON_NAME, ...). The model's
    raw label is already mapped via ``GLINER_LABEL_TO_ENTITY`` upstream."""

    confidence: float
    """Model confidence 0.0-1.0."""

    start: int
    """Character offset in the source value where the span begins (inclusive)."""

    end: int
    """Character offset in the source value where the span ends (exclusive)."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_core_types.py -v -k span_detection`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add data_classifier/core/types.py tests/test_core_types.py
git commit -m "feat(types): add SpanDetection dataclass for per-value NER output

Prerequisite for Sprint 13 Item B (per-value GLiNER aggregation).
Frozen dataclass so instances can live in sets during aggregation.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `per_value_sample_size` config key

**Files:**
- Modify: `data_classifier/config/engine_defaults.yaml`
- Modify: `data_classifier/engines/gliner_engine.py` (add `_load_per_value_sample_size()` module-level helper)
- Test: `tests/engines/test_gliner_per_value.py` (new file)

**Why:** Sprint 13 scoping Q2 decision: N=60 is the starting point but must be retunable without a code change.

- [ ] **Step 1: Write the failing test**

Create `tests/engines/test_gliner_per_value.py`:

```python
"""Unit tests for per-value GLiNER inference (Sprint 13 Item B)."""

from __future__ import annotations

import pytest

from data_classifier.engines.gliner_engine import _load_per_value_sample_size


class TestPerValueSampleSizeConfig:
    def test_default_is_60_when_config_present(self):
        assert _load_per_value_sample_size() == 60

    def test_falls_back_to_60_when_config_missing(self, monkeypatch):
        import data_classifier.engines.gliner_engine as gm

        monkeypatch.setattr(gm, "load_engine_config", lambda: {})
        assert gm._load_per_value_sample_size() == 60

    def test_reads_override_from_config(self, monkeypatch):
        import data_classifier.engines.gliner_engine as gm

        monkeypatch.setattr(
            gm,
            "load_engine_config",
            lambda: {"gliner_engine": {"per_value_sample_size": 120}},
        )
        assert gm._load_per_value_sample_size() == 120
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/engines/test_gliner_per_value.py::TestPerValueSampleSizeConfig -v`
Expected: FAIL with `ImportError: cannot import name '_load_per_value_sample_size'`.

- [ ] **Step 3: Add config key**

Append to `data_classifier/config/engine_defaults.yaml`:

```yaml
gliner_engine:
  # Sprint 13 Item B (2026-04-17): cap per-value inference at this many
  # deterministically-subsampled values on the free_text_heterogeneous
  # branch. N=60 picked during Sprint 13 scoping Q2: large enough for
  # Chao-1 cardinality estimates to be stable, small enough that the
  # worst-case latency is understood before imposing a fallback threshold.
  # "Measure, do not gate" — retune this number based on ColumnShapeEvent
  # telemetry once it accumulates from production.
  per_value_sample_size: 60
```

- [ ] **Step 4: Add loader helper**

In `data_classifier/engines/gliner_engine.py`, add at the top after the existing imports:

```python
from data_classifier.config import load_engine_config
```

Then add a module-level helper near the other module-level helpers (after `_find_bundled_onnx_model`):

```python
_DEFAULT_PER_VALUE_SAMPLE_SIZE: int = 60


def _load_per_value_sample_size() -> int:
    """Read the per-value sample-size cap from ``engine_defaults.yaml``.

    Falls back to ``_DEFAULT_PER_VALUE_SAMPLE_SIZE`` (60) when the config
    section is absent so legacy deployments never break. Malformed values
    (non-int, non-positive) also fall back.
    """
    try:
        cfg = load_engine_config().get("gliner_engine", {}) or {}
        value = cfg.get("per_value_sample_size", _DEFAULT_PER_VALUE_SAMPLE_SIZE)
        if isinstance(value, int) and value > 0:
            return value
    except Exception:
        logger.exception("Failed to load per_value_sample_size; falling back to default")
    return _DEFAULT_PER_VALUE_SAMPLE_SIZE
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/engines/test_gliner_per_value.py::TestPerValueSampleSizeConfig -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add data_classifier/config/engine_defaults.yaml data_classifier/engines/gliner_engine.py tests/engines/test_gliner_per_value.py
git commit -m "feat(gliner): add per_value_sample_size config key (default 60)

Sprint 13 Item B — retunable cap on per-value inference sample size.
Loader falls back to 60 when config section is absent or malformed.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Deterministic stable subsample helper

**Files:**
- Modify: `data_classifier/engines/gliner_engine.py` (add `_stable_subsample` private helper)
- Test: `tests/engines/test_gliner_per_value.py` (append `TestStableSubsample` class)

**Why:** Sprint 13 scoping Q2 decision was explicit: deterministic by stable hash, reproducible across runs, insertion-order-independent. Prevents telemetry noise from "same column, different numbers each call" and prevents subtle accuracy drift from row-ordering differences between connectors.

- [ ] **Step 1: Write the failing tests**

Append to `tests/engines/test_gliner_per_value.py`:

```python
from data_classifier.engines.gliner_engine import _stable_subsample


class TestStableSubsample:
    def test_identity_when_input_fits(self):
        values = ["a", "b", "c"]
        assert set(_stable_subsample(values, n=10)) == set(values)
        # Length is min(n, len(values)).
        assert len(_stable_subsample(values, n=10)) == 3

    def test_cap_is_respected(self):
        values = [f"value_{i}" for i in range(100)]
        assert len(_stable_subsample(values, n=60)) == 60

    def test_deterministic_across_calls(self):
        values = [f"value_{i}" for i in range(100)]
        first = _stable_subsample(values, n=60)
        second = _stable_subsample(values, n=60)
        assert first == second

    def test_insertion_order_independent(self):
        values = [f"value_{i}" for i in range(100)]
        forward = _stable_subsample(values, n=60)
        reverse = _stable_subsample(list(reversed(values)), n=60)
        # Same SET regardless of input order — this is the reproducibility
        # contract across connectors that deliver rows in different orders.
        assert set(forward) == set(reverse)

    def test_empty_input(self):
        assert _stable_subsample([], n=60) == []

    def test_zero_cap(self):
        assert _stable_subsample(["a", "b"], n=0) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/engines/test_gliner_per_value.py::TestStableSubsample -v`
Expected: FAIL with `ImportError: cannot import name '_stable_subsample'`.

- [ ] **Step 3: Add the helper**

Add this `import hashlib` near the top of `data_classifier/engines/gliner_engine.py` if not already present, then add the helper near the other module-level helpers:

```python
import hashlib


def _stable_subsample(values: list[str], *, n: int) -> list[str]:
    """Deterministically pick up to ``n`` values by stable hash.

    The hash is SHA-1 of the UTF-8-encoded value; ties (extremely rare)
    fall through to the underlying Python sort stability. The output is
    insertion-order-independent: two orchestrators that receive the same
    set of values in different orders produce the same sampled set.

    Sprint 13 scoping Q2 (2026-04-16): reproducibility across runs is
    required so ColumnShapeEvent telemetry is comparable column-to-column
    and run-to-run.
    """
    if n <= 0 or not values:
        return []
    if len(values) <= n:
        return list(values)

    def _key(v: str) -> bytes:
        return hashlib.sha1(v.encode("utf-8", errors="replace")).digest()

    return sorted(values, key=_key)[:n]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/engines/test_gliner_per_value.py::TestStableSubsample -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add data_classifier/engines/gliner_engine.py tests/engines/test_gliner_per_value.py
git commit -m "feat(gliner): add _stable_subsample helper — SHA-1-keyed, order-independent

Sprint 13 Item B prerequisite. SHA-1 of UTF-8 bytes as the sort key
gives reproducible subsampling across connectors that deliver rows
in different orders.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `GLiNER2Engine.classify_per_value()` method

**Files:**
- Modify: `data_classifier/engines/gliner_engine.py`
- Test: `tests/engines/test_gliner_per_value.py` (append `TestClassifyPerValue` class)

**Why:** Current `classify_column` concatenates all sample values into one prompt and runs one inference call. Item B needs one inference call per value so the aggregator can compute per-entity-type coverage across rows. The existing engine's data-type pre-filter, ONNX session, and label list are reused; only the call pattern changes.

- [ ] **Step 1: Write the failing tests (with stub model)**

Append to `tests/engines/test_gliner_per_value.py`:

```python
from unittest.mock import MagicMock

from data_classifier.core.types import ColumnInput, SpanDetection
from data_classifier.engines.gliner_engine import GLiNER2Engine


def _make_stub_engine(stub_model):
    """Construct a GLiNER2Engine whose _get_model returns the stub."""
    engine = GLiNER2Engine()
    engine._get_model = lambda: stub_model  # type: ignore[assignment]
    # Skip startup() — _get_model override makes registry irrelevant.
    engine._registered = True
    return engine


class TestClassifyPerValue:
    def test_empty_column_returns_empty(self):
        engine = _make_stub_engine(MagicMock())
        column = ColumnInput(column_id="c0", column_name="logs", sample_values=[])
        spans, sampled = engine.classify_per_value(column)
        assert spans == []
        assert sampled == 0

    def test_non_text_data_type_skipped(self):
        engine = _make_stub_engine(MagicMock())
        column = ColumnInput(
            column_id="c0", column_name="id", sample_values=["1"], data_type="INTEGER"
        )
        spans, sampled = engine.classify_per_value(column)
        assert spans == []
        assert sampled == 0

    def test_runs_one_inference_per_sampled_value(self):
        """Stub model returns a single EMAIL prediction per call. Verify
        the outer list has one entry per sampled value."""
        def _predict(text, _labels, **_kwargs):
            # Deterministic stub: always predict one email at start of value.
            return [{"label": "email", "text": text[:10], "score": 0.9, "start": 0, "end": 10}]

        stub = MagicMock()
        stub.predict_entities.side_effect = _predict

        engine = _make_stub_engine(stub)
        column = ColumnInput(
            column_id="c0",
            column_name="logs",
            sample_values=[f"line_{i}_value" for i in range(5)],
        )
        spans, sampled = engine.classify_per_value(column, sample_size=3)

        # Exactly sample_size calls — one per sampled row.
        assert stub.predict_entities.call_count == 3
        assert sampled == 3
        assert len(spans) == 3
        # Every row produced one EMAIL SpanDetection.
        for row_spans in spans:
            assert len(row_spans) == 1
            assert row_spans[0].entity_type == "EMAIL"
            assert isinstance(row_spans[0], SpanDetection)

    def test_per_value_inference_error_is_isolated(self):
        """If model raises on one value, that row yields an empty list
        and the other rows are unaffected."""
        call_count = {"n": 0}

        def _predict(text, _labels, **_kwargs):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("OOM on row 2")
            return [{"label": "email", "text": "x", "score": 0.8, "start": 0, "end": 1}]

        stub = MagicMock()
        stub.predict_entities.side_effect = _predict

        engine = _make_stub_engine(stub)
        column = ColumnInput(
            column_id="c0",
            column_name="logs",
            sample_values=["row_one", "row_two", "row_three"],
        )
        spans, sampled = engine.classify_per_value(column, sample_size=3)
        assert sampled == 3
        assert len(spans) == 3
        # Row 0, 2 succeeded; row 1 raised and yielded [].
        non_empty = [rs for rs in spans if rs]
        assert len(non_empty) == 2

    def test_unknown_label_skipped(self):
        """Model returns a label not in GLINER_LABEL_TO_ENTITY — drop it."""
        def _predict(text, _labels, **_kwargs):
            return [{"label": "unknown_label", "text": "x", "score": 0.9, "start": 0, "end": 1}]

        stub = MagicMock()
        stub.predict_entities.side_effect = _predict

        engine = _make_stub_engine(stub)
        column = ColumnInput(column_id="c0", column_name="x", sample_values=["a"])
        spans, _ = engine.classify_per_value(column, sample_size=1)
        assert spans == [[]]

    def test_default_sample_size_from_config(self, monkeypatch):
        """When sample_size arg is None, the cap comes from the config helper."""
        import data_classifier.engines.gliner_engine as gm

        monkeypatch.setattr(gm, "_load_per_value_sample_size", lambda: 2)

        stub = MagicMock()
        stub.predict_entities.return_value = []

        engine = _make_stub_engine(stub)
        column = ColumnInput(
            column_id="c0", column_name="x", sample_values=["a", "b", "c", "d"]
        )
        _, sampled = engine.classify_per_value(column)
        assert sampled == 2
        assert stub.predict_entities.call_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/engines/test_gliner_per_value.py::TestClassifyPerValue -v`
Expected: FAIL with `AttributeError: 'GLiNER2Engine' object has no attribute 'classify_per_value'`.

- [ ] **Step 3: Add the method**

In `data_classifier/engines/gliner_engine.py`, add this method to the `GLiNER2Engine` class (after `classify_batch`, before `_run_ner_on_samples`):

```python
    def classify_per_value(
        self,
        column: ColumnInput,
        *,
        sample_size: int | None = None,
    ) -> tuple[list[list[SpanDetection]], int]:
        """Run GLiNER per-value on a deterministic subsample of the column.

        Unlike ``classify_column``, this method runs the model once per
        sampled value and returns the raw spans without aggregation. Used
        by the Sprint 13 Item B heterogeneous-branch handler in the
        orchestrator, which feeds the result into ``aggregate_per_value_spans``.

        Args:
            column: The column whose sample values should be NER-ed.
            sample_size: Cap on how many values to run inference on. When
                ``None``, reads ``per_value_sample_size`` from
                ``engine_defaults.yaml`` (default 60).

        Returns:
            A tuple of ``(per_value_spans, sampled_row_count)``.

            ``per_value_spans`` is aligned with the deterministically-subsampled
            value list: outer index is the sampled row, inner list is the
            spans detected in that row (possibly empty).

            ``sampled_row_count`` is the actual number of rows inferred —
            equal to ``min(sample_size, len(column.sample_values))`` on
            success, or 0 if the column was skipped entirely
            (empty / non-text data_type).

        Errors:
            Per-value failures (OOM, model divergence on a specific value,
            etc.) are swallowed and that row yields ``[]``; the other rows
            are unaffected. A total model-load failure propagates —
            the orchestrator's outer try/except catches it and falls back
            to the cascade output.
        """
        from data_classifier.core.types import SpanDetection  # local to avoid circular

        if column.data_type and column.data_type.upper() in _NON_TEXT_DATA_TYPES:
            return [], 0
        if not column.sample_values:
            return [], 0

        if sample_size is None:
            sample_size = _load_per_value_sample_size()

        sampled = _stable_subsample(column.sample_values, n=sample_size)
        if not sampled:
            return [], 0

        model = self._get_model()  # may raise ModelDependencyError — caller handles

        per_value_spans: list[list[SpanDetection]] = []
        for value in sampled:
            # Preserve the Sprint 10 S1 wrapping behavior so per-value text
            # enters the model in-distribution. For a single value the
            # wrapper degrades gracefully to the raw value when metadata is
            # absent — no extra branching needed here.
            text = _build_ner_prompt(column, [value])
            row_spans: list[SpanDetection] = []
            try:
                if self._is_v2:
                    v2_entity_spec: list[str] | dict[str, str] = (
                        self._gliner_labels_v2 if self._descriptions_enabled else self._gliner_labels
                    )
                    result = model.extract_entities(
                        text,
                        v2_entity_spec,
                        threshold=self._gliner_threshold,
                        include_confidence=True,
                    )
                    for gliner_label, matches in result.get("entities", {}).items():
                        entity_type = GLINER_LABEL_TO_ENTITY.get(gliner_label)
                        if entity_type is None:
                            continue
                        for match in matches:
                            if isinstance(match, dict):
                                row_spans.append(
                                    SpanDetection(
                                        text=str(match.get("text", "")),
                                        entity_type=entity_type,
                                        confidence=float(match.get("confidence", 0.5)),
                                        start=int(match.get("start", 0)),
                                        end=int(match.get("end", 0)),
                                    )
                                )
                else:
                    preds = model.predict_entities(
                        text, self._gliner_labels, threshold=self._gliner_threshold
                    )
                    for pred in preds:
                        entity_type = GLINER_LABEL_TO_ENTITY.get(pred.get("label", ""))
                        if entity_type is None:
                            continue
                        row_spans.append(
                            SpanDetection(
                                text=str(pred.get("text", "")),
                                entity_type=entity_type,
                                confidence=float(pred.get("score", 0.0)),
                                start=int(pred.get("start", 0)),
                                end=int(pred.get("end", 0)),
                            )
                        )
            except Exception:
                logger.exception(
                    "GLiNER per-value inference failed on one value for column %s",
                    column.column_id,
                )
                # Fall through — row_spans stays empty. Other rows continue.
            per_value_spans.append(row_spans)

        return per_value_spans, len(sampled)
```

Also, add the import needed for the return-type annotation at the top of the module:

```python
from data_classifier.core.types import (
    ClassificationFinding,
    ClassificationProfile,
    ColumnInput,
    SampleAnalysis,
    SpanDetection,
)
```

(Append `SpanDetection` to the existing tuple import.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/engines/test_gliner_per_value.py::TestClassifyPerValue -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Run the full GLiNER test module**

Run: `.venv/bin/pytest tests/engines/test_gliner_per_value.py -v`
Expected: All tests pass (3 from Task 2 + 6 from Task 3 + 6 from Task 4 = 15).

- [ ] **Step 6: Commit**

```bash
git add data_classifier/engines/gliner_engine.py tests/engines/test_gliner_per_value.py
git commit -m "feat(gliner): add classify_per_value — per-value NER inference method

Runs model once per deterministically-subsampled value, returning
(list[list[SpanDetection]], sampled_count). Per-value exceptions are
isolated to the affected row so one OOM doesn't poison the batch.
Total model-load failure propagates for the orchestrator's outer
fallback. Reuses Sprint 10 S1 NL-prompt-wrapping so each single-value
call lands in-distribution.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `aggregate_per_value_spans` helper

**Files:**
- Create: `data_classifier/orchestrator/per_value_aggregator.py`
- Test: `tests/orchestrator/test_per_value_aggregator.py`

**Why:** Pure function separation — the aggregator has no model dependency and no orchestrator dependency, so it's unit-testable with hand-built `SpanDetection` inputs. Confidence formula is `coverage × max_span_confidence`; coverage threshold is `0.1` (drop an entity type that appears in fewer than 10% of sampled rows — noise floor).

- [ ] **Step 1: Write the failing tests**

Create `tests/orchestrator/test_per_value_aggregator.py`:

```python
"""Unit tests for the per-value aggregator helper (Sprint 13 Item B)."""

from __future__ import annotations

import pytest

from data_classifier.core.types import SpanDetection
from data_classifier.orchestrator.per_value_aggregator import aggregate_per_value_spans


def _span(entity_type: str, confidence: float) -> SpanDetection:
    return SpanDetection(text="x", entity_type=entity_type, confidence=confidence, start=0, end=1)


class TestAggregatePerValueSpans:
    def test_empty_input_returns_empty(self):
        assert aggregate_per_value_spans([], n_samples=0, column_id="c0") == []

    def test_single_entity_type_across_all_rows(self):
        per_value = [[_span("EMAIL", 0.9)] for _ in range(10)]
        findings = aggregate_per_value_spans(per_value, n_samples=10, column_id="c0")
        assert len(findings) == 1
        assert findings[0].entity_type == "EMAIL"
        assert findings[0].column_id == "c0"
        # coverage = 10/10 = 1.0, max_conf = 0.9 → confidence = 0.9
        assert findings[0].confidence == pytest.approx(0.9)

    def test_coverage_below_min_is_dropped(self):
        # EMAIL only in 1 of 20 rows — coverage 0.05, below 0.1 threshold.
        per_value: list[list[SpanDetection]] = [[] for _ in range(20)]
        per_value[0] = [_span("EMAIL", 0.95)]
        findings = aggregate_per_value_spans(per_value, n_samples=20, column_id="c0")
        assert findings == []

    def test_two_entity_types_independently_aggregated(self):
        per_value: list[list[SpanDetection]] = []
        # Rows 0-9: EMAIL + IP_ADDRESS
        for _ in range(10):
            per_value.append([_span("EMAIL", 0.9), _span("IP_ADDRESS", 0.8)])
        # Rows 10-19: IP_ADDRESS only
        for _ in range(10):
            per_value.append([_span("IP_ADDRESS", 0.85)])
        findings = aggregate_per_value_spans(per_value, n_samples=20, column_id="c0")
        by_type = {f.entity_type: f for f in findings}
        assert set(by_type) == {"EMAIL", "IP_ADDRESS"}
        # EMAIL: coverage 10/20 = 0.5, max = 0.9, confidence = 0.45
        assert by_type["EMAIL"].confidence == pytest.approx(0.45)
        # IP_ADDRESS: coverage 20/20 = 1.0, max = 0.85 (both sets), confidence = 0.85
        assert by_type["IP_ADDRESS"].confidence == pytest.approx(0.85)

    def test_multiple_spans_same_type_same_row_count_row_once(self):
        """Coverage counts ROWS that have ≥1 span of the type, not total spans."""
        per_value = [[_span("EMAIL", 0.9), _span("EMAIL", 0.7)]] * 10
        findings = aggregate_per_value_spans(per_value, n_samples=10, column_id="c0")
        assert len(findings) == 1
        # coverage = 10/10 = 1.0 (not 20/10), max_conf = 0.9
        assert findings[0].confidence == pytest.approx(0.9)

    def test_engine_attribution_is_gliner2(self):
        per_value = [[_span("EMAIL", 0.9)] for _ in range(10)]
        findings = aggregate_per_value_spans(per_value, n_samples=10, column_id="c0")
        assert findings[0].engine == "gliner2"

    def test_evidence_mentions_coverage(self):
        per_value = [[_span("EMAIL", 0.9)] for _ in range(8)] + [[] for _ in range(2)]
        findings = aggregate_per_value_spans(per_value, n_samples=10, column_id="c0")
        assert "8/10" in findings[0].evidence or "0.80" in findings[0].evidence

    def test_custom_min_coverage(self):
        per_value: list[list[SpanDetection]] = [[] for _ in range(20)]
        for i in range(3):  # 15% coverage
            per_value[i] = [_span("EMAIL", 0.9)]
        # Default 0.1 threshold — passes.
        assert len(aggregate_per_value_spans(per_value, n_samples=20, column_id="c0")) == 1
        # Raised threshold 0.2 — dropped.
        assert aggregate_per_value_spans(per_value, n_samples=20, column_id="c0", min_coverage=0.2) == []

    def test_entity_metadata_populated_from_gliner_engine(self):
        """Sensitivity / regulatory fields come from gliner_engine._ENTITY_METADATA."""
        per_value = [[_span("SSN", 0.9)] for _ in range(10)]
        findings = aggregate_per_value_spans(per_value, n_samples=10, column_id="c0")
        assert len(findings) == 1
        assert findings[0].sensitivity == "HIGH"
        assert "HIPAA" in findings[0].regulatory
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/orchestrator/test_per_value_aggregator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'data_classifier.orchestrator.per_value_aggregator'`.

- [ ] **Step 3: Create the aggregator module**

Create `data_classifier/orchestrator/per_value_aggregator.py`:

```python
"""Per-value GLiNER span aggregator (Sprint 13 Item B).

Takes the ``list[list[SpanDetection]]`` output from
``GLiNER2Engine.classify_per_value`` and aggregates it into column-level
``ClassificationFinding`` instances.

Aggregation rules:

  coverage(entity_type) = (# rows with ≥1 span of entity_type) / n_samples
  confidence(entity_type) = coverage × max(span.confidence for that type)

An entity type with ``coverage < min_coverage`` (default 0.1) is dropped as
below the noise floor. The threshold is a first-pass heuristic and should
be retuned against real BQ heterogeneous columns once ColumnShapeEvent
telemetry accumulates.

Entity-level sensitivity and regulatory metadata are copied from
``gliner_engine._ENTITY_METADATA`` so the aggregator stays the single
source of truth for per-value findings.
"""

from __future__ import annotations

from data_classifier.core.types import ClassificationFinding, SampleAnalysis, SpanDetection

# Noise floor: drop entity types observed in fewer than this fraction of
# sampled rows. Heuristic starting point — revisit in Sprint 14 after
# production telemetry.
_DEFAULT_MIN_COVERAGE: float = 0.1

# Max sample evidence strings to include on each ClassificationFinding.
_MAX_EVIDENCE_SAMPLES: int = 5


def aggregate_per_value_spans(
    per_value_spans: list[list[SpanDetection]],
    *,
    n_samples: int,
    column_id: str,
    min_coverage: float = _DEFAULT_MIN_COVERAGE,
) -> list[ClassificationFinding]:
    """Convert per-value GLiNER spans into column-level findings.

    Args:
        per_value_spans: Outer list = per sampled row; inner list = spans in
            that row (possibly empty). This is the exact return shape of
            ``GLiNER2Engine.classify_per_value``.
        n_samples: Number of rows actually inferred. Divisor of coverage.
        column_id: Column ID stamped onto emitted findings.
        min_coverage: Drop entity types whose coverage falls below this.

    Returns:
        One ClassificationFinding per entity type meeting the coverage
        floor. Empty list on empty input or when every type was dropped.
    """
    if not per_value_spans or n_samples <= 0:
        return []

    # Import metadata here to avoid an orchestrator → engines import cycle
    # at module-load time.
    from data_classifier.engines.gliner_engine import _ENTITY_METADATA

    # Per entity type: rows that contained at least one span, max confidence,
    # and a list of sample texts for evidence.
    rows_with_type: dict[str, int] = {}
    max_conf: dict[str, float] = {}
    sample_texts: dict[str, list[str]] = {}

    for row_spans in per_value_spans:
        seen_this_row: set[str] = set()
        for span in row_spans:
            if span.entity_type not in seen_this_row:
                rows_with_type[span.entity_type] = rows_with_type.get(span.entity_type, 0) + 1
                seen_this_row.add(span.entity_type)
            prior_max = max_conf.get(span.entity_type, 0.0)
            if span.confidence > prior_max:
                max_conf[span.entity_type] = span.confidence
            bucket = sample_texts.setdefault(span.entity_type, [])
            if len(bucket) < _MAX_EVIDENCE_SAMPLES and span.text:
                bucket.append(span.text)

    findings: list[ClassificationFinding] = []
    for entity_type, count in rows_with_type.items():
        coverage = count / n_samples
        if coverage < min_coverage:
            continue
        confidence = min(coverage * max_conf.get(entity_type, 0.0), 1.0)
        metadata = _ENTITY_METADATA.get(entity_type, {})
        findings.append(
            ClassificationFinding(
                column_id=column_id,
                entity_type=entity_type,
                category=metadata.get("category", "PII"),
                sensitivity=metadata.get("sensitivity", "MEDIUM"),
                confidence=round(confidence, 4),
                regulatory=list(metadata.get("regulatory", [])),
                engine="gliner2",
                evidence=(
                    f"GLiNER per-value: {entity_type} detected in "
                    f"{count}/{n_samples} sampled rows "
                    f"(coverage={coverage:.2f}, max_span_conf={max_conf.get(entity_type, 0.0):.2f})"
                ),
                sample_analysis=SampleAnalysis(
                    samples_scanned=n_samples,
                    samples_matched=count,
                    samples_validated=count,
                    match_ratio=coverage,
                    sample_matches=sample_texts.get(entity_type, []),
                ),
            )
        )
    return findings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/orchestrator/test_per_value_aggregator.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add data_classifier/orchestrator/per_value_aggregator.py tests/orchestrator/test_per_value_aggregator.py
git commit -m "feat(orchestrator): add aggregate_per_value_spans helper

Sprint 13 Item B — pure aggregator over per-value GLiNER output.
confidence = coverage × max_span_confidence, drops below coverage 0.1.
Entity metadata (sensitivity, regulatory) sourced from gliner_engine
to keep a single source of truth.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Orchestrator integration — heterogeneous branch (union design)

**Files:**
- Modify: `data_classifier/orchestrator/orchestrator.py`
- Test: `tests/orchestrator/test_heterogeneous_branch_integration.py`

**Why:** This is the central change. On `free_text_heterogeneous` shape, the orchestrator must:
1. Run `GLiNER2Engine.classify_per_value` against the column,
2. Aggregate via `aggregate_per_value_spans`,
3. Merge the aggregation into the post-merge cascade result (union — the existing authority/suppression passes are NOT re-run; we're just adding findings and deduping by entity_type+engine),
4. Populate `ColumnShapeEvent.per_value_inference_ms` and `sampled_row_count`,
5. Fall back to the unmodified cascade on any error.

**Key design note:** the existing `ColumnShapeEvent` emission currently happens *before* the per-value call in the orchestrator flow. We need to move it to *after* so we can stamp the latency fields, OR we add a second "enrichment" step before emit. The cleanest fix is to delay the `ColumnShapeEvent` emit until after the optional per-value step — `ClassificationEvent` can still emit first.

- [ ] **Step 1: Write the failing integration tests**

Create `tests/orchestrator/test_heterogeneous_branch_integration.py`:

```python
"""End-to-end tests for the Sprint 13 Item B free_text_heterogeneous branch."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from data_classifier.core.types import (
    ClassificationFinding,
    ColumnInput,
    SampleAnalysis,
    SpanDetection,
)
from data_classifier.events.emitter import EventEmitter
from data_classifier.events.types import ColumnShapeEvent
from data_classifier.orchestrator.orchestrator import Orchestrator


def _heterogeneous_column() -> ColumnInput:
    """Build a column whose content routes to free_text_heterogeneous.

    Long-form log-like values with dictionary words push dict_word_ratio
    above 0.1 and avg_len_normalized above 0.3 → hetero branch.
    """
    return ColumnInput(
        column_id="logs_column",
        column_name="event_log",
        sample_values=[
            f"user alice@example.com accessed resource from IP 10.0.0.{i} at 10:{i:02d}"
            for i in range(50)
        ],
    )


def _structured_column() -> ColumnInput:
    """Control — avg_len < 0.3 and single cascade entity → structured_single."""
    return ColumnInput(
        column_id="email_col",
        column_name="email",
        sample_values=[f"user{i}@example.com" for i in range(50)],
    )


def _install_stub_gliner(orchestrator, per_value_output: list[list[SpanDetection]]):
    """Replace the gliner2 engine's classify_per_value with a stub."""
    for engine in orchestrator._engines:
        if engine.name == "gliner2":
            engine.classify_per_value = lambda column, sample_size=None: (  # type: ignore[method-assign]
                per_value_output,
                len(per_value_output),
            )
            return
    pytest.fail("Orchestrator has no gliner2 engine — test setup error")


class TestHeterogeneousBranchIntegration:
    def test_per_value_findings_unioned_with_cascade(self):
        """Cascade finds EMAIL + IP; GLiNER adds ORGANIZATION. Output: all three."""
        orchestrator = Orchestrator()

        # Inject a stub per-value result with ORGANIZATION (not in cascade).
        org_spans = [
            [SpanDetection(text="ExampleCo", entity_type="ORGANIZATION", confidence=0.85, start=0, end=9)]
            for _ in range(40)
        ] + [[] for _ in range(10)]
        _install_stub_gliner(orchestrator, org_spans)

        result = orchestrator.classify_column(_heterogeneous_column())

        types = {f.entity_type for f in result}
        # Cascade floor preserved.
        assert "EMAIL" in types
        assert "IP_ADDRESS" in types
        # GLiNER lift added on top.
        assert "ORGANIZATION" in types

    def test_duplicate_entity_type_keeps_higher_confidence(self):
        """Cascade finds EMAIL at 0.95; GLiNER finds EMAIL at 0.72 — cascade wins."""
        orchestrator = Orchestrator()
        low_conf_email = [
            [SpanDetection(text="x", entity_type="EMAIL", confidence=0.72, start=0, end=1)]
            for _ in range(50)
        ]
        _install_stub_gliner(orchestrator, low_conf_email)

        result = orchestrator.classify_column(_heterogeneous_column())
        emails = [f for f in result if f.entity_type == "EMAIL"]
        assert len(emails) == 1
        # The cascade's regex engine fires at ~0.95 on these literal email strings.
        # The union keeps the higher of the two confidences.
        assert emails[0].confidence >= 0.9

    def test_gliner_failure_falls_back_to_cascade_cleanly(self):
        """classify_per_value raises — output is untouched cascade result."""
        orchestrator = Orchestrator()
        for engine in orchestrator._engines:
            if engine.name == "gliner2":
                def _boom(column, sample_size=None):
                    raise RuntimeError("model load failed")
                engine.classify_per_value = _boom  # type: ignore[method-assign]

        result = orchestrator.classify_column(_heterogeneous_column())
        # Cascade still produced its regex findings — test doesn't assert count,
        # just that no exception surfaced and the result is non-empty.
        types = {f.entity_type for f in result}
        assert "EMAIL" in types

    def test_column_shape_event_populated_with_latency(self):
        """per_value_inference_ms and sampled_row_count are set on hetero branch."""
        events: list[object] = []
        emitter = EventEmitter()
        emitter.subscribe(events.append)

        orchestrator = Orchestrator(emitter=emitter)
        org_spans = [
            [SpanDetection(text="X", entity_type="ORGANIZATION", confidence=0.8, start=0, end=1)]
            for _ in range(50)
        ]
        _install_stub_gliner(orchestrator, org_spans)

        orchestrator.classify_column(_heterogeneous_column())

        shape_events = [e for e in events if isinstance(e, ColumnShapeEvent)]
        assert len(shape_events) == 1
        assert shape_events[0].shape == "free_text_heterogeneous"
        assert shape_events[0].per_value_inference_ms is not None
        assert shape_events[0].per_value_inference_ms >= 0
        assert shape_events[0].sampled_row_count == 50

    def test_structured_branch_untouched(self):
        """Control: structured_single columns see NO per-value call and event fields are None."""
        events: list[object] = []
        emitter = EventEmitter()
        emitter.subscribe(events.append)

        orchestrator = Orchestrator(emitter=emitter)
        # Install a trap — structured branch must NOT call this.
        call_count = {"n": 0}
        for engine in orchestrator._engines:
            if engine.name == "gliner2":
                original = engine.classify_per_value

                def _tracked(column, sample_size=None):
                    call_count["n"] += 1
                    return original(column, sample_size=sample_size)

                engine.classify_per_value = _tracked  # type: ignore[method-assign]

        orchestrator.classify_column(_structured_column())

        assert call_count["n"] == 0, "structured_single must not invoke per-value"
        shape_events = [e for e in events if isinstance(e, ColumnShapeEvent)]
        if shape_events:  # may be absent if shape detection was skipped on this column
            assert shape_events[0].per_value_inference_ms is None
            assert shape_events[0].sampled_row_count is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/orchestrator/test_heterogeneous_branch_integration.py -v`
Expected: FAIL — per-value branch not yet wired.

- [ ] **Step 3: Wire the heterogeneous branch in the orchestrator**

Open `data_classifier/orchestrator/orchestrator.py`. Find the block starting around line 340 where `detect_column_shape` is called and `ColumnShapeEvent` is emitted (Item A code). Change the flow to:

1. After `detect_column_shape`, if shape is `free_text_heterogeneous`, run per-value GLiNER + aggregator in a try/except; merge into `result`.
2. Only after that, emit `ColumnShapeEvent` with populated latency fields.

Replace the existing block (the exact lines may shift — search for `# ── Sprint 13 Item A: emit ColumnShapeEvent ──`) with:

```python
        # ── Sprint 13 Item A: column-shape detection ─────────────────────
        try:
            shape_detection = detect_column_shape(column, result)
        except Exception:
            logger.debug("Shape detection failed; defaulting to structured_single behavior", exc_info=True)
            shape_detection = None
        self.emitter.emit(
            ClassificationEvent(
                column_id=column.column_id,
                total_findings=len(result),
                total_ms=round(total_ms, 2),
                engines_executed=engines_executed,
                engines_skipped=engines_skipped,
                run_id=run_id or "",
            )
        )

        # ── Sprint 13 Item B: per-value GLiNER on heterogeneous branch ────
        # Union design (2026-04-17): per-value aggregated findings are
        # MERGED with the cascade output, not replaced. Regex floor is
        # preserved. Duplicate entity_types are deduped by keeping the
        # higher-confidence finding.
        per_value_inference_ms: int | None = None
        sampled_row_count: int | None = None
        if shape_detection is not None and shape_detection.shape == "free_text_heterogeneous":
            gliner = self._find_engine_by_name("gliner2")
            if gliner is not None:
                t0 = time.monotonic()
                try:
                    per_value_spans, sampled = gliner.classify_per_value(column)
                    if sampled > 0:
                        from data_classifier.orchestrator.per_value_aggregator import (
                            aggregate_per_value_spans,
                        )

                        aggregated = aggregate_per_value_spans(
                            per_value_spans,
                            n_samples=sampled,
                            column_id=column.column_id,
                        )
                        result = _union_findings(result, aggregated)
                        sampled_row_count = sampled
                except Exception:
                    logger.exception(
                        "Per-value GLiNER handler failed for column %s; "
                        "falling back to cascade output",
                        column.column_id,
                    )
                finally:
                    per_value_inference_ms = int((time.monotonic() - t0) * 1000)

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
                    per_value_inference_ms=per_value_inference_ms,
                    sampled_row_count=sampled_row_count,
                    run_id=run_id or "",
                )
            )
```

Then add these two helpers near the bottom of `orchestrator.py` (module scope, before the last class/function):

```python
def _union_findings(
    cascade: list[ClassificationFinding],
    additions: list[ClassificationFinding],
) -> list[ClassificationFinding]:
    """Union cascade findings with per-value aggregated additions.

    Dedup rule: (column_id, entity_type) is the key. On duplicate, keep
    the higher-confidence finding — this preserves the cascade's regex
    floor when regex fires at 0.95+ while GLiNER confirms at 0.7, and
    lets GLiNER win when it fires with materially higher confidence on
    an entity the cascade scored low on.

    Sprint 13 Item B union design: additions add entity types the
    cascade did not express (ORGANIZATION, free-form DOB, prose
    PERSON_NAME) and the cascade's own findings are never dropped.
    """
    by_key: dict[tuple[str, str], ClassificationFinding] = {
        (f.column_id, f.entity_type): f for f in cascade
    }
    for f in additions:
        key = (f.column_id, f.entity_type)
        existing = by_key.get(key)
        if existing is None or f.confidence > existing.confidence:
            by_key[key] = f
    return list(by_key.values())
```

And add a method to the `Orchestrator` class (next to other private helpers):

```python
    def _find_engine_by_name(self, name: str) -> ClassificationEngine | None:
        """Return the engine registered under ``name``, or ``None`` if absent.

        Used by the Sprint 13 Item B per-value branch to dispatch to the
        GLiNER engine without coupling the orchestrator to a specific
        engine class.
        """
        for engine in self._engines:
            if engine.name == name:
                return engine
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/orchestrator/test_heterogeneous_branch_integration.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Run broader orchestrator tests to catch regressions**

Run: `.venv/bin/pytest tests/orchestrator/ tests/test_orchestrator_column_shape_event.py tests/test_meta_classifier_shadow.py -v`
Expected: All green. Pay attention to any test that counted emissions of `ColumnShapeEvent` — the emission now happens after the per-value branch.

- [ ] **Step 6: Commit**

```bash
git add data_classifier/orchestrator/orchestrator.py tests/orchestrator/test_heterogeneous_branch_integration.py
git commit -m "feat(orchestrator): wire per-value GLiNER into heterogeneous branch (union)

Sprint 13 Item B. On free_text_heterogeneous shape, run
GLiNER2Engine.classify_per_value, aggregate via
aggregate_per_value_spans, and union the result with the post-merge
cascade output. Duplicate entity types resolve by higher confidence.
On any failure, fall back to unmodified cascade output.

ColumnShapeEvent now carries per_value_inference_ms and
sampled_row_count on the heterogeneous branch (both None on other
shapes, per Item A schema).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Safety audit Q3 extension (union win condition)

**Files:**
- Modify: `tests/benchmarks/meta_classifier/sprint12_safety_audit.py`
- Test: `tests/benchmarks/meta_classifier/` (existing audit tests)

**Why:** The new acceptance criteria need machine-checkable verification. Q3 previously checked `collapse_verdict` values; we add two new structural asserts:
1. **Superset:** orchestrator output ⊇ pre-Item-B cascade set (regex floor preserved),
2. **GLiNER lift:** on ≥ 3 of 6 fixtures, GLiNER contributed ≥ 1 entity type not in the cascade set,
3. **Hallucination guard:** no fixture emits an entity type outside a per-fixture allowlist.

- [ ] **Step 1: Read the current Q3 logic**

Find the Q3 block in `tests/benchmarks/meta_classifier/sprint12_safety_audit.py`. Note where `collapse_verdict` values are assigned and where `aggregate_verdict` is computed. (Item A added `router_deflected` as a verdict.)

- [ ] **Step 2: Add per-fixture plausible-entity allowlists**

Near the top of the Q3 fixture definitions, add:

```python
# Sprint 13 Item B (2026-04-17): per-fixture allowlist of plausible
# entity types. Anything outside this set emitted on the fixture is a
# hallucination and fails the precision guard. Kept conservative —
# false positives on the allowlist are cheaper than false positives on
# the precision test.
Q3_PLAUSIBLE_ENTITIES: dict[str, set[str]] = {
    "original_q3_log": {"EMAIL", "IP_ADDRESS", "URL", "API_KEY", "PERSON_NAME", "ORGANIZATION"},
    "apache_access_log": {"IP_ADDRESS", "URL"},
    "json_event_log": {"EMAIL", "IP_ADDRESS", "URL", "PERSON_NAME"},
    "base64_encoded_payloads": set(),  # nothing plausibly identifiable
    "support_chat_messages": {"EMAIL", "PHONE", "PERSON_NAME", "ORGANIZATION", "DATE_OF_BIRTH"},
    "kafka_event_stream": {"EMAIL", "IP_ADDRESS", "URL", "PERSON_NAME"},
}
```

- [ ] **Step 3: Extend per-fixture runner**

Inside the per-fixture loop (where `live_findings` is currently computed for Q3), add a second capture — the post-Item-B union output. Since the orchestrator now does this automatically on the hetero branch, the two are equal on hetero columns: `live_findings` IS the union output. The "pre-Item-B cascade" can be captured by running a classification that forces `structured_single` shape (which bypasses the per-value branch). The simplest approach:

- Keep `live_findings` as the post-Item-B orchestrator result.
- Capture a separate `cascade_baseline` by running the same input through an orchestrator with the per-value branch disabled via monkey-patch — or simpler, store the pre-Item-B baseline as a committed JSON fixture (`tests/benchmarks/meta_classifier/sprint13_q3_cascade_baseline.json`) so the benchmark is self-contained and reproducible.

Create `tests/benchmarks/meta_classifier/sprint13_q3_cascade_baseline.json` by first running the Q3 fixtures **before** wiring Task 6 (or by using the Item-A-era family benchmark's known cascade outputs on these fixtures). Format:

```json
{
  "original_q3_log": ["API_KEY", "EMAIL", "IP_ADDRESS", "URL"],
  "apache_access_log": ["IP_ADDRESS"],
  "json_event_log": ["EMAIL", "IP_ADDRESS"],
  "base64_encoded_payloads": [],
  "support_chat_messages": ["EMAIL", "PHONE"],
  "kafka_event_stream": ["EMAIL", "IP_ADDRESS", "URL"]
}
```

(These match the current `live_findings` from `docs/research/meta_classifier/sprint13_item_a_safety_audit.json` §`q3_heterogeneous.per_fixture`.)

In the per-fixture loop, add these assertions:

```python
# Sprint 13 Item B union-design checks.
cascade_types = set(cascade_baseline[fixture_name])
emitted_types = {f.entity_type for f in live_findings}

# (a) Superset check: output ⊇ cascade.
missing = cascade_types - emitted_types
if missing:
    fixture_result["union_verdict"] = "regression"
    fixture_result["missing_cascade_types"] = sorted(missing)
else:
    fixture_result["union_verdict"] = "superset_ok"

# (b) GLiNER-only lift.
lift = emitted_types - cascade_types
fixture_result["gliner_only_types"] = sorted(lift)
fixture_result["has_gliner_lift"] = bool(lift)

# (c) Hallucination guard.
plausible = Q3_PLAUSIBLE_ENTITIES[fixture_name]
hallucinated = emitted_types - plausible
fixture_result["hallucinated_types"] = sorted(hallucinated)
```

And in the aggregate verdict block:

```python
regressions = [f for f in q3_results["per_fixture"] if f.get("union_verdict") == "regression"]
lift_count = sum(1 for f in q3_results["per_fixture"] if f.get("has_gliner_lift"))
hallucinations = [f for f in q3_results["per_fixture"] if f.get("hallucinated_types")]

q3_results["n_cascade_regressions"] = len(regressions)
q3_results["n_fixtures_with_gliner_lift"] = lift_count
q3_results["n_fixtures_with_hallucinations"] = len(hallucinations)

if regressions:
    q3_results["aggregate_verdict"] = "RED_CASCADE_REGRESSION"
elif hallucinations:
    q3_results["aggregate_verdict"] = "YELLOW_HALLUCINATION"
elif lift_count >= 3:
    q3_results["aggregate_verdict"] = "GREEN_UNION_LIFT"
else:
    # Safe but unconvincing — no regression, but < 3 fixtures got real lift.
    q3_results["aggregate_verdict"] = "YELLOW_NO_LIFT"
```

- [ ] **Step 4: Run the safety audit and verify results**

Run: `.venv/bin/python -m tests.benchmarks.meta_classifier.sprint12_safety_audit`
Expected: exits 0, writes updated JSON. Inspect:

```bash
python3 -c "
import json
s = json.load(open('/tmp/sprint13_item_b_safety_audit.json'))
print('Q3 aggregate:', s['q3_heterogeneous']['aggregate_verdict'])
print('lift count:', s['q3_heterogeneous']['n_fixtures_with_gliner_lift'])
print('regressions:', s['q3_heterogeneous']['n_cascade_regressions'])
print('hallucinations:', s['q3_heterogeneous']['n_fixtures_with_hallucinations'])
"
```

Expected: verdict `GREEN_UNION_LIFT`, regressions = 0. If hallucinations > 0, revisit the aggregator's coverage threshold (Task 5) before declaring Task 7 done.

- [ ] **Step 5: Save as Item B baseline**

```bash
cp /tmp/sprint13_item_b_safety_audit.json docs/research/meta_classifier/sprint13_item_b_safety_audit.json
git add tests/benchmarks/meta_classifier/sprint12_safety_audit.py tests/benchmarks/meta_classifier/sprint13_q3_cascade_baseline.json docs/research/meta_classifier/sprint13_item_b_safety_audit.json
```

- [ ] **Step 6: Commit**

```bash
git commit -m "test(safety-audit): Q3 union-design checks — superset, lift, hallucination

Sprint 13 Item B. New asserts on the 6 Q3 fixtures:
  (a) orchestrator output ⊇ pre-Item-B cascade set (no regex floor loss)
  (b) ≥ 3 of 6 fixtures show a GLiNER-only entity type (real lift)
  (c) no fixture emits an entity type outside its plausible allowlist

Baselined sprint13_item_b_safety_audit.json and cascade baseline JSON.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Family benchmark no-regression check

**Files:**
- Run: `tests/benchmarks/family_accuracy_benchmark.py`
- Output: `docs/research/meta_classifier/sprint13_item_b_family_benchmark.json`

**Why:** Item B only touches the heterogeneous branch, which makes up ~11.25% of the 9870-row family benchmark corpus (from Item A: 1110 / 9870 columns). The structured_single slice (77%) must be unchanged; the opaque_tokens slice (12%) must also be unchanged. The emitted-metric slice (post-Item-A) must not regress.

- [ ] **Step 1: Run the benchmark against the Sprint 13 Item A baseline**

Run:

```bash
DATA_CLASSIFIER_DISABLE_ML=0 \
    .venv/bin/python -m tests.benchmarks.family_accuracy_benchmark \
    --out /tmp/item_b.predictions.jsonl \
    --summary /tmp/item_b.summary.json \
    --compare-to docs/research/meta_classifier/sprint13_item_a_family_benchmark.json
```

(Note `DISABLE_ML=0` — ML engines ON so GLiNER actually runs.)

Expected: exits 0. The summary JSON will include a `delta_vs_previous` section.

- [ ] **Step 2: Inspect the delta**

```bash
python3 -c "
import json
s = json.load(open('/tmp/item_b.summary.json'))
print('=== shadow emitted (structured_single slice) ===')
sf = s['shadow']['overall']['family']
print('  cross_family_rate_emitted:', sf['cross_family_rate_emitted'])
print('  family_macro_f1_emitted:', sf['family_macro_f1_emitted'])
print('  router_suppression_rate:', sf['router_suppression_rate'])
print('=== live overall ===')
lf = s['live']['overall']['family']
print('  cross_family_rate:', lf['cross_family_rate'])
print('  family_macro_f1:', lf['family_macro_f1'])
print('=== delta vs Item A ===')
print(json.dumps(s['delta_vs_previous'], indent=2))
"
```

Expected:
- `shadow.cross_family_rate_emitted` ≤ 0.0001 (no regression on structured_single).
- `shadow.router_suppression_rate` ≈ 0.2305 (Item A baseline, unchanged — router is upstream of B).
- `live.cross_family_rate` may shift slightly on hetero columns because union adds GLiNER findings; the structured-single majority means overall change is small. Acceptable band: `|Δ| ≤ 0.01`. Anything larger flags investigation.

- [ ] **Step 3: If regression detected, bisect**

If `shadow.cross_family_rate_emitted` rose > 0.0001, something is wrong — the hetero branch should be invisible to structured_single columns. Likely cause: `_find_engine_by_name` matched but per-value call ran on a non-hetero column. Re-read Task 6 step 3 and confirm the guard `shape_detection.shape == "free_text_heterogeneous"` is in place.

- [ ] **Step 4: Commit the baseline**

```bash
cp /tmp/item_b.summary.json docs/research/meta_classifier/sprint13_item_b_family_benchmark.json
git add docs/research/meta_classifier/sprint13_item_b_family_benchmark.json
git commit -m "chore(benchmark): baseline family benchmark after Item B union wiring

Confirms no regression on structured_single slice and characterizes
live-output delta on heterogeneous columns now that GLiNER per-value
findings are unioned with the cascade.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Sprint 13 handover — latency characterization + Item B close-out

**Files:**
- Modify: `docs/sprints/SPRINT13_HANDOVER.md` (create if missing; copy the Sprint 12 structure)

**Why:** Sprint 13 scoping Q2 decision was "measure, do not gate". The handover is where the measurement is written down. Without it there's no input signal for the Sprint 14 decision on whether to impose a latency fallback threshold.

- [ ] **Step 1: Collect latency data from the Q3 fixtures**

Run:

```bash
python3 -c "
import json
s = json.load(open('docs/research/meta_classifier/sprint13_item_b_safety_audit.json'))
for f in s['q3_heterogeneous']['per_fixture']:
    print(f'{f[\"fixture\"]:30s} sampled={f.get(\"sampled_row_count\", \"?\"):>3} ms={f.get(\"per_value_inference_ms\", \"?\"):>5}')
"
```

- [ ] **Step 2: Collect latency data from 10 synthetic heterogeneous columns**

Create a short script `tests/benchmarks/item_b_latency_probe.py`:

```python
"""Probe per-value latency across 10 synthetic heterogeneous columns."""

from __future__ import annotations

import json
import sys

from data_classifier.core.types import ColumnInput
from data_classifier.events.emitter import EventEmitter
from data_classifier.events.types import ColumnShapeEvent
from data_classifier.orchestrator.orchestrator import Orchestrator


def _columns() -> list[ColumnInput]:
    templates = [
        ("app_log", "{i} alice@example.com logged in from 10.0.0.{i}"),
        ("audit", "user {i} updated record at 2026-04-17T10:{i:02d}"),
        ("json_event", '{{"user":"u{i}","ip":"10.0.0.{i}","org":"ExampleCo"}}'),
        ("chat", "Hi, my email is user{i}@example.com, please call me at 555-0{i:03d}"),
        ("kafka", "event={i} source=10.0.0.{i} url=https://example.com/api/{i}"),
        ("nginx", '10.0.0.{i} - - [17/Apr/2026:10:{i:02d}:00 +0000] "GET /{i} HTTP/1.1" 200'),
        ("syslog", "Apr 17 10:{i:02d}:00 host sshd[{i}]: Accepted for user{i}"),
        ("backup", "backup_{i} of org ExampleCo by alice@example.com at 10:{i:02d}"),
        ("trace", "trace_id=abc{i} user=user{i}@example.com latency_ms={i}00"),
        ("report", "Report {i}: contact alice@example.com or call +1-555-0{i:03d}"),
    ]
    return [
        ColumnInput(
            column_id=f"probe_{name}",
            column_name=name,
            sample_values=[tpl.format(i=i) for i in range(50)],
        )
        for name, tpl in templates
    ]


def main() -> None:
    events: list[object] = []
    emitter = EventEmitter()
    emitter.subscribe(events.append)
    orchestrator = Orchestrator(emitter=emitter)

    for col in _columns():
        orchestrator.classify_column(col)

    shape_events = [e for e in events if isinstance(e, ColumnShapeEvent)]
    rows = [
        {
            "column_id": e.column_id,
            "shape": e.shape,
            "sampled_row_count": e.sampled_row_count,
            "per_value_inference_ms": e.per_value_inference_ms,
        }
        for e in shape_events
    ]
    json.dump({"rows": rows}, sys.stdout, indent=2)


if __name__ == "__main__":
    main()
```

Run:

```bash
.venv/bin/python -m tests.benchmarks.item_b_latency_probe > /tmp/item_b_latency.json
python3 -c "
import json
rows = json.load(open('/tmp/item_b_latency.json'))['rows']
het = [r for r in rows if r['shape'] == 'free_text_heterogeneous' and r['per_value_inference_ms'] is not None]
if het:
    ms = sorted([r['per_value_inference_ms'] for r in het])
    n = len(ms)
    print(f'n={n}  min={ms[0]}ms  median={ms[n//2]}ms  p90={ms[int(n*0.9)]}ms  max={ms[-1]}ms')
    for r in het:
        print(f'  {r[\"column_id\"]:25s} sampled={r[\"sampled_row_count\"]:3d} ms={r[\"per_value_inference_ms\"]}')
"
```

- [ ] **Step 3: Draft the handover section**

Append to `docs/sprints/SPRINT13_HANDOVER.md` (create if it doesn't exist; model after the Sprint 12 handover structure):

```markdown
## Item B — Per-Value GLiNER Aggregation (Union Design)

**Status:** Shipped 2026-04-17. Phase = review.

### Architectural change
On `free_text_heterogeneous` columns, the orchestrator now runs
`GLiNER2Engine.classify_per_value` on a deterministic N=60 subsample,
aggregates spans via `aggregate_per_value_spans`, and **unions** the
result with the post-merge cascade findings. Duplicate entity types are
deduped by higher confidence. Cascade regex floor is preserved.

Spec revision 2026-04-17: the original "GLiNER replaces cascade" framing
was changed to "GLiNER augments cascade" — the commit message on
backlog/sprint13-per-value-gliner-aggregation.yaml captures the
rationale (regex precision, English-only model, hallucination risk).

### Safety audit Q3 — GREEN_UNION_LIFT
See `docs/research/meta_classifier/sprint13_item_b_safety_audit.json`.
All 6 fixtures:
  - No cascade-set regression (superset assertion holds).
  - GLiNER contributed ≥ 1 non-cascade entity type on <N> of 6 fixtures.
  - No hallucinations outside the per-fixture plausible allowlist.

### Family benchmark — no regression
See `docs/research/meta_classifier/sprint13_item_b_family_benchmark.json`.
  - `shadow.cross_family_rate_emitted`: <value> (Item A baseline: 0.0001).
  - `shadow.family_macro_f1_emitted`: <value> (Item A baseline: 0.9999).
  - `live.cross_family_rate` delta: <value> — within ±0.01 band.

### Per-value latency — "measure, do not gate" (Sprint 13 scoping Q2)

Q3 fixtures (6 columns, ONNX GLiNER v1, 50-row samples):

| Fixture | sampled | ms |
|---|---|---|
| original_q3_log | <n> | <ms> |
| apache_access_log | <n> | <ms> |
| json_event_log | <n> | <ms> |
| base64_encoded_payloads | <n> | <ms> |
| support_chat_messages | <n> | <ms> |
| kafka_event_stream | <n> | <ms> |

Synthetic heterogeneous probe (10 columns, 50 rows each):

  - min: <ms>
  - median: <ms>
  - p90: <ms>
  - max: <ms>

### Sprint 14 decision point
Sprint 13 shipped with no latency gate. Before Sprint 14 imposes a
timeout fallback, the ColumnShapeEvent stream from production should
accumulate at least 1 week of data so the tail (p99) can be
characterized against the Sprint 13 in-repo measurement.

### Files touched
(auto-filled by the commit message audit; see `git log --oneline sprint13/main`)

### Follow-ups not taken
(carried over from backlog `sprint13-per-value-gliner-aggregation.yaml`
Notes block unchanged — non-English generalization, structured-branch
GLiNER assist, per-entity-type confidence calibration.)
```

Replace `<n>`, `<ms>`, `<value>`, `<N>` with the numbers from steps 1–2.

- [ ] **Step 4: Commit**

```bash
git add docs/sprints/SPRINT13_HANDOVER.md tests/benchmarks/item_b_latency_probe.py
git commit -m "docs(sprint13): Item B handover + latency characterization

Documents the union-design change, safety-audit GREEN_UNION_LIFT verdict,
family-benchmark no-regression, and per-fixture + synthetic-probe
latency distribution. Sets up the Sprint 14 'should we impose a gate'
decision point.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: CI gate + close-out

**Files:**
- Run: full CI suite
- Move: backlog item to phase=review

- [ ] **Step 1: Run ruff**

```bash
ruff check . --exclude .claude/worktrees && ruff format --check . --exclude .claude/worktrees
```
Expected: zero warnings, zero diffs.

- [ ] **Step 2: Run full test suite**

```bash
.venv/bin/pytest tests/ -v
```
Expected: all pass (~1615 tests — +15 from Task 4, +9 from Task 5, +5 from Task 6 = ~1629; adjust for any added boilerplate).

- [ ] **Step 3: Verify benchmark JSONs committed**

```bash
git status
git log --oneline sprint13/main ^main | head -15
```
Expected: clean tree, commits for Tasks 1–9 visible.

- [ ] **Step 4: Move backlog item to review**

```bash
agile-backlog edit sprint13-per-value-gliner-aggregation --phase review
git add backlog/sprint13-per-value-gliner-aggregation.yaml
git commit -m "chore(sprint13): mark Item B phase=review after CI gate"
```

- [ ] **Step 5: Push**

```bash
git push origin sprint13/main
```

---

## Self-Review (before dispatching subagents)

### 1. Spec coverage
- "GLiNERInferenceEngine supports a per_value mode" → Task 4 ✔
- "aggregate_per_value_spans helper exists" → Task 5 ✔
- "Orchestrator free_text_heterogeneous branch calls per-value handler and merges via authority passes" → Task 6 ✔ (union via `_union_findings`; note this is NOT a full re-run of the 7-pass authority merge — it's a simpler dedupe-on-`(column_id, entity_type)`-keep-higher-confidence. The spec text says "authority + suppression passes" but Item B's union is narrower: cascade findings are already post-merge, so re-running authority on them is a no-op; we only need to reconcile new GLiNER findings against them. If reviewer disagrees, the fix is to extract the 7-pass logic into a pure helper and call it here — ~half day of work, deferable to Sprint 14.)
- "Output is a SUPERSET of pre-Item-B cascade" → Task 7 check (a) ✔
- "GLiNER contributes ≥ 1 entity type not in cascade on ≥ 3 of 6 fixtures" → Task 7 check (b) ✔
- "No hallucination" → Task 7 check (c) ✔
- "Integration test produces GREEN after this item lands" → Task 7 ✔
- "No regression on family benchmark" → Task 8 ✔
- "Lint + format clean, full test suite green" → Task 10 ✔
- "Per-value latency measured + characterized" → Task 9 ✔
- "`per_value_gliner_sample_size` exposed in engine_defaults.yaml" → Task 2 ✔ (named `per_value_sample_size` under the `gliner_engine:` section — slightly shorter than the spec's YAML key name; update the spec YAML if strict naming matters, otherwise the shorter name is fine since the `gliner_engine.` prefix disambiguates).

### 2. Placeholders — none.

### 3. Type consistency — `SpanDetection` is introduced in Task 1 and used unchanged through Tasks 4, 5, 6. `classify_per_value` signature is `(column: ColumnInput, *, sample_size: int | None = None) -> tuple[list[list[SpanDetection]], int]` consistent across Tasks 4 and 6. `aggregate_per_value_spans` signature is consistent across Tasks 5 and 6.

### 4. Known scope deviations (flagged for user review at spec revision)
1. Config key name: spec says `per_value_gliner_sample_size`; plan uses `per_value_sample_size` under a `gliner_engine:` parent — the prefix provides the namespacing. If the spec's literal name is required, it's a one-line fix.
2. "Authority + suppression passes" wording in spec implies re-running the 7-pass merge on the unioned set. The plan uses `_union_findings`, a simpler `(column_id, entity_type)` dedupe-keep-higher-confidence. Rationale: cascade findings are already post-merge; authority collisions live inside the cascade, not between cascade and GLiNER. GLiNER ⊕ cascade only needs entity-type-level dedup. If Sprint 13 review finds a case where authority re-run would matter (e.g., cascade's column_name_engine finds ORGANIZATION at authority 10 and GLiNER finds PERSON_NAME at authority 5 and both conflict on the same column), the fix is to invoke the existing merge helper. Explicitly deferred pending a real example.

---

## Execution Handoff

Plan complete and saved to `docs/plans/2026-04-17-sprint13-item-b-per-value-gliner-aggregation.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — fresh implementer subagent per task, two-stage review (spec compliance → code quality) between tasks. Fast iteration.
2. **Inline Execution** — execute tasks sequentially in this session with checkpoints. Slower but one less handoff.

Which approach?
