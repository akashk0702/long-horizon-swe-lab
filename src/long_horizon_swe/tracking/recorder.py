"""A synchronous JSONL writer that never supplies business success/failure decisions."""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from long_horizon_swe.tracking.errors import TraceWriteError
from long_horizon_swe.tracking.event import TERMINAL_EVENTS, Event, EventType, Payload

MAX_EVENT_BYTES = 32 * 1024


class TraceRecorder:
    def __init__(
        self,
        path: Path,
        run_id: UUID,
        *,
        monotonic_ns: Callable[[], int] = time.perf_counter_ns,
        utc_now: Callable[[], datetime] | None = None,
    ) -> None:
        self.run_id = run_id
        self._monotonic_ns = monotonic_ns
        self._utc_now = utc_now or (lambda: datetime.now(UTC))
        self._started = monotonic_ns()
        self._elapsed = 0.0
        self._sequence = 0
        self._terminal = False
        self.error: TraceWriteError | None = None
        try:
            self._stream = path.open("xb")
        except OSError as error:
            raise TraceWriteError("cannot create trace file") from error

    def emit(self, event_type: EventType, payload: Payload) -> None:
        # Once evidence writing fails, preserve the prefix. Never retry/backfill records.
        if self.error is not None:
            return
        try:
            elapsed = (self._monotonic_ns() - self._started) / 1_000_000
            if self._terminal or elapsed < self._elapsed:
                raise ValueError("terminal event or monotonic clock invariant violated")
            if self._sequence == 0 and event_type != EventType.RUN_STARTED:
                raise ValueError("a trace must start with RUN_STARTED")
            if self._sequence > 0 and event_type == EventType.RUN_STARTED:
                raise ValueError("RUN_STARTED may only be recorded once")
            event = Event(
                schema_version="1.0",
                run_id=self.run_id,
                sequence=self._sequence + 1,
                event_type=event_type,
                timestamp_utc=self._utc_now(),
                elapsed_ms=elapsed,
                payload=payload,
            )
            encoded = event.model_dump_json().encode("utf-8") + b"\n"
            if len(encoded) > MAX_EVENT_BYTES:
                raise ValueError("event exceeds the configured record limit")
            written = self._stream.write(encoded)
            if written != len(encoded):
                raise OSError("incomplete event write")
            self._stream.flush()
            self._sequence += 1
            self._elapsed = elapsed
            self._terminal = event_type in TERMINAL_EVENTS
        except (OSError, ValueError, ValidationError):
            self.error = TraceWriteError("trace recording failed", line_number=self._sequence + 1)

    def close(self) -> None:
        try:
            self._stream.close()
        except OSError:
            if self.error is None:
                self.error = TraceWriteError("trace close failed", line_number=self._sequence + 1)
