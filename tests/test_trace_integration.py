import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

from long_horizon_swe.application.verification import verify_manifest
from long_horizon_swe.cli.main import main
from long_horizon_swe.core.exceptions import TaskConfigError
from long_horizon_swe.execution.options import WorkspaceOptions
from long_horizon_swe.execution.runner import TaskRunner
from long_horizon_swe.tracking.artifacts import ArtifactStore, ResultArtifact
from long_horizon_swe.tracking.errors import TraceWriteError
from long_horizon_swe.tracking.event import EventType
from long_horizon_swe.tracking.reader import read_trace
from long_horizon_swe.tracking.recorder import TraceRecorder

# These programs execute real assertions on synthetic, temporary test repositories.
CHECK = (
    "import json,pathlib; "
    "ok=pathlib.Path('input.txt').read_text() == 'original'; "
    "pathlib.Path('input.txt').write_text('changed in copy'); "
    "print(json.dumps(dict(schema_version='1.0',passed=ok,"
    "tests_passed=int(ok),tests_failed=int(not ok),details=[])))"
)


@pytest.fixture
def run_setup(tmp_path: Path, task_data: dict) -> tuple[Path, Path, Path]:
    source = tmp_path / "source"
    repository = source / "repository"
    repository.mkdir(parents=True)
    (repository / "input.txt").write_text("original", encoding="utf-8")
    task_data["verification_command"] = [sys.executable, "-c", CHECK]
    manifest = source / "task.yaml"
    manifest.write_text(yaml.safe_dump(task_data), encoding="utf-8")
    temporary = tmp_path / "workspaces"
    temporary.mkdir()
    return manifest, tmp_path / "output", temporary


def change_command(manifest: Path, command: list[str], **updates: object) -> None:
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    data.update(verification_command=command, **updates)
    manifest.write_text(yaml.safe_dump(data), encoding="utf-8")


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_success_has_measured_events_exact_artifact_and_unchanged_source(run_setup: tuple) -> None:
    manifest, output, temporary = run_setup
    before = snapshot(manifest.parent)
    run = verify_manifest(
        manifest,
        output_root=output,
        runner=TaskRunner(options=WorkspaceOptions(temp_parent=temporary)),
    )
    trace = read_trace(run.directory / "trace.jsonl")
    assert [e.event_type for e in trace.events] == [
        EventType.RUN_STARTED,
        EventType.TASK_VALIDATED,
        EventType.WORKSPACE_PREPARATION_STARTED,
        EventType.WORKSPACE_PREPARED,
        EventType.VERIFICATION_STARTED,
        EventType.PROCESS_STARTED,
        EventType.PROCESS_COMPLETED,
        EventType.VERIFICATION_COMPLETED,
        EventType.WORKSPACE_CLEANUP_STARTED,
        EventType.WORKSPACE_CLEANED,
        EventType.RUN_COMPLETED,
    ]
    assert all(e.run_id == run.run_id for e in trace.events)
    artifact = ResultArtifact.model_validate_json((run.directory / "result.json").read_bytes())
    assert artifact.run_id == run.run_id
    assert artifact.result == run.result
    assert artifact.trace_error is None
    execution = run.result.executions[0]
    process_event = next(e for e in trace.events if e.event_type == EventType.PROCESS_COMPLETED)
    assert process_event.payload.stdout_bytes_observed == execution.stdout_bytes_observed
    assert execution.stdout_bytes_observed == len(execution.stdout.encode("utf-8"))
    assert process_event.payload.duration_ms == execution.duration_ms > 0
    assert snapshot(manifest.parent) == before
    assert list(temporary.iterdir()) == []


@pytest.mark.parametrize("mode", ["behavior", "malformed", "timeout", "launch"])
def test_failed_runs_leave_truthful_traces(run_setup: tuple, mode: str) -> None:
    manifest, output, temporary = run_setup
    commands = {
        "behavior": [sys.executable, "-c", CHECK.replace("== 'original'", "== 'different'")],
        "malformed": [sys.executable, "-c", "print('invalid protocol')"],
        "timeout": [sys.executable, "-c", "import time; time.sleep(60)"],
        "launch": [str(temporary / "executable-that-does-not-exist")],
    }
    change_command(manifest, commands[mode], timeout_seconds=1.5)
    before = snapshot(manifest.parent)
    run = verify_manifest(
        manifest,
        output_root=output,
        runner=TaskRunner(options=WorkspaceOptions(temp_parent=temporary)),
    )
    events = read_trace(run.directory / "trace.jsonl").events
    types = [e.event_type for e in events]
    assert types[-1] == EventType.RUN_FAILED
    assert EventType.RUN_COMPLETED not in types
    assert EventType.WORKSPACE_CLEANED in types
    assert (EventType.PROCESS_TIMED_OUT in types) == (mode == "timeout")
    assert (EventType.PROCESS_STARTED in types) == (mode != "launch")
    assert (EventType.PROCESS_COMPLETED in types) == (mode != "launch")
    assert (
        events[-1].payload.failure_type
        == {
            "behavior": "verification",
            "malformed": "verification",
            "timeout": "timeout",
            "launch": "execution",
        }[mode]
    )
    assert snapshot(manifest.parent) == before
    assert list(temporary.iterdir()) == []


def test_invalid_configuration_has_failure_artifact_without_validation_event(
    run_setup: tuple,
) -> None:
    manifest, output, _ = run_setup
    manifest.write_text("not: a task", encoding="utf-8")
    with pytest.raises(TaskConfigError):
        verify_manifest(manifest, output_root=output)
    directory = next(output.iterdir())
    trace = read_trace(directory / "trace.jsonl")
    assert [e.event_type for e in trace.events] == [EventType.RUN_STARTED, EventType.RUN_FAILED]
    artifact = ResultArtifact.model_validate_json((directory / "result.json").read_bytes())
    assert artifact.run_id == trace.events[0].run_id
    assert artifact.outcome == "failure"
    assert artifact.result is None
    assert artifact.failure.failure_type == "configuration"


def test_copy_failure_has_preparation_and_cleanup_without_prepared_event(run_setup: tuple) -> None:
    manifest, output, temporary = run_setup
    run = verify_manifest(
        manifest,
        output_root=output,
        runner=TaskRunner(options=WorkspaceOptions(temp_parent=temporary, max_copy_bytes=1)),
    )
    types = [e.event_type for e in read_trace(run.directory / "trace.jsonl").events]
    assert EventType.WORKSPACE_PREPARATION_STARTED in types
    assert EventType.WORKSPACE_PREPARED not in types
    assert EventType.PROCESS_STARTED not in types
    assert EventType.WORKSPACE_CLEANED in types
    assert types[-1] == EventType.RUN_FAILED
    assert list(temporary.iterdir()) == []


def test_cleanup_failure_never_claims_workspace_cleaned(
    run_setup: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, output, temporary = run_setup
    original = shutil.rmtree

    def refuse_cleanup(path: Path, *args: object, **kwargs: object) -> None:
        assert Path(path).resolve().parent == temporary.resolve()
        raise PermissionError("synthetic cleanup failure")

    with monkeypatch.context() as patch:
        patch.setattr("long_horizon_swe.execution.workspace.shutil.rmtree", refuse_cleanup)
        run = verify_manifest(
            manifest,
            output_root=output,
            runner=TaskRunner(options=WorkspaceOptions(temp_parent=temporary)),
        )
    types = [e.event_type for e in read_trace(run.directory / "trace.jsonl").events]
    assert EventType.VERIFICATION_COMPLETED in types
    assert EventType.WORKSPACE_CLEANUP_STARTED in types
    assert EventType.WORKSPACE_CLEANED not in types
    assert types[-1] == EventType.RUN_FAILED
    for directory in temporary.iterdir():
        assert directory.resolve().parent == temporary.resolve()
        original(directory)


def test_retained_workspace_is_reported_without_cleanup_events(run_setup: tuple) -> None:
    manifest, output, temporary = run_setup
    change_command(manifest, [sys.executable, "-c", "print('invalid protocol')"])
    run = verify_manifest(
        manifest,
        output_root=output,
        runner=TaskRunner(options=WorkspaceOptions(temp_parent=temporary, retain_on_failure=True)),
    )
    types = [e.event_type for e in read_trace(run.directory / "trace.jsonl").events]
    assert EventType.WORKSPACE_RETAINED in types
    assert EventType.WORKSPACE_CLEANUP_STARTED not in types
    assert Path(run.result.retained_workspace).is_dir()
    assert not run.directory.is_relative_to(Path(run.result.retained_workspace))


def test_trace_omits_parent_environment_arguments_output_and_host_paths(
    run_setup: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, output, temporary = run_setup
    secret = "synthetic-parent-sentinel"
    diagnostic = "synthetic-diagnostic-sentinel"
    monkeypatch.setenv("UNRELATED_ACCESS_TOKEN", secret)
    code = (
        "import os,sys; assert 'UNRELATED_ACCESS_TOKEN' not in os.environ; "
        f"sys.stderr.write({diagnostic!r}); " + CHECK
    )
    change_command(manifest, [sys.executable, "-c", code])
    run = verify_manifest(manifest, output_root=output)
    trace_text = (run.directory / "trace.jsonl").read_text(encoding="utf-8")
    for omitted in [
        secret,
        diagnostic,
        code,
        str(manifest.parent),
        str(temporary),
        str(Path(sys.executable).parent),
    ]:
        assert omitted not in trace_text
        assert json.dumps(omitted)[1:-1] not in trace_text
    assert run.result.status.value == "completed"
    # The exact result artifact deliberately preserves existing bounded diagnostics, unlike traces.
    assert diagnostic in (run.directory / "result.json").read_text(encoding="utf-8")
    assert secret not in (run.directory / "result.json").read_text(encoding="utf-8")


def test_replay_cli_only_reads_evidence_and_preserves_values(
    run_setup: tuple, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    manifest, output, _ = run_setup
    change_command(manifest, [sys.executable, "-c", "print('invalid protocol')"])
    run = verify_manifest(manifest, output_root=output)
    path = run.directory / "trace.jsonl"
    before = path.read_bytes()

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Replay attempted to execute or verify")

    monkeypatch.setattr("subprocess.Popen", forbidden)
    monkeypatch.setattr(TaskRunner, "verify", forbidden)
    assert main(["replay", str(path)]) == 0
    rendered = capsys.readouterr()
    assert "RUN_FAILED" in rendered.out
    assert rendered.err == ""
    assert main(["replay", str(path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == [json.loads(line) for line in before.splitlines()]
    assert path.read_bytes() == before
    path.write_bytes(before + b"broken\n")
    assert main(["replay", str(path)]) == 2
    failure = capsys.readouterr()
    assert failure.out == ""
    assert json.loads(failure.err)["line_number"] == len(before.splitlines()) + 1


def test_verify_cli_preserves_stdout_contract_and_reports_artifact_directory(
    run_setup: tuple, capsys: pytest.CaptureFixture
) -> None:
    manifest, output, _ = run_setup
    assert main(["verify", str(manifest), "--output-root", str(output)]) == 0
    captured = capsys.readouterr()
    directory = next(output.iterdir())
    assert captured.err.strip() == f"Artifacts: {directory}"
    envelope = json.loads((directory / "result.json").read_text())
    assert json.loads(captured.out) == envelope["result"]


def test_recording_error_preserves_verdict_without_backfilling(
    run_setup: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, output, _ = run_setup
    original = TraceRecorder.emit

    def fail_after_start(self: TraceRecorder, event_type: EventType, payload: object) -> None:
        if event_type == EventType.TASK_VALIDATED:
            self.error = TraceWriteError("synthetic recorder failure", line_number=2)
        original(self, event_type, payload)

    monkeypatch.setattr(TraceRecorder, "emit", fail_after_start)
    with pytest.raises(TraceWriteError):
        verify_manifest(manifest, output_root=output)
    directory = next(output.iterdir())
    assert len(read_trace(directory / "trace.jsonl").events) == 1
    artifact = ResultArtifact.model_validate_json((directory / "result.json").read_bytes())
    assert artifact.result.status.value == "completed"
    assert artifact.trace_error.line_number == 2


def test_large_output_records_observed_bytes_beyond_capture_limit(run_setup: tuple) -> None:
    manifest, output, _ = run_setup
    size = 2 * 1024 * 1024
    change_command(manifest, [sys.executable, "-c", f"import os; os.write(1, b'x' * {size})"])
    run = verify_manifest(manifest, output_root=output)
    event = next(
        e
        for e in read_trace(run.directory / "trace.jsonl").events
        if e.event_type == EventType.PROCESS_COMPLETED
    )
    assert event.payload.stdout_bytes_observed == size
    assert event.payload.stdout_truncated
    assert run.result.executions[0].stdout_bytes_observed == size


def test_result_write_failure_leaves_trace_without_success_event(
    run_setup: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, output, _ = run_setup

    def fail_write(self: ArtifactStore, artifact: ResultArtifact) -> None:
        raise TraceWriteError("synthetic artifact write failure")

    monkeypatch.setattr(ArtifactStore, "write", fail_write)
    with pytest.raises(TraceWriteError):
        verify_manifest(manifest, output_root=output)
    directory = next(output.iterdir())
    events = read_trace(directory / "trace.jsonl").events
    assert events[-1].event_type == EventType.RUN_FAILED
    assert events[-1].payload.failure_type == "artifact"
    assert EventType.WORKSPACE_CLEANED in [e.event_type for e in events]
    assert not (directory / "result.json").exists()


def test_cancellation_saves_stopping_point_and_reraises(
    run_setup: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, output, _ = run_setup

    def interrupt(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(TaskRunner, "verify", interrupt)
    with pytest.raises(KeyboardInterrupt):
        verify_manifest(manifest, output_root=output)
    directory = next(output.iterdir())
    trace = read_trace(directory / "trace.jsonl")
    assert [e.event_type for e in trace.events] == [EventType.RUN_STARTED, EventType.RUN_FAILED]
    assert trace.events[-1].payload.failure_type == "cancelled"
    artifact = ResultArtifact.model_validate_json((directory / "result.json").read_bytes())
    assert artifact.outcome == "failure"
    assert artifact.failure.failure_type == "cancelled"
