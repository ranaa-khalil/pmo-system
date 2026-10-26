"""Tests for BRD depth (P4.3): requirements → epics → features coverage.

build_brd_coverage(db, tenant, project) walks the traceability chain from the
project's intake-sourced requirements (epic groups of backlog items) to the
backlog items they produced, and reports which requirements have no backlog
items (gaps) plus which items trace back to no intake source.
"""
import json

from app.models.backlog_item import BacklogItem
from app.services.brd import build_brd_coverage


def _world(db):
    from app.models.tenant import Tenant

    tenant = Tenant(name="BRD Tenant", slug="brd-tenant", plan="enterprise", status="active")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    project = Project = None
    from app.models.project import Project as P
    project = P(name="BRD Project", client_id=1, tenant_id=tenant.id, status="Active")
    db.add(project)
    db.commit()
    db.refresh(project)
    return tenant, project


def test_coverage_reports_gaps_and_traced(db, auth_user):
    """Epics with items → traced; requirement with no items → gap."""
    tenant, project = _world(db)
    # Epic "Onboarding" has 2 features (both intake-sourced)
    for title in ("SSO login", "Course browse"):
        db.add(BacklogItem(
            tenant_id=tenant.id, project_id=project.id, title=title,
            epic="Onboarding", status="Draft", current_phase="Requirements",
            description="[Source: Intake draft #1 — AI-structured kickoff]",
        ))
    # Epic "Reporting" has NO items → coverage gap
    db.add(BacklogItem(
        tenant_id=tenant.id, project_id=project.id, title="Manual entry (no source)",
        epic="Ad-hoc", status="Draft", current_phase="Requirements",
        description="Hand-added, no intake source",
    ))
    db.commit()

    brd = build_brd_coverage(db, tenant, project)
    epics = {e["epic"]: e for e in brd["epics"]}
    assert epics["Onboarding"]["feature_count"] == 2
    assert epics["Onboarding"]["traced"] is True
    # Ad-hoc has an item but no intake source → untraced item
    assert epics["Ad-hoc"]["traced"] is False
    assert brd["summary"]["total_items"] == 3
    assert brd["summary"]["untraced_items"] == 1


def test_empty_project_returns_empty_coverage(db, auth_user):
    tenant, project = _world(db)
    brd = build_brd_coverage(db, tenant, project)
    assert brd["epics"] == []
    assert brd["summary"]["total_items"] == 0


def test_coverage_detects_requirement_gaps(db, auth_user):
    """An epic whose items were all deleted (or never created) → requirement gap.

    Modeled as: the draft promised epics that have zero items in this project —
    the coverage report surfaces them as requirement_gaps via the stored draft.
    """
    tenant, project = _world(db)
    # Simulate an applied intake draft record (AiInteraction kind=intake)
    from app.models.ai_interaction import AiInteraction
    from app.models.user import User

    user = User(
        email="brd@pmo.test", name="BRD User", hashed_password="x",
        system_role="tenant_admin", active_tenant_id=tenant.id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    draft = {
        "summary": "Student platform",
        "epics": [
            {"name": "Onboarding", "features": [{"title": "SSO login", "description": "Login"}]},
            {"name": "Analytics", "features": [{"title": "Dashboards", "description": "Charts"}]},
        ],
        "personas": [], "kpis": [], "assumptions": [],
        "draft_id": 7,
    }
    db.add(AiInteraction(
        tenant_id=tenant.id, user_id=user.id, project_id=project.id,
        kind="intake", question="kickoff",
        answer=json.dumps(draft),  # the draft tree lives in `answer` (real flow)
        status="applied",
    ))
    db.commit()

    # Only the Onboarding feature was actually created
    db.add(BacklogItem(
        tenant_id=tenant.id, project_id=project.id, title="SSO login",
        epic="Onboarding", status="Draft", current_phase="Requirements",
        description="[Source: Intake draft #7]",
    ))
    db.commit()

    brd = build_brd_coverage(db, tenant, project)
    # "Analytics" was promised by the draft but has no items → requirement gap
    assert "Analytics" in [g["epic"] for g in brd["requirement_gaps"]]
    assert brd["summary"]["promised_epics"] == 2
