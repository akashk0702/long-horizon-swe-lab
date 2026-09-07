"""Construct an allowlisted environment without inheriting arbitrary parent values."""

import os
import sys
from collections.abc import Mapping
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from long_horizon_swe.core.exceptions import EnvironmentConfigError
from long_horizon_swe.core.types import TaskEnvironment
from long_horizon_swe.execution.workspace import PreparedWorkspace


def build_environment(
    workspace: PreparedWorkspace,
    overrides: Mapping[str, str] | None = None,
    *,
    parent: Mapping[str, str] | None = None,
) -> dict[str, str]:
    inherited = os.environ if parent is None else parent
    lookup = {
        key.upper(): inherited[key]
        for key in inherited
        if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR"}
    }
    try:
        parameters = TypeAdapter(TaskEnvironment).validate_python(dict(overrides or {}))
    except ValidationError as error:
        raise EnvironmentConfigError("invalid TASK_ environment parameters") from error
    search = [str(Path(sys.executable).parent)]
    search.extend(
        part
        for part in lookup.get("PATH", os.defpath).split(os.pathsep)
        if part and Path(part).is_absolute()
    )
    result = {
        "PATH": os.pathsep.join(dict.fromkeys(search)),
        "HOME": str(workspace.home),
        "USERPROFILE": str(workspace.home),
        "TMP": str(workspace.temp),
        "TEMP": str(workspace.temp),
        "TMPDIR": str(workspace.temp),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8:replace",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
    }
    if os.name == "nt":
        system = lookup.get("SYSTEMROOT") or lookup.get("WINDIR")
        if not system or not Path(system).is_absolute():
            raise EnvironmentConfigError("Windows execution requires an absolute SYSTEMROOT")
        result.update(SYSTEMROOT=system, WINDIR=system)
        for key, suffix in [("APPDATA", "Roaming"), ("LOCALAPPDATA", "Local")]:
            directory = workspace.home / "AppData" / suffix
            directory.mkdir(parents=True, exist_ok=True)
            result[key] = str(directory)
    result.update(parameters)
    return result
