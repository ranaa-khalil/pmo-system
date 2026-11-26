"""Tests for the AI & Copilot Rethink slice 2 contracts — TDD.

1. Grounding bundles — five deterministic bundles ({bundle, scope, records[],
   counts{}, notes[]}) fetched through the ONE tenant_scoped seam; every
   record carries entity_type/entity_id/title; build_context is a facade
   over the bundles (chat keeps working — see the parity-gate tests).
2. Orchestration — copilot_chat routes intent rules-first: the FAST path
   answers lookups from the bundles with ZERO LLM tokens (no llm_usage row,
   no quota burn), the REASONED path writes with ONE repair retry and
   degrades to the deterministic digest when the LLM is down/unparseable
   (never a raw 502; a quota 403 keeps propagating).
3. Metering — llm_usage rows carry per-capability labels (copilot.reasoned /
   copilot.briefing) and the nullable prompt/completion token columns;
   /tenant/usage + /tenant/limits expose burn per capability.
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
from app.models.risk import Risk
from app.models.stakeholder import Stakeholder
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.models.user_task import UserTask
from app.services import copilot as copilot_service
from app.services import grounding
from app.services.llm import FALLBACK_TEXT

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
def copilot_world(db):
    """Tenant + super-admin + project + backlog item (the chat tests' pattern)."""
    tenant = Tenant(name="S2 Ref Co", slug="s2-ref-co", plan="enterprise")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    admin = _make_admin(db, "test@pmo.test")
    admin.active_tenant_id = tenant.id
    db.add(TenantMembership(user_id=admin.id, tenant_id=tenant.id, role="owner"))
    db.commit()
    db.refresh(admin)

    project = Project(name="S2 Cloud", client_id=1, tenant_id=tenant.id,
                      project_manager_id=admin.id)
    db.add(project)
    db.commit()
    db.refresh(project)

    item = BacklogItem(
        tenant_id=tenant.id, project_id=project.id, title="SSO login",
        epic="Auth", current_phase="Development", status="In Progress",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"tenant": tenant, "admin": admin, "project": project, "item": item}


@pytest.fixture()
def scoping_world(db):
    """TWO tenants, each with a full data set — the bundle-scoping world."""
    world = {}
    for letter in ("A", "B"):
        slug = f"s2-scope-{letter.lower()}"
        tenant = Tenant(name=f"S2 Scope {letter}", slug=slug, plan="enterprise")
        db.add(tenant)
        db.commit()
        db.refresh(tenant)

        admin = _make_admin(db, f"s2-scope-{letter.lower()}@pmo.test")
        admin.active_tenant_id = tenant.id
        db.add(TenantMembership(user_id=admin.id, tenant_id=tenant.id, role="owner"))
        db.commit()
        db.refresh(admin)

        project = Project(name=f"S2 Scope Cloud {letter}", client_id=1,
                          tenant_id=tenant.id, project_manager_id=admin.id)
        db.add(project)
        db.commit()
        db.refresh(project)

        item = BacklogItem(tenant_id=tenant.id, project_id=project.id,
                           title=f"Scope item {letter}", epic="Auth",
                           current_phase="Development", status="In Progress")
        db.add(item)
        risk = Risk(tenant_id=tenant.id, project_id=project.id,
                    title=f"Scope vendor delay {letter}", severity="High",
                    probability="Likely", status="Open")
        db.add(risk)
        approval = ApprovalRequest(tenant_id=tenant.id, project_id=project.id,
                                   title=f"Scope gate approval {letter}",
                                   request_type="phase_gate", status="Pending")
        db.add(approval)
        stakeholder = Stakeholder(tenant_id=tenant.id, project_id=project.id,
                                  name=f"Scope Owner {letter}",
                                  role_name="Product Owner", raci_type="A")
        db.add(stakeholder)
        overdue = UserTask(
            tenant_id=tenant.id, project_id=project.id, assigned_to=admin.id,
            title=f"Scope overdue task {letter}",
            due_date=date.today() - timedelta(days=3), status="Pending",
        )
        db.add(overdue)
        db.commit()
        for obj in (item, risk, approval, stakeholder, overdue):
            db.refresh(obj)
        world[letter] = {"tenant": tenant, "admin": admin, "project": project,
                         "item": item, "risk": risk, "approval": approval,
                         "stakeholder": stakeholder, "overdue": overdue}
    return world


@pytest.fixture()
def ai_configured(monkeypatch):
    """Mock the per-tenant AI config (no live calls). Patch the router namespace."""
    import app.routers.ai as ai_router

    monkeypatch.setattr(ai_router, "get_ai_config",
                        lambda db, tid: {"api_key": "k", "base_url": "u", "model": "m"})


# ════════════════════ 1. Grounding bundles ════════════════════

class TestGroundingBundles:
    """The five bundles: contract shape + the tenant_scoped seam."""

    def test_all_five_bundles_exist(self):
        assert grounding.BUNDLES == (
            "project_health", "release_readiness", "risk_exposure",
            "stakeholder_map", "backlog_shape",
        )

    def test_bundle_contract_shape(self, db, copilot_world):
        """Every bundle carries {bundle, scope, records[], counts{}, notes[]}
        and every record has entity_type/entity_id/title (+ its section)."""
        world = copilot_world
        for name in grounding.BUNDLES:
            bundle = grounding.get_bundle(
                db, name, world["admin"], world["tenant"], [world["project"].id],
            )
            assert bundle["bundle"] == name
            assert bundle["scope"]["tenant_id"] == world["tenant"].id
            assert bundle["scope"]["project_ids"] == [world["project"].id]
            assert isinstance(bundle["records"], list)
            assert isinstance(bundle["counts"], dict)
            assert isinstance(bundle["notes"], list) and bundle["notes"]
            for rec in bundle["records"]:
                assert rec.get("entity_type"), f"{name}: record missing entity_type"
                assert rec.get("entity_id") is not None, f"{name}: record missing entity_id"
                assert rec.get("title"), f"{name}: record missing title"
                assert rec.get("section"), f"{name}: record missing its section tag"

    def test_unknown_bundle_raises_value_error(self, db, copilot_world):
        with pytest.raises(ValueError):
            grounding.get_bundle(
                db, "bogus_bundle", copilot_world["admin"],
                copilot_world["tenant"], [copilot_world["project"].id],
            )

    def test_every_bundle_is_scoped_through_the_seam(self, db, scoping_world):
        """Tenant A's bundles NEVER contain tenant B's records — every model
        query rides tenant_scoped() (the extraction is the tightening point)."""
        a, b = scoping_world["A"], scoping_world["B"]
        b_ids = {b["project"].id, b["item"].id, b["risk"].id,
                 b["approval"].id, b["stakeholder"].id, b["overdue"].id}
        for name in grounding.BUNDLES:
            bundle = grounding.get_bundle(
                db, name, a["admin"], a["tenant"], [a["project"].id],
            )
            for rec in bundle["records"]:
                assert rec.get("entity_id") not in b_ids, (
                    f"{name} leaked tenant B record {rec.get('entity_id')}"
                )
                assert rec.get("project_id") in (None, a["project"].id), (
                    f"{name} leaked tenant B project"
                )
        # The same holds for the assembled facade view.
        ctx = grounding.assemble(grounding.get_bundles(
            db, list(grounding.BUNDLES), a["admin"], a["tenant"], [a["project"].id],
        ))
        leaked = [r for key in ("open_risks", "pending_approvals", "aging_items",
                                "overdue_tasks", "at_risk_releases")
                  for r in ctx[key] if r.get("entity_id") in b_ids]
        assert leaked == [], "the facade view leaked tenant B records"

    def test_resolve_project_ids_hides_invisible_projects(self, db, scoping_world):
        """A project the user can't see (other tenant) yields [] — the same
        empty-context rule build_context always applied."""
        a, b = scoping_world["A"], scoping_world["B"]
        assert grounding.resolve_project_ids(
            db, a["admin"], a["tenant"], b["project"].id,
        ) == []
        assert grounding.resolve_project_ids(
            db, a["admin"], a["tenant"], a["project"].id,
        ) == [a["project"].id]

    def test_project_health_serves_the_needs_you_aggregate(self, db, scoping_world):
        """project_health carries identity, the schedule block, aging items,
        overdue tasks and predictive flags — the carved build_context."""
        a = scoping_world["A"]
        bundle = grounding.get_bundle(
            db, "project_health", a["admin"], a["tenant"], [a["project"].id],
        )
        sections = bundle["sections"]
        assert sections["overdue_tasks"], "the overdue task must surface"
        assert sections["overdue_tasks"][0]["entity_id"] == a["overdue"].id
        assert sections["overdue_tasks"][0]["days_overdue"] == 3
        assert bundle["counts"]["overdue_tasks"] == 1

    def test_risk_exposure_is_uncapped(self, db, copilot_world):
        """risk_exposure returns EVERY open risk — the legacy [:15] cap stays
        only in the assembled prompt view (assemble)."""
        from app.models.risk import Risk as RiskModel

        tid = copilot_world["tenant"].id
        for i in range(20):
            db.add(RiskModel(tenant_id=tid, project_id=copilot_world["project"].id,
                             title=f"Capped risk {i}", severity="Low",
                             probability="Rare", status="Open"))
        db.commit()
        bundle = grounding.get_bundle(
            db, "risk_exposure", copilot_world["admin"],
            copilot_world["tenant"], [copilot_world["project"].id],
        )
        assert bundle["counts"]["open_risks"] >= 20
        assert len(bundle["sections"]["open_risks"]) >= 20
        # The assembled facade keeps the legacy 15-cap for prompt parity.
        assembled = grounding.assemble([bundle])
        assert len(assembled["open_risks"]) <= 15

    def test_build_context_is_a_facade(self, db, copilot_world):
        """build_context still returns the legacy dict — same keys, now
        assembled from the bundles (behavior unchanged for chat)."""
        legacy_keys = {
            "projects", "project_identity", "portfolio_identity",
            "pending_approvals", "aging_items", "overdue_tasks",
            "at_risk_releases", "open_risks", "predictive_flags",
            "epic_tree", "schedule", "schedules",
        }
        ctx = copilot_service.build_context(
            db, copilot_world["admin"], copilot_world["tenant"],
            project_id=copilot_world["project"].id,
        )
        assert set(ctx.keys()) == legacy_keys
        assert ctx["pending_approvals"] == []  # none in this world
        assert ctx["projects"]  # the schedule/identity view


# ════════════════════ 2. The fast path ════════════════════

class TestFastPath:
    """Lookup questions answer from the bundles — ZERO LLM tokens."""

    def test_lookup_answers_without_the_llm(self, client, auth_headers,
                                            copilot_world, ai_configured,
                                            monkeypatch, db):
        """mode=auto + "how many approvals" → the fast path: a deterministic
        digest, mode="lookup", ZERO _call_llm calls, and NO llm_usage row."""
        def _no_llm(*a, **k):
            raise AssertionError("the fast path must not call the LLM")

        monkeypatch.setattr(copilot_service, "_call_llm", _no_llm)
        db.add(LlmUsage(tenant_id=copilot_world["tenant"].id, feature="sentinel",
                        ok=True, latency_ms=1))
        db.commit()
        resp = client.post(
            "/api/ai/copilot/chat",
            json={"question": "how many approvals are pending?",
                  "project_id": copilot_world["project"].id},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["mode"] == "lookup"
        assert body["degraded"] is False
        assert body["bundles_used"] == ["release_readiness"]
        assert "Release readiness" in body["answer"]
        assert "pending approval" in body["answer"].lower()
        # No usage row beyond the sentinel: the fast path never meters.
        assert db.query(LlmUsage).filter(LlmUsage.feature != "sentinel").count() == 0
        # The audit trail still lands.
        row = db.query(AiInteraction).filter(
            AiInteraction.id == body["interaction_id"]).first()
        assert row is not None and row.kind == "query"
        assert row.answer == body["answer"]

    def test_spelled_out_overdue_is_a_fast_lookup(self, client, auth_headers,
                                                  copilot_world, ai_configured,
                                                  monkeypatch):
        """The spelled-out "what is overdue" fires the fast path — the
        contraction "what's overdue?" stays on the reasoned writer (pinned by
        the chat contract tests)."""
        def _no_llm(*a, **k):
            raise AssertionError("the fast path must not call the LLM")

        monkeypatch.setattr(copilot_service, "_call_llm", _no_llm)
        resp = client.post(
            "/api/ai/copilot/chat",
            json={"question": "what is overdue"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "lookup"
        assert body["bundles_used"] == ["project_health"]

    def test_what_needs_me_spans_two_bundles(self, client, auth_headers,
                                             copilot_world, ai_configured,
                                             monkeypatch):
        """'what needs me' aggregates project_health (overdue/aging) AND
        release_readiness (pending approvals)."""
        def _no_llm(*a, **k):
            raise AssertionError("the fast path must not call the LLM")

        monkeypatch.setattr(copilot_service, "_call_llm", _no_llm)
        resp = client.post(
            "/api/ai/copilot/chat",
            json={"question": "what needs me"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "lookup"
        assert body["bundles_used"] == ["project_health", "release_readiness"]

    def test_mode_lookup_forces_the_fast_path(self, client, auth_headers,
                                              copilot_world, ai_configured,
                                              monkeypatch):
        """mode="lookup" with a question no rule matches → the orientation
        bundle, still zero LLM tokens."""
        def _no_llm(*a, **k):
            raise AssertionError("forced lookup must not call the LLM")

        monkeypatch.setattr(copilot_service, "_call_llm", _no_llm)
        resp = client.post(
            "/api/ai/copilot/chat",
            json={"question": "tell me about this place", "mode": "lookup"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "lookup"
        assert body["bundles_used"] == ["project_health"]
        assert body["degraded"] is False

    def test_invalid_mode_is_a_400(self, client, auth_headers, copilot_world,
                                   ai_configured):
        resp = client.post(
            "/api/ai/copilot/chat",
            json={"question": "hello", "mode": "bogus"},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "mode" in resp.json()["detail"].lower()


# ════════════════════ 3. The reasoned path ════════════════════

class TestReasonedPath:
    """Bundle selection → compact prompt → strict-JSON writer with ONE
    repair retry → validated citations; degraded fallback never raw."""

    def test_auto_routes_non_lookups_to_the_reasoned_path(self, client,
                                                          auth_headers,
                                                          copilot_world,
                                                          ai_configured,
                                                          monkeypatch):
        """mode=auto + "what should I do next?" → the reasoned path. The
        question matches NO selection rule → the FULL grounding (all five
        bundles), the same context the pre-facade chat assembled — general
        questions lose nothing."""
        seen = {}

        def fake_llm(system, user, *a, **k):
            seen["user"] = user
            return json.dumps({"answer": "Work the SSO login item first.",
                               "sources": []})

        monkeypatch.setattr(copilot_service, "_call_llm", fake_llm)
        resp = client.post(
            "/api/ai/copilot/chat",
            json={"question": "what should I do next?",
                  "project_id": copilot_world["project"].id},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["mode"] == "reasoned"
        assert body["degraded"] is False
        assert body["bundles_used"] == list(grounding.BUNDLES)
        assert "PROJECT DATA:" in seen["user"]
        assert "QUESTION:" in seen["user"]

    def test_rule_matched_selection_is_one_to_three_bundles(self, client,
                                                            auth_headers,
                                                            copilot_world,
                                                            ai_configured,
                                                            monkeypatch):
        """A question the rules can name → the spine (project_health) plus
        the named bundles, capped at three — the compact prompt carries only
        those bundles' records."""
        seen = {}

        def fake_llm(system, user, *a, **k):
            seen["user"] = user
            return json.dumps({"answer": "Two risks, one approval.", "sources": []})

        monkeypatch.setattr(copilot_service, "_call_llm", fake_llm)
        resp = client.post(
            "/api/ai/copilot/chat",
            json={"question": "any risks or approvals I should know about?"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "reasoned"
        assert body["bundles_used"] == [
            "project_health", "release_readiness", "risk_exposure",
        ]
        # The compact prompt carries only the selected bundles' sections —
        # no stakeholder/backlog prose for a risk+approval question.
        assert "STAKEHOLDERS" not in seen["user"]
        assert "BACKLOG" not in seen["user"]

    def test_mode_reasoned_forces_the_writer(self, client, auth_headers,
                                             copilot_world, ai_configured,
                                             monkeypatch):
        """mode="reasoned" with a lookup-shaped question → the writer runs
        (the fast rule is overridden)."""
        monkeypatch.setattr(
            copilot_service, "_call_llm",
            lambda *a, **k: json.dumps({"answer": "Answered.", "sources": []}),
        )
        resp = client.post(
            "/api/ai/copilot/chat",
            json={"question": "how many approvals", "mode": "reasoned"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "reasoned"

    def test_llm_down_degrades_to_the_digest(self, client, auth_headers,
                                             copilot_world, ai_configured,
                                             monkeypatch):
        """FALLBACK_TEXT (LLM down/timeout at the door) → the degraded digest
        over the already-fetched bundles — 200, never a raw 502."""
        monkeypatch.setattr(copilot_service, "_call_llm",
                            lambda *a, **k: FALLBACK_TEXT)
        resp = client.post(
            "/api/ai/copilot/chat",
            json={"question": "what should I do next?"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["degraded"] is True
        assert body["mode"] == "reasoned"
        assert body["answer"], "the digest must still answer the question"
        assert "Project health" in body["answer"] or "open risk" in body["answer"].lower()
        # Degraded answers cite only what the digest was rendered from.
        assert isinstance(body["references"], list)

    def test_unparseable_degrades_after_one_repair_retry(self, client,
                                                         auth_headers,
                                                         copilot_world,
                                                         ai_configured,
                                                         monkeypatch):
        """Garbage → ONE repair retry → still garbage → the degraded digest."""
        calls = []

        def fake_llm(*a, **k):
            calls.append(1)
            return "not json at all"

        monkeypatch.setattr(copilot_service, "_call_llm", fake_llm)
        resp = client.post(
            "/api/ai/copilot/chat",
            json={"question": "what should I do next?"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["degraded"] is True
        assert len(calls) == 2, "exactly ONE repair retry"
        assert body["answer"], "the degraded digest must still answer"

    def test_repair_retry_recovers(self, client, auth_headers, copilot_world,
                                   ai_configured, monkeypatch):
        """First reply unparseable, repair reply valid JSON → NOT degraded."""
        calls = []

        def fake_llm(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                return "oops {broken"
            return json.dumps({"answer": "Recovered answer.", "sources": []})

        monkeypatch.setattr(copilot_service, "_call_llm", fake_llm)
        resp = client.post(
            "/api/ai/copilot/chat",
            json={"question": "what should I do next?"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["degraded"] is False
        assert body["answer"] == "Recovered answer."

    def test_quota_403_keeps_propagating(self, client, auth_headers,
                                         copilot_world, ai_configured,
                                         monkeypatch):
        """The plan gate is a deliberate hard stop — the reasoned path must
        NOT swallow the 403 into a degraded digest."""
        from fastapi import HTTPException

        def quota_llm(*a, **k):
            raise HTTPException(403, "Quota exceeded: AI call limit is 0/month")

        monkeypatch.setattr(copilot_service, "_call_llm", quota_llm)
        resp = client.post(
            "/api/ai/copilot/chat",
            json={"question": "what should I do next?"},
            headers=auth_headers,
        )
        assert resp.status_code == 403


# ════════════════════ 4. Per-capability metering ════════════════════

class TestMetering:
    """Feature labels + nullable token columns + the per-capability views."""

    def test_reasoned_writer_labels_copilot_reasoned(self, client, auth_headers,
                                                     copilot_world,
                                                     ai_configured, monkeypatch):
        """The copilot writer's llm_usage row carries feature=copilot.reasoned
        (distinct from the legacy "ai" label)."""
        import app.services.llm as llm_mod

        captured = {}

        def fake_call(system, user, tenant_config=None, max_tokens=1500,
                      json_mode=False, feature="ai"):
            captured["feature"] = feature
            return json.dumps({"answer": "Answer.", "sources": []})

        monkeypatch.setattr(llm_mod, "call_llm", fake_call)
        resp = client.post(
            "/api/ai/copilot/chat",
            json={"question": "what should I do next?"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert captured["feature"] == "copilot.reasoned"

    def test_briefing_labels_copilot_briefing(self, client, auth_headers,
                                              copilot_world, ai_configured,
                                              monkeypatch):
        """The Today Brief narrative burn is labeled copilot.briefing."""
        import app.services.llm as llm_mod

        captured = {}

        def fake_call(system, user, tenant_config=None, max_tokens=1500,
                      json_mode=False, feature="ai"):
            captured["feature"] = feature
            return "One. Two. Three."

        monkeypatch.setattr(llm_mod, "call_llm", fake_call)
        resp = client.post("/api/ai/today-brief/narrative", headers=auth_headers)
        assert resp.status_code == 200
        assert captured["feature"] == "copilot.briefing"

    def test_usage_row_fills_tokens_from_the_provider_payload(self, db, monkeypatch):
        """The provider's usage payload fills the nullable token columns."""
        from tests.conftest import TestSessionLocal

        monkeypatch.setattr("app.database.SessionLocal", TestSessionLocal)

        class _FakeResp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": [{"message": {"content": "ok"}}],
                        "usage": {"prompt_tokens": 120, "completion_tokens": 45}}

        class _FakeClient:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def post(self, *a, **k):
                return _FakeResp()

        monkeypatch.setattr(httpx, "Client", _FakeClient)
        out = llm_mod_call(
            tenant_config={"api_key": "k", "base_url": "b", "model": "m"},
            feature="copilot.reasoned",
        )
        assert out == "ok"
        row = db.query(LlmUsage).order_by(LlmUsage.id.desc()).first()
        assert row.feature == "copilot.reasoned"
        assert row.prompt_tokens == 120
        assert row.completion_tokens == 45

    def test_usage_row_tokens_stay_null_without_a_payload(self, db, monkeypatch):
        """No usage payload in the provider reply → the columns stay NULL."""
        from tests.conftest import TestSessionLocal

        monkeypatch.setattr("app.database.SessionLocal", TestSessionLocal)

        class _FakeResp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": [{"message": {"content": "ok"}}]}

        class _FakeClient:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def post(self, *a, **k):
                return _FakeResp()

        monkeypatch.setattr(httpx, "Client", _FakeClient)
        llm_mod_call(tenant_config={"api_key": "k", "base_url": "b", "model": "m"})
        row = db.query(LlmUsage).order_by(LlmUsage.id.desc()).first()
        assert row.prompt_tokens is None
        assert row.completion_tokens is None

    def test_capability_breakdown_groups_by_feature(self, db, copilot_world):
        """ai_capability_breakdown: one entry per feature label with calls +
        token totals — the fast path (no row) never appears."""
        from app.services.usage_service import ai_capability_breakdown

        tid = copilot_world["tenant"].id
        prefix = date.today().strftime("%Y-%m")
        db.add(LlmUsage(tenant_id=tid, feature="copilot.reasoned", ok=True,
                        latency_ms=10, prompt_tokens=100, completion_tokens=20,
                        created_at=f"{prefix}-15T10:00:00"))
        db.add(LlmUsage(tenant_id=tid, feature="copilot.briefing", ok=True,
                        latency_ms=10, prompt_tokens=50, completion_tokens=10,
                        created_at=f"{prefix}-15T11:00:00"))
        db.add(LlmUsage(tenant_id=tid, feature="copilot.briefing", ok=True,
                        latency_ms=10, prompt_tokens=30, completion_tokens=5,
                        created_at=f"{prefix}-16T11:00:00"))
        db.commit()
        breakdown = ai_capability_breakdown(db, tid)
        assert breakdown["copilot.reasoned"] == {
            "calls": 1, "prompt_tokens": 100, "completion_tokens": 20,
        }
        assert breakdown["copilot.briefing"] == {
            "calls": 2, "prompt_tokens": 80, "completion_tokens": 15,
        }

    def test_tenant_usage_exposes_ai_capabilities(self, client, auth_headers,
                                                  copilot_world, db):
        """/tenant/usage carries the per-capability breakdown."""
        from datetime import date as _date

        prefix = _date.today().strftime("%Y-%m")
        db.add(LlmUsage(tenant_id=copilot_world["tenant"].id,
                        feature="copilot.reasoned", ok=True, latency_ms=10,
                        prompt_tokens=7, completion_tokens=3,
                        created_at=f"{prefix}-15T10:00:00"))
        db.commit()
        resp = client.get("/api/tenant/usage", headers=auth_headers)
        assert resp.status_code == 200
        caps = resp.json()["ai_capabilities"]
        assert caps["copilot.reasoned"]["calls"] == 1
        assert caps["copilot.reasoned"]["prompt_tokens"] == 7

    def test_tenant_limits_exposes_ai_capabilities(self, client, auth_headers,
                                                   copilot_world):
        """/tenant/limits (the Plan tiles' source) carries the breakdown."""
        resp = client.get("/api/tenant/limits", headers=auth_headers)
        assert resp.status_code == 200
        assert "ai_capabilities" in resp.json()

    def test_migration_declares_the_token_columns(self):
        from app.migrate import COLUMNS

        assert ("llm_usage", "prompt_tokens INTEGER") in COLUMNS
        assert ("llm_usage", "completion_tokens INTEGER") in COLUMNS

    def test_model_declares_the_token_columns(self):
        from app.models.llm_usage import LlmUsage

        assert hasattr(LlmUsage, "prompt_tokens")
        assert hasattr(LlmUsage, "completion_tokens")


# ════════════════════ 5. Frontend wiring ════════════════════

class TestSlice2Static:
    """The usage display + cache-bust pins bump together."""

    def _repo(self):
        from pathlib import Path
        return Path(__file__).resolve().parent.parent

    def test_settings_tile_renders_the_capability_burn(self):
        html = (self._repo() / "app/templates/pmo/views/settings.html").read_text()
        assert "ai_capabilities" in html, "the tile must read the breakdown"
        assert "cap.calls" in html, "burn per capability: calls (+ tokens)"

    def test_tenants_js_carries_ai_capabilities(self):
        js = (self._repo() / "app/static/js/app/domains/tenants.js").read_text()
        assert "ai_capabilities" in js, "loadTenantLimits must carry the breakdown"


def llm_mod_call(system="s", user="u", tenant_config=None, feature="ai"):
    """Direct call through the ONE door (helper for the token-column tests)."""
    from app.services.llm import call_llm

    return call_llm(system, user, tenant_config=tenant_config, feature=feature)
