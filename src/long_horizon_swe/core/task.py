"""Versioned task definitions; parsing a definition never executes its command."""

import json
from typing import Annotated, Literal

from pydantic import Field, JsonValue, StringConstraints, field_validator

from long_horizon_swe.core.types import (
    Command,
    ContractModel,
    NonBlank,
    PositiveSeconds,
    TaskEnvironment,
    portable_relative_path,
)

TaskId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")]


class TaskSpec(ContractModel):
    """A manifest whose paths are relative to the manifest's directory and workspace."""

    schema_version: Literal["1.0"] = "1.0"
    id: TaskId
    title: NonBlank
    description: NonBlank
    workspace: str
    timeout_seconds: PositiveSeconds
    verification_command: Command
    allowed_paths: Annotated[tuple[str, ...], Field(min_length=1)]
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    environment: TaskEnvironment = Field(default_factory=dict)

    @field_validator("workspace")
    @classmethod
    def workspace_is_relative(cls, value: str) -> str:
        return portable_relative_path(value, allow_root=True)

    @field_validator("allowed_paths")
    @classmethod
    def writable_roots_are_explicit(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        seen: set[str] = set()
        for value in values:
            portable_relative_path(value)
            if ".git" in value.casefold().split("/"):
                raise ValueError("Git metadata cannot be declared writable")
            if value.casefold() in seen:
                raise ValueError("allowed_paths must be unique ignoring case")
            seen.add(value.casefold())
        return values

    @field_validator("metadata")
    @classmethod
    def metadata_is_finite_json(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        # JSON excludes NaN and Infinity even though Python's encoder accepts them by default.
        json.dumps(value, allow_nan=False)
        return value
