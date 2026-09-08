"""Service construction options."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceConfig:
    id_prefix: str = "job"

    def __post_init__(self) -> None:
        if not isinstance(self.id_prefix, str) or not self.id_prefix.strip():
            raise ValueError("id_prefix must be a nonblank string")
