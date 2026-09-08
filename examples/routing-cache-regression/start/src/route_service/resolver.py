"""Resolve requests through the configured hierarchy and cache successful lookups."""

from route_service.cache import RouteCache
from route_service.errors import RouteNotFoundError
from route_service.models import RouteKey, nonblank
from route_service.registry import RouteRegistry


class RouteResolver:
    def __init__(self, registry: RouteRegistry, cache: RouteCache | None = None) -> None:
        self.registry = registry
        self.cache = cache if cache is not None else RouteCache()
        registry.subscribe(self.cache.invalidate)

    def resolve(self, tenant_id: str, region: str) -> str:
        key = RouteKey(nonblank(tenant_id, "tenant_id"), nonblank(region, "region"))
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        destination = self._lookup(key)
        self.cache.put(key, destination)
        return destination

    def _lookup(self, key: RouteKey) -> str:
        scopes = (
            key,
            RouteKey(tenant_id=key.tenant_id),
            RouteKey(region=key.region),
            RouteKey(),
        )
        for scope in scopes:
            destination = self.registry.get(scope)
            if destination is not None:
                return destination
        assert key.tenant_id is not None and key.region is not None
        raise RouteNotFoundError(key.tenant_id, key.region)
