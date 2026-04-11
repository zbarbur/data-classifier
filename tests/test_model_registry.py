"""Tests for model registry — Sprint 4 Stream C.

All tests use mock models and require NO ML dependencies (torch, transformers, etc.).
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from data_classifier.core.types import ClassificationFinding, ClassificationProfile, ColumnInput
from data_classifier.engines.interface import ClassificationEngine
from data_classifier.registry import ModelRegistry, check_model_deps, get_model, register_model
from data_classifier.registry.model_entry import ModelDependencyError, ModelEntry

# ── ModelEntry basics ───────────────────────────────────────────────────────


class TestModelEntry:
    def test_create_entry(self):
        loader = MagicMock(return_value="model_instance")
        entry = ModelEntry(name="test-model", loader=loader, model_class="test.Model", requires=["json"])
        assert entry.name == "test-model"
        assert entry.model_class == "test.Model"
        assert entry.requires == ["json"]
        assert entry._instance is None
        assert entry._loaded is False

    def test_repr_excludes_private_fields(self):
        entry = ModelEntry(name="test-model", loader=lambda: None, model_class="test.Model", requires=[])
        r = repr(entry)
        assert "test-model" in r
        assert "_instance" not in r
        assert "_lock" not in r


# ── Registration ────────────────────────────────────────────────────────────


class TestRegistration:
    def test_register_and_list(self):
        registry = ModelRegistry()
        registry.register("mock-model", loader=lambda: "instance", model_class="mock.Model")
        assert "mock-model" in registry.list_registered()

    def test_duplicate_name_raises(self):
        registry = ModelRegistry()
        registry.register("dup-model", loader=lambda: "a", model_class="mock.A")
        with pytest.raises(ValueError, match="already registered"):
            registry.register("dup-model", loader=lambda: "b", model_class="mock.B")

    def test_list_registered_empty(self):
        registry = ModelRegistry()
        assert registry.list_registered() == []


# ── Lazy loading ────────────────────────────────────────────────────────────


class TestLazyLoading:
    def test_not_loaded_after_register(self):
        registry = ModelRegistry()
        registry.register("lazy-model", loader=lambda: "instance", model_class="mock.Model", requires=["json"])
        assert registry.is_loaded("lazy-model") is False

    def test_get_calls_loader_once(self):
        loader = MagicMock(return_value="model_obj")
        registry = ModelRegistry()
        registry.register("once-model", loader=loader, model_class="mock.Model", requires=["json"])

        result1 = registry.get("once-model")
        assert result1 == "model_obj"
        assert registry.is_loaded("once-model") is True
        assert loader.call_count == 1

        result2 = registry.get("once-model")
        assert result2 is result1  # same instance
        assert loader.call_count == 1  # NOT called again

    def test_get_unknown_model_raises(self):
        registry = ModelRegistry()
        with pytest.raises(KeyError, match="not registered"):
            registry.get("nonexistent")


# ── Dependency checking ─────────────────────────────────────────────────────


class TestDependencyCheck:
    def test_missing_dependency(self):
        registry = ModelRegistry()
        registry.register("needs-fake", loader=lambda: "x", model_class="fake.Model", requires=["nonexistent_pkg_xyz"])
        ok, missing = registry.check_dependencies("needs-fake")
        assert ok is False
        assert "nonexistent_pkg_xyz" in missing

    def test_stdlib_dependency_ok(self):
        registry = ModelRegistry()
        registry.register("needs-json", loader=lambda: "x", model_class="std.Model", requires=["json"])
        ok, missing = registry.check_dependencies("needs-json")
        assert ok is True
        assert missing == []

    def test_get_raises_model_dependency_error(self):
        registry = ModelRegistry()
        registry.register("bad-deps", loader=lambda: "x", model_class="bad.Model", requires=["nonexistent_pkg_xyz"])
        with pytest.raises(ModelDependencyError, match="nonexistent_pkg_xyz"):
            registry.get("bad-deps")

    def test_no_requires_defaults_empty(self):
        registry = ModelRegistry()
        registry.register("no-req", loader=lambda: "x", model_class="nr.Model")
        ok, missing = registry.check_dependencies("no-req")
        assert ok is True
        assert missing == []


# ── Unload ──────────────────────────────────────────────────────────────────


class TestUnload:
    def test_unload_releases_instance(self):
        loader = MagicMock(return_value="instance")
        registry = ModelRegistry()
        registry.register("unload-me", loader=loader, model_class="mock.Model", requires=["json"])

        registry.get("unload-me")
        assert registry.is_loaded("unload-me") is True

        registry.unload("unload-me")
        assert registry.is_loaded("unload-me") is False

    def test_get_after_unload_reloads(self):
        call_count = 0

        def counting_loader():
            nonlocal call_count
            call_count += 1
            return f"instance_{call_count}"

        registry = ModelRegistry()
        registry.register("reload-me", loader=counting_loader, model_class="mock.Model", requires=["json"])

        first = registry.get("reload-me")
        assert first == "instance_1"

        registry.unload("reload-me")
        second = registry.get("reload-me")
        assert second == "instance_2"
        assert call_count == 2

    def test_unload_all(self):
        registry = ModelRegistry()
        registry.register("m1", loader=lambda: "a", model_class="mock.A", requires=["json"])
        registry.register("m2", loader=lambda: "b", model_class="mock.B", requires=["json"])
        registry.get("m1")
        registry.get("m2")
        assert registry.is_loaded("m1") is True
        assert registry.is_loaded("m2") is True

        registry.unload_all()
        assert registry.is_loaded("m1") is False
        assert registry.is_loaded("m2") is False

    def test_unload_unknown_raises(self):
        registry = ModelRegistry()
        with pytest.raises(KeyError):
            registry.unload("nope")


# ── classify_batch default implementation ───────────────────────────────────


class ConcreteEngine(ClassificationEngine):
    """Minimal concrete engine for testing classify_batch."""

    name = "test-engine"
    order = 100
    supported_modes = frozenset({"structured"})

    def classify_column(
        self,
        column: ColumnInput,
        *,
        profile: ClassificationProfile | None = None,
        min_confidence: float = 0.5,
        mask_samples: bool = False,
        max_evidence_samples: int = 5,
    ) -> list[ClassificationFinding]:
        return [
            ClassificationFinding(
                column_id=column.column_id,
                entity_type="MOCK",
                confidence=0.9,
                engine="test-engine",
                sensitivity="LOW",
                category="PII",
                regulatory=[],
            )
        ]


class TestClassifyBatch:
    def test_default_delegates_to_classify_column(self):
        engine = ConcreteEngine()
        columns = [ColumnInput(column_id=f"col_{i}", column_name=f"col_{i}", data_type="STRING") for i in range(3)]
        results = engine.classify_batch(columns)
        assert len(results) == 3
        for i, findings in enumerate(results):
            assert len(findings) == 1
            assert findings[0].column_id == f"col_{i}"

    def test_classify_batch_calls_classify_column_per_item(self):
        engine = ConcreteEngine()
        engine.classify_column = MagicMock(return_value=[])  # type: ignore[method-assign]
        columns = [ColumnInput(column_id=f"col_{i}", column_name=f"col_{i}", data_type="STRING") for i in range(3)]
        engine.classify_batch(columns)
        assert engine.classify_column.call_count == 3


# ── Module-level convenience functions ──────────────────────────────────────


class TestModuleLevelFunctions:
    def test_register_and_get(self):
        """Test module-level register_model / get_model / check_model_deps."""
        # These operate on the module-level _registry singleton.
        # Use a unique name to avoid collisions with other tests.
        import data_classifier.registry as reg

        # Save and restore to avoid leaking state
        old_registry = reg._registry
        reg._registry = ModelRegistry()
        try:
            register_model("mod-level", loader=lambda: "ml_instance", model_class="ml.Model", requires=["json"])
            ok, missing = check_model_deps("mod-level")
            assert ok is True
            assert missing == []
            result = get_model("mod-level")
            assert result == "ml_instance"
        finally:
            reg._registry = old_registry


# ── Thread safety ───────────────────────────────────────────────────────────


class TestThreadSafety:
    def test_concurrent_get_calls_loader_once(self):
        call_count = 0
        lock = threading.Lock()

        def slow_loader():
            nonlocal call_count
            with lock:
                call_count += 1
            # Simulate some load time
            import time

            time.sleep(0.01)
            return "shared_instance"

        registry = ModelRegistry()
        registry.register("thread-model", loader=slow_loader, model_class="mock.Model", requires=["json"])

        results = [None] * 10
        errors = []

        def worker(idx):
            try:
                results[idx] = registry.get("thread-model")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors in threads: {errors}"
        assert call_count == 1, f"Loader called {call_count} times, expected 1"
        assert all(r == "shared_instance" for r in results)
