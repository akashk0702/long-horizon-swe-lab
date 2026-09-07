"""Render validated stored evidence. This module has no execution dependency."""

import json

from long_horizon_swe.tracking.event import (
    ProcessCompletedPayload,
    ProcessStartedPayload,
    RunFailedPayload,
    TaskValidatedPayload,
    VerificationCompletedPayload,
)
from long_horizon_swe.tracking.reader import ReadTrace


def render_timeline(trace: ReadTrace) -> str:
    task = next(
        (
            event.payload.task_id
            for event in trace.events
            if isinstance(event.payload, TaskValidatedPayload)
        ),
        "not validated",
    )
    lines = [f"Run: {trace.events[0].run_id}", f"Task: {task}"]
    for event in trace.events:
        # Truncate to recorded whole milliseconds; do not invent sub-ms display precision.
        minutes, remainder = divmod(int(event.elapsed_ms), 60_000)
        seconds, milliseconds = divmod(remainder, 1000)
        label = f"{minutes:02}:{seconds:02}.{milliseconds:03}  {event.event_type.value}"
        payload = event.payload
        if isinstance(payload, ProcessStartedPayload):
            label += (
                f"  {json.dumps(payload.executable_name)}"
                f" [{payload.arguments_omitted} arguments omitted]"
            )
        elif isinstance(payload, ProcessCompletedPayload):
            label += f"  exit={payload.exit_code} timed_out={str(payload.timed_out).lower()}"
        elif isinstance(payload, VerificationCompletedPayload):
            label += f"  passed={str(payload.passed).lower()}"
        elif isinstance(payload, RunFailedPayload):
            label += f"  {payload.failure_type}: {json.dumps(payload.message)}"
        lines.append(label)
    if not trace.complete:
        lines.append("Incomplete trace: no terminal run event was recorded.")
    return "\n".join(lines)


def render_json(trace: ReadTrace) -> str:
    # Records were fully validated before output. Preserve field values without model coercion.
    return "[" + ",".join(record.strip() for record in trace.records) + "]"
