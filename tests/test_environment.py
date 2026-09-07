import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from long_horizon_swe.core.exceptions import EnvironmentConfigError
from long_horizon_swe.core.task import TaskSpec
from long_horizon_swe.execution.environment import build_environment
from long_horizon_swe.execution.workspace import PreparedWorkspace


@pytest.fixture
def prepared(tmp_path: Path) -> PreparedWorkspace:
    for part in ["repository", "home", "tmp"]:
        (tmp_path / part).mkdir()
    return PreparedWorkspace(tmp_path, tmp_path / "repository", tmp_path / "home", tmp_path / "tmp")


def test_only_allowlisted_parent_values_are_used(prepared: PreparedWorkspace) -> None:
    parent = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "UNRELATED_TOKEN": "sentinel",
        "PYTHONPATH": "untrusted",
        "HOME": "old-home",
        "TASK_MODE": "inherited-must-not-survive",
    }
    before = parent.copy()
    env = build_environment(prepared, {"TASK_MODE": "explicit"}, parent=parent)
    assert "UNRELATED_TOKEN" not in env
    assert "PYTHONPATH" not in env
    assert "sentinel" not in env.values()
    assert env["HOME"] == str(prepared.home)
    assert env["TMP"] == str(prepared.temp)
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONHASHSEED"] == "0"
    assert env["TASK_MODE"] == "explicit"
    assert parent == before
    assert all(Path(part).is_absolute() for part in env["PATH"].split(os.pathsep))


@pytest.mark.parametrize(
    "mapping",
    [
        {"PATH": "value"},
        {"TASK_ACCESS_TOKEN": "value"},
        {"TASK_MODE": "\x00"},
        {"TASK_MODE": 1},
        {"task_mode": "value"},
    ],
)
def test_invalid_explicit_environment_is_rejected(
    prepared: PreparedWorkspace, task_data: dict, mapping: dict
) -> None:
    with pytest.raises(EnvironmentConfigError):
        build_environment(prepared, mapping)
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(task_data | {"environment": mapping})


def test_schema_accepts_explicit_task_parameters(task_data: dict) -> None:
    task = TaskSpec.model_validate(task_data | {"environment": {"TASK_MODE": "strict"}})
    assert task.environment == {"TASK_MODE": "strict"}


@pytest.mark.skipif(os.name != "nt", reason="Windows environment requirement")
def test_windows_requires_system_root(prepared: PreparedWorkspace) -> None:
    with pytest.raises(EnvironmentConfigError, match="SYSTEMROOT"):
        build_environment(prepared, parent={})
