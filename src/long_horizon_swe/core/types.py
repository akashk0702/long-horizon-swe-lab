"""Shared validation rules for the public contracts."""

import re
from pathlib import PureWindowsPath
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints


class ContractModel(BaseModel):
    """Reject unknown fields and attribute reassignment; metadata is not deeply frozen."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
DurationMs = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
PositiveSeconds = Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def validate_command(command: tuple[str, ...]) -> tuple[str, ...]:
    """Retain argument boundaries, including empty arguments and significant spaces."""
    if not command or not command[0].strip():
        raise ValueError("command must contain a nonblank executable")
    if any("\x00" in argument for argument in command):
        raise ValueError("command arguments cannot contain NUL characters")
    return command


Command = Annotated[tuple[str, ...], AfterValidator(validate_command)]


def validate_environment(values: dict[str, str]) -> dict[str, str]:
    """Only task parameters may be supplied; never override process configuration."""
    for key, value in values.items():
        if not re.fullmatch(r"TASK_[A-Z][A-Z0-9_]*", key):
            raise ValueError("environment keys must use the TASK_ namespace")
        if re.search(r"(?:^|_)(?:TOKEN|SECRET|PASSWORD|CREDENTIALS?|KEY)(?:_|$)", key):
            raise ValueError("credential parameters are not supported")
        if "\x00" in value:
            raise ValueError("environment values cannot contain NUL characters")
    return values


TaskEnvironment = Annotated[dict[str, str], AfterValidator(validate_environment)]


def portable_relative_path(value: str, *, allow_root: bool = False) -> str:
    """Require canonical relative paths with the same meaning on supported hosts."""
    if value == "." and allow_root:
        return value
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("use a nonempty relative path without empty, '.' or '..' segments")
    for part in parts:
        if any(ord(character) < 32 or character in '\\<>:"|?*' for character in part):
            raise ValueError("path contains a control character or a nonportable character")
        if part.endswith((" ", ".")) or part != part.strip():
            raise ValueError("path segments cannot have surrounding spaces or trailing dots")
        if PureWindowsPath(part).is_reserved():
            raise ValueError("path contains a reserved device name")
    return value
