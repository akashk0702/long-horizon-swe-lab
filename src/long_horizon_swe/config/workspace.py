"""Read-only checks of declared paths; this module is not a security sandbox."""

from pathlib import Path

from long_horizon_swe.core.exceptions import WorkspaceError
from long_horizon_swe.core.task import TaskSpec


def resolve_workspace(task: TaskSpec, manifest_path: Path) -> Path:
    """Resolve workspace relative to the manifest, independently of the caller's cwd.

    Existing symlinks must stay within the resolved manifest directory/workspace.
    Writable paths may be absent so tasks can introduce new files.
    """
    try:
        root = manifest_path.resolve(strict=True).parent
        workspace = (root / task.workspace).resolve(strict=True)
        if not workspace.is_relative_to(root):
            raise WorkspaceError("workspace resolves outside the manifest directory")
        if not workspace.is_dir():
            raise WorkspaceError("workspace must be an existing directory")
        for writable in task.allowed_paths:
            resolved = (workspace / writable).resolve(strict=False)
            if not resolved.is_relative_to(workspace):
                raise WorkspaceError("an allowed path resolves outside the workspace")
            relative_parts = resolved.relative_to(workspace).parts
            if any(part.casefold() == ".git" for part in relative_parts):
                raise WorkspaceError("an allowed path resolves to Git metadata")
        return workspace
    except (OSError, RuntimeError) as error:
        raise WorkspaceError(
            "workspace paths cannot be resolved; check existence and access"
        ) from error
