import pytest
from route_service import RouteNotFoundError, RouteRegistry, RouteResolver


def test_hierarchy_on_first_lookup_and_repeated_lookup() -> None:
    registry = RouteRegistry()
    registry.set_global_default("base")
    registry.set_global_region("east", "region")
    registry.set_global_region("west", "west-region")
    registry.set_tenant_default("oak", "tenant")
    registry.set_tenant_region("oak", "east", "specific")
    resolver = RouteResolver(registry)
    for _ in range(2):
        assert resolver.resolve("oak", "east") == "specific"
        assert resolver.resolve("oak", "west") == "tenant"
        assert resolver.resolve("pine", "east") == "region"
        assert resolver.resolve("pine", "west") == "west-region"
        assert resolver.resolve("pine", "south") == "base"


def test_exact_override_replacement_is_visible() -> None:
    registry = RouteRegistry()
    registry.set_tenant_region("oak", "east", "first")
    resolver = RouteResolver(registry)
    assert resolver.resolve("oak", "east") == "first"
    registry.set_tenant_region("oak", "east", "second")
    assert resolver.resolve("oak", "east") == "second"


def test_configuration_removal_before_first_lookup_uses_fallback() -> None:
    registry = RouteRegistry()
    registry.set_global_default("base")
    registry.set_tenant_default("oak", "tenant")
    registry.remove_tenant_default("oak")
    assert RouteResolver(registry).resolve("oak", "east") == "base"


def test_missing_route_and_invalid_lookup_are_distinct_errors() -> None:
    resolver = RouteResolver(RouteRegistry())
    with pytest.raises(RouteNotFoundError) as missing:
        resolver.resolve("oak", "east")
    assert (missing.value.tenant_id, missing.value.region) == ("oak", "east")
    with pytest.raises(ValueError):
        resolver.resolve("", "east")


def test_independent_registries_do_not_share_results() -> None:
    first, second = RouteRegistry(), RouteRegistry()
    first.set_global_default("first")
    second.set_global_default("second")
    assert RouteResolver(first).resolve("oak", "east") == "first"
    assert RouteResolver(second).resolve("oak", "east") == "second"
