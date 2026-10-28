"""Artifact Chain API — the hash-chained audit trail.

GET /api/artifacts/{entity_type}/{entity_id} — chain + integrity verdict
GET /api/artifacts/{entity_type}/{entity_id}/verify — re-walk the chain
POST /api/artifacts/{entity_type}/{entity_id}/entries — append an entry
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.tenant import Tenant
from app.models.user import User
from app.services.artifact_chain import (
    append_artifact,
    get_chain,
    verify_chain,
)
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])

# Entity types the API exposes. Extending this list is deliberate — the chain
# is wired in-code at the state-change sites (approvals, backlog, templates).
ALLOWED_ENTITY_TYPES = {
    "approval_request", "backlog_item", "release", "project",
    "lifecycle_template", "risk", "kpi",
}


def _guard(entity_type: str):
    if entity_type not in ALLOWED_ENTITY_TYPES:
        raise HTTPException(404, f"Unknown entity type: {entity_type}")


class ArtifactEntryCreate(BaseModel):
    action: str
    payload: dict = {}
    artifact_type: str = "state_change"


@router.get("/{entity_type}/{entity_id}")
def read_chain(
    entity_type: str,
    entity_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """The entity's full audit trail + integrity verdict."""
    _guard(entity_type)
    entries = get_chain(db, current_tenant.id, entity_type, entity_id)
    verdict = verify_chain(db, current_tenant.id, entity_type, entity_id)
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "entries": entries,
        "valid": verdict["valid"],
        "length": verdict["length"],
        "broken_at": verdict["broken_at"],
    }


@router.get("/{entity_type}/{entity_id}/verify")
def verify(
    entity_type: str,
    entity_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Re-walk the hash chain: tampering breaks verification."""
    _guard(entity_type)
    return verify_chain(db, current_tenant.id, entity_type, entity_id)


@router.post("/{entity_type}/{entity_id}/entries", status_code=201)
def append_entry(
    entity_type: str,
    entity_id: int,
    data: ArtifactEntryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Append one hash-linked entry (actor = current user)."""
    _guard(entity_type)
    row = append_artifact(
        db,
        current_tenant.id,
        entity_type,
        entity_id,
        data.action,
        actor_id=current_user.id,
        actor_name=current_user.name,
        payload=data.payload,
        artifact_type=data.artifact_type,
    )
    db.commit()
    return {
        "id": row.id,
        "seq": row.seq,
        "action": row.action,
        "hash": row.hash,
        "prev_hash": row.prev_hash,
    }
