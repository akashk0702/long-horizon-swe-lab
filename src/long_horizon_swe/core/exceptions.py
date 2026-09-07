"""Errors at the library and CLI boundary."""


class LabError(Exception):
    """Base class for expected, user-actionable errors."""


class TaskConfigError(LabError):
    """A task manifest cannot be read or does not satisfy its schema."""


class WorkspaceError(LabError):
    """A configured workspace or writable path is unavailable or escapes its root."""


class InvalidStateTransition(LabError):
    """An operation would skip a required lifecycle boundary."""
