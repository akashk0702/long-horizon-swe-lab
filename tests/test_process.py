import csv
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from long_horizon_swe.core.exceptions import ProcessLaunchError
from long_horizon_swe.execution.environment import build_environment
from long_horizon_swe.execution.options import ProcessOptions
from long_horizon_swe.execution.process import ProcessRunner
from long_horizon_swe.execution.timeout import ProcessTree
from long_horizon_swe.execution.workspace import PreparedWorkspace


@pytest.fixture
def process_context(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    for name in ["cwd", "home", "tmp"]:
        (tmp_path / name).mkdir()
    work = PreparedWorkspace(tmp_path, tmp_path / "cwd", tmp_path / "home", tmp_path / "tmp")
    return work.cwd, build_environment(work, {"TASK_MODE": "test"})


def test_command_cwd_arguments_unicode_stderr_and_environment(process_context: tuple) -> None:
    cwd, environment = process_context
    code = (
        "import json,os,sys; "
        "print(json.dumps([os.getcwd(),sys.argv[1:],os.environ['TASK_MODE']])); "
        "print('caf\u00e9 \u03bb',file=sys.stderr)"
    )
    arguments = [sys.executable, "-c", code, "", "a b", "$(literal)", "a;b"]
    result = ProcessRunner().run(arguments, cwd=cwd, environment=environment, timeout_seconds=10)
    assert result.succeeded
    assert result.duration_ms > 0
    assert result.command == tuple(arguments)
    assert json.loads(result.stdout) == [str(cwd), arguments[3:], "test"]
    assert result.stderr.strip() == "caf\u00e9 \u03bb"
    assert not result.stdout_truncated


def test_nonzero_exit_is_observed(process_context: tuple) -> None:
    cwd, environment = process_context
    result = ProcessRunner().run(
        [sys.executable, "-c", "raise SystemExit(7)"],
        cwd=cwd,
        environment=environment,
        timeout_seconds=10,
    )
    assert result.exit_code == 7
    assert not result.succeeded


def test_missing_executable_has_a_structured_launch_error(process_context: tuple) -> None:
    cwd, environment = process_context
    with pytest.raises(ProcessLaunchError) as failure:
        ProcessRunner().run(
            ["this-executable-does-not-exist-3946"],
            cwd=cwd,
            environment=environment,
            timeout_seconds=10,
        )
    assert failure.value.duration_ms >= 0
    assert failure.value.command == ("this-executable-does-not-exist-3946",)
    assert not hasattr(failure.value, "exit_code")


@pytest.mark.parametrize("command", ["python -V", [], [""], ["python", "\x00"]])
def test_invalid_command_is_rejected_before_launch(process_context: tuple, command: object) -> None:
    cwd, environment = process_context
    with pytest.raises(ValidationError):
        ProcessRunner().run(command, cwd=cwd, environment=environment, timeout_seconds=10)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), True, "10"])
def test_invalid_timeout_is_rejected(process_context: tuple, timeout: object) -> None:
    cwd, environment = process_context
    with pytest.raises(ValidationError):
        ProcessRunner().run(
            [sys.executable], cwd=cwd, environment=environment, timeout_seconds=timeout
        )


def test_large_output_is_drained_but_capture_is_bounded(process_context: tuple) -> None:
    cwd, environment = process_context
    code = "import os; os.write(1,b'a'*2000000); os.write(2,b'b'*2000000)"
    runner = ProcessRunner(ProcessOptions(max_stdout_bytes=123, max_stderr_bytes=77))
    result = runner.run(
        [sys.executable, "-c", code], cwd=cwd, environment=environment, timeout_seconds=15
    )
    assert result.exit_code == 0
    assert result.stdout == "a" * 123
    assert result.stderr == "b" * 77
    assert result.stdout_truncated and result.stderr_truncated


def test_invalid_utf8_is_replaced_and_recorded(process_context: tuple) -> None:
    cwd, environment = process_context
    result = ProcessRunner().run(
        [sys.executable, "-c", "import os; os.write(1,b'a\\xffb')"],
        cwd=cwd,
        environment=environment,
        timeout_seconds=10,
    )
    assert result.stdout == "a\ufffdb"
    assert result.stdout_decode_errors
    assert not result.stderr_decode_errors


def test_timeout_preserves_partial_output(process_context: tuple) -> None:
    cwd, environment = process_context
    result = ProcessRunner().run(
        [sys.executable, "-c", "import time; print('started',flush=True); time.sleep(30)"],
        cwd=cwd,
        environment=environment,
        timeout_seconds=1.5,
    )
    assert result.timed_out and not result.succeeded
    assert "started" in result.stdout
    assert result.duration_ms >= 1500
    assert result.duration_ms < 12000


def _alive(pid: int) -> bool:
    if os.name == "nt":
        listing = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return any(
            len(row) > 1 and row[1] == str(pid) for row in csv.reader(io.StringIO(listing.stdout))
        )
    status = Path(f"/proc/{pid}/stat")
    if status.exists():
        # Linux may keep a terminated orphan as a zombie until init reaps it.
        return status.read_text().rsplit(")", 1)[1].split()[0] != "Z"
    return False


@pytest.mark.parametrize("leader_exits", [False, True])
def test_descendants_are_terminated_on_timeout_and_normal_exit(
    process_context: tuple, leader_exits: bool
) -> None:
    cwd, environment = process_context
    child = "import time; time.sleep(60)"
    parent = (
        "import pathlib,subprocess,sys,time; "
        f"p=subprocess.Popen([sys.executable,'-c',{child!r}]); "
        "pathlib.Path('child.pid').write_text(str(p.pid)); "
        + ("" if leader_exits else "time.sleep(60)")
    )
    result = ProcessRunner().run(
        [sys.executable, "-c", parent], cwd=cwd, environment=environment, timeout_seconds=2.0
    )
    pid = int((cwd / "child.pid").read_text())
    deadline = time.monotonic() + 3
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.03)
    assert not _alive(pid), f"descendant {pid} survived cleanup"
    assert result.timed_out is not leader_exits


def test_arbitrary_parent_parameter_is_not_in_child(
    process_context: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd, environment = process_context
    monkeypatch.setenv("UNRELATED_TOKEN", "sentinel")
    result = ProcessRunner().run(
        [sys.executable, "-c", "import os; print('UNRELATED_TOKEN' in os.environ)"],
        cwd=cwd,
        environment=environment,
        timeout_seconds=10,
    )
    assert result.stdout.strip() == "False"


def test_setup_cancellation_reaps_the_created_process(
    process_context: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd, environment = process_context
    created = []

    def interrupt(tree: ProcessTree, process: subprocess.Popen) -> None:
        created.append(process.pid)
        raise KeyboardInterrupt

    monkeypatch.setattr(ProcessTree, "attach", interrupt)
    with pytest.raises(KeyboardInterrupt):
        ProcessRunner().run(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=cwd,
            environment=environment,
            timeout_seconds=5,
        )
    assert len(created) == 1
    assert not _alive(created[0])


def test_cwd_missing_is_launch_error(process_context: tuple) -> None:
    cwd, environment = process_context
    with pytest.raises(ProcessLaunchError):
        ProcessRunner().run(
            [sys.executable, "-V"], cwd=cwd / "missing", environment=environment, timeout_seconds=5
        )


def test_zero_and_exact_capture_limits(process_context: tuple) -> None:
    cwd, environment = process_context
    for limit, expected, truncated in [(0, "", True), (3, "abc", False)]:
        result = ProcessRunner(ProcessOptions(max_stdout_bytes=limit)).run(
            [sys.executable, "-c", "import os; os.write(1,b'abc')"],
            cwd=cwd,
            environment=environment,
            timeout_seconds=5,
        )
        assert result.stdout == expected
        assert result.stdout_truncated is truncated
