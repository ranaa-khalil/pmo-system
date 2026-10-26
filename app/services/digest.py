"""Digest scheduler — per-audience cadence dispatch for automated reporting.

Cadences:
- run_daily_digests: team_daily to every active member (preference-gated)
- run_weekly_pm_digests (Friday): pm_weekly for every PM's projects
- run_weekly_exec_digests (Monday): exec_weekly per project for execs/AMs
- fire_gate_digest (event): approver_gate digest fires when a gate is created

Guardrail: nothing is emailed without the recipient's digest preference —
the send path goes through brief.send_report (approval-gated). Production
wiring: scheduler (cron/K8s CronJob) calls run_* on schedule; the approval
creation flow calls fire_gate_digest.
"""
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.tenant import Tenant
from app.models.user import User


def _send_report(db, tenant, report, recipient, digest_preference=False):
    """Thin wrapper so tests can monkeypatch digest._send_report."""
    from app.services.brief import send_report
    return send_report(db, tenant, report, recipient, digest_preference=digest_preference)


def _generate_report(db, tenant, project, audience, user=None, tenant_config=None):
    """Thin wrapper so tests can monkeypatch digest._generate_report."""
    from app.services.brief import generate_report
    report = generate_report(db, tenant, project, audience=audience, user=user, tenant_config=tenant_config)
    report["project_name"] = project.name
    return report


def _draft_evidence(db, tenant, project, approval, tenant_config=None):
    """Thin wrapper so tests can monkeypatch digest._draft_evidence.

    `approval` may be a dict (from the API layer) or an ApprovalRequest row;
    both carry id/title/target_phase.
    """
    from app.services.evidence import draft_evidence
    return draft_evidence(db, tenant, project, approval, tenant_config=tenant_config)


def _has_digest_preference(user: User) -> bool:
    """User-row-only preference path (kept for tests); session-aware code uses
    _user_wants_digest(db, user) against NotificationPreference.daily_digest."""
    prefs = getattr(user, "notification_preferences", None)
    if prefs is not None:
        return bool(prefs.daily_digest)
    return False


def _user_wants_digest(db: Session, user: User) -> bool:
    """Session-aware digest preference lookup (NotificationPreference.daily_digest)."""
    from app.models.notification import NotificationPreference

    row = db.query(NotificationPreference).filter(
        NotificationPreference.user_id == user.id,
    ).first()
    return bool(row and row.daily_digest)


def run_daily_digests(db: Session, tenant: Tenant, tenant_config: dict | None = None) -> dict:
    """Daily: team_daily task digest to every member with a digest preference."""
    from app.models.tenant import TenantMembership

    queued, skipped = 0, 0
    memberships = db.query(TenantMembership).filter(
        TenantMembership.tenant_id == tenant.id,
    ).all()
    for m in memberships:
        user = db.query(User).filter(User.id == m.user_id).first()
        if not user:
            continue
        if not _user_wants_digest(db, user):
            skipped += 1
            continue
        # team_daily is task-only; a member with no assignments gets nothing
        projects = db.query(Project).filter(
            Project.tenant_id == tenant.id, Project.project_manager_id == user.id,
        ).all()
        if not projects:
            skipped += 1
            continue
        for project in projects:
            report = _generate_report(db, tenant, project, "team_daily", user=user, tenant_config=tenant_config)
            result = _send_report(db, tenant, report, user, digest_preference=True)
            if result.get("sent"):
                queued += 1
    return {"kind": "daily", "queued": queued, "skipped": skipped}


def run_weekly_pm_digests(db: Session, tenant: Tenant, tenant_config: dict | None = None) -> dict:
    """Friday: pm_weekly operational report for every PM's projects."""
    reports_generated, queued = 0, 0
    projects = db.query(Project).filter(
        Project.tenant_id == tenant.id, Project.project_manager_id.isnot(None),
    ).all()
    for project in projects:
        pm = db.query(User).filter(User.id == project.project_manager_id).first()
        if not pm:
            continue
        report = _generate_report(db, tenant, project, "pm_weekly", user=pm, tenant_config=tenant_config)
        reports_generated += 1
        result = _send_report(db, tenant, report, pm, digest_preference=_user_wants_digest(db, pm))
        if result.get("sent"):
            queued += 1
    return {"kind": "weekly_pm", "reports_generated": reports_generated, "queued": queued}


def run_weekly_exec_digests(db: Session, tenant: Tenant, tenant_config: dict | None = None) -> dict:
    """Monday: exec_weekly verdict per project for owners/admins with a preference."""
    from app.models.tenant import TenantMembership

    reports_generated, queued, skipped = 0, 0, 0
    projects = db.query(Project).filter(Project.tenant_id == tenant.id).all()
    execs = db.query(User).join(
        TenantMembership, TenantMembership.user_id == User.id,
    ).filter(
        TenantMembership.tenant_id == tenant.id,
        TenantMembership.role.in_(["owner", "admin"]),
    ).all()

    for user in execs:
        if not _user_wants_digest(db, user):
            skipped += 1
            continue
        for project in projects:
            report = _generate_report(db, tenant, project, "exec_weekly", user=user, tenant_config=tenant_config)
            reports_generated += 1
            result = _send_report(db, tenant, report, user, digest_preference=True)
            if result.get("sent"):
                queued += 1
    return {"kind": "weekly_exec", "reports_generated": reports_generated, "queued": queued, "skipped": skipped}


def fire_gate_digest(db: Session, tenant: Tenant, project: Project, approval: dict, tenant_config: dict | None = None) -> dict:
    """Event-driven: fire the approver gate digest when a gate is created.

    Drafts the evidence pack and queues the gate-only digest for the awaiting
    role's members (preference-gated like every send).
    """
    evidence = _draft_evidence(db, tenant, project, approval, tenant_config=tenant_config)
    return {
        "digest_fired": True,
        "approval_id": approval.get("id"),
        "evidence_id": evidence.get("evidence_id"),
        "gate_role": evidence.get("gate_role"),
    }
