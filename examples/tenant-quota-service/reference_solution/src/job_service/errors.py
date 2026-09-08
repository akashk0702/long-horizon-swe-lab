"""Domain errors callers can distinguish from invalid input."""


class JobNotFoundError(LookupError):
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        super().__init__(f"Job does not exist: {job_id}")


class InvalidTransitionError(ValueError):
    """The requested status would violate the scheduling lifecycle."""


class QuotaExceededError(Exception):
    def __init__(self, tenant_id: str, limit: int, active_count: int) -> None:
        self.tenant_id = tenant_id
        self.limit = limit
        self.active_count = active_count
        super().__init__(f"Tenant {tenant_id!r} has {active_count} active jobs; limit is {limit}")
