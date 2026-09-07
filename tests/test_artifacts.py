from pathlib import Path
from uuid import uuid4

import pytest

from long_horizon_swe.tracking.artifacts import ArtifactStore, ResultArtifact
from long_horizon_swe.tracking.errors import TraceWriteError
from long_horizon_swe.tracking.event import RunFailedPayload


def artifact(store: ArtifactStore) -> ResultArtifact:
    return ResultArtifact(
        schema_version="1.0",
        run_id=store.run_id,
        outcome="failure",
        result=None,
        failure=RunFailedPayload(failure_type="configuration", message="Synthetic test failure."),
    )


def test_run_directories_are_unique_and_outside_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "output"
    first = ArtifactStore.create(source, output)
    second = ArtifactStore.create(source, output)
    assert first.run_id != second.run_id
    assert first.directory.name == str(first.run_id)
    assert len(list(output.iterdir())) == 2
    assert list(source.iterdir()) == []


@pytest.mark.parametrize("suffix", ["", "runs", "nested/runs"])
def test_overlapping_output_rejected_before_writing(tmp_path: Path, suffix: str) -> None:
    with pytest.raises(TraceWriteError, match="outside"):
        ArtifactStore.create(tmp_path, tmp_path / suffix)
    assert list(tmp_path.iterdir()) == []


def test_artifact_rejects_another_run_id(tmp_path: Path) -> None:
    store = ArtifactStore.create(tmp_path / "source", tmp_path / "output")
    with pytest.raises(TraceWriteError, match="run_id"):
        store.write(artifact(store).model_copy(update={"run_id": uuid4()}))
    assert list(store.directory.iterdir()) == []


def test_atomic_replace_failure_preserves_previous_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ArtifactStore.create(tmp_path / "source", tmp_path / "output")
    expected = artifact(store)
    store.write(expected)
    path = store.directory / "result.json"
    before = path.read_bytes()

    def fail_replace(*args: object) -> None:
        raise PermissionError("synthetic replacement failure")

    monkeypatch.setattr("long_horizon_swe.tracking.artifacts.os.replace", fail_replace)
    with pytest.raises(TraceWriteError):
        store.write(expected)
    assert path.read_bytes() == before
    assert list(store.directory.iterdir()) == [path]
    assert ResultArtifact.model_validate_json(before) == expected
