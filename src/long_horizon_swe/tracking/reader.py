"""Bounded validation of complete JSONL records, including valid partial runs."""

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from long_horizon_swe.tracking.errors import TraceReadError
from long_horizon_swe.tracking.event import TERMINAL_EVENTS, Event, EventType
from long_horizon_swe.tracking.recorder import MAX_EVENT_BYTES

MAX_TRACE_BYTES = 64 * 1024 * 1024
MAX_TRACE_EVENTS = 100_000


@dataclass(frozen=True)
class ReadTrace:
    events: tuple[Event, ...]
    records: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return self.events[-1].event_type in TERMINAL_EVENTS


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    values: dict[str, object] = {}
    for key, value in pairs:
        if key in values:
            raise ValueError("duplicate JSON key")
        values[key] = value
    return values


def _finite_json(value: str) -> object:
    raise ValueError("non-finite JSON number")


def read_trace(path: Path) -> ReadTrace:
    events: list[Event] = []
    records: list[str] = []
    total = 0
    line_number = 1
    try:
        with path.open("rb") as source:
            while raw := source.readline(MAX_EVENT_BYTES + 1):
                total += len(raw)
                if len(raw) > MAX_EVENT_BYTES:
                    raise TraceReadError("record exceeds size limit", line_number=line_number)
                if total > MAX_TRACE_BYTES or line_number > MAX_TRACE_EVENTS:
                    raise TraceReadError("trace exceeds read limits", line_number=line_number)
                if not raw.endswith(b"\n"):
                    raise TraceReadError(
                        "record is truncated (missing newline)", line_number=line_number
                    )
                record = raw.decode("utf-8")
                data = json.loads(
                    record, object_pairs_hook=_unique_keys, parse_constant=_finite_json
                )
                event = Event.model_validate(data)
                if event.sequence != line_number:
                    raise TraceReadError("non-contiguous sequence", line_number=line_number)
                if not events and event.event_type != EventType.RUN_STARTED:
                    raise TraceReadError(
                        "trace must start with RUN_STARTED", line_number=line_number
                    )
                if events:
                    previous = events[-1]
                    if event.run_id != previous.run_id:
                        raise TraceReadError("mixed run identifiers", line_number=line_number)
                    if event.elapsed_ms < previous.elapsed_ms:
                        raise TraceReadError("elapsed time decreased", line_number=line_number)
                    if previous.event_type in TERMINAL_EVENTS:
                        raise TraceReadError(
                            "record follows terminal event", line_number=line_number
                        )
                    if event.event_type == EventType.RUN_STARTED:
                        raise TraceReadError("duplicate run start", line_number=line_number)
                events.append(event)
                records.append(record)
                line_number += 1
    except TraceReadError:
        raise
    except (OSError, ValueError, UnicodeError, RecursionError, ValidationError) as error:
        raise TraceReadError("cannot read a valid event record", line_number=line_number) from error
    if not events:
        raise TraceReadError("trace is empty", line_number=1)
    return ReadTrace(tuple(events), tuple(records))
