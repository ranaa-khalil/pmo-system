"""Data export service — export all tenant data as JSON (GDPR compliance).

Exports all tenant-scoped data: clients, projects, backlog items, releases,
stakeholders, personas, KPIs, roadmaps, milestones, approvals, forms, etc.
"""
import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog
from app.models.approval import ApprovalRequest, ApprovalStep
from app.models.backlog_item import BacklogItem
from app.models.client import Client
from app.models.form_template import FormInstance, FormTemplate
from app.models.github_board_config import GitHubBoardConfig
from app.models.kpi import KPI
from app.models.milestone import Milestone
from app.models.notification import Notification
from app.models.project import Project
from app.models.project_test_account import ProjectTestAccount
from app.models.project_vision import ProjectVision
from app.models.release import Release, ReleaseItem
from app.models.roadmap import Roadmap
from app.models.stakeholder import Stakeholder
from app.models.tenant import TenantMembership
from app.models.user_persona import UserPersona
from app.models.user_task import UserTask


def _serialize(obj) -> dict:
    """Serialize a SQLAlchemy model instance to a dict."""
    if obj is None:
        return None
    result = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name)
        if isinstance(val, datetime):
            val = val.isoformat()
        result[col.name] = val
    return result


def export_tenant_data(db: Session, tenant_id: int) -> dict:
    """Export all data for a tenant as a JSON-serializable dict."""
    tid = tenant_id

    clients = db.query(Client).filter(Client.tenant_id == tid).all()
    projects = db.query(Project).filter(Project.tenant_id == tid).all()
    backlog = db.query(BacklogItem).filter(BacklogItem.tenant_id == tid).all()
    releases = db.query(Release).filter(Release.tenant_id == tid).all()
    release_items = db.query(ReleaseItem).filter(ReleaseItem.tenant_id == tid).all()
    stakeholders = db.query(Stakeholder).filter(Stakeholder.tenant_id == tid).all()
    personas = db.query(UserPersona).filter(UserPersona.tenant_id == tid).all()
    kpis = db.query(KPI).filter(KPI.tenant_id == tid).all()
    roadmaps = db.query(Roadmap).filter(Roadmap.tenant_id == tid).all()
    milestones = db.query(Milestone).filter(Milestone.tenant_id == tid).all()
    visions = db.query(ProjectVision).filter(ProjectVision.tenant_id == tid).all()
    test_accounts = db.query(ProjectTestAccount).filter(ProjectTestAccount.tenant_id == tid).all()
    approvals = db.query(ApprovalRequest).filter(ApprovalRequest.tenant_id == tid).all()
    approval_steps = db.query(ApprovalStep).filter(ApprovalStep.tenant_id == tid).all()
    form_templates = db.query(FormTemplate).filter(FormTemplate.tenant_id == tid).all()
    form_instances = db.query(FormInstance).filter(FormInstance.tenant_id == tid).all()
    github_configs = db.query(GitHubBoardConfig).filter(GitHubBoardConfig.tenant_id == tid).all()
    tasks = db.query(UserTask).filter(UserTask.tenant_id == tid).all()
    members = db.query(TenantMembership).filter(TenantMembership.tenant_id == tid).all()
    notifications = db.query(Notification).filter(Notification.tenant_id == tid).all()
    activity = db.query(ActivityLog).filter(ActivityLog.tenant_id == tid).all()

    return {
        "exported_at": datetime.utcnow().isoformat(),
        "tenant_id": tid,
        "summary": {
            "clients": len(clients),
            "projects": len(projects),
            "backlog_items": len(backlog),
            "releases": len(releases),
            "stakeholders": len(stakeholders),
            "personas": len(personas),
            "kpis": len(kpis),
            "roadmaps": len(roadmaps),
            "milestones": len(milestones),
            "approvals": len(approvals),
            "form_instances": len(form_instances),
            "user_tasks": len(tasks),
            "members": len(members),
        },
        "clients": [_serialize(c) for c in clients],
        "projects": [_serialize(p) for p in projects],
        "backlog_items": [_serialize(b) for b in backlog],
        "releases": [_serialize(r) for r in releases],
        "release_items": [_serialize(ri) for ri in release_items],
        "stakeholders": [_serialize(s) for s in stakeholders],
        "personas": [_serialize(p) for p in personas],
        "kpis": [_serialize(k) for k in kpis],
        "roadmaps": [_serialize(r) for r in roadmaps],
        "milestones": [_serialize(m) for m in milestones],
        "project_visions": [_serialize(v) for v in visions],
        "test_accounts": [_serialize(t) for t in test_accounts],
        "approval_requests": [_serialize(a) for a in approvals],
        "approval_steps": [_serialize(s) for s in approval_steps],
        "form_templates": [_serialize(t) for t in form_templates],
        "form_instances": [_serialize(f) for f in form_instances],
        "github_configs": [_serialize(g) for g in github_configs],
        "user_tasks": [_serialize(t) for t in tasks],
        "memberships": [_serialize(m) for m in members],
        "notifications": [_serialize(n) for n in notifications],
        "activity_log": [_serialize(a) for a in activity],
    }


def export_project_data(db: Session, tenant_id: int, project_id: int) -> dict:
    """Export a single project's data as JSON."""
    tid = tenant_id
    project = db.query(Project).filter(Project.id == project_id, Project.tenant_id == tid).first()
    if not project:
        return None

    backlog = db.query(BacklogItem).filter(BacklogItem.project_id == project_id, BacklogItem.tenant_id == tid).all()
    releases = db.query(Release).filter(Release.project_id == project_id, Release.tenant_id == tid).all()
    stakeholders = db.query(Stakeholder).filter(Stakeholder.project_id == project_id, Stakeholder.tenant_id == tid).all()
    personas = db.query(UserPersona).filter(UserPersona.project_id == project_id, UserPersona.tenant_id == tid).all()
    kpis = db.query(KPI).filter(KPI.project_id == project_id, KPI.tenant_id == tid).all()
    vision = db.query(ProjectVision).filter(ProjectVision.project_id == project_id, ProjectVision.tenant_id == tid).first()

    return {
        "exported_at": datetime.utcnow().isoformat(),
        "project": _serialize(project),
        "backlog_items": [_serialize(b) for b in backlog],
        "releases": [_serialize(r) for r in releases],
        "stakeholders": [_serialize(s) for s in stakeholders],
        "personas": [_serialize(p) for p in personas],
        "kpis": [_serialize(k) for k in kpis],
        "vision": _serialize(vision) if vision else None,
    }
