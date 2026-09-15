"""Middleware package — quota headers and rate limiting."""

from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware import rate_limit as rate_limit_module

# Keep the QuotaHeaderMiddleware from the original __init__.py
from starlette.middleware.base import BaseHTTPMiddleware


class QuotaHeaderMiddleware(BaseHTTPMiddleware):
    """Add X-Quota-* headers to API responses."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        try:
            if hasattr(request.state, "tenant_id") and hasattr(request.state, "db"):
                from app.services.usage_service import get_quota_headers
                from app.models.tenant import Tenant
                db = request.state.db
                tenant = db.query(Tenant).filter(Tenant.id == request.state.tenant_id).first()
                if tenant:
                    headers = get_quota_headers(db, tenant)
                    for key, value in headers.items():
                        response.headers[key] = value
        except Exception:
            pass
        return response


__all__ = ["QuotaHeaderMiddleware", "RateLimitMiddleware"]
