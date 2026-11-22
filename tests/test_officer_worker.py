"""Officer beat (R1, Slice 4) — the scheduler runtime tests.

Covers: scheduler disabled in tests (no thread leak), the advisory-lock
SQLite no-op, the RAID escalation template seed, the item_blocked matcher,
one-broken-tenant-continues, the BeatRun window dedupe, catch-up-on-start,
and the /api/officer status + scan surface.
"""
import threading
from datetime import datetime, timedelta

import pytest

import app.worker as worker
from app.main import app
from app.models.automation_rule import AutomationRule
from app.models.backlog_item import BacklogItem
from app.models.beat_run import BeatRun
from app.models.project import Project
from app.services.officer import ensure_rule_templates, publish_day_reports
from app.services.rules_engine import evaluate_rules


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


# ---------------------------------------------------------------------------
# 1. Scheduler disabled in tests — no thread leak
# ---------------------------------------------------------------------------

def test_scheduler_disabled_in_tests():
    """The startup handler is wired, the env is off → the suite never
    spawns scheduler threads."""
    before = threading.active_count()
    handlers = [getattr(h, "__name__", "") for h in app.router.on_startup]
    assert "start_officer_beat" in handlers
    worker.start_scheduler()  # PMO_SCHEDULER_ENABLED=0 → None
    assert worker._scheduler is None
    assert threading.active_count() <= before, "scheduler threads leaked into the suite"


def test_scheduler_env_off_means_no_start():
    import os

    old = os.environ.get("PMO_SCHEDULER_ENABLED")
    os.environ["PMO_SCHEDULER_ENABLED"] = "0"
    try:
        assert worker.start_scheduler() is None
        assert worker._scheduler is None
    finally:
        if old is None:
            os.environ.pop("PMO_SCHEDULER_ENABLED", None)
        else:
            os.environ["PMO_SCHEDULER_ENABLED"] = old


# ---------------------------------------------------------------------------
# 2. Advisory lock — SQLite no-op
# ---------------------------------------------------------------------------

def test_advisory_lock_noops_on_sqlite():
    assert worker.engine.dialect.name == "sqlite"
    conn = worker.engine.connect()
    try:
        assert worker._acquire_beat_lock(conn, "nightly") is True
    finally:
        worker._release_beat_lock(conn, "nightly")
        conn.close()


# ---------------------------------------------------------------------------
# 3. RAID escalation template seed
# ---------------------------------------------------------------------------

def test_escalation_template_seeded_once(db, auth_user):
    first = ensure_rule_templates(db, auth_user["tenant"])
    assert first == {"seeded": 1}
    rule = (
        db.query(AutomationRule)
        .filter(AutomationRule.tenant_id == auth_user["tenant"].id)
        .first()
    )
    assert rule.trigger == "item_blocked"
    assert rule.source == "template"
    assert rule.enabled is False  # never auto-enabled — the human flips it
    second = ensure_rule_templates(db, auth_user["tenant"])
    assert second == {"seeded": 0}


# ---------------------------------------------------------------------------
# 4. item_blocked matcher fires the escalation draft
# ---------------------------------------------------------------------------

def test_item_blocked_matcher_fires(db, auth_user):
    tenant, user = auth_user["tenant"], auth_user["user"]
    project = Project(
        tenant_id=tenant.id, name="Blocked Project", status="active",
        client_id=_make_client(db, tenant).id, project_manager_id=user.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    stale = (datetime.utcnow() - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
    item = BacklogItem(
        tenant_id=tenant.id, project_id=project.id, title="Stuck dependency",
        status="Blocked", assigned_to=user.id, updated_at=stale,
    )
    fresh = BacklogItem(
        tenant_id=tenant.id, project_id=project.id, title="Just blocked",
        status="Blocked", assigned_to=user.id,
        updated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    )
    rule = AutomationRule(
        tenant_id=tenant.id, name="Blocked escalation", trigger="item_blocked",
        conditions={"days_blocked": 3}, actions=[
            {"type": "notify", "role": "assignee"},
            {"type": "create_task", "title_prefix": "Escalate: "},
        ],
        source="template", enabled=True,
    )
    db.add_all([item, fresh, rule])
    db.commit()

    result = evaluate_rules(db, tenant)
    assert result["fired"] >= 1
    # The stale item raised exactly one escalation task; the fresh one did not
    from app.models.user_task import UserTask

    escalation = (
        db.query(UserTask)
        .filter(UserTask.tenant_id == tenant.id, UserTask.status != "Completed")
        .all()
    )
    titles = [t.title for t in escalation]
    assert any("Escalate: Blocked > " in t and "Stuck dependency" in t for t in titles)
    assert not any("Just blocked" in t for t in titles)


def test_item_blocked_matcher_disabled_rule_never_fires(db, auth_user):
    tenant, user = auth_user["tenant"], auth_user["user"]
    project = Project(
        tenant_id=tenant.id, name="P2", status="active",
        client_id=_make_client(db, tenant).id, project_manager_id=user.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    db.add(BacklogItem(
        tenant_id=tenant.id, project_id=project.id, title="Blocked item",
        status="Blocked", assigned_to=user.id,
        updated_at=(datetime.utcnow() - timedelta(days=9)).strftime("%Y-%m-%d %H:%M:%S"),
    ))
    db.add(AutomationRule(
        tenant_id=tenant.id, name="Off", trigger="item_blocked",
        conditions={"days_blocked": 3}, actions=[{"type": "notify"}],
        source="template", enabled=False,
    ))
    db.commit()
    result = evaluate_rules(db, tenant)
    assert result["evaluated"] == 0  # disabled rules are not even evaluated


# ---------------------------------------------------------------------------
# 5. One broken tenant never blocks the beat
# ---------------------------------------------------------------------------

def test_one_broken_tenant_continues(db, auth_user, monkeypatch):
    from app.models.tenant import Tenant, TenantMembership

    tenant_a = auth_user["tenant"]
    tenant_b = Tenant(name="Second", slug="second", plan="free", status="active")
    db.add(tenant_b)
    db.commit()
    db.refresh(tenant_b)
    db.add(TenantMembership(user_id=auth_user["user"].id, tenant_id=tenant_b.id, role="owner"))
    db.commit()

    calls = []
    real = worker._tenant_nightly

    def flaky(db_, tenant, tenant_config=None):
        calls.append(tenant.id)
        if tenant.id == tenant_a.id:
            raise RuntimeError("LLM down — connection refused")
        return real(db_, tenant, tenant_config)

    monkeypatch.setattr(worker, "_tenant_nightly", flaky)
    summary = worker.run_beat("nightly")
    assert tenant_a.id in calls and tenant_b.id in calls
    assert "error" in summary["tenants"][str(tenant_a.id)]
    assert "day_reports" in summary["tenants"][str(tenant_b.id)]


# ---------------------------------------------------------------------------
# 6. BeatRun window dedupe — a window runs at most once
# ---------------------------------------------------------------------------

def test_beat_window_runs_once(db, auth_user, monkeypatch):
    calls = []
    monkeypatch.setattr(worker, "_tenant_nightly", lambda db_, t, tenant_config=None: calls.append(t.id) or {})
    first = worker.run_beat("nightly", window="2026-11-22")
    assert "skipped" not in first
    second = worker.run_beat("nightly", window="2026-11-22")
    assert second["skipped"] == "already_ran"
    assert len(calls) == 1  # the second run touched no tenants
    assert db.query(BeatRun).filter(BeatRun.job == "nightly").count() == 1


# ---------------------------------------------------------------------------
# 7. Catch-up-on-start
# ---------------------------------------------------------------------------

def test_catchup_runs_missed_nightly(db, auth_user, monkeypatch):
    calls = []
    monkeypatch.setattr(worker, "_tenant_nightly", lambda db_, t, tenant_config=None: calls.append(t.id) or {})
    now = datetime(2026, 11, 22, 23, 30)
    result = worker.run_catchup(now=now)
    assert "nightly" in result
    assert len(calls) == 1


def test_catchup_nothing_due_early(db, auth_user, monkeypatch):
    calls = []
    monkeypatch.setattr(worker, "_tenant_nightly", lambda db_, t, tenant_config=None: calls.append(t.id) or {})
    now = datetime(2026, 11, 22, 10, 0)
    result = worker.run_catchup(now=now)
    assert result == {"catchup": "nothing_due"}
    assert calls == []


# ---------------------------------------------------------------------------
# 8. Day report — published to Today, deduped per day
# ---------------------------------------------------------------------------

def test_day_report_published_and_deduped(db, auth_user):
    from app.models.notification import Notification

    tenant, user = auth_user["tenant"], auth_user["user"]
    # Pending approval + overdue task so the member has pending work
    project = Project(tenant_id=tenant.id, name="DR", status="active",
                      client_id=_make_client(db, tenant).id, project_manager_id=user.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    from app.models.approval import ApprovalRequest, ApprovalStep

    approval = ApprovalRequest(
        tenant_id=tenant.id, project_id=project.id, title="Gate approval",
        request_type="gate", requested_by=user.id, status="Pending",
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)
    db.add(ApprovalStep(
        tenant_id=tenant.id, request_id=approval.id, step_order=1,
        role_name="pm", approver_id=user.id, status="Pending",
    ))
    db.commit()

    first = publish_day_reports(db, tenant)
    assert first["published"] >= 1
    notes = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.type == "day_report")
        .all()
    )
    assert len(notes) == 1
    assert notes[0].link == "/today"
    second = publish_day_reports(db, tenant)
    assert second["published"] == 0  # deduped per user per day
    assert (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.type == "day_report")
        .count()
        == 1
    )


# ---------------------------------------------------------------------------
# 9. /api/officer surface
# ---------------------------------------------------------------------------

def test_officer_status_shape(client):
    resp = client.get("/api/officer/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["scheduler"]["enabled"] is False  # disabled in tests
    assert body["scheduler"]["running"] is False
    assert set(body["jobs"]) == {"rules_sweep", "nightly", "weekly"}
    assert body["rules"]["total"] == 0 and body["rules"]["enabled"] == 0


def test_officer_status_requires_tenant(anon_client):
    assert anon_client.get("/api/officer/status").status_code in (401, 403)


def test_officer_scan_is_draft_producing_and_idempotent(client, db, auth_user):
    tenant, user = auth_user["tenant"], auth_user["user"]
    project = Project(tenant_id=tenant.id, name="Scan P", status="active",
                      client_id=_make_client(db, tenant).id, project_manager_id=user.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    db.add(BacklogItem(
        tenant_id=tenant.id, project_id=project.id, title="Blocked scan target",
        status="Blocked", assigned_to=user.id,
        updated_at=(datetime.utcnow() - timedelta(days=6)).strftime("%Y-%m-%d %H:%M:%S"),
    ))
    # An ENABLED escalation rule so the sweep has something to fire (the
    # seeded template is disabled by design — rules are never auto-enabled)
    db.add(AutomationRule(
        tenant_id=tenant.id, name="Blocked escalation", trigger="item_blocked",
        conditions={"days_blocked": 3}, actions=[
            {"type": "notify"}, {"type": "create_task", "title_prefix": "Escalate: "},
        ],
        source="manual", enabled=True,
    ))
    db.commit()

    first = client.post("/api/officer/scan")
    assert first.status_code == 200
    body = first.json()
    assert body["fired"] >= 1
    assert set(body.keys()) == {"evaluated", "fired", "details"}
    # The scan seeded the escalation template too
    seeded = (
        db.query(AutomationRule)
        .filter(AutomationRule.tenant_id == tenant.id, AutomationRule.source == "template")
        .count()
    )
    assert seeded == 1
    # Draft-producing only: the escalation TASK exists, nothing executed
    from app.models.user_task import UserTask

    assert (
        db.query(UserTask)
        .filter(UserTask.tenant_id == tenant.id)
        .filter(UserTask.title.like("Escalate: %"))
        .count()
        == 1
    )
    # Idempotent: a second scan never duplicates the escalation task
    second = client.post("/api/officer/scan")
    assert second.status_code == 200
    assert (
        db.query(UserTask)
        .filter(UserTask.tenant_id == tenant.id)
        .filter(UserTask.title.like("Escalate: %"))
        .count()
        == 1
    )


# ---------------------------------------------------------------------------
# 10. Registry mirror for the status API
# ---------------------------------------------------------------------------

def test_registry_updates_after_beat(db, auth_user, monkeypatch):
    monkeypatch.setattr(worker, "_tenant_nightly", lambda db_, t, tenant_config=None: {"ok": 1})
    worker.run_beat("nightly", window="2026-11-23")
    assert "nightly" in worker._LAST_RUN
    info = worker._LAST_RUN["nightly"]
    assert info["window"] == "2026-11-23"
    assert info["tenants"] >= 1
