"""Projects API router — CRUD endpoints with hierarchical RBAC."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app.models.project import Project
from app.models.client import Client
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse
from app.dependencies import get_current_user
from app.permissions import can_create_project, can_manage_client, can_manage_project, can_assign_pm, get_visible_projects

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("", response_model=ProjectResponse, status_code=201)
def create_project(project: ProjectCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Create a new project (super admin or account manager for this client)."""
    client = db.query(Client).filter(Client.id == project.client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    if not can_create_project(current_user, client):
        raise HTTPException(status_code=403, detail="Only super admins or the account manager can create projects for this client")
    db_project = Project(
        name=project.name,
        client_id=project.client_id,
        description=project.description,
        status=project.status or "Active",
        start_date=project.start_date,
        github_repo=project.github_repo,
        version_prefix=project.version_prefix,
        dev_url=project.dev_url,
        uat_url=project.uat_url,
        prod_url=project.prod_url,
    )
    db.add(db_project)
    db.commit()
    db.refresh(db_project)
    return db_project


@router.get("", response_model=List[ProjectResponse])
def list_projects(
    client_id: Optional[int] = Query(None, description="Filter by client ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List projects visible to the current user."""
    projects = get_visible_projects(current_user, db)
    if client_id is not None:
        projects = [p for p in projects if p.client_id == client_id]
    return projects


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get a specific project by ID."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(project_id: int, project_update: ProjectUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Update a project (super admin, AM, or PM)."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not can_manage_project(current_user, project, db):
        raise HTTPException(status_code=403, detail="You don't have permission to manage this project")
    update_data = project_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return project


@router.put("/{project_id}/project-manager", response_model=ProjectResponse)
def assign_project_manager(
    project_id: int,
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Assign a project manager to a project (super admin, AM, or current PM)."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not can_assign_pm(current_user, project, db):
        raise HTTPException(status_code=403, detail="You don't have permission to assign a PM to this project")
    pm_id = data.get("project_manager_id")
    if pm_id:
        pm = db.query(User).filter(User.id == pm_id).first()
        if not pm:
            raise HTTPException(status_code=404, detail="User not found")
        if pm.system_role == "member":
            pm.system_role = "project_manager"
    project.project_manager_id = pm_id
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Delete a project (super admin or AM)."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    client = db.query(Client).filter(Client.id == project.client_id).first()
    if not can_manage_client(current_user, client):
        raise HTTPException(status_code=403, detail="Only super admins or the account manager can delete projects")
    db.delete(project)
    db.commit()
