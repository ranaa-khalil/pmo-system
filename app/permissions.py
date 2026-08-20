"""Permission helpers for hierarchical RBAC.

Hierarchy:
  super_admin → creates clients, assigns Account Managers
  account_manager → creates projects for their clients, assigns Project Managers
  project_manager → manages their projects, assigns team members
  member → works on assigned items
"""
from app.models.user import User
from app.models.client import Client
from app.models.project import Project
from app.models.role_assignment import RoleAssignment
from sqlalchemy.orm import Session


def is_super_admin(user: User) -> bool:
    return user.system_role == "super_admin"


def is_account_manager(user: User) -> bool:
    return user.system_role == "account_manager"


def is_project_manager(user: User) -> bool:
    return user.system_role == "project_manager"


def can_create_client(user: User) -> bool:
    """Only super admins can create clients."""
    return is_super_admin(user)


def can_manage_client(user: User, client: Client) -> bool:
    """Super admin or the assigned account manager."""
    if is_super_admin(user):
        return True
    if is_account_manager(user) and client.account_manager_id == user.id:
        return True
    return False


def can_create_project(user: User, client: Client) -> bool:
    """Super admin or the account manager for this client."""
    return can_manage_client(user, client)


def can_manage_project(user: User, project: Project, db: Session) -> bool:
    """Super admin, the client's AM, or the project's PM."""
    if is_super_admin(user):
        return True
    client = db.query(Client).filter(Client.id == project.client_id).first()
    if client and can_manage_client(user, client):
        return True
    if is_project_manager(user) and project.project_manager_id == user.id:
        return True
    # Also check if user has a role assignment on this project
    assignment = db.query(RoleAssignment).filter(
        RoleAssignment.user_id == user.id,
        RoleAssignment.project_id == project.id,
    ).first()
    return assignment is not None


def get_visible_clients(user: User, db: Session):
    """Return clients the user can see."""
    if is_super_admin(user):
        return db.query(Client).all()
    if is_account_manager(user):
        return db.query(Client).filter(Client.account_manager_id == user.id).all()
    # Members and PMs see clients of projects they're assigned to
    project_ids = db.query(RoleAssignment.project_id).filter(
        RoleAssignment.user_id == user.id
    ).all()
    pids = [p[0] for p in project_ids]
    if not pids:
        return []
    projects = db.query(Project).filter(Project.id.in_(pids)).all()
    client_ids = list(set(p.client_id for p in projects))
    return db.query(Client).filter(Client.id.in_(client_ids)).all()


def get_visible_projects(user: User, db: Session):
    """Return projects the user can see."""
    if is_super_admin(user):
        return db.query(Project).all()
    if is_account_manager(user):
        client_ids = [c.id for c in db.query(Client).filter(
            Client.account_manager_id == user.id
        ).all()]
        if not client_ids:
            return []
        return db.query(Project).filter(Project.client_id.in_(client_ids)).all()
    # PMs and members see projects they're assigned to
    if is_project_manager(user):
        managed = db.query(Project).filter(Project.project_manager_id == user.id).all()
        assigned_ids = [p[0] for p in db.query(RoleAssignment.project_id).filter(
            RoleAssignment.user_id == user.id
        ).all()]
        assigned = db.query(Project).filter(Project.id.in_(assigned_ids)).all() if assigned_ids else []
        # Merge and dedupe
        seen = set()
        result = []
        for p in managed + assigned:
            if p.id not in seen:
                seen.add(p.id)
                result.append(p)
        return result
    # Members
    project_ids = db.query(RoleAssignment.project_id).filter(
        RoleAssignment.user_id == user.id
    ).all()
    pids = [p[0] for p in project_ids]
    if not pids:
        return []
    return db.query(Project).filter(Project.id.in_(pids)).all()
