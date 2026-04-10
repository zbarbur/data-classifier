"""Engine interface — all classification engines implement this.

The base class defines the contract that the orchestrator depends on.
Each engine declares which modes it supports and its execution order
in the cascade.  The orchestrator filters engines by mode and runs
them in order.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from data_classifier.core.types import ClassificationFinding, ClassificationProfile, ColumnInput


class ClassificationEngine(ABC):
    """Base class for all classification engines.

    Subclasses must set the class-level attributes and implement
    ``classify_column``.  The orchestrator calls engines in ``order``
    sequence, filtering by ``supported_modes``.
    """

    name: str = ""
    """Unique engine identifier (e.g. ``regex``, ``column_name``, ``gliner2``)."""

    order: int = 0
    """Execution order in the cascade.  Lower runs first."""

    min_confidence: float = 0.0
    """Minimum confidence threshold for this engine to emit a finding."""

    supported_modes: set[str] = frozenset()
    """Which orchestrator modes this engine participates in.
    Valid values: ``structured``, ``unstructured``, ``prompt``."""

    @abstractmethod
    def classify_column(
        self,
        column: ColumnInput,
        *,
        profile: ClassificationProfile | None = None,
        min_confidence: float = 0.5,
        mask_samples: bool = False,
        max_evidence_samples: int = 5,
    ) -> list[ClassificationFinding]:
        """Classify a single column.  Return empty list if no findings."""
        ...

    def startup(self) -> None:
        """Optional lifecycle hook — called once before first use.

        Use for lazy model loading, pattern compilation, etc.
        Default is a no-op.
        """

    def shutdown(self) -> None:
        """Optional lifecycle hook — called on orchestrator shutdown.

        Use for releasing model memory, closing connections, etc.
        Default is a no-op.
        """
