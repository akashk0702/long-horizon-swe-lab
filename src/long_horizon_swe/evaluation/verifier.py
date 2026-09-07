"""Execute a declared, operator-trusted verifier and interpret only its captured output."""

from dataclasses import dataclass

from long_horizon_swe.core.exceptions import ProcessError, VerifierProtocolError
from long_horizon_swe.core.result import ExecutionResult, VerificationResult
from long_horizon_swe.core.task import TaskSpec
from long_horizon_swe.evaluation.adapters import JsonVerifierAdapter, VerifierAdapter
from long_horizon_swe.execution.environment import build_environment
from long_horizon_swe.execution.process import ProcessRunner
from long_horizon_swe.execution.workspace import PreparedWorkspace


@dataclass(frozen=True)
class VerificationOutcome:
    execution: ExecutionResult | None
    verification: VerificationResult


class BehavioralVerifier:
    def __init__(
        self, process_runner: ProcessRunner | None = None, adapter: VerifierAdapter | None = None
    ) -> None:
        self.process_runner = process_runner or ProcessRunner()
        self.adapter = adapter or JsonVerifierAdapter()

    def verify(self, task: TaskSpec, workspace: PreparedWorkspace) -> VerificationOutcome:
        environment = build_environment(workspace, task.environment)
        try:
            execution = self.process_runner.run(
                self.adapter.build_command(task),
                cwd=workspace.cwd,
                environment=environment,
                timeout_seconds=task.timeout_seconds,
            )
        except ProcessError as error:
            return VerificationOutcome(
                None,
                VerificationResult(
                    passed=False,
                    tests_passed=None,
                    tests_failed=None,
                    exit_code=None,
                    duration_ms=error.duration_ms,
                    details=(f"{type(error).__name__}: {error}",),
                ),
            )
        try:
            verification = self.adapter.parse_result(execution)
        except VerifierProtocolError as error:
            verification = VerificationResult(
                passed=False,
                tests_passed=None,
                tests_failed=None,
                exit_code=execution.exit_code,
                duration_ms=execution.duration_ms,
                details=(str(error),),
            )
        return VerificationOutcome(execution, verification)
