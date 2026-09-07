"""Resource limits supplied by the operator, independently of task metadata."""

from pathlib import Path
from typing import Annotated

from pydantic import Field, StrictBool

from long_horizon_swe.core.types import ContractModel, NonNegativeInt


class WorkspaceOptions(ContractModel):
    temp_parent: Path | None = None
    retain_on_failure: StrictBool = False
    max_files: Annotated[int, Field(strict=True, gt=0)] = 10_000
    max_copy_bytes: Annotated[int, Field(strict=True, gt=0)] = 256 * 1024 * 1024


class ProcessOptions(ContractModel):
    max_stdout_bytes: NonNegativeInt = 1024 * 1024
    max_stderr_bytes: NonNegativeInt = 256 * 1024
    cleanup_timeout_seconds: Annotated[float, Field(strict=True, gt=0)] = 5.0
