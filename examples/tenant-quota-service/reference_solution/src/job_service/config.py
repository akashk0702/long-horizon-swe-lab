"""Service construction options."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType


def _validate_limit(limit: int) -> None:
    if type(limit) is not int or limit < 0:
        raise ValueError("active job limits must be nonnegative integers")


@dataclass(frozen=True)
class ServiceConfig:
    id_prefix: str = "job"
    default_active_job_limit: int = 3
    tenant_active_job_limits: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.id_prefix, str) or not self.id_prefix.strip():
            raise ValueError("id_prefix must be a nonblank string")
        _validate_limit(self.default_active_job_limit)
        if not isinstance(self.tenant_active_job_limits, Mapping):
            raise ValueError("tenant_active_job_limits must be a mapping")
        for tenant, limit in self.tenant_active_job_limits.items():
            if not isinstance(tenant, str) or not tenant.strip():
                raise ValueError("override tenant IDs must be nonblank strings")
            _validate_limit(limit)
        object.__setattr__(
            self, "tenant_active_job_limits", MappingProxyType(dict(self.tenant_active_job_limits))
        )
