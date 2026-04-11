"""Model registry — lazy-loading, thread-safe model management.

Provides a singleton :class:`ModelRegistry` for registering ML model loaders
and retrieving shared instances on demand.  Models are loaded lazily on first
``get()`` call and cached for subsequent calls.

Module-level convenience functions delegate to a default registry instance::

    from data_classifier.registry import register_model, get_model, check_model_deps

    register_model("gliner2-205m", loader=load_gliner, model_class="gliner2.GLiNER",
                    requires=["torch", "gliner"])
    model = get_model("gliner2-205m")  # loads on first call, cached after
"""

from __future__ import annotations

import importlib.util
import logging
from typing import Any, Callable

from data_classifier.registry.model_entry import ModelDependencyError, ModelEntry

__all__ = [
    "ModelRegistry",
    "ModelDependencyError",
    "ModelEntry",
    "register_model",
    "get_model",
    "check_model_deps",
]

logger = logging.getLogger(__name__)


class ModelRegistry:
    """Thread-safe, lazy-loading model registry.

    Each model is registered with a loader callable and a list of required
    packages.  On first ``get()``, dependencies are checked and the loader
    is called.  Subsequent ``get()`` calls return the cached instance.
    """

    def __init__(self) -> None:
        self._entries: dict[str, ModelEntry] = {}

    def register(
        self,
        name: str,
        *,
        loader: Callable[[], Any],
        model_class: str,
        requires: list[str] | None = None,
    ) -> None:
        """Register a model loader.

        Args:
            name: Unique model name.
            loader: Factory callable that returns the model instance.
            model_class: Qualified class name for error messages.
            requires: Package names that must be importable.

        Raises:
            ValueError: If a model with this name is already registered.
        """
        if name in self._entries:
            raise ValueError(f"Model '{name}' is already registered")
        self._entries[name] = ModelEntry(
            name=name,
            loader=loader,
            model_class=model_class,
            requires=requires or [],
        )
        logger.debug("Registered model '%s' (class=%s, requires=%s)", name, model_class, requires or [])

    def get(self, name: str) -> Any:
        """Get a model instance, loading lazily on first call.

        Thread-safe: concurrent calls block on per-entry lock; loader runs once.

        Args:
            name: Registered model name.

        Returns:
            The model instance.

        Raises:
            KeyError: If the model is not registered.
            ModelDependencyError: If required packages are missing.
        """
        entry = self._get_entry(name)
        if entry._loaded:
            return entry._instance
        with entry._lock:
            # Double-check after acquiring lock
            if entry._loaded:
                return entry._instance
            # Check dependencies before loading
            ok, missing = self._check_deps(entry)
            if not ok:
                raise ModelDependencyError(
                    f"Cannot load model '{name}' ({entry.model_class}): "
                    f"missing packages: {', '.join(missing)}. "
                    f"Install with: pip install {' '.join(missing)}"
                )
            logger.info("Loading model '%s' (%s)...", name, entry.model_class)
            entry._instance = entry.loader()
            entry._loaded = True
            logger.info("Model '%s' loaded successfully.", name)
            return entry._instance

    def is_loaded(self, name: str) -> bool:
        """Check whether a model is currently loaded in memory.

        Args:
            name: Registered model name.

        Returns:
            ``True`` if the model has been loaded via ``get()``.

        Raises:
            KeyError: If the model is not registered.
        """
        return self._get_entry(name)._loaded

    def unload(self, name: str) -> None:
        """Release a loaded model instance.

        The model remains registered and can be re-loaded via ``get()``.

        Args:
            name: Registered model name.

        Raises:
            KeyError: If the model is not registered.
        """
        entry = self._get_entry(name)
        with entry._lock:
            entry._instance = None
            entry._loaded = False
        logger.info("Unloaded model '%s'.", name)

    def unload_all(self) -> None:
        """Release all loaded model instances."""
        for name in list(self._entries):
            entry = self._entries[name]
            with entry._lock:
                entry._instance = None
                entry._loaded = False
        logger.info("Unloaded all models.")

    def list_registered(self) -> list[str]:
        """Return names of all registered models."""
        return list(self._entries.keys())

    def check_dependencies(self, name: str) -> tuple[bool, list[str]]:
        """Check whether a model's required packages are importable.

        Args:
            name: Registered model name.

        Returns:
            Tuple of ``(ok, missing)`` where *ok* is ``True`` when all
            dependencies are available and *missing* lists any that are not.

        Raises:
            KeyError: If the model is not registered.
        """
        return self._check_deps(self._get_entry(name))

    # ── Internal helpers ────────────────────────────────────────────────────

    def _get_entry(self, name: str) -> ModelEntry:
        try:
            return self._entries[name]
        except KeyError:
            raise KeyError(f"Model '{name}' is not registered") from None

    @staticmethod
    def _check_deps(entry: ModelEntry) -> tuple[bool, list[str]]:
        missing = [pkg for pkg in entry.requires if importlib.util.find_spec(pkg) is None]
        return (len(missing) == 0, missing)


# ── Module-level default registry and convenience functions ─────────────────

_registry = ModelRegistry()


def register_model(
    name: str,
    *,
    loader: Callable[[], Any],
    model_class: str,
    requires: list[str] | None = None,
) -> None:
    """Register a model on the default registry.

    See :meth:`ModelRegistry.register` for details.
    """
    _registry.register(name, loader=loader, model_class=model_class, requires=requires)


def get_model(name: str) -> Any:
    """Get a model from the default registry.

    See :meth:`ModelRegistry.get` for details.
    """
    return _registry.get(name)


def check_model_deps(name: str) -> tuple[bool, list[str]]:
    """Check dependencies on the default registry.

    See :meth:`ModelRegistry.check_dependencies` for details.
    """
    return _registry.check_dependencies(name)
