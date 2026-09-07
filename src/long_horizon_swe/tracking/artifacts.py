"""Private run directories and atomic, versioned result envelopes."""

import os
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import UUID4, model_validator

from long_horizon_swe.core.result import TaskResult
from long_horizon_swe.core.types import ContractModel, NonNegativeInt
from long_horizon_swe.tracking.errors import TraceWriteError
from long_horizon_swe.tracking.event import RunFailedPayload


class RecordingFailure(ContractModel):
    message: Literal["Trace recording was incomplete."] = "Trace recording was incomplete."
    line_number: NonNegativeInt | None


class ResultArtifact(ContractModel):
    schema_version: Literal["1.0"]
    run_id: UUID4
    outcome: Literal["result", "failure"]
    result: TaskResult | None
    failure: RunFailedPayload | None
    trace_error: RecordingFailure | None = None

    @model_validator(mode="after")
    def outcome_matches_contents(self) -> Self:
        if self.outcome == "result":
            if self.result is None or self.failure is not None:
                raise ValueError("result outcome requires only a TaskResult")
        elif self.failure is None or self.result is not None:
            raise ValueError("failure outcome requires only a structured failure")
        return self


@dataclass(frozen=True)
class ArtifactStore:
    run_id: UUID
    directory: Path

    @classmethod
    def create(cls, protected_root: Path, output_root: Path | None = None) -> Self:
        """Keep all artifacts outside the manifest directory, which bounds its workspace."""
        try:
            protected = protected_root.resolve()
            output = (output_root or Path(tempfile.gettempdir()) / "long-swe-runs").resolve()
            if output.is_relative_to(protected):
                raise TraceWriteError("output root must be outside the task manifest directory")
            output.mkdir(parents=True, exist_ok=True)
            run_id = uuid4()
            directory = output / str(run_id)
            if directory.is_relative_to(protected):
                raise TraceWriteError("run directory would overlap the task source")
            directory.mkdir(mode=0o700)
            return cls(run_id, directory)
        except (OSError, RuntimeError) as error:
            raise TraceWriteError("cannot create run output directory") from error

    def write(self, artifact: ResultArtifact) -> None:
        if artifact.run_id != self.run_id:
            raise TraceWriteError("result artifact run_id does not match the run directory")
        temporary: Path | None = None
        try:
            descriptor, name = tempfile.mkstemp(
                prefix=".result-", suffix=".tmp", dir=self.directory
            )
            temporary = Path(name)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(artifact.model_dump_json().encode("utf-8") + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.directory / "result.json")
        except OSError as error:
            raise TraceWriteError("cannot persist result artifact") from error
        finally:
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink(missing_ok=True)
