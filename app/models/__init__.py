"""Import all models so SQLAlchemy registers them with Base.metadata."""
from app.models.client import Client
from app.models.project import Project
from app.models.user import User
from app.models.role import Role
from app.models.role_assignment import RoleAssignment

__all__ = ["Client", "Project", "User", "Role", "RoleAssignment"]
