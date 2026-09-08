"""Evidence errors are distinct from behavioral verification failures."""


class TraceError(Exception):
    def __init__(self, message: str, *, line_number: int | None = None) -> None:
        super().__init__(message)
        self.line_number = line_number


class TraceReadError(TraceError):
    """A trace contains invalid, inconsistent, or incomplete record bytes."""


class TraceWriteError(TraceError):
    """Evidence could not be recorded or persisted reliably."""
