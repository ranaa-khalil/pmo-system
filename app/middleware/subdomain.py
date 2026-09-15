"""Subdomain middleware — resolves tenant from the request subdomain.

When a request comes to `acme.localhost:8000` or `acme.pmosystem.app`,
this middleware extracts `acme` as the tenant slug, looks up the tenant
in the database, and stores it on `request.state.tenant_slug` and
`request.state.tenant_branding`.

For `localhost:8000` (no subdomain), no tenant is resolved — the app
shows its default branding. This is the super-admin / root access point.
"""
import json as _json
import logging

from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# Domains that are considered "root" (no tenant subdomain)
ROOT_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "pmosystem.app"}


class SubdomainMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        host = request.headers.get("host", "").split(":")[0].lower()

        # Try to extract subdomain
        # e.g. "acme.localhost" → subdomain="acme"
        #      "acme.pmosystem.app" → subdomain="acme"
        #      "localhost" → subdomain=None
        parts = host.split(".")
        tenant_slug = None

        if len(parts) >= 2:
            sub = parts[0]
            # Skip www, api, and root hosts
            if sub not in ("www", "api", "") and host not in ROOT_HOSTS:
                # Check if the remaining parts form a known root domain
                remaining = ".".join(parts[1:])
                if remaining in ROOT_HOSTS or remaining == "localhost":
                    tenant_slug = sub
                elif len(parts) >= 3:
                    # e.g. acme.pmosystem.app — subdomain is first part
                    tenant_slug = sub

        request.state.tenant_slug = tenant_slug

        # Resolve branding from DB if we have a slug
        if tenant_slug:
            try:
                from app.database import SessionLocal
                from app.models.tenant import Tenant

                db = SessionLocal()
                tenant = db.query(Tenant).filter(Tenant.slug == tenant_slug).first()
                if tenant:
                    branding = _json.loads(tenant.branding) if tenant.branding else {}
                    request.state.tenant_branding = {
                        "slug": tenant.slug,
                        "name": tenant.name,
                        "logo_url": tenant.logo_url or branding.get("logo_url", ""),
                        "primary_color": branding.get("primary_color", ""),
                        "app_name": branding.get("app_name", tenant.name),
                        "hide_powered_by": branding.get("hide_powered_by", False),
                    }
                else:
                    request.state.tenant_branding = None
                db.close()
            except Exception as e:
                logger.warning(f"Subdomain resolution error for '{tenant_slug}': {e}")
                request.state.tenant_branding = None
        else:
            request.state.tenant_branding = None

        response = await call_next(request)
        return response
