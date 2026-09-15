"""API key authentication service.

Resolves an API key from the X-API-Key header, validates it against
the database, and returns the associated tenant + scopes.
"""
import hashlib
from fastapi import Depends, HTTPException, Header, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.api_key import ApiKey
from app.models.tenant import Tenant


def authenticate_api_key(
    request: Request,
    x_api_key: str = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> tuple[Tenant, ApiKey]:
    """Authenticate a request using an API key.

    Returns (tenant, api_key) if valid.
    Raises 401 if no key or invalid key.
    """
    if not x_api_key:
        raise HTTPException(401, "API key required. Provide it in the X-API-Key header.")

    key_hash = ApiKey.hash_key(x_api_key)
    api_key = db.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()

    if not api_key:
        raise HTTPException(401, "Invalid API key.")

    tenant = db.query(Tenant).filter(Tenant.id == api_key.tenant_id).first()
    if not tenant or tenant.status != "active":
        raise HTTPException(403, "Tenant is not active.")

    # Update last_used_at
    from datetime import datetime
    api_key.last_used_at = datetime.utcnow()
    db.commit()

    # Store tenant_id on request state for rate limiting middleware
    request.state.tenant_id = tenant.id
    request.state.tenant_plan = tenant.plan

    return tenant, api_key


def require_api_key_scope(scope: str):
    """Dependency factory: require an API key with the given scope."""
    def checker(
        auth: tuple = Depends(authenticate_api_key),
    ) -> tuple[Tenant, ApiKey]:
        tenant, api_key = auth
        if not api_key.has_scope(scope):
            raise HTTPException(
                403,
                f"API key '{api_key.name}' does not have the '{scope}' scope.",
            )
        return tenant, api_key
    return checker
