"""API Keys router — create, list, revoke API keys for programmatic access."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.api_key import ApiKey, ALL_SCOPES
from app.models.tenant import Tenant
from app.models.user import User
from app.services.tenant import get_current_tenant, require_tenant_role

router = APIRouter(prefix="/api", tags=["api-keys"])


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    scopes: str = Field("read", pattern=r"^(read|read,write|read,write,admin|write|admin)$")


class ApiKeyResponse(BaseModel):
    id: int
    name: str
    key_prefix: str
    scopes: str
    last_used_at: str | None = None
    created_at: str


@router.post("/api-keys")
def create_api_key(
    req: ApiKeyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
    _user: User = Depends(require_tenant_role("owner", "admin")),
):
    """Create a new API key. The full key is only shown once."""
    raw_key = ApiKey.generate_key()
    key_hash = ApiKey.hash_key(raw_key)
    key_prefix = ApiKey.get_prefix(raw_key)

    api_key = ApiKey(
        tenant_id=current_tenant.id,
        name=req.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        scopes=req.scopes,
        created_by=current_user.id,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    return {
        "id": api_key.id,
        "name": api_key.name,
        "key": raw_key,  # Only shown once!
        "key_prefix": key_prefix,
        "scopes": api_key.scopes,
        "message": "Save this key securely — it won't be shown again.",
    }


@router.get("/api-keys")
def list_api_keys(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
    _user: User = Depends(require_tenant_role("owner", "admin")),
):
    """List all API keys for the current tenant."""
    keys = db.query(ApiKey).filter(
        ApiKey.tenant_id == current_tenant.id,
    ).order_by(ApiKey.created_at.desc()).all()

    return [
        {
            "id": k.id,
            "name": k.name,
            "key_prefix": k.key_prefix,
            "scopes": k.scopes,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "created_at": k.created_at.isoformat() if k.created_at else None,
        }
        for k in keys
    ]


@router.delete("/api-keys/{key_id}")
def revoke_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
    _user: User = Depends(require_tenant_role("owner", "admin")),
):
    """Revoke (delete) an API key."""
    api_key = db.query(ApiKey).filter(
        ApiKey.id == key_id,
        ApiKey.tenant_id == current_tenant.id,
    ).first()
    if not api_key:
        raise HTTPException(404, "API key not found.")
    db.delete(api_key)
    db.commit()
    return {"ok": True, "revoked": key_id}
