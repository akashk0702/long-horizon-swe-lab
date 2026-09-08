"""Value objects: frozen attributes with independently owned payload snapshots."""

from copy import deepcopy
from dataclasses import dataclass


def nonblank(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonblank string")


@dataclass(frozen=True)
class InputRecord:
    record_id: str
    profile_id: str
    payload: dict[str, object]

    def __post_init__(self) -> None:
        nonblank(self.record_id, "record_id")
        nonblank(self.profile_id, "profile_id")
        object.__setattr__(self, "payload", deepcopy(self.payload))


@dataclass(frozen=True)
class MetadataProfile:
    profile_id: str
    category: str
    version: int
    labels: tuple[str, ...]
    required_fields: tuple[str, ...]


@dataclass(frozen=True)
class EnrichedRecord:
    record_id: str
    profile_id: str
    payload: dict[str, object]
    category: str
    version: int
    labels: list[str]
