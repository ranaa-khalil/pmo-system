"""Import all models so SQLAlchemy registers them with Base.metadata."""
from app.models.client import Client
from app.models.project import Project
from app.models.user import User
from app.models.role import Role
from app.models.role_assignment import RoleAssignment
from app.models.permission import Permission
from app.models.role_permission import RolePermission
from app.models.project_vision import ProjectVision
from app.models.kpi import KPI
from app.models.roadmap import Roadmap
from app.models.milestone import Milestone
from app.models.backlog_item import BacklogItem
from app.models.user_task import UserTask
from app.models.form_template import FormTemplate, FormInstance
from app.models.approval import ApprovalRequest, ApprovalStep
from app.models.stakeholder import Stakeholder
from app.models.release import Release, ReleaseItem
from app.models.user_persona import UserPersona
from app.models.project_test_account import ProjectTestAccount

__all__ = [
    "Client", "Project", "User", "Role", "RoleAssignment",
    "Permission", "RolePermission",
    "ProjectVision", "KPI", "Roadmap", "Milestone", "BacklogItem",
    "UserTask",
    "FormTemplate", "FormInstance",
    "ApprovalRequest", "ApprovalStep",
    "Stakeholder",
    "Release", "ReleaseItem",
    "UserPersona", "ProjectTestAccount",
]
