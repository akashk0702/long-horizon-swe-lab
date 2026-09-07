"""A small state machine supporting investigation, feedback, and explicit retries."""

from enum import StrEnum
from types import MappingProxyType
from typing import Final

from long_horizon_swe.core.exceptions import InvalidStateTransition


class TaskState(StrEnum):
    PENDING = "pending"
    INSPECTING = "inspecting"
    IMPLEMENTING = "implementing"
    TESTING = "testing"
    FAILED = "failed"
    COMPLETED = "completed"


_TRANSITIONS: Final = MappingProxyType(
    {
        TaskState.PENDING: frozenset({TaskState.INSPECTING, TaskState.FAILED}),
        TaskState.INSPECTING: frozenset(
            {TaskState.IMPLEMENTING, TaskState.TESTING, TaskState.FAILED}
        ),
        TaskState.IMPLEMENTING: frozenset(
            {TaskState.INSPECTING, TaskState.TESTING, TaskState.FAILED}
        ),
        TaskState.TESTING: frozenset(
            {TaskState.IMPLEMENTING, TaskState.COMPLETED, TaskState.FAILED}
        ),
        TaskState.FAILED: frozenset({TaskState.INSPECTING}),
        TaskState.COMPLETED: frozenset(),
    }
)


def transition(current: TaskState, target: TaskState) -> TaskState:
    """Return an allowed next state without recording or fabricating an execution event.

    FAILED -> INSPECTING denotes a caller-requested retry. Completing a run also
    requires a passing verification result; see TaskResult.
    """
    if target not in _TRANSITIONS[current]:
        raise InvalidStateTransition(f"cannot transition from {current.value} to {target.value}")
    return target
