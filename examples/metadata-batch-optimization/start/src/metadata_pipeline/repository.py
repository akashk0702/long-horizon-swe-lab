"""Mutable encoded profile storage behind a small read protocol."""

from collections.abc import Mapping
from typing import Protocol

from metadata_pipeline.errors import MissingProfileError
from metadata_pipeline.models import nonblank


class ProfileRepository(Protocol):
    def get_encoded(self, profile_id: str) -> str: ...


class InMemoryProfileRepository:
    def __init__(self, profiles: Mapping[str, str] | None = None) -> None:
        self._profiles: dict[str, str] = {}
        for key, value in (profiles or {}).items():
            self.set_encoded(key, value)

    def get_encoded(self, profile_id: str) -> str:
        try:
            return self._profiles[profile_id]
        except KeyError:
            raise MissingProfileError(profile_id) from None

    def set_encoded(self, profile_id: str, encoded: str) -> None:
        nonblank(profile_id, "profile_id")
        if not isinstance(encoded, str):
            raise TypeError("encoded must be a string")
        self._profiles[profile_id] = encoded

    def remove(self, profile_id: str) -> bool:
        return self._profiles.pop(profile_id, None) is not None
