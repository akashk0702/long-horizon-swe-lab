"""Interpretation stays separate from process management and candidate files."""

from typing import Protocol

from long_horizon_swe.core.exceptions import VerifierProtocolError
from long_horizon_swe.core.result import ExecutionResult, VerificationResult
from long_horizon_swe.core.task import TaskSpec
from long_horizon_swe.evaluation.parser import parse_document


class VerifierAdapter(Protocol):
    def build_command(self, task: TaskSpec) -> tuple[str, ...]: ...

    def parse_result(self, result: ExecutionResult) -> VerificationResult: ...


class JsonVerifierAdapter:
    """Trust the operator's verifier implementation, never a workspace report file."""

    def build_command(self, task: TaskSpec) -> tuple[str, ...]:
        return task.verification_command

    def parse_result(self, result: ExecutionResult) -> VerificationResult:
        if result.timed_out:
            raise VerifierProtocolError("verifier exceeded its timeout")
        if result.stdout_truncated or result.stderr_truncated:
            raise VerifierProtocolError(
                "verifier output was truncated; complete evidence is required"
            )
        if result.stdout_decode_errors:
            raise VerifierProtocolError("verifier stdout is not valid UTF-8")
        document = parse_document(result.stdout)
        if document.passed and result.exit_code != 0:
            raise VerifierProtocolError("verifier claimed success but exited unsuccessfully")
        return VerificationResult(
            passed=document.passed,
            tests_passed=document.tests_passed,
            tests_failed=document.tests_failed,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
            details=document.details,
        )
