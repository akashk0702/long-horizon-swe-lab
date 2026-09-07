import json
import sys
from pathlib import Path

import pytest

from long_horizon_swe.core.exceptions import VerifierProtocolError
from long_horizon_swe.core.result import ExecutionResult
from long_horizon_swe.core.task import TaskSpec
from long_horizon_swe.evaluation.adapters import JsonVerifierAdapter
from long_horizon_swe.evaluation.parser import parse_document
from long_horizon_swe.evaluation.verifier import BehavioralVerifier
from long_horizon_swe.execution.options import ProcessOptions, WorkspaceOptions
from long_horizon_swe.execution.process import ProcessRunner
from long_horizon_swe.execution.runner import TaskRunner


@pytest.fixture
def valid_document() -> dict:
    return {
        "schema_version": "1.0",
        "passed": True,
        "tests_passed": 1,
        "tests_failed": 0,
        "details": [],
    }


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": "2.0"},
        {"passed": "true"},
        {"tests_passed": 0},
        {"tests_failed": 1},
        {"tests_failed": True},
        {"tests_passed": None},
        {"extra": "value"},
        {"passed": False},
        {"tests_passed": -1},
    ],
)
def test_protocol_rejects_contradictory_and_invalid_fields(
    valid_document: dict, change: dict
) -> None:
    with pytest.raises(VerifierProtocolError):
        parse_document(json.dumps(valid_document | change))


@pytest.mark.parametrize(
    "field", ["schema_version", "passed", "tests_passed", "tests_failed", "details"]
)
def test_protocol_requires_all_fields(valid_document: dict, field: str) -> None:
    del valid_document[field]
    with pytest.raises(VerifierProtocolError):
        parse_document(json.dumps(valid_document))


@pytest.mark.parametrize(
    "text",
    [
        "",
        "[]",
        "not JSON",
        '{"passed":true,"passed":false}',
        '{"number":NaN}',
        '{"number":Infinity}',
        "[" * 2000 + "]" * 2000,
    ],
)
def test_protocol_rejects_malformed_json(text: str) -> None:
    with pytest.raises(VerifierProtocolError):
        parse_document(text)


def test_extra_stdout_is_not_ignored(valid_document: dict) -> None:
    serialized = json.dumps(valid_document)
    for output in ["banner\n" + serialized, serialized + "\nnoise", serialized + serialized]:
        with pytest.raises(VerifierProtocolError):
            parse_document(output)


@pytest.mark.parametrize(
    "change",
    [
        {"exit_code": 2},
        {"timed_out": True},
        {"stdout_truncated": True},
        {"stderr_truncated": True},
        {"stdout_decode_errors": True},
    ],
)
def test_success_document_cannot_override_process_evidence(
    valid_document: dict, change: dict
) -> None:
    execution = ExecutionResult.model_validate(
        dict(
            command=["verifier"],
            exit_code=0,
            stdout=json.dumps(valid_document),
            stderr="",
            duration_ms=1.0,
            timed_out=False,
        )
        | change
    )
    with pytest.raises(VerifierProtocolError):
        JsonVerifierAdapter().parse_result(execution)


@pytest.mark.parametrize("exit_code", [0, 1])
def test_failed_document_remains_failed_even_with_zero_exit(
    valid_document: dict, exit_code: int
) -> None:
    document = valid_document | {
        "passed": False,
        "tests_failed": 1,
        "details": ["assertion failed"],
    }
    result = JsonVerifierAdapter().parse_result(
        ExecutionResult(
            command=("verifier",),
            exit_code=exit_code,
            stdout=json.dumps(document),
            stderr="",
            duration_ms=1.0,
            timed_out=False,
        )
    )
    assert not result.passed
    assert result.tests_failed == 1


def _task(task_data: dict, code: str, **changes: object) -> TaskSpec:
    return TaskSpec.model_validate(
        task_data | {"verification_command": [sys.executable, "-c", code], **changes}
    )


def test_real_behavior_is_verified_and_source_remains_unchanged(
    task_data: dict, tmp_path: Path
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "input.txt").write_text("expected", encoding="utf-8")
    # The operator-authored command runs an actual assertion and counts its outcome.
    code = "\n".join(
        [
            "import json,pathlib",
            "passed=failed=0; details=[]",
            "try:",
            "    assert pathlib.Path('input.txt').read_text() == 'expected'",
            "    passed += 1",
            "except AssertionError:",
            "    failed += 1; details.append('input differs')",
            "pathlib.Path('input.txt').write_text('modified copy')",
            "print(json.dumps(dict(schema_version='1.0',passed=failed==0,tests_passed=passed,tests_failed=failed,details=details)))",
        ]
    )
    runner = TaskRunner(options=WorkspaceOptions(temp_parent=tmp_path))
    success = runner.verify(_task(task_data, code), source)
    assert success.status == "completed"
    assert success.verification.tests_passed == 1
    assert success.executions[0].duration_ms > 0
    assert success.duration_ms >= success.executions[0].duration_ms
    assert (source / "input.txt").read_text() == "expected"
    assert list(tmp_path.iterdir()) == [source]
    (source / "input.txt").write_text("wrong", encoding="utf-8")
    failure = runner.verify(_task(task_data, code), source)
    assert failure.status == "failed"
    assert failure.verification.tests_failed == 1
    assert (source / "input.txt").read_text() == "wrong"


@pytest.mark.parametrize("code", ["print('not JSON')", "raise SystemExit(0)"])
def test_candidate_report_files_are_not_verification_evidence(
    tmp_path: Path, task_data: dict, valid_document: dict, code: str
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "result.json").write_text(json.dumps(valid_document), encoding="utf-8")
    result = TaskRunner().verify(_task(task_data, code), source)
    assert result.status == "failed"
    assert result.verification.tests_passed is None
    assert result.verification.tests_failed is None


def test_timeout_retains_a_recoverable_workspace(tmp_path: Path, task_data: dict) -> None:
    source = tmp_path / "source"
    source.mkdir()
    code = "import pathlib,time; pathlib.Path('partial.txt').write_text('progress'); time.sleep(30)"
    runner = TaskRunner(options=WorkspaceOptions(temp_parent=tmp_path, retain_on_failure=True))
    result = runner.verify(_task(task_data, code, timeout_seconds=1.5), source)
    assert result.status == "failed"
    assert result.executions[0].timed_out
    assert result.verification.tests_passed is None
    retained = Path(result.retained_workspace)
    assert (retained / "repository" / "partial.txt").read_text() == "progress"
    assert list(source.iterdir()) == []


def test_truncated_verifier_output_is_not_success(
    tmp_path: Path, task_data: dict, valid_document: dict
) -> None:
    runner = TaskRunner(BehavioralVerifier(ProcessRunner(ProcessOptions(max_stdout_bytes=5))))
    result = runner.verify(_task(task_data, f"print({json.dumps(valid_document)!r})"), tmp_path)
    assert not result.verification.passed
    assert result.executions[0].stdout_truncated
    assert result.verification.tests_passed is None


def test_launch_failure_has_unknown_counts_and_no_invented_exit(
    tmp_path: Path, task_data: dict
) -> None:
    task = TaskSpec.model_validate(
        task_data | {"verification_command": ["missing-executable-4927"]}
    )
    result = TaskRunner().verify(task, tmp_path)
    assert result.status == "failed"
    assert result.executions == ()
    assert result.verification.exit_code is None
    assert result.verification.tests_passed is None
    assert "ProcessLaunchError" in result.failure_reason
