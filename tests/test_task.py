import math

import pytest
from pydantic import ValidationError

from long_horizon_swe.core.task import TaskSpec


def test_normalizes_contract_and_round_trips_json(task_data: dict) -> None:
    task = TaskSpec.model_validate(task_data | {"title": "  Contract check  "})
    assert task.title == "Contract check"
    assert task.timeout_seconds == 30.0
    assert task.verification_command == ("python", "-m", "pytest")
    assert TaskSpec.model_validate_json(task.model_dump_json()) == task


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "Mixed_Case"),
        ("id", "two--hyphens"),
        ("title", "  "),
        ("description", ""),
        ("schema_version", "2.0"),
        ("timeout_seconds", 0),
        ("timeout_seconds", -1),
        ("timeout_seconds", math.inf),
        ("timeout_seconds", math.nan),
        ("timeout_seconds", True),
        ("timeout_seconds", "30"),
        ("verification_command", "python -m pytest"),
        ("verification_command", []),
        ("verification_command", [" "]),
        ("verification_command", ["python", "\x00"]),
        ("verification_command", ["python", 42]),
        ("allowed_paths", []),
        ("allowed_paths", ["src", "SRC"]),
        ("allowed_paths", ["src/.GIT/config"]),
        ("metadata", {"timing": math.nan}),
        ("metadata", {"nested": [math.inf]}),
    ],
)
def test_rejects_invalid_contract_fields(task_data: dict, field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(task_data | {field: value})


@pytest.mark.parametrize(
    "path",
    [
        "",
        "../escape",
        "/absolute",
        "C:/absolute",
        "src\\file.py",
        "src//file.py",
        "src/./file.py",
        "src/../file.py",
        "src/",
        "src/*.py",
        "src/NUL.txt",
        "src/COM¹",
        "src/CONIN$",
        "src/a:",
        "src/space ",
        "src/dot.",
        "src/\x00",
        "//server/share",
    ],
)
def test_rejects_nonportable_paths(task_data: dict, path: str) -> None:
    for field, value in [("workspace", path), ("allowed_paths", [path])]:
        with pytest.raises(ValidationError):
            TaskSpec.model_validate(task_data | {field: value})


def test_root_workspace_allowed_but_writable_root_must_be_explicit(task_data: dict) -> None:
    assert TaskSpec.model_validate(task_data | {"workspace": "."}).workspace == "."
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(task_data | {"allowed_paths": ["."]})


def test_argument_boundaries_are_preserved(task_data: dict) -> None:
    command = ["/path with spaces/python", "", "  value  ", "a; b", "$(literal)"]
    task = TaskSpec.model_validate(task_data | {"verification_command": command})
    assert list(task.verification_command) == command


def test_rejects_missing_and_unknown_fields(task_data: dict) -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        TaskSpec.model_validate(task_data | {"timeuot_seconds": 10})
    del task_data["verification_command"]
    with pytest.raises(ValidationError, match="verification_command"):
        TaskSpec.model_validate(task_data)


def test_metadata_defaults_are_independent_and_attributes_are_frozen(task_data: dict) -> None:
    del task_data["metadata"]
    first = TaskSpec.model_validate(task_data)
    second = TaskSpec.model_validate(task_data)
    first.metadata["annotation"] = "local"
    assert second.metadata == {}
    with pytest.raises(ValidationError, match="frozen"):
        first.timeout_seconds = -1


def test_schema_exposes_required_contract_and_forbids_extra_fields() -> None:
    schema = TaskSpec.model_json_schema()
    assert schema["additionalProperties"] is False
    assert "verification_command" in schema["required"]
    assert schema["properties"]["verification_command"]["type"] == "array"
