"""A cache generation represents one observed configuration state."""

from dataclasses import dataclass

from route_service.models import RouteChange, RouteKey


@dataclass(frozen=True)
class _CachedRoute:
    generation: int
    destination: str


class RouteCache:
    def __init__(self) -> None:
        self._entries: dict[RouteKey, _CachedRoute] = {}
        self._generation = 0

    def get(self, key: RouteKey) -> str | None:
        cached = self._entries.get(key)
        if cached is None:
            return None
        if cached.generation != self._generation:
            self._entries.pop(key)
            return None
        return cached.destination

    def put(self, key: RouteKey, destination: str) -> None:
        self._entries[key] = _CachedRoute(self._generation, destination)

    def invalidate(self, change: RouteChange) -> None:
        self._generation += 1

    def clear(self) -> None:
        self._entries.clear()
