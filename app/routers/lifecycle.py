"""Lifecycle API — template vocabulary per project type for the UI.

GET /api/lifecycle/{type} returns the template (name, item phases, release
stages, gate deliverables, gate roles, fields). Unknown types default to
software. P4.4: tenant-defined custom templates override built-ins for
their project_type key; GET/POST /templates manages them.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.activity_log import ActivityLog
from app.models.tenant import Tenant
from app.models.user import User
from app.services.lifecycle import (
    LIFECYCLE_TEMPLATES,
    template_for,
)
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api/lifecycle", tags=["lifecycle"])


def _template_response(key: str, t: dict) -> dict:
    return {
        "key": key,
        "name": t["name"],
        "item_phases": t["item_phases"],
        "release_stages": t["release_stages"],
        "gate_deliverables": t["gate_deliverables"],
        "gate_roles": t["gate_roles"],
        "fields": t["fields"],
        "custom": t.get("custom", False),
    }


@router.get("/types")
def list_types(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Available project types with their template names (custom ones included)."""
    from app.models.lifecycle_template import TenantLifecycleTemplate
    rows = (
        db.query(TenantLifecycleTemplate)
        .filter(TenantLifecycleTemplate.tenant_id == current_tenant.id)
        .all()
    )
    custom = [{"key": r.project_type, "name": r.name, "custom": True} for r in rows]
    builtin = [{"key": key, "name": t["name"], "custom": False} for key, t in LIFECYCLE_TEMPLATES.items()]
    return custom + builtin


@router.get("/{project_type}")
def get_template(
    project_type: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Full template vocabulary for one project type (tenant override first)."""
    t = template_for(project_type, tenant_id=current_tenant.id, db=db)
    key = (project_type or "software").lower()
    if key not in LIFECYCLE_TEMPLATES and not t.get("custom"):
        key = "software"
    return _template_response(key, t)


# ── Template builder (P4.4) ──────────────────────────────────────────────

class TemplateCreate(BaseModel):
    project_type: str
    name: str
    description: str | None = None
    item_phases: list[str]
    release_stages: list[str]
    gate_deliverables: dict[str, list[str]]
    gate_roles: dict[str, str]
    fields: list[dict] = []


@router.get("/{project_type}/templates")
def list_tenant_templates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """All custom lifecycle templates the tenant has defined."""
    from app.models.lifecycle_template import TenantLifecycleTemplate
    rows = (
        db.query(TenantLifecycleTemplate)
        .filter(TenantLifecycleTemplate.tenant_id == current_tenant.id)
        .order_by(TenantLifecycleTemplate.id)
        .all()
    )
    return {
        "templates": [
            {
                "id": r.id, "project_type": r.project_type, "name": r.name,
                "description": r.description, "item_phases": r.item_phases,
                "release_stages": r.release_stages,
                "gate_deliverables": r.gate_deliverables, "gate_roles": r.gate_roles,
                "fields": r.fields,
            }
            for r in rows
        ]
    }


@router.post("/templates", status_code=201)
def create_tenant_template(
    data: TemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Define (or replace) a custom lifecycle for a project_type key."""
    from app.models.lifecycle_template import TenantLifecycleTemplate
    key = data.project_type.strip().lower()
    if not key:
        raise HTTPException(400, "project_type is required")
    if not data.item_phases:
        raise HTTPException(400, "At least one item phase is required")

    row = (
        db.query(TenantLifecycleTemplate)
        .filter(
            TenantLifecycleTemplate.tenant_id == current_tenant.id,
            TenantLifecycleTemplate.project_type == key,
        )
        .first()
    )
    if row:
        row.name = data.name
        row.description = data.description
        row.item_phases = data.item_phases
        row.release_stages = data.release_stages
        row.gate_deliverables = data.gate_deliverables
        row.gate_roles = data.gate_roles
        row.fields = data.fields
    else:
        row = TenantLifecycleTemplate(
            tenant_id=current_tenant.id, project_type=key,
            name=data.name, description=data.description,
            item_phases=data.item_phases, release_stages=data.release_stages,
            gate_deliverables=data.gate_deliverables, gate_roles=data.gate_roles,
            fields=data.fields, created_by=current_user.id,
        )
        db.add(row)
    db.flush()
    db.add(ActivityLog(
        tenant_id=current_tenant.id, user_id=current_user.id,
        entity_type="lifecycle_template", entity_id=row.id, action="updated",
        summary=f"Lifecycle template '{data.name}' defined for type '{key}'",
    ))
    db.commit()
    db.refresh(row)
    return {"id": row.id, "project_type": row.project_type, "name": row.name}


@router.delete("/templates/{template_id}")
def delete_tenant_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Remove a custom template — the project type falls back to the built-in."""
    from app.models.lifecycle_template import TenantLifecycleTemplate
    row = (
        db.query(TenantLifecycleTemplate)
        .filter(
            TenantLifecycleTemplate.id == template_id,
            TenantLifecycleTemplate.tenant_id == current_tenant.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, "Template not found in this tenant.")
    key = row.project_type
    db.delete(row)
    db.commit()
    return {"deleted": key}
