import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from long_horizon_swe.tracking.errors import TraceReadError, TraceWriteError
from long_horizon_swe.tracking.event import (
    EmptyPayload,
    EventType,
    RunCompletedPayload,
    RunFailedPayload,
    RunStartedPayload,
    TaskValidatedPayload,
)
from long_horizon_swe.tracking.reader import read_trace
from long_horizon_swe.tracking.recorder import MAX_EVENT_BYTES, TraceRecorder
from long_horizon_swe.tracking.replay import render_json, render_timeline


@pytest.fixture
def trace_path(tmp_path: Path) -> Path:
    path = tmp_path / "trace.jsonl"
    counter = iter([0, 0, 1_234_567, 2_000_000])
    wall = datetime(2026, 1, 1, tzinfo=UTC)
    stamps = iter([wall, wall - timedelta(seconds=2), wall + timedelta(seconds=1)])
    recorder = TraceRecorder(
        path, uuid4(), monotonic_ns=lambda: next(counter), utc_now=lambda: next(stamps)
    )
    recorder.emit(EventType.RUN_STARTED, RunStartedPayload())
    recorder.emit(EventType.TASK_VALIDATED, TaskValidatedPayload(task_id="trace-contract"))
    recorder.emit(EventType.RUN_COMPLETED, RunCompletedPayload(duration_ms=1.0))
    recorder.close()
    assert recorder.error is None
    return path


def test_read_and_replay_use_sequence_not_wall_clock(trace_path: Path) -> None:
    trace = read_trace(trace_path)
    assert [event.sequence for event in trace.events] == [1, 2, 3]
    assert [event.elapsed_ms for event in trace.events] == [0, 1.234567, 2]
    assert trace.events[1].timestamp_utc < trace.events[0].timestamp_utc
    assert trace.complete
    timeline = render_timeline(trace)
    assert "00:00.001  TASK_VALIDATED" in timeline
    assert (
        timeline.index("RUN_STARTED")
        < timeline.index("TASK_VALIDATED")
        < timeline.index("RUN_COMPLETED")
    )
    assert json.loads(render_json(trace)) == [
        json.loads(line) for line in trace_path.read_text().splitlines()
    ]


def test_records_are_flushed_before_close_and_partial_run_is_explicit(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    recorder = TraceRecorder(path, uuid4())
    try:
        recorder.emit(EventType.RUN_STARTED, RunStartedPayload())
        assert path.read_bytes().endswith(b"\n")
        trace = read_trace(path)
        assert not trace.complete
        assert "Incomplete trace" in render_timeline(trace)
    finally:
        recorder.close()


@pytest.mark.parametrize(
    "mutation",
    [
        "malformed",
        "truncated",
        "schema",
        "mixed_id",
        "gap",
        "duplicate",
        "elapsed",
        "terminal",
        "oversized",
        "timezone",
        "unknown_event",
        "payload",
        "duplicate_key",
        "blank",
        "second_start",
        "invalid_utf8",
        "missing_version",
    ],
)
def test_corruption_reports_the_offending_line(trace_path: Path, mutation: str) -> None:
    lines = trace_path.read_bytes().splitlines(keepends=True)
    record = json.loads(lines[1])
    line_number = 2
    if mutation == "malformed":
        lines[1] = b"{bad JSON}\n"
    elif mutation == "truncated":
        lines = [lines[0], lines[1].rstrip(b"\n")]
    elif mutation == "oversized":
        lines[1] = b"x" * (MAX_EVENT_BYTES + 1) + b"\n"
    elif mutation == "terminal":
        terminal = json.loads(lines[-1])
        terminal["sequence"] = 4
        lines.append((json.dumps(terminal) + "\n").encode())
        line_number = 4
    elif mutation == "blank":
        lines[1] = b"\n"
    elif mutation == "invalid_utf8":
        lines[1] = b"\xff\n"
    elif mutation == "duplicate_key":
        lines[1] = lines[1].replace(b'"sequence":2', b'"sequence":2,"sequence":2')
    else:
        if mutation == "schema":
            record["schema_version"] = "2.0"
        elif mutation == "mixed_id":
            record["run_id"] = str(uuid4())
        elif mutation == "gap":
            record["sequence"] = 3
        elif mutation == "duplicate":
            record["sequence"] = 1
        elif mutation == "elapsed":
            # Give the first record a later elapsed value while retaining contiguous sequence.
            first = json.loads(lines[0])
            first["elapsed_ms"] = 2.0
            lines[0] = (json.dumps(first) + "\n").encode()
        elif mutation == "timezone":
            record["timestamp_utc"] = "2026-01-01T00:00:00"
        elif mutation == "unknown_event":
            record["event_type"] = "UNKNOWN"
        elif mutation == "payload":
            record["payload"] = {"exit_code": 0}
        elif mutation == "second_start":
            record["event_type"] = "RUN_STARTED"
            record["payload"] = {"operation": "verify"}
        elif mutation == "missing_version":
            del record["schema_version"]
        lines[1] = (json.dumps(record) + "\n").encode()
    trace_path.write_bytes(b"".join(lines))
    with pytest.raises(TraceReadError) as error:
        read_trace(trace_path)
    assert error.value.line_number == line_number
    if mutation == "terminal":
        assert "terminal" in str(error.value)


def test_empty_trace_and_missing_file_fail_clearly(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    with pytest.raises(TraceReadError) as missing:
        read_trace(path)
    assert missing.value.line_number == 1
    path.touch()
    with pytest.raises(TraceReadError, match="empty"):
        read_trace(path)


def test_utf8_records_preserve_non_ascii_diagnostics(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    recorder = TraceRecorder(path, uuid4())
    recorder.emit(EventType.RUN_STARTED, RunStartedPayload())
    recorder.emit(
        EventType.RUN_FAILED,
        RunFailedPayload(failure_type="configuration", message="Synthetic Unicode: café λ"),
    )
    recorder.close()
    assert recorder.error is None
    assert "café λ".encode() in path.read_bytes()
    assert read_trace(path).events[-1].payload.message == "Synthetic Unicode: café λ"


def test_recorder_does_not_backfill_after_clock_failure(tmp_path: Path) -> None:
    ticks = iter([1_000_000, 2_000_000, 1_000_000])
    path = tmp_path / "trace.jsonl"
    recorder = TraceRecorder(path, uuid4(), monotonic_ns=lambda: next(ticks))
    recorder.emit(EventType.RUN_STARTED, RunStartedPayload())
    recorder.emit(EventType.WORKSPACE_PREPARATION_STARTED, EmptyPayload())
    recorder.emit(EventType.WORKSPACE_PREPARED, EmptyPayload())
    recorder.close()
    assert recorder.error is not None
    assert recorder.error.line_number == 2
    assert len(read_trace(path).events) == 1


def test_existing_trace_cannot_be_overwritten(trace_path: Path) -> None:
    before = trace_path.read_bytes()
    with pytest.raises(TraceWriteError):
        TraceRecorder(trace_path, uuid4())
    assert trace_path.read_bytes() == before


def test_record_size_limit_fails_without_writing_invalid_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("long_horizon_swe.tracking.recorder.MAX_EVENT_BYTES", 1)
    path = tmp_path / "trace.jsonl"
    recorder = TraceRecorder(path, uuid4())
    recorder.emit(EventType.RUN_STARTED, RunStartedPayload())
    recorder.close()
    assert recorder.error is not None
    assert path.read_bytes() == b""


@pytest.mark.parametrize("failure", ["write", "partial_write", "flush", "close"])
def test_io_errors_are_reported_without_retry(tmp_path: Path, failure: str) -> None:
    path = tmp_path / "trace.jsonl"
    recorder = TraceRecorder(path, uuid4())
    recorder.emit(EventType.RUN_STARTED, RunStartedPayload())
    stream = recorder._stream

    class BrokenStream:
        def write(self, data: bytes) -> int:
            if failure == "write":
                raise OSError("synthetic write failure")
            if failure == "partial_write":
                return stream.write(data[:10])
            return stream.write(data)

        def flush(self) -> None:
            if failure == "flush":
                raise OSError("synthetic flush failure")
            stream.flush()

        def close(self) -> None:
            stream.close()
            if failure == "close":
                raise OSError("synthetic close failure")

    recorder._stream = BrokenStream()
    recorder.emit(EventType.WORKSPACE_PREPARATION_STARTED, EmptyPayload())
    recorder.close()
    assert recorder.error is not None
    if failure == "partial_write":
        with pytest.raises(TraceReadError) as error:
            read_trace(path)
        assert error.value.line_number == 2
    else:
        assert len(read_trace(path).events) == (1 if failure == "write" else 2)


@pytest.mark.parametrize("limit_name", ["MAX_TRACE_BYTES", "MAX_TRACE_EVENTS"])
def test_total_read_limits_are_enforced(
    trace_path: Path, monkeypatch: pytest.MonkeyPatch, limit_name: str
) -> None:
    monkeypatch.setattr(f"long_horizon_swe.tracking.reader.{limit_name}", 1)
    with pytest.raises(TraceReadError, match="read limits"):
        read_trace(trace_path)
