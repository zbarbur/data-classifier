"""Model entry dataclass and related exceptions.

Each registered model is stored as a ``ModelEntry`` that holds the loader
callable, dependency list, and cached instance.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable


class ModelDependencyError(Exception):
    """Raised when a model's required packages are not installed."""


@dataclass
class ModelEntry:
    """Descriptor for a single registered model.

    Attributes:
        name: Unique model identifier (e.g. ``"gliner2-205m"``).
        loader: Factory callable that creates/loads the model instance.
        model_class: Qualified class name for error messages.
        requires: Package names that must be importable before loading.
    """

    name: str
    loader: Callable[[], Any]
    model_class: str
    requires: list[str] = field(default_factory=list)
    _instance: Any = field(default=None, repr=False)
    _loaded: bool = field(default=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
