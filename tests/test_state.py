import pytest

from long_horizon_swe.core.exceptions import InvalidStateTransition
from long_horizon_swe.core.state import TaskState, transition


def follow(*states: TaskState) -> TaskState:
    current = states[0]
    for target in states[1:]:
        current = transition(current, target)
    return current


def test_workflow_can_return_to_investigation_and_respond_to_test_feedback() -> None:
    final = follow(
        TaskState.PENDING,
        TaskState.INSPECTING,
        TaskState.IMPLEMENTING,
        TaskState.INSPECTING,
        TaskState.IMPLEMENTING,
        TaskState.TESTING,
        TaskState.IMPLEMENTING,
        TaskState.TESTING,
        TaskState.COMPLETED,
    )
    assert final == TaskState.COMPLETED


def test_failure_recovery_restarts_investigation() -> None:
    final = follow(
        TaskState.PENDING,
        TaskState.FAILED,
        TaskState.INSPECTING,
        TaskState.TESTING,
        TaskState.FAILED,
        TaskState.INSPECTING,
        TaskState.IMPLEMENTING,
        TaskState.TESTING,
        TaskState.COMPLETED,
    )
    assert final == TaskState.COMPLETED


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskState.PENDING, TaskState.COMPLETED),
        (TaskState.IMPLEMENTING, TaskState.COMPLETED),
        (TaskState.FAILED, TaskState.COMPLETED),
        (TaskState.FAILED, TaskState.TESTING),
        (TaskState.INSPECTING, TaskState.INSPECTING),
    ],
)
def test_illegal_skips_have_actionable_errors(current: TaskState, target: TaskState) -> None:
    with pytest.raises(InvalidStateTransition, match=f"{current.value} to {target.value}"):
        transition(current, target)


@pytest.mark.parametrize("target", list(TaskState))
def test_completed_is_terminal(target: TaskState) -> None:
    with pytest.raises(InvalidStateTransition):
        transition(TaskState.COMPLETED, target)
