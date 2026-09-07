from pathlib import Path

import pytest

from long_horizon_swe.config.loader import MAX_MANIFEST_BYTES, load_task
from long_horizon_swe.config.workspace import resolve_workspace
from long_horizon_swe.core.exceptions import TaskConfigError, WorkspaceError
from long_horizon_swe.core.task import TaskSpec


def test_load_and_resolve_are_independent_of_caller_directory(
    manifest: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    task = load_task(manifest)
    workspace = resolve_workspace(task, manifest)
    assert workspace == (manifest.parent / "repository").resolve()
    assert not (workspace / "src").exists()  # Validation permits future files but creates nothing.


@pytest.mark.parametrize(
    "text",
    [
        "",
        "[]",
        "name: [",
        "id: first\nid: second",
        "metadata: {x: 1, x: 2}",
        "metadata: &shared {x: 1}\nother: *shared",
        "metadata: {1: value}",
        "metadata: !!python/object/apply:builtins.print [unexpected]",
        "---\nid: a\n---\nid: b",
        "metadata: {<<: {x: 1}}",
        "metadata: " + "[" * 40 + "0" + "]" * 40,
    ],
)
def test_ambiguous_unsafe_or_malformed_yaml_is_rejected(tmp_path: Path, text: str) -> None:
    manifest = tmp_path / "task.yaml"
    manifest.write_text(text, encoding="utf-8")
    with pytest.raises(TaskConfigError):
        load_task(manifest)


def test_duplicate_key_error_identifies_line_without_echoing_value(tmp_path: Path) -> None:
    manifest = tmp_path / "task.yaml"
    manifest.write_text("id: first\nid: sensitive-input-value", encoding="utf-8")
    with pytest.raises(TaskConfigError, match="line 2") as failure:
        load_task(manifest)
    assert "sensitive-input-value" not in str(failure.value)


def test_validation_error_names_field_without_dumping_input(manifest: Path) -> None:
    with manifest.open("a", encoding="utf-8") as stream:
        stream.write("unknown_field: sensitive-input-value\n")
    with pytest.raises(TaskConfigError, match="unknown_field") as failure:
        load_task(manifest)
    assert "sensitive-input-value" not in str(failure.value)


def test_unreadable_and_non_utf8_manifests_fail_clearly(tmp_path: Path) -> None:
    with pytest.raises(TaskConfigError, match="cannot read"):
        load_task(tmp_path / "missing.yaml")
    manifest = tmp_path / "task.yaml"
    manifest.write_bytes(b"\xff\xfe")
    with pytest.raises(TaskConfigError, match="UTF-8"):
        load_task(manifest)


def test_manifest_size_is_bounded(tmp_path: Path) -> None:
    manifest = tmp_path / "task.yaml"
    manifest.write_bytes(b" " * (MAX_MANIFEST_BYTES + 1))
    with pytest.raises(TaskConfigError, match="exceeds"):
        load_task(manifest)


def test_parse_does_not_require_workspace_but_resolution_does(manifest: Path) -> None:
    (manifest.parent / "repository").rmdir()
    task = load_task(manifest)
    with pytest.raises(WorkspaceError, match="cannot be resolved"):
        resolve_workspace(task, manifest)


def test_workspace_must_be_a_directory(manifest: Path) -> None:
    workspace = manifest.parent / "repository"
    workspace.rmdir()
    workspace.write_text("a file", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="existing directory"):
        resolve_workspace(load_task(manifest), manifest)


def make_directory_link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as error:
        if getattr(error, "winerror", None) == 1314:
            pytest.skip("Host does not grant permission to create directory symlinks")
        raise


def test_workspace_symlink_cannot_escape_manifest_directory(
    tmp_path: Path, task_data: dict
) -> None:
    root = tmp_path / "task"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    manifest = root / "task.yaml"
    manifest.touch()
    make_directory_link(root / "repository", outside)
    with pytest.raises(WorkspaceError, match="outside the manifest"):
        resolve_workspace(TaskSpec.model_validate(task_data), manifest)


def test_writable_symlink_cannot_escape_workspace(manifest: Path) -> None:
    outside = manifest.parent / "outside"
    outside.mkdir()
    make_directory_link(manifest.parent / "repository" / "src", outside)
    with pytest.raises(WorkspaceError, match="outside the workspace"):
        resolve_workspace(load_task(manifest), manifest)


def test_writable_alias_cannot_target_git_metadata(manifest: Path) -> None:
    git_directory = manifest.parent / "repository" / ".git"
    git_directory.mkdir()
    make_directory_link(manifest.parent / "repository" / "src", git_directory)
    with pytest.raises(WorkspaceError, match="Git metadata"):
        resolve_workspace(load_task(manifest), manifest)


def test_internal_symlink_is_allowed(manifest: Path) -> None:
    target = manifest.parent / "repository" / "package"
    target.mkdir()
    make_directory_link(manifest.parent / "repository" / "src", target)
    assert resolve_workspace(load_task(manifest), manifest).is_dir()
