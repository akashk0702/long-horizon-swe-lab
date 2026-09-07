"""An observation port; operation code does not depend on recording or replay I/O."""

from typing import Protocol

from long_horizon_swe.tracking.event import EventType, Payload


class Observer(Protocol):
    def emit(self, event_type: EventType, payload: Payload) -> None: ...


class NullObserver:
    def emit(self, event_type: EventType, payload: Payload) -> None:
        pass
