"""Public operator-owned assertions, independent of candidate implementation details."""

import unittest
from typing import Any


class RoutingContract(unittest.TestCase):
    def fresh(self) -> tuple[Any, Any]:
        from route_service import RouteRegistry, RouteResolver

        registry = RouteRegistry()
        return registry, RouteResolver(registry)

    def test_hierarchy_precedence(self) -> None:
        registry, resolver = self.fresh()
        registry.set_global_default("G")
        registry.set_global_region("east", "GE")
        registry.set_global_region("west", "GW")
        registry.set_tenant_default("oak", "T")
        registry.set_tenant_region("oak", "east", "TE")
        for _ in range(2):
            for tenant, region, expected in (
                ("oak", "east", "TE"),
                ("oak", "west", "T"),
                ("pine", "east", "GE"),
                ("pine", "west", "GW"),
                ("pine", "south", "G"),
            ):
                with self.subTest(tenant=tenant, region=region):
                    self.assertEqual(resolver.resolve(tenant, region), expected)

    def test_cached_global_default_replacement(self) -> None:
        registry, resolver = self.fresh()
        registry.set_global_default("A")
        self.assertEqual(resolver.resolve("oak", "west"), "A")
        registry.set_global_default("B")
        self.assertEqual(resolver.resolve("oak", "west"), "B")

    def test_cached_global_region_replacement(self) -> None:
        registry, resolver = self.fresh()
        registry.set_global_region("east", "E1")
        self.assertEqual(resolver.resolve("oak", "east"), "E1")
        registry.set_global_region("east", "E2")
        self.assertEqual(resolver.resolve("oak", "east"), "E2")

    def test_cached_tenant_default_replacement(self) -> None:
        registry, resolver = self.fresh()
        registry.set_tenant_default("oak", "T1")
        self.assertEqual(resolver.resolve("oak", "west"), "T1")
        registry.set_tenant_default("oak", "T2")
        self.assertEqual(resolver.resolve("oak", "west"), "T2")

    def test_cached_tenant_region_replacement(self) -> None:
        registry, resolver = self.fresh()
        registry.set_tenant_region("oak", "east", "TE1")
        self.assertEqual(resolver.resolve("oak", "east"), "TE1")
        registry.set_tenant_region("oak", "east", "TE2")
        self.assertEqual(resolver.resolve("oak", "east"), "TE2")

    def test_tenant_region_removal_uses_current_fallback(self) -> None:
        registry, resolver = self.fresh()
        registry.set_tenant_default("oak", "T1")
        registry.set_tenant_region("oak", "east", "TE")
        self.assertEqual(resolver.resolve("oak", "east"), "TE")
        registry.set_tenant_default("oak", "T2")
        self.assertEqual(resolver.resolve("oak", "east"), "TE")
        self.assertTrue(registry.remove_tenant_region("oak", "east"))
        self.assertEqual(resolver.resolve("oak", "east"), "T2")

    def test_tenant_default_removal_uses_region_and_global_routes(self) -> None:
        registry, resolver = self.fresh()
        registry.set_global_default("G")
        registry.set_global_region("east", "GE")
        registry.set_tenant_default("oak", "T")
        self.assertEqual(resolver.resolve("oak", "east"), "T")
        self.assertEqual(resolver.resolve("oak", "west"), "T")
        registry.remove_tenant_default("oak")
        self.assertEqual(resolver.resolve("oak", "east"), "GE")
        self.assertEqual(resolver.resolve("oak", "west"), "G")

    def test_global_region_removal_uses_global_default(self) -> None:
        registry, resolver = self.fresh()
        registry.set_global_default("G")
        registry.set_global_region("east", "GE")
        self.assertEqual(resolver.resolve("oak", "east"), "GE")
        registry.remove_global_region("east")
        self.assertEqual(resolver.resolve("oak", "east"), "G")

    def test_unrelated_tenant_and_region_semantics(self) -> None:
        registry, resolver = self.fresh()
        registry.set_global_default("G")
        registry.set_global_region("east", "GE")
        registry.set_tenant_default("oak", "T1")
        self.assertEqual(resolver.resolve("oak", "west"), "T1")
        self.assertEqual(resolver.resolve("pine", "east"), "GE")
        self.assertEqual(resolver.resolve("pine", "west"), "G")
        registry.set_tenant_default("oak", "T2")
        self.assertEqual(resolver.resolve("pine", "east"), "GE")
        self.assertEqual(resolver.resolve("pine", "west"), "G")
        self.assertEqual(resolver.resolve("oak", "west"), "T2")
        registry.set_global_region("east", "GE2")
        self.assertEqual(resolver.resolve("oak", "east"), "T2")
        self.assertEqual(resolver.resolve("pine", "west"), "G")
        self.assertEqual(resolver.resolve("pine", "east"), "GE2")

    def test_repeated_update_resolve_and_remove_cycles(self) -> None:
        registry, resolver = self.fresh()
        for index in range(4):
            destination = f"G{index}"
            registry.set_global_default(destination)
            self.assertEqual(resolver.resolve("oak", "west"), destination)
            registry.set_tenant_region("oak", "west", "override")
            self.assertEqual(resolver.resolve("oak", "west"), "override")
            registry.remove_tenant_region("oak", "west")
            self.assertEqual(resolver.resolve("oak", "west"), destination)

    def test_broad_update_refreshes_every_affected_pair(self) -> None:
        registry, resolver = self.fresh()
        pairs = (("oak", "west"), ("pine", "east"), ("birch", "south"))
        registry.set_global_default("A")
        for tenant, region in pairs:
            self.assertEqual(resolver.resolve(tenant, region), "A")
        registry.set_global_default("B")
        for tenant, region in pairs:
            with self.subTest(tenant=tenant, region=region):
                self.assertEqual(resolver.resolve(tenant, region), "B")

    def test_region_and_tenant_updates_refresh_multiple_dependents(self) -> None:
        registry, resolver = self.fresh()
        registry.set_global_region("east", "E1")
        registry.set_tenant_default("oak", "T1")
        for tenant, region, expected in (
            ("pine", "east", "E1"),
            ("birch", "east", "E1"),
            ("oak", "west", "T1"),
            ("oak", "south", "T1"),
        ):
            self.assertEqual(resolver.resolve(tenant, region), expected)
        registry.set_global_region("east", "E2")
        for tenant in ("pine", "birch"):
            with self.subTest(tenant=tenant, stage="region update"):
                self.assertEqual(resolver.resolve(tenant, "east"), "E2")
        for region in ("west", "south"):
            self.assertEqual(resolver.resolve("oak", region), "T1")
        registry.set_tenant_default("oak", "T2")
        for tenant, region, expected in (
            ("pine", "east", "E2"),
            ("birch", "east", "E2"),
            ("oak", "west", "T2"),
            ("oak", "south", "T2"),
        ):
            with self.subTest(tenant=tenant, region=region):
                self.assertEqual(resolver.resolve(tenant, region), expected)

    def test_complete_fallback_descent_after_cached_results(self) -> None:
        registry, resolver = self.fresh()
        registry.set_global_default("G")
        registry.set_global_region("east", "GE")
        registry.set_tenant_default("oak", "T")
        registry.set_tenant_region("oak", "east", "TE")
        self.assertEqual(resolver.resolve("oak", "east"), "TE")
        registry.remove_tenant_region("oak", "east")
        self.assertEqual(resolver.resolve("oak", "east"), "T")
        registry.remove_tenant_default("oak")
        self.assertEqual(resolver.resolve("oak", "east"), "GE")
        registry.remove_global_region("east")
        self.assertEqual(resolver.resolve("oak", "east"), "G")

    def test_new_specific_routes_override_previous_fallbacks(self) -> None:
        registry, resolver = self.fresh()
        registry.set_global_default("G")
        self.assertEqual(resolver.resolve("oak", "east"), "G")
        registry.set_global_region("east", "GE")
        self.assertEqual(resolver.resolve("oak", "east"), "GE")
        registry.set_tenant_default("oak", "T")
        self.assertEqual(resolver.resolve("oak", "east"), "T")
        registry.set_tenant_region("oak", "east", "TE")
        self.assertEqual(resolver.resolve("oak", "east"), "TE")

    def test_missing_routes_recover_and_last_removal_raises_domain_error(self) -> None:
        from route_service import RouteNotFoundError

        registry, resolver = self.fresh()
        with self.assertRaises(RouteNotFoundError) as missing:
            resolver.resolve("oak", "east")
        self.assertEqual((missing.exception.tenant_id, missing.exception.region), ("oak", "east"))
        registry.set_global_default("G")
        self.assertEqual(resolver.resolve("oak", "east"), "G")
        self.assertTrue(registry.remove_global_default())
        with self.assertRaises(RouteNotFoundError):
            resolver.resolve("oak", "east")
        registry.set_global_default("new")
        self.assertEqual(resolver.resolve("oak", "east"), "new")

    def test_multiple_live_resolvers_see_the_same_registry_changes(self) -> None:
        from route_service import RouteResolver

        registry, first = self.fresh()
        second = RouteResolver(registry)
        registry.set_global_default("A")
        self.assertEqual(first.resolve("oak", "east"), "A")
        self.assertEqual(second.resolve("oak", "east"), "A")
        registry.set_global_default("B")
        self.assertEqual(first.resolve("oak", "east"), "B")
        self.assertEqual(second.resolve("oak", "east"), "B")

    def test_public_api_identity_validation_and_independent_state(self) -> None:
        from route_service import RouteCache, RouteRegistry, RouteResolver
        from route_service.models import RouteKey

        registry = RouteRegistry()
        cache = RouteCache()
        resolver = RouteResolver(registry, cache)
        self.assertIsNone(registry.set_global_default(" G "))
        registry.set_tenant_default("Oak", "T")
        self.assertEqual(resolver.resolve("oak", "east"), " G ")
        self.assertEqual(resolver.resolve("Oak", "east"), "T")
        self.assertIs(registry.remove_global_region("missing"), False)
        with self.assertRaises(ValueError):
            registry.set_global_default("")
        with self.assertRaises(ValueError):
            registry.set_tenant_region("", "east", "bad")
        with self.assertRaises(ValueError):
            resolver.resolve("oak", " ")
        self.assertEqual(resolver.resolve("oak", "east"), " G ")
        cache.clear()
        self.assertIsNone(cache.get(RouteKey("oak", "east")))
        other = RouteRegistry()
        other.set_global_default("independent")
        self.assertEqual(RouteResolver(other).resolve("oak", "east"), "independent")
