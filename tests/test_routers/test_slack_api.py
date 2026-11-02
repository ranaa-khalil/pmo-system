"""Tests for the Slack digest — config + digest build (D4: second).

Config is tenant-level, admin-only, webhook masked on read and validated on
write. The digest builder is a pure read; sends are mocked — no network.
"""
import pytest

import app.models  # noqa: F401
from app.models.project import Project
from app.models.risk import Risk
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User


@pytest.fixture()
def slack_world(client, db):
    """Tenant admin + member with a project."""
    tenant = Tenant(name="Slack Co", slug="slack-co", plan="enterprise")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    admin = User(email="admin-slack@copilot.test", name="Admin", hashed_password="x",
                 system_role="tenant_admin")
    member = User(email="member-slack@copilot.test", name="Member", hashed_password="x")
    db.add_all([admin, member])
    db.commit()
    db.refresh(admin)
    db.refresh(member)
    for u, role in [(admin, "owner"), (member, "member")]:
        db.add(TenantMembership(user_id=u.id, tenant_id=tenant.id, role=role))
        u.active_tenant_id = tenant.id
    db.commit()
    project = Project(name="Slack Proj", client_id=1, tenant_id=tenant.id, project_manager_id=admin.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return {"tenant": tenant, "admin": admin, "member": member, "project": project}


def _as(client, user):
    from app.services.auth import create_access_token
    client.headers.update({"Authorization": f"Bearer {create_access_token(data={'sub': str(user.id)})}"})


HOOK = "https://hooks.slack.com/services/T000/B000/XXXXXXXXXXXXXXXX"


def test_config_roundtrip_masked(slack_world, client):
    admin = slack_world["admin"]
    _as(client, admin)
    save = client.put("/api/integrations/slack", json={
        "webhook_url": HOOK, "enabled": True, "digest_time": "08:30",
    })
    assert save.status_code == 200
    got = client.get("/api/integrations/slack")
    assert got.status_code == 200
    data = got.json()
    assert data["configured"] is True
    assert data["enabled"] is True
    assert data["digest_time"] == "08:30"
    # webhook masked — the secret token never leaves the server
    assert data["webhook_masked"] != HOOK
    assert "XXXXXXXXXXXXXXXX" not in (data["webhook_masked"] or "")


def test_member_cannot_manage_slack(slack_world, client):
    member = slack_world["member"]
    _as(client, member)
    resp = client.put("/api/integrations/slack", json={"webhook_url": HOOK})
    assert resp.status_code == 403
    assert client.get("/api/integrations/slack").status_code == 403


def test_config_requires_slack_webhook(slack_world, client):
    _as(client, slack_world["admin"])
    resp = client.put("/api/integrations/slack", json={"webhook_url": "https://example.com/hook"})
    assert resp.status_code == 422


def test_unconfigured_returns_shape(slack_world, client):
    _as(client, slack_world["admin"])
    resp = client.get("/api/integrations/slack")
    assert resp.status_code == 200
    assert resp.json()["configured"] is False


def test_digest_builder_counts(slack_world, client, db):
    """build_digest reads tenant data: items by status, open RAID by kind, hours."""
    from datetime import date

    from app.models.backlog_item import BacklogItem
    from app.models.time_entry import TimeEntry
    from app.services.slack_digest import build_digest

    project = slack_world["project"]
    tenant = slack_world["tenant"]
    member = slack_world["member"]
    db.add(BacklogItem(title="One", project_id=project.id, tenant_id=tenant.id, status="Done"))
    db.add(BacklogItem(title="Two", project_id=project.id, tenant_id=tenant.id, status="In Progress"))
    db.add(Risk(project_id=project.id, tenant_id=tenant.id, title="R", kind="Risk", severity="High", probability="Likely", status="Open"))
    db.add(Risk(project_id=project.id, tenant_id=tenant.id, title="A", kind="Assumption", status="Open"))
    db.add(TimeEntry(project_id=project.id, tenant_id=tenant.id, user_id=member.id,
                     entry_date=date.today(), hours=2))
    db.commit()

    digest = build_digest(db, tenant.id)
    assert digest["progress"].get("Done") == 1
    assert digest["progress"].get("In Progress") == 1
    assert digest["raid"].get("Risk") == 1
    assert digest["raid"].get("Assumption") == 1
    assert digest["week_hours"] == 2.0
    assert digest["totals"]["items"] == 2


def test_digest_text_renders(slack_world, client, db):
    from app.services.slack_digest import build_digest, digest_text

    digest = build_digest(db, slack_world["tenant"].id)
    text = digest_text(digest, "Slack Co")
    assert "Slack Co" in text
    assert "Daily Digest" in text


def test_digest_send_mocked(slack_world, client, monkeypatch):
    """POST /digest builds and sends with a mocked webhook — no network."""
    _as(client, slack_world["admin"])
    client.put("/api/integrations/slack", json={"webhook_url": HOOK, "enabled": True})

    from app.routers import slack as slack_router

    sent = {}

    def fake_send(url, text, timeout=10):
        sent["url"] = url
        sent["text"] = text

    monkeypatch.setattr(slack_router, "send_to_slack", fake_send)
    resp = client.post("/api/integrations/slack/digest")
    assert resp.status_code == 200
    assert resp.json()["sent"] is True
    assert sent["url"] == HOOK
    assert "Daily Digest" in sent["text"]


def test_test_endpoint_mocked(slack_world, client, monkeypatch):
    """POST /test sends a test message with a mocked webhook."""
    _as(client, slack_world["admin"])
    client.put("/api/integrations/slack", json={"webhook_url": HOOK, "enabled": True})

    from app.routers import slack as slack_router

    sent = {}
    monkeypatch.setattr(slack_router, "send_to_slack", lambda url, text, timeout=10: sent.update(url=url, text=text))
    resp = client.post("/api/integrations/slack/test")
    assert resp.status_code == 200
    assert resp.json()["sent"] is True
    assert "PMO test" in sent["text"]
