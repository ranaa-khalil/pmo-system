"""Stakeholder + Roles API router."""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.client import Client
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


@router.get("/projects/{project_id}/traceability")
def get_traceability(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the full traceability chain: Vision → KPIs → Milestones → Releases → Backlog Items."""
    from app.models.project_vision import ProjectVision
    from app.models.kpi import KPI
    from app.models.roadmap import Roadmap
    from app.models.milestone import Milestone
    from app.models.backlog_item import BacklogItem
    from app.models.release import Release, ReleaseItem

    # Vision
    vision = db.query(ProjectVision).filter(ProjectVision.project_id == project_id).first()
    vision_data = None
    if vision:
        vision_data = {
            "statement": vision.statement,
            "strategic_objectives": vision.strategic_objectives,
        }

    # KPIs (with linked backlog items)
    kpis = db.query(KPI).filter(KPI.project_id == project_id).all()
    kpi_data = []
    for k in kpis:
        linked_items = db.query(BacklogItem).filter(BacklogItem.kpi_id == k.id).all()
        kpi_data.append({
            "id": k.id,
            "name": k.name,
            "target_value": k.target_value,
            "current_value": k.current_value,
            "unit": k.unit,
            "category": k.category,
            "vision_objective": k.vision_objective,
            "backlog_items": [{"id": i.id, "title": i.title, "phase": i.current_phase, "status": i.status} for i in linked_items],
        })

    # Roadmaps → Milestones → Releases
    roadmaps = db.query(Roadmap).filter(Roadmap.project_id == project_id).all()
    roadmap_data = []
    for rm in roadmaps:
        milestones = db.query(Milestone).filter(Milestone.roadmap_id == rm.id).all()
        milestone_list = []
        for ms in milestones:
            linked_releases = db.query(Release).filter(Release.milestone_id == ms.id).all()
            release_list = []
            for rel in linked_releases:
                items = db.query(ReleaseItem).filter(ReleaseItem.release_id == rel.id).all()
                backlog_items = []
                for ri in items:
                    bi = db.query(BacklogItem).filter(BacklogItem.id == ri.backlog_item_id).first()
                    if bi:
                        backlog_items.append({
                            "id": bi.id, "title": bi.title, "phase": bi.current_phase,
                            "status": bi.status, "priority": bi.priority, "kpi_id": bi.kpi_id,
                        })
                release_list.append({
                    "id": rel.id, "version": rel.version, "name": rel.name,
                    "status": rel.status, "target_date": rel.target_date,
                    "items": backlog_items,
                })
            milestone_list.append({
                "id": ms.id, "title": ms.title, "target_date": str(ms.target_date) if ms.target_date else None,
                "status": ms.status, "releases": release_list,
            })
        roadmap_data.append({
            "id": rm.id, "title": rm.title,
            "start_date": str(rm.start_date) if rm.start_date else None,
            "end_date": str(rm.end_date) if rm.end_date else None,
            "milestones": milestone_list,
        })

    # Unlinked backlog items (no KPI)
    unlinked = db.query(BacklogItem).filter(
        BacklogItem.project_id == project_id, BacklogItem.kpi_id.is_(None)
    ).all()
    unlinked_data = [{"id": i.id, "title": i.title, "phase": i.current_phase, "status": i.status, "priority": i.priority} for i in unlinked]

    # Unlinked releases (no milestone)
    unlinked_releases = db.query(Release).filter(
        Release.project_id == project_id, Release.milestone_id.is_(None)
    ).all()
    unlinked_rel_data = [{"id": r.id, "version": r.version, "name": r.name, "status": r.status, "target_date": r.target_date} for r in unlinked_releases]

    return {
        "vision": vision_data,
        "kpis": kpi_data,
        "roadmaps": roadmap_data,
        "unlinked_backlog": unlinked_data,
        "unlinked_releases": unlinked_rel_data,
    }


# ===== User Management (Super Admin) =====

@router.get("/users", response_model=List[dict])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all users (super admin only)."""
    users = db.query(User).order_by(User.created_at.desc()).all()
    result = []
    for u in users:
        assignments = db.query(RoleAssignment).filter(RoleAssignment.user_id == u.id).all()
        roles = []
        for a in assignments:
            role = db.query(Role).filter(Role.id == a.role_id).first()
            if role:
                roles.append({"role": role.name, "project_id": a.project_id})
        # Find managed clients and projects
        managed_clients = db.query(Client).filter(Client.account_manager_id == u.id).all()
        managed_projects = db.query(Project).filter(Project.project_manager_id == u.id).all()
        result.append({
            "id": u.id,
            "email": u.email,
            "name": u.name,
            "system_role": u.system_role,
            "is_active": u.is_active,
            "created_at": str(u.created_at) if u.created_at else None,
            "roles": roles,
            "managed_clients": [{"id": c.id, "name": c.name} for c in managed_clients],
            "managed_projects": [{"id": p.id, "name": p.name} for p in managed_projects],
        })
    return result


@router.post("/users", status_code=201)
def create_user(
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new user (super admin only)."""
    from app.services.auth import hash_password
    email = data.get("email")
    name = data.get("name")
    password = data.get("password")
    system_role = data.get("system_role", "member")
    if not email or not name or not password:
        raise HTTPException(status_code=400, detail="email, name, and password are required")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(email=email, name=name, hashed_password=hash_password(password), system_role=system_role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "email": user.email, "name": user.name, "system_role": user.system_role, "message": "User created"}


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a user (super admin only)."""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()
