"""Pluggable event emitter for classification telemetry.

The library emits events; consumers decide how to handle them.
Default is NullHandler (discard).  Consumers can register handlers
at initialization for logging, metrics, or persistence.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict
from typing import Any, Callable, Protocol

logger = logging.getLogger(__name__)

EventData = Any  # TierEvent | ClassificationEvent | any future event type


class EventHandler(Protocol):
    """Protocol for event handlers."""

    def handle(self, event: EventData) -> None: ...


class NullHandler:
    """Discards all events.  Default handler."""

    def handle(self, event: EventData) -> None:
        pass


class StdoutHandler:
    """Writes events as JSON lines to stdout."""

    def handle(self, event: EventData) -> None:
        print(json.dumps(asdict(event)), file=sys.stdout, flush=True)


class LogHandler:
    """Writes events via Python logging."""

    def __init__(self, level: int = logging.DEBUG) -> None:
        self._level = level

    def handle(self, event: EventData) -> None:
        logger.log(self._level, "%s: %s", type(event).__name__, asdict(event))


class CallbackHandler:
    """Calls a user-provided function for each event."""

    def __init__(self, callback: Callable[[EventData], None]) -> None:
        self._callback = callback

    def handle(self, event: EventData) -> None:
        self._callback(event)


class EventEmitter:
    """Dispatches events to registered handlers.

    Usage::

        emitter = EventEmitter()
        emitter.add_handler(StdoutHandler())
        emitter.emit(TierEvent(tier="regex", latency_ms=1.2, outcome="hit"))
    """

    def __init__(self) -> None:
        self._handlers: list[EventHandler] = []

    def add_handler(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    def emit(self, event: EventData) -> None:
        for handler in self._handlers:
            try:
                handler.handle(event)
            except Exception:
                logger.exception("Event handler %s failed", type(handler).__name__)
