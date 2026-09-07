"""Own evidence lifetime without letting recording failures change a test verdict."""

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from long_horizon_swe.config.loader import load_task
from long_horizon_swe.config.workspace import resolve_workspace
from long_horizon_swe.core.exceptions import TaskConfigError, WorkspaceError
from long_horizon_swe.core.result import TaskResult
from long_horizon_swe.core.state import TaskState
from long_horizon_swe.execution.runner import TaskRunner
from long_horizon_swe.tracking.artifacts import ArtifactStore, RecordingFailure, ResultArtifact
from long_horizon_swe.tracking.errors import TraceWriteError
from long_horizon_swe.tracking.event import (
    EventType,
    RunCompletedPayload,
    RunFailedPayload,
    RunStartedPayload,
)
from long_horizon_swe.tracking.recorder import TraceRecorder


@dataclass(frozen=True)
class VerificationRun:
    result: TaskResult
    run_id: UUID
    directory: Path


def _exception_failure(error: BaseException) -> RunFailedPayload:
    if isinstance(error, TaskConfigError):
        return RunFailedPayload(
            failure_type="configuration", message="Task configuration was invalid."
        )
    if isinstance(error, WorkspaceError):
        return RunFailedPayload(failure_type="workspace", message="Workspace operation failed.")
    if isinstance(error, KeyboardInterrupt):
        return RunFailedPayload(failure_type="cancelled", message="Verification was interrupted.")
    return RunFailedPayload(failure_type="internal", message="Verification stopped unexpectedly.")


def _result_failure(result: TaskResult) -> RunFailedPayload:
    if any(execution.timed_out for execution in result.executions):
        return RunFailedPayload(
            failure_type="timeout", message="The verifier exceeded its timeout."
        )
    if result.verification is None:
        return RunFailedPayload(failure_type="workspace", message="Run setup or cleanup failed.")
    if not result.executions:
        return RunFailedPayload(failure_type="execution", message="The verifier could not execute.")
    return RunFailedPayload(
        failure_type="verification", message="Behavioral verification did not pass."
    )


def verify_manifest(
    manifest: Path, *, output_root: Path | None = None, runner: TaskRunner | None = None
) -> VerificationRun:
    store = ArtifactStore.create(manifest.parent, output_root)
    try:
        recorder = TraceRecorder(store.directory / "trace.jsonl", store.run_id)
    except TraceWriteError:
        store.write(
            ResultArtifact(
                schema_version="1.0",
                run_id=store.run_id,
                outcome="failure",
                result=None,
                failure=RunFailedPayload(failure_type="artifact", message="Trace creation failed."),
            )
        )
        raise
    recorder.emit(EventType.RUN_STARTED, RunStartedPayload())
    result: TaskResult | None = None
    exception: BaseException | None = None
    failure: RunFailedPayload | None = None
    try:
        task = load_task(manifest)
        source = resolve_workspace(task, manifest)
        result = (runner or TaskRunner()).verify(task, source, observer=recorder)
    except BaseException as error:
        # Persist the actual stopping point, including cancellation; never synthesize completions.
        exception = error
        failure = _exception_failure(error)
    artifact = ResultArtifact(
        schema_version="1.0",
        run_id=store.run_id,
        outcome="result" if result is not None else "failure",
        result=result,
        failure=failure,
    )
    try:
        store.write(artifact)
        if result is not None and result.status == TaskState.COMPLETED:
            recorder.emit(
                EventType.RUN_COMPLETED, RunCompletedPayload(duration_ms=result.duration_ms)
            )
        else:
            if failure is None:
                assert result is not None
                failure = _result_failure(result)
            recorder.emit(EventType.RUN_FAILED, failure)
    except TraceWriteError:
        recorder.emit(
            EventType.RUN_FAILED,
            RunFailedPayload(failure_type="artifact", message="Result persistence failed."),
        )
        raise
    finally:
        recorder.close()
    if recorder.error is not None:
        # Preserve the measured business result even when recording failed. Surface evidence failure
        # separately; do not turn a passing behavioral verdict into a fictional test failure.
        artifact = artifact.model_copy(
            update={"trace_error": RecordingFailure(line_number=recorder.error.line_number)}
        )
        store.write(artifact)
        raise recorder.error
    if exception is not None:
        raise exception
    assert result is not None
    return VerificationRun(result, store.run_id, store.directory)
