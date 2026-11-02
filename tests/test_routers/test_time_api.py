"""Tests for time tracking — manual hours log + timesheet lock (Q1).

Members log their own hours; PM/tenant-admin can log for others, lock weeks,
and delete anyone's entries. The approval-locks-timesheet invariant: a locked
week rejects create/delete for that user's entries.
"""
import pytest

import app.models  # noqa: F401
from app.models.project import Project
from app.models.tenant import Tenant, TenantMembership
from app.models.time_entry import TimeEntry, TimesheetLock
from app.models.user import User


@pytest.fixture()
def time_world(client, db):
    """PM + member with a project."""
    tenant = Tenant(name="Time Co", slug="time-co", plan="enterprise")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    pm = User(email="pm-time@copilot.test", name="PM", hashed_password="x",
              system_role="project_manager")
    member = User(email="member-time@copilot.test", name="Member", hashed_password="x")
    db.add_all([pm, member])
    db.commit()
    db.refresh(pm)
    db.refresh(member)
    for u, role in [(pm, "owner"), (member, "member")]:
        db.add(TenantMembership(user_id=u.id, tenant_id=tenant.id, role=role))
        u.active_tenant_id = tenant.id
    db.commit()
    project = Project(name="Time Proj", client_id=1, tenant_id=tenant.id, project_manager_id=pm.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return {"tenant": tenant, "pm": pm, "member": member, "project": project}


def _as(client, user):
    from app.services.auth import create_access_token
    client.headers.update({"Authorization": f"Bearer {create_access_token(data={'sub': str(user.id)})}"})


def test_member_logs_own_hours(time_world, client):
    member, project = time_world["member"], time_world["project"]
    _as(client, member)
    resp = client.post(f"/api/projects/{project.id}/time-entries", json={
        "entry_date": "2026-11-02", "hours": 3.5, "note": "API work",
    })
    assert resp.status_code == 201
    row = resp.json()
    assert row["hours"] == 3.5
    assert row["user_id"] == member.id


def test_member_cannot_log_for_others(time_world, client):
    member, pm, project = time_world["member"], time_world["pm"], time_world["project"]
    _as(client, member)
    resp = client.post(f"/api/projects/{project.id}/time-entries", json={
        "entry_date": "2026-11-02", "hours": 2, "user_id": pm.id,
    })
    assert resp.status_code == 403


def test_pm_logs_for_member(time_world, client):
    pm, member, project = time_world["pm"], time_world["member"], time_world["project"]
    _as(client, pm)
    resp = client.post(f"/api/projects/{project.id}/time-entries", json={
        "entry_date": "2026-11-02", "hours": 5, "user_id": member.id, "note": "Review",
    })
    assert resp.status_code == 201
    assert resp.json()["user_id"] == member.id


def test_locked_week_rejects_create(time_world, client):
    member, project = time_world["member"], time_world["project"]
    _as(client, member)
    client.post(f"/api/projects/{project.id}/time-entries", json={
        "entry_date": "2026-11-02", "hours": 2,
    })
    # PM locks the member's week
    _as(client, time_world["pm"])
    lock = client.post(f"/api/projects/{project.id}/timesheets/lock", json={
        "user_id": member.id, "week_start": "2026-11-02",
    })
    assert lock.status_code == 201
    # Member can no longer add to that week
    _as(client, member)
    resp = client.post(f"/api/projects/{project.id}/time-entries", json={
        "entry_date": "2026-11-04", "hours": 1,
    })
    assert resp.status_code == 409


def test_locked_week_rejects_delete(time_world, client, db):
    member, project = time_world["member"], time_world["project"]
    _as(client, member)
    entry = client.post(f"/api/projects/{project.id}/time-entries", json={
        "entry_date": "2026-11-02", "hours": 2,
    }).json()
    _as(client, time_world["pm"])
    client.post(f"/api/projects/{project.id}/timesheets/lock", json={
        "user_id": member.id, "week_start": "2026-11-02",
    })
    _as(client, member)
    resp = client.delete(f"/api/time-entries/{entry['id']}")
    assert resp.status_code == 409


def test_unlock_restores_write_access(time_world, client):
    member, project = time_world["member"], time_world["project"]
    _as(client, time_world["pm"])
    client.post(f"/api/projects/{project.id}/timesheets/lock", json={
        "user_id": member.id, "week_start": "2026-11-02",
    })
    resp = client.delete(
        f"/api/projects/{project.id}/timesheets/lock?user_id={member.id}&week_start=2026-11-02"
    )
    assert resp.status_code == 204
    _as(client, member)
    ok = client.post(f"/api/projects/{project.id}/time-entries", json={
        "entry_date": "2026-11-03", "hours": 1,
    })
    assert ok.status_code == 201


def test_member_cannot_lock_timesheets(time_world, client):
    member, project = time_world["member"], time_world["project"]
    _as(client, member)
    resp = client.post(f"/api/projects/{project.id}/timesheets/lock", json={
        "user_id": member.id, "week_start": "2026-11-02",
    })
    assert resp.status_code == 403


def test_time_summary_totals(time_world, client):
    member, project = time_world["member"], time_world["project"]
    _as(client, member)
    client.post(f"/api/projects/{project.id}/time-entries", json={
        "entry_date": "2026-11-02", "hours": 3,
    })
    client.post(f"/api/projects/{project.id}/time-entries", json={
        "entry_date": "2026-10-20", "hours": 2,
    })
    _as(client, time_world["pm"])
    resp = client.get(f"/api/projects/{project.id}/time-summary")
    assert resp.status_code == 200
    rows = {r["user_id"]: r for r in resp.json()}
    assert rows[member.id]["total_hours"] == 5.0
    assert rows[member.id]["week_hours"] == 3.0


def test_entry_requires_valid_hours(time_world, client):
    member, project = time_world["member"], time_world["project"]
    _as(client, member)
    resp = client.post(f"/api/projects/{project.id}/time-entries", json={
        "entry_date": "2026-11-02", "hours": 0,
    })
    assert resp.status_code == 422
