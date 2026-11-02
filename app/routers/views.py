"""Saved project views API — GitHub Boards parity (R7).

GET    /api/projects/{project_id}/views   list views (shared OR own, tenant-scoped)
POST   /api/projects/{project_id}/views   create a saved view (PM/tenant-admin/AM)
DELETE /api/views/{view_id}               delete (creator, PM, or tenant admin)
"""
import json as _json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.project import Project
from app.models.project_view import ProjectView
from app.models.tenant import TenantMembership
from app.models.user import User
from app.permissions import can_manage_project
from app.schemas.project_view import ProjectViewCreate, ProjectViewResponse

router = APIRouter(prefix="/api", tags=["views"])


def _load_project(db: Session, project_id: int, user: User) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    membership = db.query(TenantMembership).filter(
        TenantMembership.user_id == user.id, TenantMembership.tenant_id == project.tenant_id,
    ).first()
    if not membership and user.system_role != "super_admin":
        raise HTTPException(403, "You don't have access to this project")
    return project


def _row(view: ProjectView) -> dict:
    filters = view.filters
    if filters and isinstance(filters, str):
        try:
            filters = _json.loads(filters)
        except ValueError:
            pass
    return {
        "id": view.id,
        "project_id": view.project_id,
        "name": view.name,
        "view_type": view.view_type,
        "filters": filters,
        "shared": view.shared,
        "created_by": view.created_by,
        "created_at": view.created_at,
    }


@router.get("/projects/{project_id}/views", response_model=list[ProjectViewResponse])
def list_views(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = _load_project(db, project_id, current_user)
    query = db.query(ProjectView).filter(
        ProjectView.tenant_id == project.tenant_id, ProjectView.project_id == project.id,
    )
    # Private views are visible only to their creator
    query = query.filter((ProjectView.shared == True) | (ProjectView.created_by == current_user.id))  # noqa: E712
    rows = query.order_by(ProjectView.id.desc()).all()
    return [_row(v) for v in rows]


@router.post("/projects/{project_id}/views", response_model=ProjectViewResponse, status_code=201)
def create_view(project_id: int, req: ProjectViewCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    project = _load_project(db, project_id, current_user)
    if not can_manage_project(current_user, project, db):
        raise HTTPException(403, "You don't have permission to save views on this project")
    filters = req.filters
    if filters is not None and not isinstance(filters, str):
        filters = _json.dumps(filters)
    view = ProjectView(
        tenant_id=project.tenant_id, project_id=project.id,
        name=req.name[:200], view_type=req.view_type,
        filters=filters, shared=req.shared, created_by=current_user.id,
    )
    db.add(view)
    db.commit()
    db.refresh(view)
    return _row(view)


@router.delete("/views/{view_id}", status_code=204)
def delete_view(view_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    view = db.query(ProjectView).filter(ProjectView.id == view_id).first()
    if not view:
        raise HTTPException(404, "View not found")
    project = db.query(Project).filter(Project.id == view.project_id).first()
    allowed = view.created_by == current_user.id or (project and can_manage_project(current_user, project, db))
    if not allowed:
        raise HTTPException(403, "You can only delete your own views")
    db.delete(view)
    db.commit()
