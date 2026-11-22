"""Slice 6 — the officer rules master switch (Unified System v2 §2 route 10).

Covers: the rules_enabled KV (default ON, read via the settings_service
helper), the PUT /api/officer/rules one-click round-trip (on→off→on), the
beat respecting rules off (_tenant_rules_sweep returns {"rules": "off"} and
evaluate_rules is NOT called), /scan respecting it, and the status payload
carrying rules_enabled.

The settings-screen static checks live in test_settings_officer_static.py.
"""
import threading
from datetime import datetime, timedelta

import pytest

import app.worker as worker
from app.models.automation_rule import AutomationRule
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.tenant_setting import SETTING_RULES_ENABLED, TenantSetting
from app.services.rules_engine import evaluate_rules
from app.services.settings_service import rules_enabled, set_setting


@pytest.fixture(autouse=True)
def _no_scheduler():
    """Belt-and-braces: the scheduler is off and down between tests."""
    worker.shutdown_scheduler()
    worker._LAST_RUN.clear()
    yield
    worker.shutdown_scheduler()


@pytest.fixture(autouse=True)
def _worker_db(monkeypatch):
    """The beat's module-level engine/SessionLocal point at the app's real
    (Postgres) DB — tests route them to the in-memory SQLite instead."""
    from tests.conftest import TestSessionLocal, test_engine

    monkeypatch.setattr(worker, "engine", test_engine)
    monkeypatch.setattr(worker, "SessionLocal", TestSessionLocal)
    yield


def _make_client(db, tenant):
    """Projects require a client (NOT NULL FK) — seed one for the test."""
    from app.models.client import Client

    c = Client(tenant_id=tenant.id, name=f"Client {tenant.id}")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _blocked_setup(db, tenant, user):
    """A blocked item + an ENABLED escalation rule — the sweep has a target."""
    project = Project(
        tenant_id=tenant.id, name="Rules P", status="active",
        client_id=_make_client(db, tenant).id, project_manager_id=user.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    db.add(BacklogItem(
        tenant_id=tenant.id, project_id=project.id, title="Blocked target",
        status="Blocked", assigned_to=user.id,
        updated_at=(datetime.utcnow() - timedelta(days=6)).strftime("%Y-%m-%d %H:%M:%S"),
    ))
    db.add(AutomationRule(
        tenant_id=tenant.id, name="Blocked escalation", trigger="item_blocked",
        conditions={"days_blocked": 3}, actions=[
            {"type": "notify"}, {"type": "create_task", "title_prefix": "Escalate: "},
        ],
        source="manual", enabled=True,
    ))
    db.commit()


# ---------------------------------------------------------------------------
# 1. The KV — default ON, read via the helper
# ---------------------------------------------------------------------------

def test_rules_enabled_defaults_on(db, auth_user):
    """No KV row → rules are ON (route 10: rules ON by default)."""
    assert rules_enabled(db, auth_user["tenant"].id) is True
    assert (
        db.query(TenantSetting)
        .filter(TenantSetting.tenant_id == auth_user["tenant"].id,
                TenantSetting.key == SETTING_RULES_ENABLED)
        .first()
        is None
    )


def test_rules_enabled_reads_the_kv(db, auth_user):
    """The helper reads the stored value — '0' is off, '1' is on."""
    tenant = auth_user["tenant"]
    set_setting(db, tenant.id, SETTING_RULES_ENABLED, "0")
    db.commit()
    assert rules_enabled(db, tenant.id) is False
    set_setting(db, tenant.id, SETTING_RULES_ENABLED, "1")
    db.commit()
    assert rules_enabled(db, tenant.id) is True


# ---------------------------------------------------------------------------
# 2. PUT /api/officer/rules — the one-click round-trip
# ---------------------------------------------------------------------------

def test_toggle_round_trip_on_off_on(client, db, auth_user):
    """One click off → on → off: the KV is written and status follows."""
    tenant = auth_user["tenant"]
    first = client.put("/api/officer/rules", json={"enabled": False})
    assert first.status_code == 200
    assert first.json()["rules_enabled"] is False
    assert rules_enabled(db, tenant.id) is False
    assert client.get("/api/officer/status").json()["rules_enabled"] is False

    second = client.put("/api/officer/rules", json={"enabled": True})
    assert second.status_code == 200
    assert second.json()["rules_enabled"] is True
    assert rules_enabled(db, tenant.id) is True
    assert client.get("/api/officer/status").json()["rules_enabled"] is True

    # The KV row persists — this is per-tenant state, not session state
    row = (
        db.query(TenantSetting)
        .filter(TenantSetting.tenant_id == tenant.id,
                TenantSetting.key == SETTING_RULES_ENABLED)
        .first()
    )
    assert row is not None and row.value == "1"


def test_toggle_validates_the_body(client):
    """The endpoint only accepts {"enabled": bool}."""
    assert client.put("/api/officer/rules", json={}).status_code == 422
    assert client.put("/api/officer/rules", json={"enabled": "yes"}).status_code == 422


def test_toggle_requires_auth(anon_client):
    assert anon_client.put("/api/officer/rules", json={"enabled": False}).status_code in (401, 403)


# ---------------------------------------------------------------------------
# 3. The beat respects rules off — evaluate_rules is NOT called
# ---------------------------------------------------------------------------

def test_sweep_respects_rules_off(db, auth_user, monkeypatch):
    """Rules off → _tenant_rules_sweep returns {"rules": "off"} and never
    evaluates (no seeds, no drafts)."""
    tenant, user = auth_user["tenant"], auth_user["user"]
    _blocked_setup(db, tenant, user)
    set_setting(db, tenant.id, SETTING_RULES_ENABLED, "0")
    db.commit()

    calls = []

    def _spy(db_, tenant_):
        calls.append(tenant_.id)
        return {"evaluated": 0, "fired": 0, "details": []}

    monkeypatch.setattr(worker, "evaluate_rules", _spy)
    result = worker._tenant_rules_sweep(db, tenant)
    assert result == {"rules": "off"}
    assert calls == [], "evaluate_rules must not run while rules are off"
    # Nothing seeded, nothing drafted
    assert db.query(AutomationRule).filter(AutomationRule.tenant_id == tenant.id).count() == 1  # only the manual rule


def test_sweep_evaluates_when_rules_on(db, auth_user):
    """Default ON: the sweep seeds + evaluates as before."""
    from app.models.user_task import UserTask

    tenant, user = auth_user["tenant"], auth_user["user"]
    _blocked_setup(db, tenant, user)
    result = worker._tenant_rules_sweep(db, tenant)
    assert result["fired"] >= 1
    assert (
        db.query(UserTask)
        .filter(UserTask.tenant_id == tenant.id, UserTask.title.like("Escalate: %"))
        .count()
        >= 1
    )


def test_beat_rules_sweep_marks_rules_off_per_tenant(db, auth_user):
    """run_beat('rules_sweep') records {"rules": "off"} for the paused tenant
    while the window still runs."""
    tenant = auth_user["tenant"]
    set_setting(db, tenant.id, SETTING_RULES_ENABLED, "0")
    db.commit()
    summary = worker.run_beat("rules_sweep", window="2026-11-22-rules-off")
    assert summary["tenants"][str(tenant.id)] == {"rules": "off"}


# ---------------------------------------------------------------------------
# 4. /scan respects rules off
# ---------------------------------------------------------------------------

def test_scan_respects_rules_off(client, db, auth_user, monkeypatch):
    """Rules off → the manual scan is a no-op: nothing seeded or evaluated."""
    import app.routers.officer as officer_router

    tenant, user = auth_user["tenant"], auth_user["user"]
    _blocked_setup(db, tenant, user)
    client.put("/api/officer/rules", json={"enabled": False})

    calls = []

    def _spy(db_, tenant_):
        calls.append(tenant_.id)
        return {"evaluated": 0, "fired": 0, "details": []}

    monkeypatch.setattr(officer_router, "evaluate_rules", _spy)
    resp = client.post("/api/officer/scan")
    assert resp.status_code == 200
    body = resp.json()
    assert body["rules"] == "off"
    assert body["evaluated"] == 0 and body["fired"] == 0
    assert calls == [], "scan must not evaluate while rules are off"
    # The escalation template was NOT seeded while rules are off
    assert (
        db.query(AutomationRule)
        .filter(AutomationRule.tenant_id == tenant.id, AutomationRule.source == "template")
        .count()
        == 0
    )


def test_seeding_resumes_after_rules_turn_on(client, db, auth_user):
    """Off → scan (no seed) → on → scan (seeds + evaluates)."""
    tenant, user = auth_user["tenant"], auth_user["user"]
    _blocked_setup(db, tenant, user)
    client.put("/api/officer/rules", json={"enabled": False})
    off = client.post("/api/officer/scan").json()
    assert off["rules"] == "off"
    client.put("/api/officer/rules", json={"enabled": True})
    on = client.post("/api/officer/scan").json()
    assert "rules" not in on or on["rules"] != "off"
    assert on["fired"] >= 1
    assert (
        db.query(AutomationRule)
        .filter(AutomationRule.tenant_id == tenant.id, AutomationRule.source == "template")
        .count()
        == 1
    )


def test_seeding_helper_respects_rules_off(db, auth_user):
    """ensure_rule_templates itself no-ops while the tenant's rules are off."""
    from app.services.officer import ensure_rule_templates

    tenant = auth_user["tenant"]
    set_setting(db, tenant.id, SETTING_RULES_ENABLED, "0")
    db.commit()
    assert ensure_rule_templates(db, tenant) == {"seeded": 0, "rules": "off"}
    set_setting(db, tenant.id, SETTING_RULES_ENABLED, "1")
    db.commit()
    assert ensure_rule_templates(db, tenant) == {"seeded": 1}


# ---------------------------------------------------------------------------
# 5. GET /api/officer/status carries rules_enabled
# ---------------------------------------------------------------------------

def test_status_carries_rules_enabled(client):
    body = client.get("/api/officer/status").json()
    assert body["rules_enabled"] is True  # default ON
    client.put("/api/officer/rules", json={"enabled": False})
    assert client.get("/api/officer/status").json()["rules_enabled"] is False


def test_status_shape_keeps_the_scheduler_and_rules_keys(client):
    body = client.get("/api/officer/status").json()
    assert set(body["jobs"]) == {"rules_sweep", "nightly", "weekly"}
    assert body["rules"]["total"] == 0 and body["rules"]["enabled"] == 0
    assert body["scheduler"]["enabled"] is False  # disabled in tests


# ---------------------------------------------------------------------------
# 6. Belt-and-braces: no scheduler threads leak into the suite
# ---------------------------------------------------------------------------

def test_no_scheduler_threads_leak():
    import os

    old = os.environ.get("PMO_SCHEDULER_ENABLED")
    os.environ["PMO_SCHEDULER_ENABLED"] = "0"
    try:
        before = threading.active_count()
        worker.start_scheduler()
        assert worker._scheduler is None
        assert threading.active_count() <= before
    finally:
        if old is None:
            os.environ.pop("PMO_SCHEDULER_ENABLED", None)
        else:
            os.environ["PMO_SCHEDULER_ENABLED"] = old


def test_evaluate_rules_untouched_signature():
    """The rules engine itself is NOT modified — the flag gates its callers."""
    import inspect

    params = list(inspect.signature(evaluate_rules).parameters)
    assert params == ["db", "tenant"]
