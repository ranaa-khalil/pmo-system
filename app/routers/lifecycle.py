"""Lifecycle API — template vocabulary per project type for the UI.

GET /api/lifecycle/{type} returns the template (name, item phases, release
stages, gate deliverables, gate roles, fields). Unknown types default to
software. The gate MECHANISM and RBAC are unchanged — only vocabulary varies.
"""
from fastapi import APIRouter, Depends

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.services.lifecycle import (
    LIFECYCLE_TEMPLATES,
    item_phases,
    release_stages,
    template_fields,
    template_for,
)

router = APIRouter(prefix="/api/lifecycle", tags=["lifecycle"])


@router.get("/types")
def list_types(current_user: User = Depends(get_current_user)):
    """Available project types with their template names."""
    return [
        {"key": key, "name": t["name"]}
        for key, t in LIFECYCLE_TEMPLATES.items()
    ]


@router.get("/{project_type}")
def get_template(
    project_type: str,
    db=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full template vocabulary for one project type."""
    t = template_for(project_type)
    return {
        "key": (project_type or "software").lower() if (project_type or "").lower() in LIFECYCLE_TEMPLATES else "software",
        "name": t["name"],
        "item_phases": item_phases(project_type),
        "release_stages": release_stages(project_type),
        "gate_deliverables": t["gate_deliverables"],
        "gate_roles": t["gate_roles"],
        "fields": template_fields(project_type),
    }
