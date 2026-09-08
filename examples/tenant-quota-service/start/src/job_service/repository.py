"""Insertion-ordered storage. Returned jobs are immutable snapshots."""

from collections.abc import Mapping
from dataclasses import replace

from job_service.errors import JobNotFoundError
from job_service.models import Job, JobStatus, validate_submission


class InMemoryJobRepository:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._next_id = 1

    def create(self, tenant_id: str, payload: Mapping[str, str], *, id_prefix: str) -> Job:
        validate_submission(tenant_id, payload)
        job = Job(f"{id_prefix}-{self._next_id}", tenant_id, JobStatus.PENDING, payload)
        self._jobs[job.id] = job
        self._next_id += 1
        return job

    def get(self, job_id: str) -> Job:
        try:
            return self._jobs[job_id]
        except KeyError:
            raise JobNotFoundError(job_id) from None

    def list(self, tenant_id: str | None = None) -> tuple[Job, ...]:
        return tuple(
            job for job in self._jobs.values() if tenant_id is None or job.tenant_id == tenant_id
        )

    def update_status(self, job_id: str, status: JobStatus) -> Job:
        updated = replace(self.get(job_id), status=status)
        self._jobs[job_id] = updated
        return updated
