"""Mutable routing configuration, indexed by scope."""

from collections.abc import Callable

from route_service.models import ChangeKind, RouteChange, RouteKey, nonblank


class RouteRegistry:
    def __init__(self) -> None:
        self._routes: dict[RouteKey, str] = {}
        self._listeners: list[Callable[[RouteChange], None]] = []

    def subscribe(self, listener: Callable[[RouteChange], None]) -> None:
        self._listeners.append(listener)

    def get(self, key: RouteKey) -> str | None:
        return self._routes.get(key)

    def _publish(self, key: RouteKey, kind: ChangeKind) -> None:
        for listener in tuple(self._listeners):
            listener(RouteChange(key, kind))

    def _set(self, key: RouteKey, destination: str) -> None:
        self._routes[key] = nonblank(destination, "destination")
        self._publish(key, ChangeKind.SET)

    def _remove(self, key: RouteKey) -> bool:
        removed = self._routes.pop(key, None) is not None
        if removed:
            self._publish(key, ChangeKind.REMOVE)
        return removed

    def set_global_default(self, destination: str) -> None:
        self._set(RouteKey(), destination)

    def set_global_region(self, region: str, destination: str) -> None:
        self._set(RouteKey(region=nonblank(region, "region")), destination)

    def set_tenant_default(self, tenant_id: str, destination: str) -> None:
        self._set(RouteKey(tenant_id=nonblank(tenant_id, "tenant_id")), destination)

    def set_tenant_region(self, tenant_id: str, region: str, destination: str) -> None:
        self._set(
            RouteKey(nonblank(tenant_id, "tenant_id"), nonblank(region, "region")), destination
        )

    def remove_global_default(self) -> bool:
        return self._remove(RouteKey())

    def remove_global_region(self, region: str) -> bool:
        return self._remove(RouteKey(region=nonblank(region, "region")))

    def remove_tenant_default(self, tenant_id: str) -> bool:
        return self._remove(RouteKey(tenant_id=nonblank(tenant_id, "tenant_id")))

    def remove_tenant_region(self, tenant_id: str, region: str) -> bool:
        return self._remove(RouteKey(nonblank(tenant_id, "tenant_id"), nonblank(region, "region")))
