"""Import all models so SQLAlchemy registers them with Base.metadata."""
from app.models.activity_log import ActivityLog
from app.models.ai_interaction import AiInteraction
from app.models.api_key import ApiKey
from app.models.approval import ApprovalRequest, ApprovalStep
from app.models.artifact_chain import ArtifactChain
from app.models.automation_rule import AutomationRule
from app.models.backlog_item import BacklogItem
from app.models.client import Client
from app.models.form_template import FormInstance, FormTemplate
from app.models.github_board_config import GitHubBoardConfig
from app.models.guest_link import ApprovalGuestDecision, ApprovalGuestLink
from app.models.infrastructure import (
    Asset,
    Environment,
    InfraDatabase,
    InfraService,
    Secret,
    SecretAccessLog,
    SecretVersion,
)
from app.models.item_type import ItemType
from app.models.kpi import KPI
from app.models.kpi_history import KpiHistory
from app.models.lifecycle_template import TenantLifecycleTemplate
from app.models.milestone import Milestone
from app.models.notification import Notification, NotificationPreference
from app.models.password_reset_token import PasswordResetToken
from app.models.permission import Permission
from app.models.plan import Plan
from app.models.project import Project
from app.models.project_test_account import ProjectTestAccount
from app.models.project_view import ProjectView
from app.models.project_vision import ProjectVision
from app.models.proof import ItemProof
from app.models.slack_config import SlackConfig
from app.models.release import Release, ReleaseItem
from app.models.risk import Risk
from app.models.roadmap import Roadmap
from app.models.role import Role
from app.models.role_assignment import RoleAssignment
from app.models.role_permission import RolePermission
from app.models.share_link import ShareLink
from app.models.stakeholder import Stakeholder
from app.models.time_entry import TimeEntry, TimesheetLock
from app.models.tag import Tag
from app.models.tenant import Invitation, Tenant, TenantMembership
from app.models.tenant_setting import TenantSetting
from app.models.usage_record import UsageRecord
from app.models.user import User
from app.models.user_persona import UserPersona
from app.models.user_preference import UserPreference
from app.models.user_task import UserTask

__all__ = [
    "AiInteraction",
    "ArtifactChain",
    "Client", "Project", "User", "Role", "RoleAssignment",
    "Permission", "RolePermission",
    "ProjectView",
    "ProjectVision", "KPI", "Roadmap", "Milestone", "BacklogItem",
    "TenantLifecycleTemplate",
    "UserTask",
    "FormTemplate", "FormInstance",
    "ApprovalRequest", "ApprovalStep",
    "AutomationRule",
    "Stakeholder",
    "Release",
    "SlackConfig", "ReleaseItem", "Risk",
    "UserPersona", "ProjectTestAccount",
    "Notification", "NotificationPreference",
    "ActivityLog",
    "GitHubBoardConfig",
    "Tenant", "TenantMembership", "Invitation",
    "TenantSetting",
    "Tag",
    "TimeEntry",
    "TimesheetLock",
    "ShareLink",
    "ItemType",
    "ItemProof",
    "ApprovalGuestLink",
    "ApprovalGuestDecision",
    "UsageRecord",
    "UserPreference",
    "ApiKey",
    "Plan",
    "Environment", "Secret", "SecretVersion", "SecretAccessLog",
    "Asset", "InfraService", "InfraDatabase",
    "PasswordResetToken",
]
