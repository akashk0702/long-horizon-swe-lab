import math

import pytest
from pydantic import ValidationError

from long_horizon_swe.core.result import ExecutionResult, TaskResult, VerificationResult
from long_horizon_swe.core.state import TaskState


@pytest.fixture
def execution() -> dict:
    # Synthetic values test serialization and invariants, not benchmark performance.
    return dict(
        command=["python", "-V"],
        exit_code=0,
        stdout="output\n",
        stderr="",
        duration_ms=1.5,
        timed_out=False,
    )


@pytest.fixture
def verification() -> dict:
    return dict(
        passed=True, tests_passed=2, tests_failed=0, exit_code=0, duration_ms=2.5, details=[]
    )


def test_execution_round_trip_and_success(execution: dict) -> None:
    result = ExecutionResult.model_validate(execution)
    assert result.succeeded
    assert ExecutionResult.model_validate_json(result.model_dump_json()) == result
    assert not ExecutionResult.model_validate(execution | {"exit_code": 7}).succeeded


@pytest.mark.parametrize("exit_code", [None, -9, 1, 0])
def test_timeout_keeps_partial_output_and_never_succeeds(
    execution: dict, exit_code: int | None
) -> None:
    result = ExecutionResult.model_validate(
        execution | {"timed_out": True, "exit_code": exit_code, "stderr": "partial diagnostic"}
    )
    assert not result.succeeded
    assert result.stderr == "partial diagnostic"
    assert result.exit_code == exit_code


@pytest.mark.parametrize(
    "change",
    [
        {"exit_code": None},
        {"exit_code": True},
        {"duration_ms": -1},
        {"duration_ms": math.inf},
        {"duration_ms": math.nan},
        {"duration_ms": True},
        {"timed_out": "false"},
        {"command": "python -V"},
        {"unexpected": 1},
    ],
)
def test_invalid_execution_measurements_are_rejected(execution: dict, change: dict) -> None:
    with pytest.raises(ValidationError):
        ExecutionResult.model_validate(execution | change)


@pytest.mark.parametrize(
    "change",
    [
        {"tests_failed": 1},
        {"tests_passed": 0},
        {"tests_passed": True},
        {"tests_passed": "2"},
        {"tests_failed": -1},
        {"exit_code": 1},
        {"exit_code": None},
        {"passed": "yes"},
        {"duration_ms": math.nan},
        {"passed": False},
    ],
)
def test_verification_cannot_claim_unsupported_success(verification: dict, change: dict) -> None:
    with pytest.raises(ValidationError):
        VerificationResult.model_validate(verification | change)


def test_infrastructure_failure_has_diagnostics_and_no_invented_test_counts() -> None:
    result = VerificationResult(
        passed=False,
        tests_passed=0,
        tests_failed=0,
        exit_code=None,
        duration_ms=0.0,
        details=("Verifier could not start.",),
    )
    assert VerificationResult.model_validate_json(result.model_dump_json()) == result


def test_terminal_report_contains_verification_and_round_trips(verification: dict) -> None:
    report = TaskResult(
        task_id="contract-check",
        status=TaskState.COMPLETED,
        duration_ms=5.0,
        verification=VerificationResult(**verification),
    )
    assert TaskResult.model_validate_json(report.model_dump_json()) == report


def test_failed_run_can_preserve_a_failed_verification(verification: dict) -> None:
    outcome = VerificationResult.model_validate(
        verification
        | {
            "passed": False,
            "tests_failed": 1,
            "exit_code": 1,
            "details": ["A behavior assertion failed."],
        }
    )
    result = TaskResult(
        task_id="contract-check",
        status=TaskState.FAILED,
        duration_ms=5.0,
        verification=outcome,
        failure_reason="Verification failed",
    )
    assert result.verification == outcome


@pytest.mark.parametrize("status", [TaskState.PENDING, TaskState.TESTING, TaskState.INSPECTING])
def test_reports_require_a_terminal_state(status: TaskState) -> None:
    with pytest.raises(ValidationError):
        TaskResult(task_id="contract-check", status=status, duration_ms=0.0)


def test_terminal_report_rejects_contradictory_outcomes(verification: dict) -> None:
    passing = VerificationResult(**verification)
    for fields in [
        {"status": TaskState.COMPLETED},
        {"status": TaskState.COMPLETED, "verification": passing, "failure_reason": "Failed"},
        {"status": TaskState.FAILED},
        {"status": TaskState.FAILED, "verification": passing, "failure_reason": "Failed"},
    ]:
        with pytest.raises(ValidationError):
            TaskResult(task_id="contract-check", duration_ms=0.0, **fields)


def test_unknown_counts_must_be_paired_and_cannot_support_success(verification: dict) -> None:
    for changes in [
        {"tests_passed": None},
        {"tests_failed": None},
        {"tests_passed": None, "tests_failed": None},
    ]:
        with pytest.raises(ValidationError):
            VerificationResult.model_validate(verification | changes)


def test_old_execution_documents_default_new_capture_flags_to_false(execution: dict) -> None:
    result = ExecutionResult.model_validate(execution)
    assert not result.stdout_truncated
    assert not result.stderr_truncated
    assert not result.stdout_decode_errors


def test_completed_report_cannot_claim_failed_workspace_retention(verification: dict) -> None:
    with pytest.raises(ValidationError, match="retain"):
        TaskResult(
            task_id="contract-check",
            duration_ms=1.0,
            status=TaskState.COMPLETED,
            verification=VerificationResult(**verification),
            retained_workspace="some-run",
        )
