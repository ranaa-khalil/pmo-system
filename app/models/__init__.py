"""Import all models so SQLAlchemy registers them with Base.metadata."""
from app.models.activity_log import ActivityLog
from app.models.approval import ApprovalRequest, ApprovalStep
from app.models.backlog_item import BacklogItem
from app.models.client import Client
from app.models.form_template import FormInstance, FormTemplate
from app.models.github_board_config import GitHubBoardConfig
from app.models.infrastructure import (
    Asset,
    Environment,
    InfraDatabase,
    InfraService,
    Secret,
    SecretAccessLog,
    SecretVersion,
)
from app.models.kpi import KPI
from app.models.milestone import Milestone
from app.models.notification import Notification, NotificationPreference
from app.models.permission import Permission
from app.models.plan import Plan
from app.models.password_reset_token import PasswordResetToken
from app.models.project import Project
from app.models.project_test_account import ProjectTestAccount
from app.models.project_vision import ProjectVision
from app.models.release import Release, ReleaseItem
from app.models.roadmap import Roadmap
from app.models.role import Role
from app.models.role_assignment import RoleAssignment
from app.models.role_permission import RolePermission
from app.models.stakeholder import Stakeholder
from app.models.tenant import Invitation, Tenant, TenantMembership
from app.models.tenant_setting import TenantSetting
from app.models.usage_record import UsageRecord
from app.models.api_key import ApiKey
from app.models.user import User
from app.models.user_persona import UserPersona
from app.models.user_task import UserTask

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
    "Notification", "NotificationPreference",
    "ActivityLog",
    "GitHubBoardConfig",
    "Tenant", "TenantMembership", "Invitation",
    "TenantSetting",
    "UsageRecord",
    "ApiKey",
    "Plan",
    "Environment", "Secret", "SecretVersion", "SecretAccessLog",
    "Asset", "InfraService", "InfraDatabase",
    "PasswordResetToken",
]
