import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from long_horizon_swe.cli.main import main


def test_validation_outputs_machine_readable_result(
    manifest: Path, capsys: pytest.CaptureFixture
) -> None:
    assert main(["validate", str(manifest)]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    result = json.loads(captured.out)
    assert result == {
        "valid": True,
        "task_id": "contract-check",
        "schema_version": "1.0",
        "workspace": str((manifest.parent / "repository").resolve()),
    }


def test_validation_never_runs_command(manifest: Path, task_data: dict) -> None:
    marker = manifest.parent / "repository" / "should-not-exist"
    task_data["verification_command"] = [
        sys.executable,
        "-c",
        "from pathlib import Path; Path('should-not-exist').touch()",
    ]
    manifest.write_text(yaml.safe_dump(task_data), encoding="utf-8")
    assert main(["validate", str(manifest)]) == 0
    assert not marker.exists()


def test_missing_manifest_is_a_structured_error(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    assert main(["validate", str(tmp_path / "missing.yaml")]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["valid"] is False
    assert error["error"] == "TaskConfigError"
    assert "cannot read" in error["message"]


def test_unavailable_workspace_uses_distinct_error(
    manifest: Path, capsys: pytest.CaptureFixture
) -> None:
    (manifest.parent / "repository").rmdir()
    assert main(["validate", str(manifest)]) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "WorkspaceError"


@pytest.mark.parametrize("arguments", [[], ["run"], ["verify"], ["replay"], ["validate"]])
def test_unimplemented_or_incomplete_commands_fail(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == 2


def test_module_entrypoint_works_outside_source_tree(manifest: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "long_horizon_swe", "validate", str(manifest)],
        cwd=manifest.parent,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["valid"] is True


def test_installed_console_script_reports_version(tmp_path: Path) -> None:
    entrypoint = Path(sys.executable).with_name("long-swe.exe" if os.name == "nt" else "long-swe")
    result = subprocess.run(
        [str(entrypoint), "--version"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "0.1.0a1"
