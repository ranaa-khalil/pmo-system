"""LLM resilience wrapper + comment notifications + report dispatch (Slice 5).

Covers: the ONE wrapper (timeout → retry → deterministic fallback, usage row
per call), the fallback's non-JSON contract (the intake's verbatim path still
triggers), comment notifications to the assignee, and the real report-send
dispatch with the artifact chain intact.
"""
import httpx
import pytest

from app.services.ai import _call_llm as ai_call_llm
from app.services.intake import _extract_json
from app.services.llm import FALLBACK_TEXT, call_llm


@pytest.fixture(autouse=True)
def _llm_db(monkeypatch):
    """The wrapper writes its usage row via app.database.SessionLocal —
    tests route it to the in-memory SQLite."""
    from tests.conftest import TestSessionLocal

    monkeypatch.setattr("app.database.SessionLocal", TestSessionLocal)
    yield


class _FakeResp:
    def __init__(self, content="LLM ANSWER"):
        self._content = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def _patch_http(monkeypatch, behavior):
    """behavior: 'ok' | 'fail' — returns the attempt counter list."""
    attempts = []

    class _FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            attempts.append(1)
            if behavior == "fail":
                raise httpx.ConnectError("connection refused")
            return _FakeResp()

    monkeypatch.setattr(httpx, "Client", _FakeClient)
    return attempts


def _usage_rows(db, tenant_id):
    from app.models.llm_usage import LlmUsage

    return (
        db.query(LlmUsage)
        .filter(LlmUsage.tenant_id == tenant_id)
        .order_by(LlmUsage.id)
        .all()
    )


# ---------------------------------------------------------------------------
# 1. The wrapper — success
# ---------------------------------------------------------------------------

def test_wrapper_success_returns_content_and_usage_row(db, auth_user, monkeypatch):
    attempts = _patch_http(monkeypatch, "ok")
    out = call_llm("system", "user", tenant_config={"api_key": "k", "tenant_id": auth_user["tenant"].id})
    assert out == "LLM ANSWER"
    assert len(attempts) == 1  # no retry on success
    rows = _usage_rows(db, auth_user["tenant"].id)
    assert len(rows) == 1 and rows[0].ok is True and rows[0].feature == "ai"


def test_wrapper_fails_twice_then_falls_back(db, auth_user, monkeypatch):
    attempts = _patch_http(monkeypatch, "fail")
    monkeypatch.setattr("app.services.llm.RETRY_DELAY_S", 0)  # no real sleep in tests
    out = call_llm("system", "user", tenant_config={"api_key": "k", "tenant_id": auth_user["tenant"].id})
    assert out == FALLBACK_TEXT
    assert len(attempts) == 2  # exactly 1 retry
    rows = _usage_rows(db, auth_user["tenant"].id)
    assert len(rows) == 1 and rows[0].ok is False and rows[0].error == "fallback"


def test_wrapper_no_key_never_raises(db, auth_user, monkeypatch):
    attempts = _patch_http(monkeypatch, "ok")
    out = call_llm("system", "user", tenant_config={"tenant_id": auth_user["tenant"].id})
    assert out == FALLBACK_TEXT
    assert attempts == []  # no HTTP call without a key
    rows = _usage_rows(db, auth_user["tenant"].id)
    assert len(rows) == 1 and rows[0].ok is False


def test_fallback_is_non_json_so_intake_verbatim_path_triggers():
    """The fallback string must never parse as JSON — the intake's own
    deterministic (verbatim) fallback path depends on that."""
    assert _extract_json(FALLBACK_TEXT) in (None, {})


def test_ai_call_llm_delegates_with_same_signature(monkeypatch):
    """ai._call_llm keeps its exact signature (tests + callers depend on it)."""
    captured = {}

    def fake_call(system, user, tenant_config=None, max_tokens=1500, json_mode=False, feature="ai"):
        captured.update(system=system, max_tokens=max_tokens, json_mode=json_mode, feature=feature)
        return "OK"

    monkeypatch.setattr("app.services.llm.call_llm", fake_call)
    out = ai_call_llm("s", "u", max_tokens=900, json_mode=True, tenant_config={"api_key": "k"})
    assert out == "OK"
    assert captured == {"system": "s", "max_tokens": 900, "json_mode": True, "feature": "ai"}


# ---------------------------------------------------------------------------
# 2. Comment notifications to the assignee
# ---------------------------------------------------------------------------

def _second_member(db, tenant):
    from app.models.tenant import TenantMembership
    from app.models.user import User
    from app.services.auth import hash_password

    user = User(
        email="dev@pmo.test", name="Dev User",
        hashed_password=hash_password("TestPass123!"),
        system_role="member", active_tenant_id=tenant.id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(TenantMembership(user_id=user.id, tenant_id=tenant.id, role="member"))
    db.commit()
    return user


def _project_with_item(db, tenant, pm, assignee):
    from app.models.backlog_item import BacklogItem
    from app.models.client import Client
    from app.models.project import Project

    c = Client(tenant_id=tenant.id, name="C")
    db.add(c)
    db.commit()
    db.refresh(c)
    project = Project(tenant_id=tenant.id, name="CP", status="active",
                      client_id=c.id, project_manager_id=pm.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    item = BacklogItem(tenant_id=tenant.id, project_id=project.id,
                       title="Commented item", status="Draft", assigned_to=assignee.id)
    db.add(item)
    db.commit()
    db.refresh(item)
    return project, item


def test_item_comment_notifies_assignee(client, db, auth_user):
    from app.models.notification import Notification

    tenant, user = auth_user["tenant"], auth_user["user"]
    dev = _second_member(db, tenant)
    _, item = _project_with_item(db, tenant, user, dev)

    resp = client.post(f"/api/backlog/{item.id}/comments", json={"body": "Looks good?"})
    assert resp.status_code == 201
    notes = (
        db.query(Notification)
        .filter(Notification.user_id == dev.id, Notification.type == "comment")
        .all()
    )
    assert len(notes) == 1
    assert "Dev User" in notes[0].title or user.name in notes[0].title
    # The commenter is never notified about their own comment
    assert (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.type == "comment")
        .count()
        == 0
    )


def test_comment_without_assignee_notifies_nothing(client, db, auth_user):
    from app.models.notification import Notification

    tenant, user = auth_user["tenant"], auth_user["user"]
    _, item = _project_with_item(db, tenant, user, user)  # assignee = commenter
    resp = client.post(f"/api/backlog/{item.id}/comments", json={"body": "self note"})
    assert resp.status_code == 201
    assert (
        db.query(Notification).filter(Notification.type == "comment").count() == 0
    )


# ---------------------------------------------------------------------------
# 3. Report send — recipients + dispatch, chain intact
# ---------------------------------------------------------------------------

def test_report_send_dispatches_to_recipients_and_keeps_chain(client, db, auth_user, monkeypatch):
    from app.models.artifact_chain import ArtifactChain
    from app.models.client import Client
    from app.models.project import Project
    from app.models.stakeholder import Stakeholder

    tenant, user = auth_user["tenant"], auth_user["user"]
    c = Client(tenant_id=tenant.id, name="RC")
    db.add(c)
    db.commit()
    db.refresh(c)
    project = Project(tenant_id=tenant.id, name="RP", status="active",
                      client_id=c.id, project_manager_id=user.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    db.add(Stakeholder(tenant_id=tenant.id, project_id=project.id,
                       name="Sponsor", email="sponsor@client.test", role_name="Sponsor"))
    db.commit()

    calls = []

    def fake_send(**kwargs):
        calls.append(kwargs)
        return True

    monkeypatch.setattr("app.routers.reports.send_email", fake_send)
    resp = client.post(f"/api/projects/{project.id}/reports/send")
    assert resp.status_code == 201
    body = resp.json()
    # Recipients: the PM + the stakeholder with an email
    assert {r["email"] for r in body["recipients"]} == {user.email, "sponsor@client.test"}
    assert len(calls) == 2  # one dispatch per recipient
    assert body["entry"]["action"] == "sent"
    # The tamper-evident chain entry still lands (dispatch never bypasses it)
    assert (
        db.query(ArtifactChain)
        .filter(
            ArtifactChain.entity_type == "report",
            ArtifactChain.entity_id == project.id,
            ArtifactChain.action == "sent",
        )
        .count()
        == 1
    )


def test_email_send_dev_mode_returns_false_without_smtp():
    """No SMTP configured → logged, not sent — digests and report sends never crash."""
    from app.services.email_service import send_email

    result = send_email(to_email="x@y.test", subject="s", body="b")
    assert result is False
