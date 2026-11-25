"""FR-T6 plan counters — AI / storage / portal quotas (design + enforcement).

The three counters meter from EXISTING tables (no new tracking tables):
- ai_calls: llm_usage rows for the calendar month, gated at the ONE LLM door
  (services/llm.call_llm) using the quota numbers get_ai_config carries on
  the caller's session — a rejected call makes no HTTP request and writes
  no llm_usage row.
- storage_bytes: SUM(item_proofs.file_size) — the one genuinely needed new
  column (app/migrate.py idempotent pattern), gated at the proof upload
  BEFORE the disk write + row insert.
- portals: clients with an enabled portal — portal views/tokens are not
  recorded anywhere (the portal JWT is stateless by design), so this is the
  countable portal state; gated at setup (passcode regen never consumes).

Limits ride the plan tiers: PLAN_LIMITS / DEFAULT_PLANS → Plan rows →
tenant.limits JSON (max_ai_calls / max_storage_bytes / max_portals).
Enforcement is 403 with an upgrade message — the same pattern the
users/projects quotas use. Storage never uses the 999999 count sentinel
(it is only ~1MB in bytes): unlimited there is None/absent.
"""
import json
import re
from pathlib import Path

import httpx
import pytest

from app.models.llm_usage import LlmUsage

REPO = Path(__file__).resolve().parent.parent
LLM_PY = REPO / "app/services/llm.py"
SETTINGS_PY = REPO / "app/services/settings_service.py"
PROOFS_PY = REPO / "app/routers/proofs.py"
PORTAL_PY = REPO / "app/routers/portal.py"

_PNG_BYTES = b"\x89PNG\r\n\x1a\n0123456789"  # 17 bytes of a valid-looking PNG


# ── helpers ──────────────────────────────────────────────────────────────


def _set_limits(db, tenant, **limits):
    """Write a limits JSON onto the tenant (the plan-propagated shape)."""
    db.refresh(tenant)
    tenant.limits = json.dumps(limits)
    db.commit()


def _seed_llm_calls(db, tenant, n):
    """Seed n llm_usage rows for this month (server-default created_at)."""
    for _ in range(n):
        db.add(LlmUsage(tenant_id=tenant.id, feature="ai", ok=True, latency_ms=10))
    db.commit()


def _llm_calls(db, tenant_id):
    return db.query(LlmUsage).filter(LlmUsage.tenant_id == tenant_id).count()


@pytest.fixture(autouse=True)
def _llm_db(monkeypatch):
    """call_llm writes its usage row via app.database.SessionLocal —
    tests route it to the in-memory SQLite (house pattern, test_llm_wrapper)."""
    from tests.conftest import TestSessionLocal

    monkeypatch.setattr("app.database.SessionLocal", TestSessionLocal)
    yield


def _patch_http_ok(monkeypatch):
    """httpx.Client → one OK response, no network."""
    attempts = []

    class _FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"answer": "ok", "sources": []}'}}]}

    class _FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            attempts.append(1)
            return _FakeResp()

    monkeypatch.setattr(httpx, "Client", _FakeClient)
    return attempts


def _configure_ai(client):
    resp = client.put("/api/ai/config", json={"api_key": "test-key"})
    assert resp.status_code == 200


def _project_with_item(db, tenant, user):
    from app.models.backlog_item import BacklogItem
    from app.models.client import Client
    from app.models.project import Project

    client = Client(tenant_id=tenant.id, name="FR-T6 Client")
    db.add(client)
    db.commit()
    db.refresh(client)
    project = Project(tenant_id=tenant.id, name="FR-T6 P", status="active",
                      client_id=client.id, project_manager_id=user.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    item = BacklogItem(tenant_id=tenant.id, project_id=project.id,
                       title="Proof item", status="Draft")
    db.add(item)
    db.commit()
    db.refresh(item)
    return project, item


def _two_clients(db, tenant):
    from app.models.client import Client

    c1 = Client(tenant_id=tenant.id, name="Portal One", contact_email="one@client.test")
    c2 = Client(tenant_id=tenant.id, name="Portal Two", contact_email="two@client.test")
    db.add_all([c1, c2])
    db.commit()
    db.refresh(c1)
    db.refresh(c2)
    return c1, c2


def _upload_proof(client, item, size=None, name="proof.png"):
    if size is None:
        payload = _PNG_BYTES
    elif size <= len(_PNG_BYTES):
        payload = _PNG_BYTES[:size]
    else:
        payload = _PNG_BYTES + b"0" * (size - len(_PNG_BYTES))
    return client.post(
        f"/api/backlog/{item.id}/proofs",
        data={"title": f"Proof {name}"},
        files={"file": (name, payload, "image/png")},
    )


# ── 1. AI quota — gated at the ONE LLM door ──────────────────────────────


def test_ai_quota_gates_at_the_llm_door(client, db, auth_user):
    """At the monthly limit, copilot chat 403s BEFORE any HTTP attempt and
    the rejected call writes no llm_usage row."""
    tenant, _ = auth_user["tenant"], auth_user["user"]
    _set_limits(db, tenant, max_ai_calls=3)
    _seed_llm_calls(db, tenant, 3)
    _configure_ai(client)

    resp = client.post("/api/ai/copilot/chat", json={"question": "hi"})
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert "Quota exceeded" in detail and "AI call limit is 3" in detail
    assert "Upgrade your plan" in detail
    # The rejected call is not metered — nothing was called
    assert _llm_calls(db, tenant.id) == 3


def test_ai_quota_meters_allowed_calls_then_gates(client, db, auth_user, monkeypatch):
    """Below the limit the call goes through (and meters); the row it writes
    counts toward the quota — the next call 403s."""
    tenant, _ = auth_user["tenant"], auth_user["user"]
    _set_limits(db, tenant, max_ai_calls=3)
    _seed_llm_calls(db, tenant, 2)
    _configure_ai(client)
    _patch_http_ok(monkeypatch)

    resp = client.post("/api/ai/copilot/chat", json={"question": "hi"})
    assert resp.status_code == 200
    assert _llm_calls(db, tenant.id) == 3  # the allowed call was metered

    resp = client.post("/api/ai/copilot/chat", json={"question": "again"})
    assert resp.status_code == 403
    assert _llm_calls(db, tenant.id) == 3  # still 3 — rejected call not metered


def test_ai_quota_unlimited_when_absent(client, db, auth_user, monkeypatch):
    """No limits JSON → unlimited (backward-compatible default)."""
    tenant, _ = auth_user["tenant"], auth_user["user"]
    assert tenant.limits is None
    _configure_ai(client)
    attempts = _patch_http_ok(monkeypatch)

    resp = client.post("/api/ai/copilot/chat", json={"question": "hi"})
    assert resp.status_code == 200
    assert len(attempts) == 1


def test_suggest_endpoint_propagates_the_quota_403(client, db, auth_user):
    """The suggest endpoints re-raise HTTPException (no 502 wrap) — the
    quota 403 reaches the client with its message, not a 502."""
    tenant, user = auth_user["tenant"], auth_user["user"]
    _set_limits(db, tenant, max_ai_calls=1)
    _seed_llm_calls(db, tenant, 1)
    _configure_ai(client)

    from app.models.client import Client
    from app.models.project import Project
    cl = Client(tenant_id=tenant.id, name="Vision Client")
    db.add(cl)
    db.commit()
    db.refresh(cl)
    project = Project(tenant_id=tenant.id, name="Vision P", status="active",
                      client_id=cl.id, project_manager_id=user.id)
    db.add(project)
    db.commit()
    db.refresh(project)

    resp = client.post("/api/ai/suggest-vision", json={"project_id": project.id})
    assert resp.status_code == 403
    assert "Quota exceeded" in resp.json()["detail"]


def test_get_ai_config_carries_the_quota_numbers(db, auth_user):
    """get_ai_config is the quota carrier: used + limit computed on the
    caller's session so the LLM door never opens its own."""
    from app.services.settings_service import get_ai_config

    tenant, _ = auth_user["tenant"], auth_user["user"]
    _set_limits(db, tenant, max_ai_calls=42)
    _seed_llm_calls(db, tenant, 2)
    config = get_ai_config(db, tenant.id)
    assert config["ai_calls_used"] == 2
    assert config["ai_calls_limit"] == 42


def test_call_llm_quota_raise_and_fail_open():
    """Service-level: at the limit → 403; without quota numbers → fail open."""
    from fastapi import HTTPException

    from app.services.llm import _enforce_ai_quota

    with pytest.raises(HTTPException) as exc:
        _enforce_ai_quota({"ai_calls_used": 3, "ai_calls_limit": 3})
    assert exc.value.status_code == 403

    # Unlimited sentinel, absent numbers, and no tenant config all fail open
    assert _enforce_ai_quota({"ai_calls_used": 999999, "ai_calls_limit": 999999}) is None
    assert _enforce_ai_quota({"ai_calls_used": 3}) is None
    assert _enforce_ai_quota({}) is None
    assert _enforce_ai_quota(None) is None


# ── 2. Storage quota — gated at the proof upload ─────────────────────────


def test_storage_quota_meters_and_gates_upload(client, db, auth_user):
    """The uploaded bytes meter into item_proofs.file_size; the upload that
    would exceed the quota 403s before any disk write or row insert."""
    tenant, user = auth_user["tenant"], auth_user["user"]
    _, item = _project_with_item(db, tenant, user)
    _set_limits(db, tenant, max_storage_bytes=30)

    resp = _upload_proof(client, item, size=12)
    assert resp.status_code == 201
    body = resp.json()

    from app.models.proof import ItemProof
    proof = db.query(ItemProof).filter(ItemProof.id == body["id"]).first()
    assert proof.file_size == 12  # the metering column is recorded

    resp = _upload_proof(client, item, size=19)
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert "storage limit is 30 B" in detail and "used: 12 B" in detail
    # The rejected upload wrote nothing
    assert db.query(ItemProof).filter(ItemProof.tenant_id == tenant.id).count() == 1

    # Dropping the limit below the current usage also blocks further uploads
    _set_limits(db, tenant, max_storage_bytes=5)
    resp = _upload_proof(client, item, size=1)
    assert resp.status_code == 403


def test_storage_quota_unlimited_when_absent(client, db, auth_user):
    """No limits JSON → unlimited storage (backward-compatible default)."""
    tenant, user = auth_user["tenant"], auth_user["user"]
    _, item = _project_with_item(db, tenant, user)

    resp = _upload_proof(client, item, size=12)
    assert resp.status_code == 201

    from app.models.proof import ItemProof
    proofs = db.query(ItemProof).filter(ItemProof.tenant_id == tenant.id).all()
    assert len(proofs) == 1 and proofs[0].file_size == 12


def test_check_storage_quota_bytes_semantics(db, auth_user):
    """Storage never uses the 999999 count sentinel: None/absent = unlimited;
    a real 50GB limit enforces (the count sentinel would shadow it)."""
    from fastapi import HTTPException

    from app.services.usage_service import check_storage_quota

    tenant, _ = auth_user["tenant"], auth_user["user"]

    # Absent → unlimited
    _set_limits(db, tenant, max_users=3)
    assert check_storage_quota(db, tenant, 10 ** 12) is None

    # A real limit (50GB) enforces — even though it is >= the count sentinel
    _set_limits(db, tenant, max_storage_bytes=50 * 1024 ** 3)
    with pytest.raises(HTTPException) as exc:
        check_storage_quota(db, tenant, 10 ** 12)
    assert exc.value.status_code == 403
    assert "50.0 GB" in exc.value.detail


# ── 3. Portal quota — gated at setup ─────────────────────────────────────


def test_portal_quota_gates_new_portal(client, db, auth_user):
    """Enabling a portal beyond the plan limit 403s; the first portal fits."""
    tenant, _ = auth_user["tenant"], auth_user["user"]
    c1, c2 = _two_clients(db, tenant)
    _set_limits(db, tenant, max_portals=1)

    resp = client.post(f"/api/clients/{c1.id}/portal", json={"passcode": "LongEnough1!"})
    assert resp.status_code == 200

    resp = client.post(f"/api/clients/{c2.id}/portal", json={"passcode": "LongEnough1!"})
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert "Quota exceeded: portals limit is 1 (current: 1)" in detail


def test_portal_quota_passcode_regen_never_consumes(client, db, auth_user):
    """Regenerating the passcode on an already-enabled portal does not hit
    the quota — only NEW portals consume capacity."""
    tenant, _ = auth_user["tenant"], auth_user["user"]
    c1, _ = _two_clients(db, tenant)
    _set_limits(db, tenant, max_portals=1)

    resp = client.post(f"/api/clients/{c1.id}/portal", json={"passcode": "LongEnough1!"})
    assert resp.status_code == 200
    resp = client.post(f"/api/clients/{c1.id}/portal", json={"passcode": "LongEnough2!"})
    assert resp.status_code == 200  # regen, not a new portal


def test_portal_quota_unlimited_when_absent(client, db, auth_user):
    """No limits JSON → unlimited portals."""
    c1, c2 = _two_clients(db, auth_user["tenant"])
    r1 = client.post(f"/api/clients/{c1.id}/portal", json={"passcode": "LongEnough1!"})
    r2 = client.post(f"/api/clients/{c2.id}/portal", json={"passcode": "LongEnough2!"})
    assert r1.status_code == 200 and r2.status_code == 200


def test_portal_count_matches_enabled_state(db, auth_user):
    """The counter meters portal_enabled clients with a passcode hash — the
    same state get_portal_client enforces at read time."""
    from app.services.usage_service import portals_enabled

    tenant, _ = auth_user["tenant"], auth_user["user"]
    c1, c2 = _two_clients(db, tenant)
    assert portals_enabled(db, tenant.id) == 0

    from app.services.auth import hash_password
    c1.portal_enabled = True
    c1.portal_passcode_hash = hash_password("LongEnough1!")
    db.commit()
    assert portals_enabled(db, tenant.id) == 1

    c2.portal_enabled = True  # enabled without a hash — not an active portal
    db.commit()
    assert portals_enabled(db, tenant.id) == 1


# ── 4. Exposure — the tenant plan/usage surface ──────────────────────────


def test_tenant_limits_exposes_the_new_counters(client, db, auth_user):
    """GET /tenant/limits carries AI/storage/portal in limits + current."""
    tenant, _ = auth_user["tenant"], auth_user["user"]
    _set_limits(db, tenant, max_ai_calls=100, max_storage_bytes=104857600, max_portals=1)
    _seed_llm_calls(db, tenant, 4)

    resp = client.get("/api/tenant/limits")
    assert resp.status_code == 200
    data = resp.json()
    assert data["limits"]["max_ai_calls"] == 100
    assert data["limits"]["max_storage_bytes"] == 104857600
    assert data["limits"]["max_portals"] == 1
    assert data["current"]["ai_calls"] == 4
    assert data["current"]["storage_bytes"] == 0
    assert data["current"]["portals"] == 0
    assert data["current"]["storage_display"] == "0 B / 100.0 MB"


def test_tenant_limits_unlimited_shapes(client, db, auth_user):
    """No limits JSON → 999999 for counts, None for storage, ∞ display."""
    resp = client.get("/api/tenant/limits")
    assert resp.status_code == 200
    data = resp.json()
    assert data["limits"]["max_ai_calls"] == 999999
    assert data["limits"]["max_storage_bytes"] is None
    assert data["limits"]["max_portals"] == 999999
    assert data["current"]["storage_display"].endswith("∞")


def test_usage_response_exposes_the_new_counters(client, db, auth_user):
    """GET /tenant/usage carries the FR-T6 counters."""
    tenant, _ = auth_user["tenant"], auth_user["user"]
    _set_limits(db, tenant, max_ai_calls=500, max_storage_bytes=1024, max_portals=2)
    _seed_llm_calls(db, tenant, 1)

    resp = client.get("/api/tenant/usage")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ai_calls"] == 1 and data["ai_calls_limit"] == 500
    assert data["storage_bytes"] == 0 and data["storage_limit"] == 1024
    assert data["portals"] == 0 and data["portals_limit"] == 2


def test_usage_history_carries_the_new_metrics(client, db, auth_user):
    """/tenant/usage/history returns counts + limits dicts — the new metrics
    flow through untouched (the JS usage card reads this shape)."""
    tenant, _ = auth_user["tenant"], auth_user["user"]
    _set_limits(db, tenant, max_ai_calls=7)
    _seed_llm_calls(db, tenant, 2)

    resp = client.get("/api/tenant/usage/history?days=1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["current"]["ai_calls"] == 2
    assert data["limits"]["ai_calls"] == 7
    assert data["current"]["storage_bytes"] == 0
    assert data["current"]["portals"] == 0


# ── 5. Plan tiers + idempotent migration ─────────────────────────────────


def test_default_plans_carry_the_new_limits():
    """The seed plans define the AI/storage/portal tier table."""
    from app.seed import DEFAULT_PLANS

    by_name = {p["name"]: p for p in DEFAULT_PLANS}
    assert by_name["Free"]["max_ai_calls"] == 100
    assert by_name["Free"]["max_storage_bytes"] == 100 * 1024 * 1024
    assert by_name["Free"]["max_portals"] == 1
    assert by_name["Team"]["max_ai_calls"] == 1_000
    assert by_name["Team"]["max_storage_bytes"] == 5 * 1024 ** 3
    assert by_name["Team"]["max_portals"] == 5
    assert by_name["Business"]["max_ai_calls"] == 10_000
    assert by_name["Business"]["max_storage_bytes"] == 20 * 1024 ** 3
    assert by_name["Business"]["max_portals"] == 25
    assert by_name["Enterprise"]["max_ai_calls"] == 100_000
    assert by_name["Enterprise"]["max_storage_bytes"] == 50 * 1024 ** 3
    assert by_name["Enterprise"]["max_portals"] == 999999


def test_plan_limits_dict_matches_default_plans():
    """PLAN_LIMITS (the spec-named tier table) mirrors DEFAULT_PLANS."""
    from app.models.tenant import PLAN_LIMITS
    from app.seed import DEFAULT_PLANS

    for pd in DEFAULT_PLANS:
        tier = PLAN_LIMITS[pd["name"].lower()]
        assert tier["ai_calls"] == pd["max_ai_calls"]
        assert tier["storage_bytes"] == pd["max_storage_bytes"]
        assert tier["portals"] == pd["max_portals"]


def test_migrate_backfills_plans_and_tenant_limits(db, auth_user, monkeypatch):
    """Existing Plan rows and tenant limits JSON pick up the new counters
    idempotently — NULL/missing keys only, never a rewrite of set values."""
    from app.models.plan import Plan
    from tests.conftest import TestSessionLocal

    monkeypatch.setattr("app.migrate.SessionLocal", TestSessionLocal)

    tenant = auth_user["tenant"]
    db.refresh(tenant)
    tenant.plan = "team"
    tenant.limits = json.dumps({"max_users": 25, "max_projects": 10})
    # A pre-FR-T6 plan row: the new columns are NULL
    legacy = Plan(name="Legacy Tier", max_users=9, max_projects=9, max_clients=9,
                  max_releases=9, max_backlog_items=9)
    db.add(legacy)
    db.commit()
    db.refresh(legacy)

    from app.migrate import _ensure_reference_data
    _ensure_reference_data()
    db.expire_all()

    team = db.query(Plan).filter(Plan.name == "Team").first()
    assert team.max_ai_calls == 1000
    assert team.max_storage_bytes == 5 * 1024 ** 3
    assert team.max_portals == 5

    limits = json.loads(db.query(type(tenant)).filter(type(tenant).id == tenant.id).first().limits)
    assert limits["max_users"] == 25  # untouched
    assert limits["max_ai_calls"] == 1000
    assert limits["max_storage_bytes"] == 5 * 1024 ** 3
    assert limits["max_portals"] == 5

    # Idempotent: a second run changes nothing
    _ensure_reference_data()
    db.expire_all()
    team2 = db.query(Plan).filter(Plan.name == "Team").first()
    assert (team2.max_ai_calls, team2.max_storage_bytes, team2.max_portals) == (1000, 5 * 1024 ** 3, 5)

    # A plan NOT in DEFAULT_PLANS stays unlimited (NULL) — no surprise 403s
    legacy2 = db.query(Plan).filter(Plan.name == "Legacy Tier").first()
    assert legacy2.max_ai_calls is None and legacy2.max_storage_bytes is None


# ── 6. Static pins — the verified shapes ─────────────────────────────────


def _read(path: Path) -> str:
    assert path.exists(), f"{path.name} missing"
    return path.read_text(encoding="utf-8")


def test_llm_door_gates_before_the_call():
    """The quota gate sits at the top of call_llm — before the timer and the
    try block, so a rejected call makes no HTTP request and writes no row."""
    src = _read(LLM_PY)
    body = re.search(r"^def call_llm\(.*?(?=^def |\Z)", src, re.S | re.M).group(0)
    gate = body.index("_enforce_ai_quota(tenant_config)")
    started = body.index("started = time.monotonic()")
    assert gate < started, "the quota gate must run before the call starts"


def test_quota_numbers_ride_in_get_ai_config():
    """get_ai_config returns the quota pair — the carrier for the ONE door."""
    src = _read(SETTINGS_PY)
    body = re.search(r"^def get_ai_config\(.*?(?=^def |\Z)", src, re.S | re.M).group(0)
    assert '"ai_calls_used"' in body and '"ai_calls_limit"' in body


def test_storage_gate_precedes_the_disk_write():
    """The storage check runs before the proof file is written to disk."""
    src = _read(PROOFS_PY)
    body = re.search(r"^def upload_proof\(.*?(?=^def |\Z)", src, re.S | re.M).group(0)
    gate = body.index("check_storage_quota(db, current_tenant, len(data))")
    write = body.index("(_PROOFS_DIR / filename).write_bytes(data)")
    assert gate < write, "the storage gate must run before the disk write"


def test_portal_gate_only_for_new_portals():
    """The portal quota check is conditional on a NOT-yet-enabled portal."""
    src = _read(PORTAL_PY)
    body = re.search(r"^def setup_portal\(.*?(?=^def |\Z)", src, re.S | re.M).group(0)
    assert "if not client.portal_enabled:" in body
    assert "check_quota(db, current_tenant, METRIC_PORTALS)" in body
