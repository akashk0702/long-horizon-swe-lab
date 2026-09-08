"""Domain error for lookups with no applicable configured destination."""


class RouteNotFoundError(LookupError):
    def __init__(self, tenant_id: str, region: str) -> None:
        self.tenant_id = tenant_id
        self.region = region
        super().__init__(f"No route for tenant {tenant_id!r} in region {region!r}")
