from route_service import RouteCache
from route_service.models import ChangeKind, RouteChange, RouteKey


def test_cache_store_replace_and_invalidate() -> None:
    cache = RouteCache()
    key = RouteKey("oak", "east")
    assert cache.get(key) is None
    cache.put(key, "first")
    assert cache.get(key) == "first"
    cache.put(key, "second")
    assert cache.get(key) == "second"
    cache.invalidate(RouteChange(key, ChangeKind.SET))
    assert cache.get(key) is None


def test_clear_and_independent_instances() -> None:
    first, second = RouteCache(), RouteCache()
    key = RouteKey("oak", "east")
    first.put(key, "route")
    assert second.get(key) is None
    first.clear()
    assert first.get(key) is None
