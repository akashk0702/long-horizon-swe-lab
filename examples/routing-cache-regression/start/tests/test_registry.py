import pytest
from route_service import RouteRegistry
from route_service.models import RouteKey


def test_scopes_are_independent_and_replacements_return_none() -> None:
    registry = RouteRegistry()
    assert registry.set_global_default("base") is None
    registry.set_global_region("east", "region")
    registry.set_tenant_default("oak", "tenant")
    registry.set_tenant_region("oak", "east", "specific")
    assert registry.get(RouteKey()) == "base"
    assert registry.get(RouteKey(region="east")) == "region"
    assert registry.get(RouteKey(tenant_id="oak")) == "tenant"
    assert registry.get(RouteKey("oak", "east")) == "specific"
    registry.set_global_default("replacement")
    assert registry.get(RouteKey()) == "replacement"


def test_removals_return_whether_a_route_existed() -> None:
    registry = RouteRegistry()
    registry.set_global_default("base")
    registry.set_global_region("east", "region")
    registry.set_tenant_default("oak", "tenant")
    registry.set_tenant_region("oak", "east", "specific")
    for remove in (
        lambda: registry.remove_tenant_region("oak", "east"),
        lambda: registry.remove_tenant_default("oak"),
        lambda: registry.remove_global_region("east"),
        registry.remove_global_default,
    ):
        assert remove() is True
        assert remove() is False
    assert registry.get(RouteKey()) is None


def test_invalid_input_preserves_configuration() -> None:
    registry = RouteRegistry()
    registry.set_global_default("base")
    with pytest.raises(ValueError):
        registry.set_global_default("")
    with pytest.raises(ValueError):
        registry.set_global_region(" ", "region")
    with pytest.raises(ValueError):
        registry.set_tenant_default("", "tenant")
    assert registry.get(RouteKey()) == "base"
