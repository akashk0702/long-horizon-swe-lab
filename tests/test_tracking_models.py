from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from long_horizon_swe.tracking.artifacts import ResultArtifact
from long_horizon_swe.tracking.event import (
    Event,
    EventType,
    ProcessStartedPayload,
    RunFailedPayload,
    RunStartedPayload,
)


@pytest.fixture
def event_data() -> dict:
    # Model-only synthetic data. Integration tests record real operations separately.
    return dict(
        schema_version="1.0",
        run_id=uuid4(),
        sequence=1,
        event_type=EventType.RUN_STARTED,
        timestamp_utc=datetime(2026, 1, 1, tzinfo=UTC),
        elapsed_ms=0.0,
        payload={"operation": "verify"},
    )


def test_event_round_trip_preserves_typed_payload(event_data: dict) -> None:
    event = Event.model_validate(event_data)
    assert isinstance(event.payload, RunStartedPayload)
    assert Event.model_validate_json(event.model_dump_json()) == event


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": "2.0"},
        {"schema_version": 1.0},
        {"run_id": "not-a-uuid"},
        {"sequence": 0},
        {"sequence": True},
        {"elapsed_ms": -1},
        {"elapsed_ms": float("nan")},
        {"elapsed_ms": "1.0"},
        {"timestamp_utc": datetime(2026, 1, 1)},
        {"timestamp_utc": "2026-01-01T00:00:00"},
        {"timestamp_utc": 0},
        {"timestamp_utc": datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1)))},
        {"event_type": "UNKNOWN"},
        {"payload": {"duration_ms": 1}},
        {"extra": "field"},
    ],
)
def test_invalid_envelopes_are_rejected(event_data: dict, change: dict) -> None:
    with pytest.raises(ValidationError):
        Event.model_validate(event_data | change)


def test_event_payload_cannot_be_repurposed_for_another_type(event_data: dict) -> None:
    with pytest.raises(ValidationError):
        Event.model_validate(event_data | {"event_type": EventType.PROCESS_STARTED})
    with pytest.raises(ValidationError):
        Event.model_validate(
            event_data
            | {"payload": ProcessStartedPayload(executable_name="python", arguments_omitted=2)}
        )


def test_process_payload_rejects_absolute_host_paths() -> None:
    for name in ["/system/python", "C:\\system\\python.exe"]:
        with pytest.raises(ValidationError):
            ProcessStartedPayload(executable_name=name, arguments_omitted=2)


def test_failure_artifact_requires_real_failure_shape() -> None:
    failure = RunFailedPayload(failure_type="configuration", message="Configuration failed.")
    artifact = ResultArtifact(
        schema_version="1.0", run_id=uuid4(), outcome="failure", result=None, failure=failure
    )
    assert ResultArtifact.model_validate_json(artifact.model_dump_json()) == artifact
    with pytest.raises(ValidationError):
        ResultArtifact(
            schema_version="1.0", run_id=uuid4(), outcome="result", result=None, failure=failure
        )
