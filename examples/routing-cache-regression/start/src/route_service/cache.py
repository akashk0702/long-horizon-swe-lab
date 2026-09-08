"""Reusable storage for previously resolved destinations."""

from route_service.models import RouteChange, RouteKey


class RouteCache:
    def __init__(self) -> None:
        self._entries: dict[RouteKey, str] = {}

    def get(self, key: RouteKey) -> str | None:
        return self._entries.get(key)

    def put(self, key: RouteKey, destination: str) -> None:
        self._entries[key] = destination

    def invalidate(self, change: RouteChange) -> None:
        self._entries.pop(change.key, None)

    def clear(self) -> None:
        self._entries.clear()
