"""A narrow coordinator for a copied workspace and one behavioral verification."""

import time
from pathlib import Path

from long_horizon_swe.core.exceptions import LabError
from long_horizon_swe.core.result import ExecutionResult, TaskResult, VerificationResult
from long_horizon_swe.core.state import TaskState, transition
from long_horizon_swe.core.task import TaskSpec
from long_horizon_swe.evaluation.verifier import BehavioralVerifier
from long_horizon_swe.execution.options import WorkspaceOptions
from long_horizon_swe.execution.workspace import PreparedWorkspace, prepare_workspace
from long_horizon_swe.tracking.event import EventType, TaskValidatedPayload
from long_horizon_swe.tracking.observer import NullObserver, Observer


class TaskRunner:
    def __init__(
        self, verifier: BehavioralVerifier | None = None, options: WorkspaceOptions | None = None
    ) -> None:
        self.verifier = verifier or BehavioralVerifier()
        self.options = options or WorkspaceOptions()

    def verify(
        self, task: TaskSpec, source: Path, *, observer: Observer | None = None
    ) -> TaskResult:
        # Metadata and environment dictionaries are not deeply frozen in Pydantic models.
        task = TaskSpec.model_validate(task.model_dump())
        observations = observer or NullObserver()
        observations.emit(EventType.TASK_VALIDATED, TaskValidatedPayload(task_id=task.id))
        started = time.perf_counter()
        state = transition(TaskState.PENDING, TaskState.INSPECTING)
        verification: VerificationResult | None = None
        executions: tuple[ExecutionResult, ...] = ()
        retained: str | None = None
        failure: str | None = None
        prepared: PreparedWorkspace | None = None
        try:
            with prepare_workspace(source, self.options, observer=observations) as workspace:
                prepared = workspace
                state = transition(state, TaskState.TESTING)
                outcome = self.verifier.verify(task, workspace, observer=observations)
                verification = outcome.verification
                executions = (outcome.execution,) if outcome.execution is not None else ()
                workspace.failed = not verification.passed
            if workspace.retained:
                retained = str(workspace.root)
            if verification.passed:
                state = transition(state, TaskState.COMPLETED)
            else:
                state = transition(state, TaskState.FAILED)
                failure = "; ".join(verification.details)
        except LabError as error:
            state = transition(state, TaskState.FAILED)
            # Cleanup/setup errors invalidate the run even if behavioral assertions passed.
            verification = None
            failure = f"{type(error).__name__}: {error}"
        if prepared is not None and prepared.retained:
            retained = str(prepared.root)
        return TaskResult(
            task_id=task.id,
            status=TaskState.COMPLETED if state == TaskState.COMPLETED else TaskState.FAILED,
            duration_ms=(time.perf_counter() - started) * 1000,
            verification=verification,
            failure_reason=failure,
            executions=executions,
            retained_workspace=retained,
        )
