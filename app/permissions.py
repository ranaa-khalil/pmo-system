"""Permission helpers for hierarchical RBAC.

Two-layer permission system:
1. System role (user.system_role): super_admin, account_manager, project_manager, member
2. Tenant role (TenantMembership.role): owner, admin, member

Tenant owners and admins have full super_admin-level permissions WITHIN their tenant.
Super admins (system_role) have global access across all tenants.

Hierarchy within a tenant:
  owner/admin → full access (create clients, projects, users, delete, manage everything)
  account_manager → creates projects for their clients, assigns Project Managers
  project_manager → manages their projects, assigns team members
  member → works on assigned items
"""
from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.project import Project
from app.models.role_assignment import RoleAssignment
from app.models.tenant import TenantMembership
from app.models.user import User


def get_tenant_role(user: User, db: Session) -> str:
    """Get the user's role within their active tenant."""
    if not user.active_tenant_id:
        return "member"
    membership = db.query(TenantMembership).filter(
        TenantMembership.user_id == user.id,
        TenantMembership.tenant_id == user.active_tenant_id,
    ).first()
    return membership.role if membership else "member"


def is_super_admin(user: User) -> bool:
    """System-level super admin (global, across all tenants)."""
    return user.system_role == "super_admin"


def is_tenant_admin_or_owner(user: User, db: Session) -> bool:
    """Tenant-level admin or owner — has full permissions within their tenant."""
    role = get_tenant_role(user, db)
    return role in ("owner", "admin")


def is_account_manager(user: User) -> bool:
    return user.system_role == "account_manager"


def is_project_manager(user: User) -> bool:
    return user.system_role == "project_manager"


def is_tenant_admin(user: User, db: Session) -> bool:
    """Check if user is either system super_admin OR tenant owner/admin.

    This is the core permission check — tenant owners and admins have
    the same capabilities as super admins within their tenant.
    """
    if is_super_admin(user):
        return True
    return is_tenant_admin_or_owner(user, db)


def can_create_client(user: User, db: Session) -> bool:
    """Super admin, tenant owner, or tenant admin can create clients."""
    return is_tenant_admin(user, db)


def can_manage_client(user: User, client: Client, db: Session) -> bool:
    """Super admin, tenant owner/admin, or the assigned account manager."""
    if is_tenant_admin(user, db):
        return True
    if is_account_manager(user) and client.account_manager_id == user.id:
        return True
    return False


def can_create_project(user: User, client: Client, db: Session) -> bool:
    """Super admin, tenant owner/admin, or the account manager for this client."""
    return can_manage_client(user, client, db)


def can_manage_project(user: User, project: Project, db: Session) -> bool:
    """Super admin, tenant owner/admin, the client's AM, or the project's PM."""
    if is_tenant_admin(user, db):
        return True
    client = db.query(Client).filter(Client.id == project.client_id).first()
    if client and can_manage_client(user, client, db):
        return True
    if is_project_manager(user) and project.project_manager_id == user.id:
        return True
    # Also check if user has a role assignment on this project
    assignment = db.query(RoleAssignment).filter(
        RoleAssignment.user_id == user.id,
        RoleAssignment.project_id == project.id,
    ).first()
    return assignment is not None


def can_create_user(user: User, db: Session) -> bool:
    """Super admin, tenant owner/admin, account manager, or project manager can create users."""
    if is_tenant_admin(user, db):
        return True
    return user.system_role in ("account_manager", "project_manager")


def can_delete_user(user: User, target_user: User, db: Session) -> bool:
    """Super admin can delete anyone. Tenant admin/owner can delete non-super_admins in their tenant."""
    if user.system_role == "super_admin":
        return True
    if target_user.system_role == "super_admin":
        return False
    if is_tenant_admin(user, db):
        return True
    if user.system_role == "account_manager":
        return True
    if user.system_role == "project_manager" and target_user.system_role == "member":
        return True
    return False


def can_set_system_role(user: User, target_role: str, db: Session) -> bool:
    """What system_role can this user assign to a new/updated user?

    super_admin → any role
    tenant owner/admin → any role within their tenant
    account_manager → member, project_manager, account_manager
    project_manager → member only
    """
    if is_tenant_admin(user, db):
        return True
    if user.system_role == "account_manager":
        return target_role in ("member", "project_manager", "account_manager")
    if user.system_role == "project_manager":
        return target_role == "member"
    return False


def can_assign_am(user: User, client: Client, db: Session) -> bool:
    """Super admin, tenant owner/admin, or the AM assigned to this client."""
    if is_tenant_admin(user, db):
        return True
    if is_account_manager(user) and client.account_manager_id == user.id:
        return True
    return False


def can_assign_pm(user: User, project: Project, db: Session) -> bool:
    """Super admin, tenant owner/admin, the client's AM, or the project's PM."""
    return can_manage_project(user, project, db)


def can_assign_role(user: User, project: Project, db: Session) -> bool:
    """Super admin, tenant owner/admin, AM for this client, or PM for this project."""
    return can_manage_project(user, project, db)


def can_manage_stakeholders(user: User, project: Project, db: Session) -> bool:
    """Super admin, tenant owner/admin, AM, or PM can add stakeholders."""
    return can_manage_project(user, project, db)


def can_list_users(user: User) -> bool:
    """Any authenticated user can list users (for dropdowns)."""
    return True


def get_visible_clients(user: User, db: Session, tenant_id: int | None = None):
    """Return clients the user can see (optionally filtered by tenant)."""
    if is_tenant_admin(user, db):
        q = db.query(Client)
        if tenant_id:
            q = q.filter(Client.tenant_id == tenant_id)
        return q.all()
    if is_account_manager(user):
        q = db.query(Client).filter(Client.account_manager_id == user.id)
        if tenant_id:
            q = q.filter(Client.tenant_id == tenant_id)
        return q.all()
    # Members and PMs see clients of projects they're assigned to
    project_ids = db.query(RoleAssignment.project_id).filter(
        RoleAssignment.user_id == user.id
    ).all()
    pids = [p[0] for p in project_ids]
    if not pids:
        return []
    projects = db.query(Project).filter(Project.id.in_(pids))
    if tenant_id:
        projects = projects.filter(Project.tenant_id == tenant_id)
    projects = projects.all()
    client_ids = list(set(p.client_id for p in projects))
    return db.query(Client).filter(Client.id.in_(client_ids)).all()


def get_visible_projects(user: User, db: Session, tenant_id: int | None = None):
    """Return projects the user can see (optionally filtered by tenant)."""
    if is_tenant_admin(user, db):
        q = db.query(Project)
        if tenant_id:
            q = q.filter(Project.tenant_id == tenant_id)
        return q.all()
    if is_account_manager(user):
        q = db.query(Client).filter(Client.account_manager_id == user.id)
        if tenant_id:
            q = q.filter(Client.tenant_id == tenant_id)
        client_ids = [c.id for c in q.all()]
        if not client_ids:
            return []
        pq = db.query(Project).filter(Project.client_id.in_(client_ids))
        if tenant_id:
            pq = pq.filter(Project.tenant_id == tenant_id)
        return pq.all()
    # PMs and members see projects they're assigned to
    if is_project_manager(user):
        q = db.query(Project).filter(Project.project_manager_id == user.id)
        if tenant_id:
            q = q.filter(Project.tenant_id == tenant_id)
        managed = q.all()
        assigned_ids = [p[0] for p in db.query(RoleAssignment.project_id).filter(
            RoleAssignment.user_id == user.id
        ).all()]
        if assigned_ids:
            aq = db.query(Project).filter(Project.id.in_(assigned_ids))
            if tenant_id:
                aq = aq.filter(Project.tenant_id == tenant_id)
            assigned = aq.all()
        else:
            assigned = []
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
    q = db.query(Project).filter(Project.id.in_(pids))
    if tenant_id:
        q = q.filter(Project.tenant_id == tenant_id)
    return q.all()
