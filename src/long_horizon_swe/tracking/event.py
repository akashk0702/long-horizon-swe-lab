"""Versioned event envelopes with event-specific, privacy-minimal payloads."""

from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Literal, Self

from pydantic import (
    UUID4,
    AwareDatetime,
    Field,
    StrictBool,
    StrictInt,
    ValidationInfo,
    field_validator,
    model_validator,
)

from long_horizon_swe.core.task import TaskId
from long_horizon_swe.core.types import ContractModel, DurationMs, NonBlank, NonNegativeInt


class EventType(StrEnum):
    RUN_STARTED = "RUN_STARTED"
    TASK_VALIDATED = "TASK_VALIDATED"
    WORKSPACE_PREPARATION_STARTED = "WORKSPACE_PREPARATION_STARTED"
    WORKSPACE_PREPARED = "WORKSPACE_PREPARED"
    VERIFICATION_STARTED = "VERIFICATION_STARTED"
    PROCESS_STARTED = "PROCESS_STARTED"
    PROCESS_COMPLETED = "PROCESS_COMPLETED"
    PROCESS_TIMED_OUT = "PROCESS_TIMED_OUT"
    VERIFICATION_COMPLETED = "VERIFICATION_COMPLETED"
    WORKSPACE_RETAINED = "WORKSPACE_RETAINED"
    WORKSPACE_CLEANUP_STARTED = "WORKSPACE_CLEANUP_STARTED"
    WORKSPACE_CLEANED = "WORKSPACE_CLEANED"
    RUN_COMPLETED = "RUN_COMPLETED"
    RUN_FAILED = "RUN_FAILED"


class EmptyPayload(ContractModel):
    """An operation boundary that needs no additional data."""


class RunStartedPayload(ContractModel):
    operation: Literal["verify"] = "verify"


class TaskValidatedPayload(ContractModel):
    task_id: TaskId


class WorkspacePayload(ContractModel):
    cwd_relative: Literal["repository"] = "repository"


class ProcessStartedPayload(ContractModel):
    executable_name: Annotated[str, Field(min_length=1, max_length=256)]
    arguments_omitted: NonNegativeInt
    cwd_relative: Literal["repository"] = "repository"

    @field_validator("executable_name")
    @classmethod
    def basename_only(cls, value: str) -> str:
        if "/" in value or "\\" in value:
            raise ValueError("event executable must be a basename, not a host path")
        return value


class ProcessCompletedPayload(ContractModel):
    exit_code: StrictInt | None
    duration_ms: DurationMs
    timed_out: StrictBool
    stdout_bytes_observed: NonNegativeInt
    stderr_bytes_observed: NonNegativeInt
    stdout_truncated: StrictBool
    stderr_truncated: StrictBool

    @model_validator(mode="after")
    def observed_exit_required(self) -> Self:
        if self.exit_code is None and not self.timed_out:
            raise ValueError("completed processes without timeout need an observed exit code")
        return self


class VerificationCompletedPayload(ContractModel):
    passed: StrictBool
    tests_passed: NonNegativeInt | None
    tests_failed: NonNegativeInt | None
    duration_ms: DurationMs

    @model_validator(mode="after")
    def counts_are_consistent(self) -> Self:
        if (self.tests_passed is None) != (self.tests_failed is None):
            raise ValueError("test counts must be observed together")
        if self.passed and (not self.tests_passed or self.tests_failed != 0):
            raise ValueError("passing verification requires observed passing tests only")
        return self


class RunCompletedPayload(ContractModel):
    duration_ms: DurationMs


class RunFailedPayload(ContractModel):
    failure_type: Literal[
        "configuration",
        "workspace",
        "verification",
        "timeout",
        "execution",
        "cancelled",
        "internal",
        "artifact",
    ]
    message: Annotated[NonBlank, Field(max_length=240)]


type Payload = (
    EmptyPayload
    | RunStartedPayload
    | TaskValidatedPayload
    | WorkspacePayload
    | ProcessStartedPayload
    | ProcessCompletedPayload
    | VerificationCompletedPayload
    | RunCompletedPayload
    | RunFailedPayload
)

PAYLOAD_TYPES: Mapping[EventType, type[ContractModel]] = MappingProxyType(
    {
        EventType.RUN_STARTED: RunStartedPayload,
        EventType.TASK_VALIDATED: TaskValidatedPayload,
        EventType.WORKSPACE_PREPARATION_STARTED: EmptyPayload,
        EventType.WORKSPACE_PREPARED: WorkspacePayload,
        EventType.VERIFICATION_STARTED: EmptyPayload,
        EventType.PROCESS_STARTED: ProcessStartedPayload,
        EventType.PROCESS_COMPLETED: ProcessCompletedPayload,
        EventType.PROCESS_TIMED_OUT: EmptyPayload,
        EventType.VERIFICATION_COMPLETED: VerificationCompletedPayload,
        EventType.WORKSPACE_RETAINED: WorkspacePayload,
        EventType.WORKSPACE_CLEANUP_STARTED: EmptyPayload,
        EventType.WORKSPACE_CLEANED: EmptyPayload,
        EventType.RUN_COMPLETED: RunCompletedPayload,
        EventType.RUN_FAILED: RunFailedPayload,
    }
)
TERMINAL_EVENTS = frozenset({EventType.RUN_COMPLETED, EventType.RUN_FAILED})


class Event(ContractModel):
    schema_version: Literal["1.0"]
    run_id: UUID4
    sequence: Annotated[int, Field(strict=True, ge=1)]
    event_type: EventType
    timestamp_utc: AwareDatetime
    elapsed_ms: DurationMs
    payload: Payload

    @field_validator("timestamp_utc", mode="before")
    @classmethod
    def timestamp_is_explicit(cls, value: object) -> object:
        if not isinstance(value, (datetime, str)):
            raise ValueError("timestamp must be a timezone-aware datetime or ISO datetime string")
        return value

    @field_validator("timestamp_utc")
    @classmethod
    def timestamp_is_utc(cls, value: AwareDatetime) -> AwareDatetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("timestamp_utc must have UTC offset zero")
        return value

    @field_validator("payload", mode="before")
    @classmethod
    def payload_matches_event(cls, value: object, info: ValidationInfo) -> object:
        kind = info.data.get("event_type")
        if kind is None:
            raise ValueError("a known event_type is required before validating payload")
        return PAYLOAD_TYPES[kind].model_validate(value)
