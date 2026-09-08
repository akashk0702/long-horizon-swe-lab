"""Domain errors callers can distinguish from invalid input."""


class JobNotFoundError(LookupError):
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        super().__init__(f"Job does not exist: {job_id}")


class InvalidTransitionError(ValueError):
    """The requested status would violate the scheduling lifecycle."""
