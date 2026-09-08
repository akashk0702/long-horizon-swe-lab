"""Immutable job snapshots and the scheduling lifecycle."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Job:
    id: str
    tenant_id: str
    status: JobStatus
    payload: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


def validate_submission(tenant_id: str, payload: Mapping[str, str]) -> None:
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("tenant_id must be a nonblank string")
    if not isinstance(payload, Mapping) or any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in payload.items()
    ):
        raise ValueError("payload must map strings to strings")


def can_transition(current: JobStatus, requested: JobStatus) -> bool:
    if current == requested:
        return True
    if current == JobStatus.PENDING:
        return requested in {JobStatus.RUNNING, JobStatus.CANCELLED}
    if current == JobStatus.RUNNING:
        return requested in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}
    return False
