"""Copy trusted, quiescent local source trees without following filesystem links."""

import os
import shutil
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from long_horizon_swe.core.exceptions import WorkspaceError
from long_horizon_swe.execution.options import WorkspaceOptions
from long_horizon_swe.tracking.event import EmptyPayload, EventType, WorkspacePayload
from long_horizon_swe.tracking.observer import NullObserver, Observer

_EXCLUDED = frozenset(
    {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
)
_BLOCK_BYTES = 64 * 1024


@dataclass
class PreparedWorkspace:
    root: Path
    cwd: Path
    home: Path
    temp: Path
    failed: bool = True
    retained: bool = False


def _copy_tree(source: Path, destination: Path, limits: WorkspaceOptions) -> None:
    files = 0
    copied = 0
    pending = [(source, destination)]
    while pending:
        directory, target = pending.pop()
        target.mkdir()
        with os.scandir(directory) as entries:
            for entry in entries:
                name = entry.name.casefold()
                if name in _EXCLUDED or name == ".env" or name.startswith(".env."):
                    continue
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    raise WorkspaceError("workspace copy rejects symlinks and reparse points")
                output = target / entry.name
                if not output.is_relative_to(destination):
                    raise WorkspaceError("copy destination escapes the run workspace")
                if stat.S_ISDIR(info.st_mode):
                    pending.append((Path(entry.path), output))
                elif stat.S_ISREG(info.st_mode):
                    files += 1
                    if files > limits.max_files:
                        raise WorkspaceError("workspace exceeds the configured file count limit")
                    with open(entry.path, "rb") as reader, output.open("xb") as writer:
                        while data := reader.read(_BLOCK_BYTES):
                            copied += len(data)
                            if copied > limits.max_copy_bytes:
                                raise WorkspaceError(
                                    "workspace exceeds the configured copy byte limit"
                                )
                            writer.write(data)
                    # Keep executable bits, but not source read-only flags or privileged mode bits.
                    output.chmod(0o600 | (stat.S_IMODE(info.st_mode) & 0o111))
                else:
                    raise WorkspaceError(
                        "workspace copy supports regular files and directories only"
                    )


def _remove_readonly(function: object, path: str, error: BaseException) -> None:
    """Retry cleanup of files made read-only by an evaluated command."""
    if not isinstance(error, PermissionError):
        raise error
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD | (stat.S_IEXEC if os.path.isdir(path) else 0))
    if callable(function):
        function(path)


def _cleanup(root: Path, parent: Path, observer: Observer) -> None:
    observer.emit(EventType.WORKSPACE_CLEANUP_STARTED, EmptyPayload())
    if root.parent != parent or root.resolve(strict=False).parent != parent:
        raise WorkspaceError("refusing cleanup of a run root outside its temporary parent")
    info = root.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise WorkspaceError("refusing cleanup of a replaced run root")
    shutil.rmtree(root, onexc=_remove_readonly)
    observer.emit(EventType.WORKSPACE_CLEANED, EmptyPayload())


@contextmanager
def prepare_workspace(
    source: Path, options: WorkspaceOptions | None = None, *, observer: Observer | None = None
) -> Iterator[PreparedWorkspace]:
    limits = options or WorkspaceOptions()
    observations = observer or NullObserver()
    observations.emit(EventType.WORKSPACE_PREPARATION_STARTED, EmptyPayload())
    root: Path | None = None
    prepared: PreparedWorkspace | None = None
    try:
        source = source.resolve(strict=True)
        parent = (limits.temp_parent or Path(tempfile.gettempdir())).resolve(strict=True)
        if not source.is_dir() or not parent.is_dir():
            raise WorkspaceError("source and temporary parent must be existing directories")
        if parent.is_relative_to(source):
            raise WorkspaceError("temporary parent must be outside the source workspace")
        root = Path(tempfile.mkdtemp(prefix="long-swe-", dir=parent))
        _copy_tree(source, root / "repository", limits)
        home, temporary = root / "home", root / "tmp"
        home.mkdir()
        temporary.mkdir()
        prepared = PreparedWorkspace(root, root / "repository", home, temporary)
        observations.emit(EventType.WORKSPACE_PREPARED, WorkspacePayload())
    except (OSError, RuntimeError) as error:
        if root is not None:
            _cleanup(root, parent, observations)
        raise WorkspaceError("cannot prepare the execution workspace") from error
    except WorkspaceError:
        if root is not None:
            _cleanup(root, parent, observations)
        raise
    try:
        yield prepared
    finally:
        if limits.retain_on_failure and prepared.failed:
            prepared.retained = True
            observations.emit(EventType.WORKSPACE_RETAINED, WorkspacePayload())
        else:
            try:
                _cleanup(root, parent, observations)
            except OSError as error:
                raise WorkspaceError(f"cannot clean run directory: {prepared.root}") from error
