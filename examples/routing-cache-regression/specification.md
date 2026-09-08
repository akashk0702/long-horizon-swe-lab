# Repair stale route resolution

Repair stale route resolution after runtime configuration changes in a hierarchical routing service.

The application resolves destinations correctly on initial lookups, and its existing developer tests pass. Some repeated lookups return an earlier destination after the registry has been changed. Repair the behavior while preserving the existing public API. Work on a copy of `start/`; choose your own internal design.

## Required routing semantics

For an exact `(tenant_id, region)` pair, return the first configured destination in this order:

1. Tenant-region route.
2. Tenant default.
3. Global region route.
4. Global default.

Every completed configuration change must be visible to the next `resolve` call. This applies to routes that already existed, newly added routes, replacement destinations, and removals. Previously resolved pairs and pairs not yet resolved must follow the same hierarchy.

One broad change can affect many pairs. If three tenants in three regions previously resolved through global default A, setting global default B must update all three answers unless a more-specific current route applies. Unrelated tenants and regions must remain semantically correct; retaining particular entries or a particular hit rate is not required.

## Public API compatibility

`route_service` exports `RouteRegistry`, `RouteResolver`, `RouteCache`, and `RouteNotFoundError`. Construct a registry with `RouteRegistry()` and a resolver with `RouteResolver(registry, cache=None)`. Multiple live resolvers may use the same registry, each with its own cache. A supplied cache belongs to that resolver/registry pairing; sharing it across different registries is outside this task. All calls are sequential.

Preserve these methods and their signatures:

- `set_global_default(destination)`
- `set_global_region(region, destination)`
- `set_tenant_default(tenant_id, destination)`
- `set_tenant_region(tenant_id, region, destination)`
- `remove_global_default()`
- `remove_global_region(region)`
- `remove_tenant_default(tenant_id)`
- `remove_tenant_region(tenant_id, region)`
- `resolve(tenant_id, region)`

Setters return None. Removers return True when a route existed and False when it did not; removing an absent route is harmless. Resolution returns the configured destination string unchanged. Tenant IDs, regions, and destinations must be nonblank strings; invalid inputs raise ValueError without changing configuration. Identity is exact and case-sensitive; do not trim or normalize strings.

If no route applies, raise `RouteNotFoundError`, preserving its `tenant_id` and `region` attributes. A missing route may become available after a later update. Removing the last applicable route must produce the same domain error even after an earlier successful lookup.

Preserve existing developer tests and their API guarantees, including the exported cache's get/put/clear behavior and independent registry state. Internal notification details and storage representations are not prescribed. No concurrent-call guarantee, persistent storage, selective-entry-retention policy, or advanced performance target is required.

## Reproduction

Run this against a working copy's `src/` package:

```python
from route_service import RouteRegistry, RouteResolver

registry = RouteRegistry()
registry.set_global_default("route-a")
resolver = RouteResolver(registry)
assert resolver.resolve("oak", "west") == "route-a"
registry.set_global_default("route-b")
assert resolver.resolve("oak", "west") == "route-b"  # Currently returns route-a.
```

Also check a previously resolved full hierarchy: tenant-region TE, tenant default T, global region GE, and global default G. Removing each applicable route in turn must yield **TE → T → GE → G** on subsequent lookups, then a domain error if G is removed. Repeated update/resolve cycles must remain correct.

## Verification and boundaries

Evaluator-owned behavioral verification is public and kept outside the candidate workspace. It calls the service API after real mutation and lookup sequences. It does not compare source code with the reference implementation, read candidate result files, or accept a printed success document as a verdict.

You may repair or add code under `src/` and add developer tests. Do not delete existing tests or modify the evaluator, framework, task manifest, or reference files. Use the README commands to run developer tests and framework verification. Different internal fixes are accepted when they preserve the documented behavior.
