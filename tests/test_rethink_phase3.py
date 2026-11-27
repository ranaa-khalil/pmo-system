"""Tests for the AI & Copilot Rethink phase 3 — TDD.

1. SSE streaming for the reasoned path — POST /api/ai/copilot/chat/stream:
   token events as the writer generates, a tool event per tool round, ONE
   terminal event (final | degraded) carrying the full structured payload
   (mode, bundles_used, tools_used, degraded, references); the fast path /
   lookup mode short-circuits to plain 200 JSON; a mid-stream LLM failure
   emits the degraded digest — never a broken half answer.
2. Bounded read-only tool loop (Ask escalation) — a registry of READ-ONLY
   tools (the 5 grounding bundles + narrow scoped record fetches), max 3
   iterations, one call per iteration; malformed/unexecutable tool requests
   and iteration overrun fall through to the existing degraded fallback;
   tools_used rides alongside bundles_used (additive contract).
3. Metering — streamed reasoned calls label copilot.reasoned and record
   tokens from the final chunk; the fast path never meters.
"""
import json
from datetime import date, timedelta

import httpx
import pytest

import app.models  # noqa: F401
from app.models.ai_interaction import AiInteraction
from app.models.approval import ApprovalRequest
from app.models.backlog_item import BacklogItem
from app.models.llm_usage import LlmUsage
from app.models.project import Project
from app.models.release import Release
from app.models.risk import Risk
from app.models.stakeholder import Stakeholder
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.models.user_task import UserTask
from app.services import copilot as copilot_service
from app.services import grounding
from app.services import tools as tools_service
from app.services.llm import LLMStreamError

REPO = __import__("pathlib").Path(__file__).resolve().parent.parent

# ════════════════════ World fixtures ════════════════════

def _make_admin(db, email):
    admin = db.query(User).filter(User.email == email).first()
    if not admin:
        admin = User(email=email, name="Admin", hashed_password="x",
                     system_role="super_admin")
        db.add(admin)
        db.commit()
    return admin


@pytest.fixture()
def phase3_world(db):
    """Tenant + super-admin + project + item + overdue task + release."""
    tenant = Tenant(name="P3 Co", slug="p3-co", plan="enterprise")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    admin = _make_admin(db, "test@pmo.test")
    admin.active_tenant_id = tenant.id
    db.add(TenantMembership(user_id=admin.id, tenant_id=tenant.id, role="owner"))
    db.commit()
    db.refresh(admin)

    project = Project(name="P3 Cloud", client_id=1, tenant_id=tenant.id,
                      project_manager_id=admin.id)
    db.add(project)
    db.commit()
    db.refresh(project)

    item = BacklogItem(
        tenant_id=tenant.id, project_id=project.id, title="SSO login",
        epic="Auth", current_phase="Development", status="In Progress",
    )
    db.add(item)
    overdue = UserTask(
        tenant_id=tenant.id, project_id=project.id, assigned_to=admin.id,
        title="P3 overdue task",
        due_date=date.today() - timedelta(days=4), status="Pending",
    )
    db.add(overdue)
    release = Release(tenant_id=tenant.id, project_id=project.id,
                      version="1.0", name="P3 first drop", status="Planning",
                      target_date=str(date.today() + timedelta(days=10)))
    db.add(release)
    db.commit()
    for obj in (item, overdue, release):
        db.refresh(obj)
    return {"tenant": tenant, "admin": admin, "project": project,
            "item": item, "overdue": overdue, "release": release}


@pytest.fixture()
def two_tenant_world(db):
    """TWO tenants, each with a project + overdue task — the isolation world."""
    world = {}
    for letter in ("A", "B"):
        slug = f"p3-scope-{letter.lower()}"
        tenant = Tenant(name=f"P3 Scope {letter}", slug=slug, plan="enterprise")
        db.add(tenant)
        db.commit()
        db.refresh(tenant)

        admin = _make_admin(db, f"p3-scope-{letter.lower()}@pmo.test")
        admin.active_tenant_id = tenant.id
        db.add(TenantMembership(user_id=admin.id, tenant_id=tenant.id, role="owner"))
        db.commit()
        db.refresh(admin)

        project = Project(name=f"P3 Scope Cloud {letter}", client_id=1,
                          tenant_id=tenant.id, project_manager_id=admin.id)
        db.add(project)
        db.commit()
        db.refresh(project)

        overdue = UserTask(
            tenant_id=tenant.id, project_id=project.id, assigned_to=admin.id,
            title=f"Scope overdue {letter}",
            due_date=date.today() - timedelta(days=2), status="Pending",
        )
        db.add(overdue)
        db.commit()
        db.refresh(overdue)
        world[letter] = {"tenant": tenant, "admin": admin, "project": project,
                         "overdue": overdue}
    return world


@pytest.fixture()
def ai_configured(monkeypatch):
    """Mock the per-tenant AI config (no live calls). Patch the router namespace."""
    import app.routers.ai as ai_router

    monkeypatch.setattr(ai_router, "get_ai_config",
                        lambda db, tid: {"api_key": "k", "base_url": "u", "model": "m"})


@pytest.fixture()
def ai_unconfigured(monkeypatch):
    import app.routers.ai as ai_router

    monkeypatch.setattr(ai_router, "get_ai_config",
                        lambda db, tid: {"api_key": "", "base_url": "u", "model": "m"})


# ════════════════════ SSE helpers ════════════════════

def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """Parse an SSE body into [(event, data), ...]."""
    events = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        event, data = "message", ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data += line[len("data:"):].strip()
        if data:
            events.append((event, json.loads(data)))
    return events


# ════════════════════ 1. The SSE stream endpoint ════════════════════

class TestStreamEndpoint:
    """POST /api/ai/copilot/chat/stream — the reasoned path streams."""

    def test_reasoned_streams_tokens_then_final_payload(self, client, auth_headers,
                                                        phase3_world, ai_configured,
                                                        monkeypatch):
        """A broad question → SSE: token events carry the writer's deltas, the
        final event carries the full structured payload (mode, bundles_used,
        degraded, references, tools_used) — the non-streaming contract."""
        def fake_stream(*args, **kwargs):
            yield '{"answer": "Answer '
            yield 'part '
            yield 'one.", "sources": []}'

        monkeypatch.setattr("app.services.llm.stream_llm", fake_stream)
        resp = client.post(
            "/api/ai/copilot/chat/stream",
            json={"question": "what should I do next?"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse(resp.text)
        tokens = [data for event, data in events if event == "token"]
        assert [t["delta"] for t in tokens] == ["Answer ", "part ", "one."]
        finals = [data for event, data in events if event == "final"]
        assert len(finals) == 1, "exactly ONE terminal event"
        payload = finals[0]
        assert payload["answer"] == "Answer part one."
        assert payload["mode"] == "reasoned"
        assert payload["degraded"] is False
        assert payload["bundles_used"] == list(grounding.BUNDLES)
        assert payload["tools_used"] == []
        assert isinstance(payload["references"], list)
        assert isinstance(payload["sources"], list)
        assert payload["interaction_id"]
        assert isinstance(payload["counts"], dict)

    def test_final_event_persists_the_interaction(self, client, auth_headers,
                                                  phase3_world, ai_configured,
                                                  monkeypatch, db):
        """The streamed turn persists the same AiInteraction audit row."""
        monkeypatch.setattr(
            "app.services.llm.stream_llm",
            lambda *a, **k: iter(['{"answer": "Done.", "sources": []}']))
        resp = client.post(
            "/api/ai/copilot/chat/stream",
            json={"question": "what should I do next?"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        payload = [d for e, d in _parse_sse(resp.text) if e == "final"][0]
        row = db.query(AiInteraction).filter(
            AiInteraction.id == payload["interaction_id"]).first()
        assert row is not None and row.kind == "query"
        assert row.answer == "Done."

    def test_fast_lookup_short_circuits_to_plain_json(self, client, auth_headers,
                                                      phase3_world, ai_configured,
                                                      monkeypatch):
        """A lookup question → 200 JSON immediately (instant, no SSE) — and
        ZERO LLM trips."""
        def _no_llm(*a, **k):
            raise AssertionError("the fast path must not call the LLM")

        monkeypatch.setattr(copilot_service, "_call_llm", _no_llm)
        monkeypatch.setattr("app.services.llm.stream_llm", _no_llm)
        resp = client.post(
            "/api/ai/copilot/chat/stream",
            json={"question": "how many approvals are pending?"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("application/json")
        body = resp.json()
        assert body["mode"] == "lookup"
        assert body["degraded"] is False
        assert body["bundles_used"] == ["release_readiness"]
        assert "Release readiness" in body["answer"]

    def test_mid_stream_failure_emits_the_degraded_digest(self, client, auth_headers,
                                                          phase3_world,
                                                          ai_configured,
                                                          monkeypatch):
        """The LLM breaks after deltas were delivered → a degraded event with
        the digest fallback — never a broken half answer."""
        def broken_stream(*args, **kwargs):
            yield "Partial "
            raise LLMStreamError("stream broke after 1 deltas: RuntimeError")

        monkeypatch.setattr("app.services.llm.stream_llm", broken_stream)
        resp = client.post(
            "/api/ai/copilot/chat/stream",
            json={"question": "what should I do next?"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        events = _parse_sse(resp.text)
        names = [e for e, _ in events]
        assert "final" not in names, "no success final after a break"
        degraded = [d for e, d in events if e == "degraded"]
        assert len(degraded) == 1, "ONE degraded terminal event"
        payload = degraded[0]
        assert payload["degraded"] is True
        assert payload["mode"] == "reasoned"
        assert payload["answer"], "the digest must still answer"
        assert "live records" in payload["answer"] or "Project health" in payload["answer"]

    def test_tool_round_emits_a_tool_event(self, client, auth_headers,
                                           phase3_world, ai_configured,
                                           monkeypatch):
        """A writer that escalates to a tool: the tool reply streams NO tokens,
        a tool event carries the round, and the final payload lists
        tools_used."""
        replies = [
            ['{"tool": "overdue_items", "args": {}}'],
            ['{"answer": "Work ', 'the overdue task.", "sources": []}'],
        ]
        calls = []

        def fake_stream(*args, **kwargs):
            calls.append(1)
            yield from replies[len(calls) - 1]

        monkeypatch.setattr("app.services.llm.stream_llm", fake_stream)
        resp = client.post(
            "/api/ai/copilot/chat/stream",
            json={"question": "which tasks are overdue and what should I do?"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        events = _parse_sse(resp.text)
        tools = [d for e, d in events if e == "tool"]
        assert len(tools) == 1 and tools[0]["tool"] == "overdue_items"
        assert tools[0]["records"] == 1
        # The tool-request reply never streamed as tokens.
        token_text = "".join(d["delta"] for e, d in events if e == "token")
        assert "tool" not in token_text
        payload = [d for e, d in events if e == "final"][0]
        assert payload["tools_used"] == ["overdue_items"]
        assert payload["degraded"] is False
        assert "overdue task" in payload["answer"]

    def test_invalid_mode_is_a_400(self, client, auth_headers, phase3_world,
                                   ai_configured):
        resp = client.post(
            "/api/ai/copilot/chat/stream",
            json={"question": "hello", "mode": "bogus"},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "mode" in resp.json()["detail"].lower()

    def test_unconfigured_ai_is_a_400(self, client, auth_headers, phase3_world,
                                      ai_unconfigured):
        resp = client.post(
            "/api/ai/copilot/chat/stream",
            json={"question": "hello"},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "not configured" in resp.json()["detail"].lower()

    def test_quota_403_before_the_stream_starts(self, client, auth_headers,
                                                phase3_world, ai_configured,
                                                monkeypatch):
        """The plan gate is a deliberate hard stop — 403 with clean status
        semantics BEFORE any SSE bytes."""
        from fastapi import HTTPException

        def quota(*a, **k):
            raise HTTPException(403, "Quota exceeded: AI call limit is 0/month")

        monkeypatch.setattr("app.services.llm.enforce_ai_quota", quota)
        resp = client.post(
            "/api/ai/copilot/chat/stream",
            json={"question": "what should I do next?"},
            headers=auth_headers,
        )
        assert resp.status_code == 403


# ════════════════════ 2. The streaming door (services/llm.py) ════════════════════

class _FakeStreamResp:
    def __init__(self, lines, break_after=None):
        self.status_code = 200
        self._lines = lines
        self._break_after = break_after

    def iter_lines(self):
        for i, line in enumerate(self._lines):
            if self._break_after is not None and i >= self._break_after:
                raise RuntimeError("connection reset")
            yield line


class _FakeStreamCtx:
    def __init__(self, resp):
        self._resp = resp

    def __enter__(self):
        return self._resp

    def __exit__(self, *a):
        return False


class _FakeStreamClient:
    def __init__(self, resp=None, **kwargs):
        self._resp = resp or _FakeStreamResp([
            'data: {"choices":[{"delta":{"content":"Hel"}}]}',
            'data: {"choices":[{"delta":{"content":"lo"}}]}',
            'data: {"choices":[{"delta":{}}],"usage":{"prompt_tokens":11,"completion_tokens":7}}',
            "data: [DONE]",
        ])

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def stream(self, method, url, **kwargs):
        return _FakeStreamCtx(self._resp)


class TestStreamingDoor:
    """stream_llm — the ONE door, stream shape."""

    def _tenant_config(self, world):
        return {"api_key": "k", "base_url": "b", "model": "m",
                "tenant_id": world["tenant"].id}

    def test_yields_deltas_and_records_usage_from_the_final_chunk(self, db,
                                                                  phase3_world,
                                                                  monkeypatch):
        from tests.conftest import TestSessionLocal

        monkeypatch.setattr("app.database.SessionLocal", TestSessionLocal)
        monkeypatch.setattr(httpx, "Client", _FakeStreamClient)
        out = list(__import__("app.services.llm", fromlist=["stream_llm"]).stream_llm(
            "s", "u", tenant_config=self._tenant_config(phase3_world),
            feature="copilot.reasoned",
        ))
        assert out == ["Hel", "lo"]
        row = db.query(LlmUsage).order_by(LlmUsage.id.desc()).first()
        assert row.feature == "copilot.reasoned"
        assert row.ok is True
        assert row.prompt_tokens == 11
        assert row.completion_tokens == 7

    def test_mid_stream_break_raises_and_records_the_failure(self, db,
                                                             phase3_world,
                                                             monkeypatch):
        from tests.conftest import TestSessionLocal

        monkeypatch.setattr("app.database.SessionLocal", TestSessionLocal)

        class _Broken(_FakeStreamClient):
            def __init__(self, **kwargs):
                super().__init__()
                self._resp = _FakeStreamResp(
                    ['data: {"choices":[{"delta":{"content":"Par"}}]}',
                     'data: {"choices":[{"delta":{"content":"tial"}}]}'],
                    break_after=1,
                )

        monkeypatch.setattr(httpx, "Client", _Broken)
        import app.services.llm as llm_mod

        with pytest.raises(LLMStreamError):
            list(llm_mod.stream_llm(
                "s", "u", tenant_config=self._tenant_config(phase3_world),
                feature="copilot.reasoned",
            ))
        row = db.query(LlmUsage).order_by(LlmUsage.id.desc()).first()
        assert row.feature == "copilot.reasoned"
        assert row.ok is False

    def test_unconfigured_key_raises(self, monkeypatch):
        import app.services.llm as llm_mod

        with pytest.raises(LLMStreamError):
            list(llm_mod.stream_llm("s", "u", tenant_config={"api_key": ""}))

    def test_bad_status_is_retried_then_raises(self, monkeypatch):
        import app.services.llm as llm_mod

        attempts = []

        class _BadStatus(_FakeStreamClient):
            def __init__(self, **kwargs):
                super().__init__()
                attempts.append(1)

            def stream(self, method, url, **kwargs):
                ctx = _FakeStreamCtx(_FakeStreamResp([]))
                ctx._resp.status_code = 500
                return ctx

        monkeypatch.setattr(httpx, "Client", _BadStatus)
        with pytest.raises(LLMStreamError):
            list(llm_mod.stream_llm("s", "u", tenant_config={"api_key": "k", "base_url": "b", "model": "m"}))
        assert len(attempts) == 2, "exactly one retry on a pre-stream failure"


# ════════════════════ 3. The bounded read-only tool loop ════════════════════

class TestToolRegistry:
    """The registry: names, compact records, READ-ONLY, tenant-scoped."""

    def test_registry_names(self):
        assert set(tools_service.REGISTRY) == {
            "project_health", "release_readiness", "risk_exposure",
            "stakeholder_map", "backlog_shape", "overdue_items",
            "project_releases",
        }
        assert tools_service.TOOL_LOOP_MAX_ITERATIONS == 3

    def test_every_tool_returns_compact_records_and_writes_nothing(self, db,
                                                                   phase3_world):
        """Run every registry tool: records carry entity_type/entity_id/title
        and NO row changes anywhere (read-only by construction)."""
        world = phase3_world
        tables = (UserTask, Release, Risk, Project, BacklogItem, Stakeholder,
                  ApprovalRequest, AiInteraction)

        def counts():
            return {t.__name__: db.query(t).count() for t in tables}

        before = counts()
        proj_ids = [world["project"].id]
        for name in tools_service.REGISTRY:
            result = tools_service.run_tool(db, world["admin"], world["tenant"],
                                            name, {}, proj_ids)
            assert "error" not in result, f"{name} errored: {result.get('error')}"
            for rec in result["records"]:
                assert rec.get("entity_type"), f"{name}: missing entity_type"
                assert rec.get("entity_id") is not None
                assert rec.get("title")
        # overdue_items surfaces the overdue task with its computed fields.
        overdue = tools_service.run_tool(db, world["admin"], world["tenant"],
                                         "overdue_items", {}, proj_ids)
        assert overdue["counts"]["overdue_items"] == 1
        rec = overdue["records"][0]
        assert rec["entity_id"] == world["overdue"].id
        assert rec["days_overdue"] == 4
        # project_releases surfaces the release.
        releases = tools_service.run_tool(db, world["admin"], world["tenant"],
                                          "project_releases", {}, proj_ids)
        assert releases["records"][0]["entity_id"] == world["release"].id
        assert counts() == before, "a tool wrote — the registry must be read-only"

    def test_out_of_scope_project_arg_is_rejected(self, db, two_tenant_world):
        """An explicit project_id outside the caller's scope (another tenant's)
        returns an error record — never data (the isolation tightening point)."""
        a, b = two_tenant_world["A"], two_tenant_world["B"]
        result = tools_service.run_tool(
            db, a["admin"], a["tenant"], "overdue_items",
            {"project_id": b["project"].id}, [a["project"].id],
        )
        assert result.get("error") == "project not in your visible scope"
        assert result.get("records") is None

    def test_in_scope_project_arg_narrows(self, db, two_tenant_world):
        a = two_tenant_world["A"]
        result = tools_service.run_tool(
            db, a["admin"], a["tenant"], "overdue_items",
            {"project_id": a["project"].id}, [a["project"].id],
        )
        assert "error" not in result
        assert [r["entity_id"] for r in result["records"]] == [a["overdue"].id]

    def test_unknown_tool_and_bad_args_error(self, db, phase3_world):
        world = phase3_world
        unknown = tools_service.run_tool(db, world["admin"], world["tenant"],
                                         "bogus_tool", {}, [world["project"].id])
        assert "unknown tool" in unknown.get("error", "")
        bad_args = tools_service.run_tool(db, world["admin"], world["tenant"],
                                          "overdue_items", "junk",
                                          [world["project"].id])
        assert "args" in bad_args.get("error", "")
        bad_pid = tools_service.run_tool(db, world["admin"], world["tenant"],
                                         "overdue_items", {"project_id": "abc"},
                                         [world["project"].id])
        assert "integer" in bad_pid.get("error", "")


class TestToolLoop:
    """The bounded loop: max 3 iterations, one call per iteration; malformed
    requests and overrun → the degraded fallback; tools_used additive."""

    def test_loop_is_bounded_at_three_iterations(self, client, auth_headers,
                                                 phase3_world, ai_configured,
                                                 monkeypatch):
        """A writer that keeps requesting tools: 3 tool rounds run, the 4th
        request hits the cap → the degraded fallback."""
        tool_reply = json.dumps({"tool": "overdue_items", "args": {}})
        calls = []

        def fake_llm(*a, **k):
            calls.append(1)
            return tool_reply

        monkeypatch.setattr(copilot_service, "_call_llm", fake_llm)
        resp = client.post(
            "/api/ai/copilot/chat",
            json={"question": "what should I do next?"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["degraded"] is True, "iteration overrun degrades"
        assert len(calls) == 4, "1 initial + 3 tool rounds — then the cap"
        assert body["tools_used"] == ["overdue_items"] * 3

    def test_malformed_tool_request_degrades(self, client, auth_headers,
                                             phase3_world, ai_configured,
                                             monkeypatch):
        """An unexecutable tool request (unknown tool) → the degraded fallback
        immediately — the writer never gets garbage back."""
        calls = []

        def fake_llm(*a, **k):
            calls.append(1)
            return json.dumps({"tool": "bogus_tool", "args": {}})

        monkeypatch.setattr(copilot_service, "_call_llm", fake_llm)
        resp = client.post(
            "/api/ai/copilot/chat",
            json={"question": "what should I do next?"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["degraded"] is True
        assert len(calls) == 1, "no second round after a malformed request"

    def test_success_adds_tools_used_and_cites_tool_records(self, client,
                                                            auth_headers,
                                                            phase3_world,
                                                            ai_configured,
                                                            monkeypatch):
        """One tool round then the answer: tools_used rides alongside
        bundles_used, and the answer's citation of a TOOL-surfaced record
        validates into a clickable reference."""
        overdue_id = phase3_world["overdue"].id
        calls = []

        def fake_llm(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                return json.dumps({"tool": "overdue_items", "args": {}})
            return json.dumps({
                "answer": f"Work Task {overdue_id} first — it is overdue.",
                "sources": [f"Task {overdue_id}"],
            })

        monkeypatch.setattr(copilot_service, "_call_llm", fake_llm)
        resp = client.post(
            "/api/ai/copilot/chat",
            json={"question": "which tasks are overdue and what should I do?"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["degraded"] is False
        assert body["mode"] == "reasoned"
        assert body["tools_used"] == ["overdue_items"]
        assert body["bundles_used"] == list(grounding.BUNDLES)
        ref = next(r for r in body["references"]
                   if r["entity_id"] == overdue_id and r["entity_type"] == "user_task")
        assert ref["url"] == "/tasks"
        # The audit trail carries the validated sources.
        row = db_query_interaction(client, body["interaction_id"])
        assert row is not None

    def test_tenant_isolation_through_the_loop(self, client, auth_headers,
                                               two_tenant_world, ai_configured,
                                               monkeypatch):
        """User A's loop requests tenant B's project → the tool errors → the
        degraded fallback; B's records never appear in the answer."""
        a, b = two_tenant_world["A"], two_tenant_world["B"]
        calls = []

        def fake_llm(*args, user_prompt=None, **k):
            calls.append(1)
            if len(calls) == 1:
                return json.dumps({"tool": "overdue_items",
                                   "args": {"project_id": b["project"].id}})
            raise AssertionError("no second round after an out-of-scope request")

        monkeypatch.setattr(copilot_service, "_call_llm", fake_llm)
        resp = client.post(
            "/api/ai/copilot/chat",
            json={"question": "which project has the most overdue items and who owns them?"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["degraded"] is True
        assert b["overdue"].title not in body["answer"]
        assert b["project"].name not in body["answer"]
        for ref in body["references"]:
            assert ref.get("project_id") != b["project"].id

    def test_rule_matched_questions_get_no_tools(self, client, auth_headers,
                                                 phase3_world, ai_configured,
                                                 monkeypatch):
        """A question the selection rules resolve → the plain writer, no tool
        round (tools_used stays empty)."""
        seen = {}

        def fake_llm(system, user, *a, **k):
            seen["system"] = system
            seen["user"] = user
            return json.dumps({"answer": "Two risks.", "sources": []})

        monkeypatch.setattr(copilot_service, "_call_llm", fake_llm)
        resp = client.post(
            "/api/ai/copilot/chat",
            json={"question": "any risks or approvals I should know about?"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["degraded"] is False
        assert body["tools_used"] == []
        assert body["bundles_used"] == [
            "project_health", "release_readiness", "risk_exposure",
        ]
        assert "AVAILABLE TOOLS" not in seen["user"]
        assert seen["system"] == copilot_service.CHAT_SYSTEM_PROMPT

    def test_tool_loop_labels_copilot_reasoned(self, client, auth_headers,
                                               phase3_world, ai_configured,
                                               monkeypatch):
        """The loop is part of reasoned: every writer call labels
        copilot.reasoned (tokens recorded as today)."""
        import app.services.llm as llm_mod

        captured = []

        def fake_call(system, user, tenant_config=None, max_tokens=1500,
                      json_mode=False, feature="ai"):
            captured.append(feature)
            if len(captured) == 1:
                return json.dumps({"tool": "overdue_items", "args": {}})
            return json.dumps({"answer": "Work the overdue task.", "sources": []})

        monkeypatch.setattr(llm_mod, "call_llm", fake_call)
        resp = client.post(
            "/api/ai/copilot/chat",
            json={"question": "what should I do next?"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert captured == ["copilot.reasoned", "copilot.reasoned"]


def db_query_interaction(client, interaction_id):
    """Read the audit row through the app's overridden session."""
    from app.database import get_db

    gen = client.app.dependency_overrides[get_db]()
    db = next(gen)
    try:
        return db.query(AiInteraction).filter(
            AiInteraction.id == interaction_id).first()
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


# ════════════════════ 4. Routing + parsing units ════════════════════

class TestRoutingUnits:
    def test_resolve_mode(self):
        assert copilot_service.resolve_mode("how many approvals", "auto") == "lookup"
        assert copilot_service.resolve_mode("what is overdue", "auto") == "lookup"
        assert copilot_service.resolve_mode("what should I do next?", "auto") == "reasoned"
        assert copilot_service.resolve_mode("anything", "lookup") == "lookup"
        assert copilot_service.resolve_mode("how many approvals", "reasoned") == "reasoned"
        with pytest.raises(ValueError):
            copilot_service.resolve_mode("hello", "bogus")

    def test_question_needs_tools(self):
        assert copilot_service._question_needs_tools("what should I do next?") is True
        assert copilot_service._question_needs_tools(
            "which project has the most overdue work and what should move first?") is True
        assert copilot_service._question_needs_tools("any risks or approvals?") is False
        assert copilot_service._question_needs_tools("what is the backlog shape?") is False

    def test_tool_request_parsing(self):
        assert copilot_service._tool_request(
            {"tool": "overdue_items", "args": {"project_id": 3}}
        ) == ("overdue_items", {"project_id": 3})
        assert copilot_service._tool_request({"tool": "overdue_items"}) == ("overdue_items", {})
        # An answer with a stray tool key is an answer.
        assert copilot_service._tool_request(
            {"answer": "done", "sources": [], "tool": "x"}) is None
        # Malformed shapes degrade.
        assert copilot_service._tool_request({"tool": ""}) is None
        assert copilot_service._tool_request({"tool": 7}) is None
        assert copilot_service._tool_request({"tool": "x", "args": "junk"}) is None
        assert copilot_service._tool_request({"answer": "hi"}) is None

    def test_registry_prompt_lists_every_tool(self):
        prompt = tools_service.tool_registry_prompt()
        for name in tools_service.REGISTRY:
            assert name in prompt
        assert "read-only" in prompt


# ════════════════════ 5. Streaming client statics ════════════════════

class TestStreamStatics:
    """The drawer's send path: fetch + ReadableStream (not EventSource), the
    final-event finish, and the non-streaming fallback."""

    def _read(self, rel):
        return (REPO / rel).read_text()

    def test_copilot_js_uses_fetch_readable_stream(self):
        js = self._read("app/static/js/app/domains/copilot.js")
        assert "/api/ai/copilot/chat/stream" in js
        assert "getReader()" in js, "fetch + ReadableStream, NOT EventSource"
        assert "text/event-stream" in js
        assert "EventSource" not in js
        assert "event === 'token'" in js
        assert "event === 'final' || ev.event === 'degraded'" in js
        assert "event === 'error'" in js
        # The fallback: the existing non-streaming call on any stream failure.
        assert "'/ai/copilot/chat'" in js

    def test_copilot_js_parses_sse_and_renders_tool_status(self):
        js = self._read("app/static/js/app/domains/copilot.js")
        assert "_parseSSE" in js
        assert "copilotStreaming" in js
        assert "toolStatus" in js
        # Bearer auth rides on the streaming fetch.
        assert "Authorization" in js

    def test_drawer_gates_the_typing_indicator_and_shows_tool_status(self):
        html = self._read("app/templates/pmo/shell/copilot_drawer.html")
        assert "copilotBusy && !copilotStreaming" in html
        assert "msg.toolStatus" in html

    def test_cache_bust_pins_bumped_together(self):
        app_js = self._read("app/static/js/app/pmo-app.js")
        import re
        versions = set(re.findall(r"from '\./domains/[a-z_]+\.js\?v=([a-z0-9]+)'", app_js))
        assert versions == {"20261126d"}
        index = self._read("app/templates/index.html")
        assert "tailwind.compiled.css?v=20261126d" in index
