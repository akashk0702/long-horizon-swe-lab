"""Public API for job submission, inspection, and lifecycle changes."""

from collections.abc import Mapping

from job_service.config import ServiceConfig
from job_service.errors import InvalidTransitionError, QuotaExceededError
from job_service.models import Job, JobStatus, can_transition, validate_submission
from job_service.repository import InMemoryJobRepository


class JobService:
    def __init__(
        self,
        repository: InMemoryJobRepository | None = None,
        config: ServiceConfig | None = None,
    ) -> None:
        self.repository = repository if repository is not None else InMemoryJobRepository()
        self.config = config if config is not None else ServiceConfig()

    def submit_job(self, tenant_id: str, payload: Mapping[str, str]) -> Job:
        validate_submission(tenant_id, payload)
        limit = self.config.tenant_active_job_limits.get(
            tenant_id, self.config.default_active_job_limit
        )
        active_count = sum(
            job.status in {JobStatus.PENDING, JobStatus.RUNNING}
            for job in self.repository.list(tenant_id)
        )
        if active_count >= limit:
            raise QuotaExceededError(tenant_id, limit, active_count)
        return self.repository.create(tenant_id, payload, id_prefix=self.config.id_prefix)

    def get_job(self, job_id: str) -> Job:
        return self.repository.get(job_id)

    def list_jobs(self, tenant_id: str | None = None) -> tuple[Job, ...]:
        return self.repository.list(tenant_id)

    def set_status(self, job_id: str, status: JobStatus) -> Job:
        if not isinstance(status, JobStatus):
            raise ValueError("status must be a JobStatus")
        job = self.repository.get(job_id)
        if not can_transition(job.status, status):
            raise InvalidTransitionError(f"Cannot transition from {job.status} to {status}")
        return self.repository.update_status(job_id, status)
