"""Artifact Chain API — the hash-chained audit trail.

GET /api/artifacts/{entity_type}/{entity_id} — chain + integrity verdict
      (?at=<ISO datetime> time-travel: the chain AS OF that moment)
GET /api/artifacts/{entity_type}/{entity_id}/verify — re-walk the chain
      (?at= verifies only the chain PREFIX up to that moment)
GET /api/artifacts/timeline — the tenant-wide ledger stream (newest first,
      ?project_id= filter, ?since=/ ?until= window, limit/offset pagination)
POST /api/artifacts/{entity_type}/{entity_id}/entries — append an entry

Time-travel is strictly READ-only: it scopes the read/verify queries to a past
moment; the ledger's write paths (append_artifact) are untouched.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.approval import ApprovalRequest
from app.models.artifact_chain import ArtifactChain
from app.models.backlog_item import BacklogItem
from app.models.decision_record import DecisionRecord
from app.models.kpi import KPI
from app.models.release import Release
from app.models.risk import Risk
from app.models.tenant import Tenant
from app.models.user import User
from app.services.artifact_chain import (
    append_artifact,
    as_of_moment,
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

# Entity types whose chain entries hang off a project, resolved through the
# entity's own project_id column. "project" entries match entity_id directly;
# lifecycle_template is tenant-level (no project linkage) and so is excluded
# from the timeline's ?project_id= scope.
_PROJECT_SCOPED_ENTITIES = {
    "approval_request": ApprovalRequest,
    "backlog_item": BacklogItem,
    "release": Release,
    "risk": Risk,
    "kpi": KPI,
    "decision": DecisionRecord,
}


def _guard(entity_type: str):
    if entity_type not in ALLOWED_ENTITY_TYPES:
        raise HTTPException(404, f"Unknown entity type: {entity_type}")


class ArtifactEntryCreate(BaseModel):
    action: str
    payload: dict = {}
    artifact_type: str = "state_change"


def _timeline_row(r: ArtifactChain) -> dict:
    return {
        "id": r.id,
        "seq": r.seq,
        "entity_type": r.entity_type,
        "entity_id": r.entity_id,
        "action": r.action,
        "actor": r.actor_name,
        "artifact_type": r.artifact_type,
        "payload": r.payload,
        "prev_hash": r.prev_hash,
        "hash": r.hash,
        "created_at": r.created_at,
    }


@router.get("/timeline")
def timeline(
    project_id: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """The tenant-wide ledger stream, newest first.

    ?project_id= chains the stream to one project's work (the project's own
    entries plus every project-scoped entity's entries); ?since= / ?until=
    window the stream in time; limit/offset paginate.
    """
    query = db.query(ArtifactChain).filter(ArtifactChain.tenant_id == current_tenant.id)
    if project_id is not None:
        scopes = [and_(ArtifactChain.entity_type == "project", ArtifactChain.entity_id == project_id)]
        for entity_type, model in _PROJECT_SCOPED_ENTITIES.items():
            ids = [row[0] for row in db.query(model.id).filter(model.project_id == project_id).all()]
            if ids:
                scopes.append(and_(ArtifactChain.entity_type == entity_type, ArtifactChain.entity_id.in_(ids)))
        query = query.filter(or_(*scopes))
    if since is not None:
        query = query.filter(ArtifactChain.created_at >= as_of_moment(since))
    if until is not None:
        query = query.filter(ArtifactChain.created_at <= as_of_moment(until))
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    total = query.count()
    rows = query.order_by(ArtifactChain.created_at.desc(), ArtifactChain.id.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "entries": [_timeline_row(r) for r in rows],
    }


@router.get("/{entity_type}/{entity_id}")
def read_chain(
    entity_type: str,
    entity_id: int,
    at: datetime | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """The entity's audit trail + integrity verdict.

    ?at=<ISO datetime> (time-travel): the chain AS OF that moment — only the
    entries with created_at <= at, with the verdict scoped to that prefix.
    Without ?at the response is unchanged.
    """
    _guard(entity_type)
    as_of = as_of_moment(at) if at is not None else None
    entries = get_chain(db, current_tenant.id, entity_type, entity_id, as_of=as_of)
    verdict = verify_chain(db, current_tenant.id, entity_type, entity_id, as_of=as_of)
    body = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "entries": entries,
        "valid": verdict["valid"],
        "length": verdict["length"],
        "broken_at": verdict["broken_at"],
    }
    if as_of is not None:
        body["as_of"] = as_of.isoformat()
    return body


@router.get("/{entity_type}/{entity_id}/verify")
def verify(
    entity_type: str,
    entity_id: int,
    at: datetime | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Re-walk the hash chain: tampering breaks verification.

    ?at=<ISO datetime>: verify only the chain PREFIX up to that moment — a
    tampered entry after `at` does not fail an as-of verify; a tampered entry
    within the prefix does.
    """
    _guard(entity_type)
    as_of = as_of_moment(at) if at is not None else None
    result = verify_chain(db, current_tenant.id, entity_type, entity_id, as_of=as_of)
    if as_of is not None:
        result = {**result, "as_of": as_of.isoformat()}
    return result


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
