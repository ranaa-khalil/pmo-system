"""Stakeholder + Roles API router."""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.role import Role
from app.models.role_assignment import RoleAssignment
from app.models.stakeholder import Stakeholder
from app.schemas.stakeholder import (
    StakeholderCreate, StakeholderUpdate, StakeholderResponse,
    RoleCreate, RoleUpdate, RoleResponse,
    RoleAssignmentCreate, RoleAssignmentResponse,
)

router = APIRouter(prefix="/api", tags=["stakeholders"])


# ===== Stakeholders =====

@router.post("/projects/{project_id}/stakeholders", response_model=StakeholderResponse, status_code=201)
def create_stakeholder(
    project_id: int,
    stakeholder: StakeholderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a stakeholder to a project."""
    if not db.query(Project).filter(Project.id == project_id).first():
        raise HTTPException(status_code=404, detail="Project not found")
    db_stakeholder = Stakeholder(project_id=project_id, **stakeholder.model_dump())
    db.add(db_stakeholder)
    db.commit()
    db.refresh(db_stakeholder)
    return db_stakeholder


@router.get("/projects/{project_id}/stakeholders", response_model=List[StakeholderResponse])
def list_stakeholders(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all stakeholders for a project."""
    return db.query(Stakeholder).filter(Stakeholder.project_id == project_id).order_by(Stakeholder.role_name).all()


@router.put("/stakeholders/{stakeholder_id}", response_model=StakeholderResponse)
def update_stakeholder(
    stakeholder_id: int,
    update: StakeholderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a stakeholder."""
    s = db.query(Stakeholder).filter(Stakeholder.id == stakeholder_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Stakeholder not found")
    for field, val in update.model_dump(exclude_unset=True).items():
        setattr(s, field, val)
    db.commit()
    db.refresh(s)
    return s


@router.delete("/stakeholders/{stakeholder_id}", status_code=204)
def delete_stakeholder(
    stakeholder_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a stakeholder."""
    s = db.query(Stakeholder).filter(Stakeholder.id == stakeholder_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Stakeholder not found")
    db.delete(s)
    db.commit()


# ===== Roles =====

@router.get("/roles", response_model=List[RoleResponse])
def list_roles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all RACI roles."""
    return db.query(Role).order_by(Role.id).all()


@router.post("/roles", response_model=RoleResponse, status_code=201)
def create_role(
    role: RoleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new role."""
    if db.query(Role).filter(Role.name == role.name).first():
        raise HTTPException(status_code=400, detail="Role already exists")
    db_role = Role(**role.model_dump())
    db.add(db_role)
    db.commit()
    db.refresh(db_role)
    return db_role


@router.put("/roles/{role_id}", response_model=RoleResponse)
def update_role(
    role_id: int,
    update: RoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a role."""
    r = db.query(Role).filter(Role.id == role_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Role not found")
    for field, val in update.model_dump(exclude_unset=True).items():
        setattr(r, field, val)
    db.commit()
    db.refresh(r)
    return r


@router.delete("/roles/{role_id}", status_code=204)
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a role."""
    r = db.query(Role).filter(Role.id == role_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Role not found")
    db.delete(r)
    db.commit()


# ===== Role Assignments =====

@router.get("/projects/{project_id}/assignments", response_model=List[dict])
def list_assignments(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List role assignments for a project — returns user + role info."""
    assignments = db.query(RoleAssignment).filter(RoleAssignment.project_id == project_id).all()
    result = []
    for a in assignments:
        user = db.query(User).filter(User.id == a.user_id).first()
        role = db.query(Role).filter(Role.id == a.role_id).first()
        result.append({
            "id": a.id,
            "user_id": a.user_id,
            "user_name": user.name if user else "Unknown",
            "user_email": user.email if user else "",
            "role_id": a.role_id,
            "role_name": role.name if role else "Unknown",
            "project_id": a.project_id,
        })
    return result


@router.post("/projects/{project_id}/assignments", status_code=201)
def create_assignment(
    project_id: int,
    assignment: RoleAssignmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Assign a user to a role on a project."""
    if assignment.project_id != project_id:
        raise HTTPException(status_code=400, detail="project_id mismatch")
    existing = db.query(RoleAssignment).filter(
        RoleAssignment.user_id == assignment.user_id,
        RoleAssignment.role_id == assignment.role_id,
        RoleAssignment.project_id == project_id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Assignment already exists")
    db_assignment = RoleAssignment(**assignment.model_dump())
    db.add(db_assignment)
    db.commit()
    db.refresh(db_assignment)
    return {"id": db_assignment.id, "message": "Assignment created"}


@router.delete("/assignments/{assignment_id}", status_code=204)
def delete_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a role assignment."""
    a = db.query(RoleAssignment).filter(RoleAssignment.id == assignment_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Assignment not found")
    db.delete(a)
    db.commit()
