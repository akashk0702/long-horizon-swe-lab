"""Scope identifiers and registry change notifications."""

from dataclasses import dataclass
from enum import StrEnum


def nonblank(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonblank string")
    return value


@dataclass(frozen=True)
class RouteKey:
    tenant_id: str | None = None
    region: str | None = None

    def __post_init__(self) -> None:
        if self.tenant_id is not None:
            nonblank(self.tenant_id, "tenant_id")
        if self.region is not None:
            nonblank(self.region, "region")


class ChangeKind(StrEnum):
    SET = "set"
    REMOVE = "remove"


@dataclass(frozen=True)
class RouteChange:
    key: RouteKey
    kind: ChangeKind
