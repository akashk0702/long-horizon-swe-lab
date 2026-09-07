"""Errors at the library and CLI boundary."""


class LabError(Exception):
    """Base class for expected, user-actionable errors."""


class TaskConfigError(LabError):
    """A task manifest cannot be read or does not satisfy its schema."""


class WorkspaceError(LabError):
    """A configured workspace or writable path is unavailable or escapes its root."""


class InvalidStateTransition(LabError):
    """An operation would skip a required lifecycle boundary."""


class EnvironmentConfigError(LabError):
    """Execution environment configuration is invalid."""


class ProcessError(LabError):
    """A process could not be launched, captured, or cleaned up reliably."""

    def __init__(self, message: str, command: tuple[str, ...], duration_ms: float) -> None:
        super().__init__(message)
        self.command = command
        self.duration_ms = duration_ms


class ProcessLaunchError(ProcessError):
    """No command outcome exists because launch/setup failed."""


class VerifierProtocolError(LabError):
    """Observed output does not satisfy the configured verifier protocol."""
