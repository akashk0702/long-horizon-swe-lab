import os
from pathlib import Path

import pytest

from long_horizon_swe.core.exceptions import WorkspaceError
from long_horizon_swe.execution.options import WorkspaceOptions
from long_horizon_swe.execution.workspace import prepare_workspace


def test_copy_is_independent_excludes_metadata_and_cleans_up(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "data").write_bytes(b"original")
    (source / "nested").mkdir()
    (source / "nested" / "empty").touch()
    for name in [".git", ".venv", ".env", ".env.local"]:
        (source / name).write_text("excluded", encoding="utf-8")
    options = WorkspaceOptions(temp_parent=tmp_path)
    with prepare_workspace(source, options) as work:
        assert (work.cwd / "nested" / "empty").is_file()
        assert sorted(path.name for path in work.cwd.iterdir()) == ["data", "nested"]
        (work.cwd / "data").write_bytes(b"changed")
        assert (source / "data").read_bytes() == b"original"
        run_root = work.root
        work.failed = False
    assert not run_root.exists()
    assert (source / "data").read_bytes() == b"original"


def test_failure_retention_is_explicit_and_success_still_cleans(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    options = WorkspaceOptions(temp_parent=tmp_path, retain_on_failure=True)
    with pytest.raises(RuntimeError), prepare_workspace(source, options) as failed:
        (failed.cwd / "diagnostic").write_text("partial result", encoding="utf-8")
        raise RuntimeError("simulated operation failure")
    assert failed.retained
    assert (failed.cwd / "diagnostic").read_text(encoding="utf-8") == "partial result"
    with prepare_workspace(source, options) as successful:
        successful.failed = False
    assert not successful.root.exists()
    assert not successful.retained


def test_each_run_is_fresh(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    options = WorkspaceOptions(temp_parent=tmp_path)
    with prepare_workspace(source, options) as first, prepare_workspace(source, options) as second:
        assert first.root != second.root
        (first.cwd / "created").touch()
        assert not (second.cwd / "created").exists()


def test_temporary_parent_cannot_be_inside_source(tmp_path: Path) -> None:
    with (
        pytest.raises(WorkspaceError, match="outside the source"),
        prepare_workspace(tmp_path, WorkspaceOptions(temp_parent=tmp_path)),
    ):
        pytest.fail("must not create a recursive copy")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("limits", [{"max_files": 1}, {"max_copy_bytes": 1}])
def test_copy_limits_fail_without_leaking_partial_directory(tmp_path: Path, limits: dict) -> None:
    source = tmp_path / "source"
    source.mkdir()
    for name in ["first", "second"]:
        (source / name).write_bytes(b"payload")
    with (
        pytest.raises(WorkspaceError, match="limit"),
        prepare_workspace(source, WorkspaceOptions(temp_parent=tmp_path, **limits)),
    ):
        pytest.fail("copy exceeded its limit")
    assert list(tmp_path.iterdir()) == [source]


def test_links_are_rejected_even_when_the_target_is_internal(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "target").mkdir()
    try:
        (source / "link").symlink_to(source / "target", target_is_directory=True)
    except OSError as error:
        if getattr(error, "winerror", None) == 1314:
            pytest.skip("Host lacks symlink creation privilege; covered on Linux CI")
        raise
    with (
        pytest.raises(WorkspaceError, match="symlinks"),
        prepare_workspace(source, WorkspaceOptions(temp_parent=tmp_path)),
    ):
        pytest.fail("links must not be copied")
    assert list(tmp_path.iterdir()) == [source]


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO behavior")
def test_special_files_fail_without_blocking(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    os.mkfifo(source / "pipe")
    with (
        pytest.raises(WorkspaceError, match="regular files"),
        prepare_workspace(source, WorkspaceOptions(temp_parent=tmp_path)),
    ):
        pytest.fail("FIFO must not be opened")


def test_copying_hardlinks_does_not_share_inodes(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "one").write_bytes(b"source")
    os.link(source / "one", source / "two")
    with prepare_workspace(source, WorkspaceOptions(temp_parent=tmp_path)) as work:
        (work.cwd / "one").write_bytes(b"new")
        assert (work.cwd / "two").read_bytes() == b"source"
        assert (source / "one").read_bytes() == b"source"
