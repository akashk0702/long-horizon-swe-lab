"""Serializable outcome contracts; these models do not measure or run anything."""

from typing import Literal, Self

from pydantic import Field, StrictBool, StrictInt, model_validator

from long_horizon_swe.core.state import TaskState
from long_horizon_swe.core.task import TaskId
from long_horizon_swe.core.types import (
    Command,
    ContractModel,
    DurationMs,
    NonBlank,
    NonNegativeInt,
)


class ExecutionResult(ContractModel):
    """A measured command outcome, including partial output after a timeout.

    A timeout may have a reaped exit code or None if no exit code was observed.
    Launch failures belong to the execution error boundary, not a fictional exit code.
    """

    command: Command
    exit_code: StrictInt | None
    stdout: str
    stderr: str
    duration_ms: DurationMs
    timed_out: StrictBool

    @model_validator(mode="after")
    def exit_code_was_observed(self) -> Self:
        if self.exit_code is None and not self.timed_out:
            raise ValueError("a command without a timeout must have an observed exit_code")
        return self

    @property
    def succeeded(self) -> bool:
        return not self.timed_out and self.exit_code == 0


class VerificationResult(ContractModel):
    """Behavioral test outcomes supplied by a future verifier adapter.

    Exit code zero is necessary but insufficient for success: the adapter must
    observe at least one passing test and no failures. Infrastructure failures
    may have no observed exit code and no counted tests.
    """

    passed: StrictBool
    tests_passed: NonNegativeInt
    tests_failed: NonNegativeInt
    exit_code: StrictInt | None
    duration_ms: DurationMs
    details: tuple[NonBlank, ...] = ()

    @model_validator(mode="after")
    def success_has_evidence(self) -> Self:
        if self.passed and (
            self.exit_code != 0 or self.tests_failed != 0 or self.tests_passed == 0
        ):
            raise ValueError("passing verification requires exit_code 0 and passing tests only")
        if not self.passed and not self.details:
            raise ValueError("failed verification requires diagnostic details")
        return self


class TaskResult(ContractModel):
    """A terminal report tied to verification, or to a diagnostic execution failure."""

    task_id: TaskId
    status: Literal[TaskState.COMPLETED, TaskState.FAILED]
    duration_ms: DurationMs
    verification: VerificationResult | None = None
    failure_reason: NonBlank | None = None
    executions: tuple[ExecutionResult, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def terminal_status_agrees(self) -> Self:
        if self.status == TaskState.COMPLETED:
            if self.verification is None or not self.verification.passed:
                raise ValueError("completed tasks require passing verification")
            if self.failure_reason is not None:
                raise ValueError("completed tasks cannot have a failure_reason")
        elif self.failure_reason is None:
            raise ValueError("failed tasks require a failure_reason")
        elif self.verification is not None and self.verification.passed:
            raise ValueError("failed tasks cannot report passing final verification")
        return self
