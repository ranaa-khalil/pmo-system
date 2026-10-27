"""Tests for the Today aggregate + Brief narrative (R1).

/api/today: needs-you aggregation — approvals pending on the user's gates,
blocked items, overdue items, escalated risks. Tenant-scoped, empty-state
shape, capped rows.

/api/projects/{id}/brief: template-based narrative from live data —
deterministic (no LLM in R1).
"""


import pytest

from app.models.approval import ApprovalRequest, ApprovalStep
from app.models.backlog_item import BacklogItem
from app.models.project import Project


@pytest.fixture
def project(db_session, auth_user):
    p = Project(
        tenant_id=auth_user["tenant"].id,
        client_id=auth_user["user"].id,  # NOT NULL FK — tests only need the row
        name="R1 Repro Project",
        status="Active",
    )
    db_session.add(p)
    db_session.commit()
    return p


def _item(db, project, **kw):
    defaults = dict(
        project_id=project.id,
        title=kw.pop("title", "Item"),
        item_type="Feature",
        current_phase=kw.pop("current_phase", "Development"),
        status=kw.pop("status", "In Progress"),
        priority=kw.pop("priority", "Medium"),
        target_release=kw.pop("target_release", "2026-01"),
    )
    defaults.update(kw)
    it = BacklogItem(**defaults)
    db.add(it)
    db.commit()
    return it


def _approval(db, project, user, **kw):
    a = ApprovalRequest(
        tenant_id=project.tenant_id,
        project_id=project.id,
        title=kw.pop("title", "Gate approval"),
        request_type=kw.pop("request_type", "backlog_advance"),
        requested_by=user.id,
        status=kw.pop("status", "Pending"),
        current_step=1,
    )
    db.add(a)
    db.flush()
    step = ApprovalStep(
        request_id=a.id,
        step_order=1,
        role_name="Accountable",
        approver_id=kw.pop("approver_id", user.id),
        status="Pending",
    )
    db.add(step)
    db.commit()
    return a


def test_today_aggregates_needs_you(db_session, auth_user, project):
    from app.services.today import build_today

    user = auth_user["user"]
    _approval(db_session, project, user, title="Waiting on you")
    _item(db_session, project, title="Blocked work", status="Blocked")
    _item(db_session, project, title="Overdue work", status="In Progress", target_release="2026-01")

    data = build_today(db_session, auth_user["tenant"], user)
    kinds = [r["kind"] for r in data["needs_you"]]
    assert "approval" in kinds
    assert "blocked" in kinds
    assert "overdue" in kinds
    assert data["counts"]["approval"] >= 1
    assert data["counts"]["blocked"] >= 1
    assert data["counts"]["overdue"] >= 1
    assert data["briefing"]["verdict"] in ("on_track", "needs_attention", "at_risk")
    assert len(data["briefing"]["lines"]) == 3


def test_today_empty_state(db_session, auth_user, project):
    from app.services.today import build_today

    data = build_today(db_session, auth_user["tenant"], auth_user["user"])
    assert data["needs_you"] == []
    assert data["briefing"]["verdict"] == "on_track"


def test_today_tenant_scoped(db_session, auth_user, project):
    from app.services.today import build_today

    other = Project(
        tenant_id=auth_user["tenant"].id + 999,
        client_id=auth_user["user"].id,
        name="Other",
        status="Active",
    )
    db_session.add(other)
    db_session.commit()
    _item(db_session, other, title="Foreign item", status="Blocked")

    data = build_today(db_session, auth_user["tenant"], auth_user["user"])
    assert all(r["project_id"] != other.id for r in data["needs_you"])


def test_today_rows_capped(db_session, auth_user, project):
    from app.services.today import build_today

    user = auth_user["user"]
    for i in range(12):
        _item(db_session, project, title=f"Blocked {i}", status="Blocked")
    data = build_today(db_session, auth_user["tenant"], user)
    assert len(data["needs_you"]) <= 8


def test_brief_narrative_from_live_data(db_session, auth_user, project):
    from app.services.today import build_brief

    _item(db_session, project, title="Alpha", current_phase="Requirements", status="Done")
    _item(db_session, project, title="Beta", current_phase="Development", status="In Progress")
    _item(db_session, project, title="Gamma", current_phase="Development", status="Blocked")

    brief = build_brief(db_session, project)
    assert "R1 Repro Project" in brief["narrative"]
    assert brief["stats"]["total"] == 3
    assert brief["stats"]["by_phase"].get("Development") == 2
    assert "2 in Development" in brief["narrative"]
    assert "1 blocked" in brief["narrative"]
