"""Tests for the notifications router — in-app notifications, preferences, activity, exports.

Notifications are user+tenant scoped: the list only shows the current user's
rows, marking read is scoped to the owner, and CSV exports use query-param
token auth. The project health endpoint computes a composite 0-100 score.
"""
import pytest

import app.models  # noqa: F401
from app.models.backlog_item import BacklogItem
from app.models.kpi import KPI
from app.models.notification import Notification
from app.models.project import Project
from app.models.user import User
from app.models.user_task import UserTask
from app.services.auth import create_access_token


@pytest.fixture()
def notif_world(client, db, auth_user):
    """The shared user with 2 notifications (1 unread) + another user's notification."""
    tenant = auth_user["tenant"]
    user = auth_user["user"]
    db.add(Notification(tenant_id=tenant.id, user_id=user.id, type="approval_request", title="Approve me", read=False))
    db.add(Notification(tenant_id=tenant.id, user_id=user.id, type="release_advanced", title="Released", read=True))
    # Someone else's notification — must never leak
    other_user = User(email="other@notif.example.com", name="Other", hashed_password="x", system_role="member", active_tenant_id=tenant.id)
    db.add(other_user)
    db.commit()
    db.refresh(other_user)
    db.add(Notification(tenant_id=tenant.id, user_id=other_user.id, type="task_due", title="Not yours"))
    db.commit()
    return {"tenant": tenant, "user": user, "other_user": other_user}


def test_list_notifications_scoped_to_user(notif_world, client):
    resp = client.get("/api/notifications")
    assert resp.status_code == 200
    data = resp.json()
    titles = [n["title"] for n in data["notifications"]]
    assert "Approve me" in titles and "Released" in titles
    assert "Not yours" not in titles
    assert data["unread_count"] == 1


def test_list_notifications_unread_only(notif_world, client):
    resp = client.get("/api/notifications?unread_only=true")
    assert resp.status_code == 200
    rows = resp.json()["notifications"]
    assert len(rows) == 1
    assert rows[0]["title"] == "Approve me"


def test_mark_notification_read(notif_world, client, db):
    notif = db.query(Notification).filter(Notification.title == "Approve me").first()
    resp = client.put(f"/api/notifications/{notif.id}/read")
    assert resp.status_code == 200
    db.refresh(notif)
    assert notif.read is True
    assert client.get("/api/notifications").json()["unread_count"] == 0


def test_mark_all_read(notif_world, client):
    resp = client.put("/api/notifications/read-all")
    assert resp.status_code == 200
    assert client.get("/api/notifications").json()["unread_count"] == 0


def test_delete_notification(notif_world, client, db):
    notif = db.query(Notification).filter(Notification.title == "Approve me").first()
    resp = client.delete(f"/api/notifications/{notif.id}")
    assert resp.status_code == 200
    assert db.query(Notification).filter(Notification.id == notif.id).first() is None


def test_notification_preferences_roundtrip(notif_world, client):
    prefs = client.get("/api/notifications/preferences").json()
    assert prefs["email_enabled"] is True  # defaults
    resp = client.put("/api/notifications/preferences", json={"daily_digest": False, "digest_time": "08:00"})
    assert resp.status_code == 200
    prefs2 = client.get("/api/notifications/preferences").json()
    assert prefs2["daily_digest"] is False
    assert prefs2["digest_time"] == "08:00"


def test_export_backlog_csv_query_token_auth(notif_world, client, db, auth_user):
    """CSV export authenticates via ?token= (query param), not the header."""
    project = Project(name="Export P", client_id=1, tenant_id=notif_world["tenant"].id)
    db.add(project)
    db.commit()
    db.refresh(project)
    db.add(BacklogItem(tenant_id=notif_world["tenant"].id, project_id=project.id, title="Row A", current_phase="Requirements"))
    db.commit()

    # No token → 401
    assert client.get(f"/api/export/backlog/{project.id}").status_code == 401

    token = create_access_token({"sub": str(auth_user["user"].id)})
    resp = client.get(f"/api/export/backlog/{project.id}?token={token}")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "Row A" in resp.text


def test_export_tasks_csv(notif_world, client, auth_user, db):
    db_task = UserTask(tenant_id=notif_world["tenant"].id, title="Do thing", assigned_to=auth_user["user"].id)
    db.add(db_task)
    db.commit()
    resp = client.get(f"/api/export/tasks?token={create_access_token({'sub': str(auth_user['user'].id)})}")
    assert resp.status_code == 200
    assert "Do thing" in resp.text
    assert "text/csv" in resp.headers["content-type"]


def test_export_kpis_csv(notif_world, client, db, auth_user):
    project = Project(name="KPI Export", client_id=1, tenant_id=notif_world["tenant"].id)
    db.add(project)
    db.commit()
    db.refresh(project)
    db.add(KPI(tenant_id=notif_world["tenant"].id, project_id=project.id, name="NPS", target_value="50", current_value="40"))
    db.commit()

    token = create_access_token({"sub": str(auth_user["user"].id)})
    resp = client.get(f"/api/export/kpis/{project.id}?token={token}")
    assert resp.status_code == 200
    assert "NPS" in resp.text


def test_export_invalid_token_401(notif_world, client):
    resp = client.get("/api/export/tasks?token=garbage")
    assert resp.status_code == 401


def test_project_health_healthy_when_empty(notif_world, client, db):
    project = Project(name="Health P", client_id=1, tenant_id=notif_world["tenant"].id)
    db.add(project)
    db.commit()
    db.refresh(project)

    resp = client.get(f"/api/projects/{project.id}/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["health_score"] == 100
    assert data["status"] == "Healthy"


def test_project_health_penalised_by_overdue_tasks(notif_world, client, db, auth_user):
    from datetime import date, timedelta

    project = Project(name="Risk P", client_id=1, tenant_id=notif_world["tenant"].id)
    db.add(project)
    db.commit()
    db.refresh(project)
    db.add(UserTask(
        tenant_id=notif_world["tenant"].id, title="Overdue",
        assigned_to=auth_user["user"].id, project_id=project.id,
        due_date=date.today() - timedelta(days=3), status="In Progress",
    ))
    db.commit()

    data = client.get(f"/api/projects/{project.id}/health").json()
    assert data["overdue_tasks"] == 1
    assert data["task_score"] == 80  # 100 - 1*20
    assert data["health_score"] < 100
