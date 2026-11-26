"""Tests for the AI & Copilot Rethink MVP contracts — TDD.

One coherent re-aim from "chat with your data" to "artifacts + radar + answers":

1. Draft Desk — POST /projects/{id}/reports/draft returns rendered markdown
   per audience (never JSON), degrades deterministically when the LLM is
   unavailable, and the ONE send path emails RENDERED MARKDOWN (the
   json.dumps-as-email bug is gone).
2. Clickable references — copilot answers carry server-VALIDATED references
   (entity_type/entity_id/title/url) computed from this turn's context;
   invalid model citations are dropped; `sources` stays backward compatible.
3. Today Brief narrative — ONE AI narrative call over the deterministic
   needs-you aggregate; degraded=true and narrative="" when the LLM is
   unavailable (the deterministic card stands alone).
4. Single Ask surface — the drawer has no mode tabs; capabilities stay
   reachable in-panel + via the ⌘K palette; the drawer renders clickable
   reference chips.
"""
import json

import pytest

import app.models  # noqa: F401
from app.models.ai_interaction import AiInteraction
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.user import User
from app.services import copilot as copilot_service

# ════════════════════ 1. Draft Desk ════════════════════

class TestDraftDesk:
    """POST /projects/{id}/reports/draft + the ONE send path (markdown emails)."""

    def _make_project(self, client, db, name="Draft Desk Project"):
        """Project with the auth user as PM (so the send path dispatches email)."""
        cid = client.post("/api/clients", json={"name": name + " Client"}).json()["id"]
        resp = client.post("/api/projects", json={"name": name, "client_id": cid})
        assert resp.status_code in (200, 201), resp.text
        project = resp.json()
        # Make the authenticated user the PM: the send path builds recipients
        # from the PM + stakeholders, so the email dispatch is exercised.
        user = db.query(User).filter(User.email == "test@pmo.test").first()
        row = db.query(Project).filter(Project.id == project["id"]).first()
        row.project_manager_id = user.id
        db.commit()
        return project

    @pytest.fixture()
    def no_llm(self, monkeypatch):
        """get_ai_config is imported into app.routers.reports — patch there."""
        import app.routers.reports as reports_router

        monkeypatch.setattr(
            reports_router, "get_ai_config",
            lambda db, tid: {"api_key": "", "base_url": "", "model": ""},
        )

    def test_draft_degrades_to_snapshot_markdown(self, client, db, no_llm):
        """LLM unavailable → 200 with the deterministic snapshot rendered as
        markdown (degraded=true) — the Draft Desk never blocks on the LLM."""
        project = self._make_project(client, db)
        resp = client.post(
            f"/api/projects/{project['id']}/reports/draft", json={"audience": "exec_weekly"}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["degraded"] is True
        assert body["audience"] == "exec_weekly"
        # Rendered markdown, not JSON: a heading + the project name.
        assert body["markdown"].lstrip().startswith("#")
        assert project["name"] in body["markdown"]
        assert not body["markdown"].lstrip().startswith("{")
        assert body["report_id"] is None

    def test_draft_with_llm_mocked(self, client, db, no_llm, monkeypatch):
        """Happy path: brief.generate_report succeeds → non-degraded markdown."""
        from app.services import brief as brief_service

        async def _unused():
            pass

        def fake_generate_report(db_, tenant_, project_, audience="exec_weekly",
                                 user=None, tenant_config=None):
            return {
                "audience": audience,
                "content": {"verdict": "On track", "risks": []},
                "markdown": "# Executive weekly verdict\n\nOn track.",
                "sections": {"verdict": "On track"},
                "data_hash": "abc123",
                "report_id": 42,
            }

        monkeypatch.setattr(brief_service, "generate_report", fake_generate_report)
        project = self._make_project(client, db)
        resp = client.post(
            f"/api/projects/{project['id']}/reports/draft", json={"audience": "exec_weekly"}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["degraded"] is False
        assert body["markdown"] == "# Executive weekly verdict\n\nOn track."
        assert body["report_id"] == 42

    def test_draft_unknown_audience_400(self, client, db, no_llm):
        project = self._make_project(client, db, "Bad Audience")
        resp = client.post(
            f"/api/projects/{project['id']}/reports/draft", json={"audience": "bogus"}
        )
        assert resp.status_code == 400
        assert "Unknown audience" in resp.json()["detail"]

    @pytest.fixture()
    def capture_email(self, monkeypatch):
        """Capture send_email calls — the email body is the contract here."""
        import app.routers.reports as reports_router

        sent = []

        def fake_send_email(db=None, tenant_id=None, to_email=None, subject="",
                            body="", html=""):
            sent.append({"to": to_email, "subject": subject, "body": body})
            return True

        monkeypatch.setattr(reports_router, "send_email", fake_send_email)
        return sent

    def test_send_draft_emails_rendered_markdown(self, client, db, capture_email):
        """THE ONE send path: an edited Draft Desk draft is emailed as rendered
        markdown — never json.dumps output."""
        project = self._make_project(client, db)
        draft_md = "# Client status update\n\nAll milestones on track."
        resp = client.post(
            f"/api/projects/{project['id']}/reports/send",
            json={"audience": "client", "markdown": draft_md},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["audience"] == "client"
        assert body["markdown"] == draft_md
        assert body["entry"]["artifact_type"] == "report"
        # The email carried the DRAFT markdown, not a JSON dump.
        assert len(capture_email) >= 1
        for mail in capture_email:
            assert mail["body"] == draft_md
            assert '"report":' not in mail["body"]
            assert mail["body"].lstrip().startswith("#")
            assert "Client status update" in mail["subject"]

    def test_send_without_draft_emails_snapshot_markdown(self, client, db, capture_email):
        """A bare snapshot send emails the deterministic snapshot rendered as
        markdown — json.dumps-as-email is gone."""
        project = self._make_project(client, db, "Snapshot Send")
        resp = client.post(f"/api/projects/{project['id']}/reports/send")
        assert resp.status_code == 201, resp.text
        assert len(capture_email) >= 1
        for mail in capture_email:
            assert mail["body"].lstrip().startswith("#")
            assert "Snapshot Send" in mail["body"]
            assert not mail["body"].lstrip().startswith("{")

    def test_send_draft_persists_in_chain(self, client, db):
        """The draft lands in the artifact chain payload (like the current send)."""
        project = self._make_project(client, db, "Chained Draft")
        draft_md = "# PM weekly\n\nGates aging."
        client.post(
            f"/api/projects/{project['id']}/reports/send",
            json={"audience": "pm_weekly", "markdown": draft_md},
        )
        reports = client.get(f"/api/projects/{project['id']}/reports").json()
        assert len(reports) == 1
        assert reports[0]["draft"]["audience"] == "pm_weekly"
        assert reports[0]["draft"]["markdown"] == draft_md


# ════════════════════ 2. Clickable references ════════════════════

@pytest.fixture()
def copilot_world(db):
    """Tenant + super-admin user + project + backlog item (the copilot tests' pattern)."""
    from app.models.tenant import TenantMembership

    tenant = Tenant(name="Ref Co", slug="ref-co", plan="enterprise")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    admin = db.query(User).filter(User.email == "test@pmo.test").first()
    if not admin:
        admin = User(email="test@pmo.test", name="Admin", hashed_password="x", system_role="super_admin")
        db.add(admin)
        db.commit()
    admin.active_tenant_id = tenant.id
    db.add(TenantMembership(user_id=admin.id, tenant_id=tenant.id, role="owner"))
    db.commit()
    db.refresh(admin)

    project = Project(name="PNU Cloud", client_id=1, tenant_id=tenant.id, project_manager_id=admin.id)
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
def ai_configured(monkeypatch):
    """Mock the per-tenant AI config (no live calls). Patch the router namespace."""
    import app.routers.ai as ai_router

    monkeypatch.setattr(ai_router, "get_ai_config",
                        lambda db, tid: {"api_key": "k", "base_url": "u", "model": "m"})


class TestClickableReferences:
    """Server-side citation validation: invalid ids dropped, survivors clickable."""

    def test_validated_references_are_returned(self, client, auth_headers, copilot_world,
                                               ai_configured, monkeypatch):
        """An answer citing a REAL context record yields a reference record with
        entity_type/entity_id/title/url — the chip's deep link."""
        monkeypatch.setattr(copilot_service, "_call_llm",
                            lambda *a, **k: json.dumps({
                                "answer": f"Item {copilot_world['item'].id} is in Development.",
                                "sources": [],
                            }))
        resp = client.post(
            "/api/ai/copilot/chat",
            json={"question": "status?", "project_id": copilot_world["project"].id},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        refs = body["references"]
        assert refs, "a valid citation must produce a reference"
        ref = refs[0]
        assert ref["entity_type"] == "backlog_item"
        assert ref["entity_id"] == copilot_world["item"].id
        assert ref["title"] == "SSO login"
        assert ref["url"] == f"/projects/{copilot_world['project'].id}/backlog"
        # Backward compatible: `sources` is still a list of label strings.
        assert isinstance(body["sources"], list)
        assert all(isinstance(s, str) for s in body["sources"])
        assert body["interaction_id"]

    def test_invalid_citations_are_dropped(self, client, auth_headers, copilot_world,
                                           ai_configured, monkeypatch):
        """A model-cited id the context doesn't contain is dropped — never rendered."""
        monkeypatch.setattr(copilot_service, "_call_llm",
                            lambda *a, **k: json.dumps({
                                "answer": "Item 999999 needs attention.",
                                "sources": [],
                            }))
        resp = client.post(
            "/api/ai/copilot/chat",
            json={"question": "status?", "project_id": copilot_world["project"].id},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["references"] == []
        assert body["sources"] == []

    def test_persisted_sources_store_the_validated_shape(self, client, auth_headers,
                                                         copilot_world, ai_configured,
                                                         monkeypatch, db):
        """AiInteraction.sources stores the validated reference records (JSON)."""
        item_id = copilot_world["item"].id

        def fake_call_llm(*a, **k):
            return json.dumps({"answer": f"Item {item_id} is in Development.", "sources": []})

        monkeypatch.setattr(copilot_service, "_call_llm", fake_call_llm)
        resp = client.post(
            "/api/ai/copilot/chat",
            json={"question": "status?", "project_id": copilot_world["project"].id},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        interaction_id = resp.json()["interaction_id"]
        row = db.query(AiInteraction).filter(AiInteraction.id == interaction_id).first()
        stored = json.loads(row.sources)
        assert isinstance(stored, list) and stored
        assert stored[0]["entity_type"] == "backlog_item"
        assert stored[0]["entity_id"] == item_id
        assert "url" in stored[0]


# ════════════════════ 3. Today Brief narrative ════════════════════

class TestTodayBriefNarrative:
    """POST /api/ai/today-brief/narrative — ONE AI call over the deterministic floor."""

    def test_unconfigured_degrades_to_deterministic_floor(self, client, auth_headers,
                                                          copilot_world, monkeypatch):
        """No API key → 200 with degraded=true, narrative="", verdict + lines
        from build_today — the deterministic card stands alone."""
        import app.routers.ai as ai_router

        monkeypatch.setattr(ai_router, "get_ai_config",
                            lambda db, tid: {"api_key": "", "base_url": "", "model": ""})
        resp = client.post("/api/ai/today-brief/narrative", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["degraded"] is True
        assert body["narrative"] == ""
        assert "verdict" in body
        assert isinstance(body["lines"], list)
        assert "needs_you_count" in body

    def test_llm_mocked_narrates(self, client, auth_headers, copilot_world,
                                 ai_configured, monkeypatch, db):
        """Happy path: the LLM narrates ~3 sentences; degraded=false; the
        interaction is persisted as kind=today_brief."""
        import app.services.ai as ai_service

        monkeypatch.setattr(ai_service, "_call_llm",
                            lambda *a, **k: "On track with two things needing you. "
                                            "The SSO approval moved today. "
                                            "Nothing is at risk today.")
        resp = client.post("/api/ai/today-brief/narrative", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["degraded"] is False
        assert body["narrative"].startswith("On track")
        assert isinstance(body["lines"], list)
        row = db.query(AiInteraction).filter(
            AiInteraction.kind == "today_brief"
        ).order_by(AiInteraction.id.desc()).first()
        assert row is not None
        assert row.answer.startswith("On track")

    def test_llm_failure_degrades(self, client, auth_headers, copilot_world,
                                  ai_configured, monkeypatch):
        """The LLM raising (over quota / down) degrades to the deterministic
        floor — it never blocks the card."""
        import app.services.ai as ai_service

        def boom(*a, **k):
            from fastapi import HTTPException
            raise HTTPException(403, "AI quota exceeded")

        monkeypatch.setattr(ai_service, "_call_llm", boom)
        resp = client.post("/api/ai/today-brief/narrative", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["degraded"] is True
        assert body["narrative"] == ""
        assert isinstance(body["lines"], list)


# ════════════════════ 4. Single Ask surface (static pins) ════════════════════

from pathlib import Path  # noqa: E402

BASE = Path(__file__).resolve().parent.parent
DRAWER = BASE / "app/templates/pmo/shell/copilot_drawer.html"
COPILOT_JS = BASE / "app/static/js/app/domains/copilot.js"
CORE_JS = BASE / "app/static/js/app/domains/core.js"
TODAY_HTML = BASE / "app/templates/pmo/views/today.html"
PLANNING_JS = BASE / "app/static/js/app/domains/planning.js"


class TestSingleAskSurface:
    """The drawer is ONE Ask surface — no mode tabs, capabilities reachable."""

    def _read(self, path):
        return path.read_text()

    def test_drawer_has_no_mode_tabs(self):
        """The 3-tab drawer (Chat | Kickoff | Guided) is gone."""
        src = self._read(DRAWER)
        assert "copilotTab" not in src
        assert 'x-show="copilotTab' not in src
        assert "showReportTab" not in src
        assert "showInterviewTab" not in src

    def test_drawer_keeps_the_qa_shell(self):
        """The drawer shell + x-show pattern hold (QA static pins)."""
        src = self._read(DRAWER)
        assert 'x-show="copilotOpen"' in src
        # No x-transition on the SAME element (leave-sequence stick bug).
        outer = src.split("\n")
        for line in outer:
            if 'x-show="copilotOpen"' in line:
                assert "x-transition" not in line
                break
        else:
            pytest.fail("the outer x-show=\"copilotOpen\" div is missing")

    def test_drawer_is_a_single_thread(self):
        """One conversation thread: chat, intake cards and interviews are
        message-type panels in the same #copilot-messages surface."""
        src = self._read(DRAWER)
        assert src.count('id="copilot-messages"') == 1
        # The kickoff paste card renders in the thread (not a separate tab).
        assert 'intakeKickoffOpen && !intakeDraft && !intakeResult' in src
        # The interview renders in the thread as a message-type card.
        assert 'interviewSession && !interviewSession.done' in src
        assert 'interviewDraft && interviewFinished' in src

    def test_capability_fallback_list(self):
        """Kickoff/Guided capabilities stay reachable in-panel — no re-plumb."""
        src = self._read(DRAWER)
        assert "showCopilotCapabilities" in src
        assert "openCopilotIntake()" in src
        for flow in ("project", "feature", "risk", "release", "escalation"):
            assert f"interviewStart('{flow}')" in src

    def test_copilot_js_single_surface_state(self):
        """copilot.js: tab state gone; capability getter + one-surface resets in."""
        src = self._read(COPILOT_JS)
        assert "copilotTab" not in src
        assert "get showCopilotCapabilities()" in src
        assert "intakeKickoffOpen" in src

    def test_regex_theater_removed(self):
        """generateBriefing/parseBriefing (the canned-question regex parsing)
        are REMOVED — the Today Brief card + narrative endpoint replace them."""
        src = self._read(COPILOT_JS)
        assert "generateBriefing" not in src
        assert "parseBriefing" not in src
        assert "briefingSummary" not in src

    def test_drawer_reference_chips_are_clickable(self):
        """References render as CLICKABLE deep-link chips (openReference)."""
        src = self._read(DRAWER)
        assert "@click=\"openReference(ref)\"" in src
        assert "x-text=\"ref.label\"" in src
        assert 'msg.references && msg.references.length > 0' in src
        # The fallback for pre-contract messages (plain chips) stays.
        assert "msg.sources" in src

    def test_copilot_js_open_reference_navigates(self):
        """openReference lands at the record: openProjectById + projectTab."""
        src = self._read(COPILOT_JS)
        assert "async openReference(ref)" in src
        assert "selectProjectById" in src
        assert "projectTab" in src

    def test_palette_ai_commands(self):
        """⌘K palette: AI commands lead — 'Ask AI about the current view' and
        the kickoff/guided capabilities; the Draft Desk is reachable too."""
        src = self._read(CORE_JS)
        assert "Ask AI about the current view" in src
        assert "ai_ask" in src
        assert "aiAskCurrentView" in src
        assert "ai_intake" in src and "ai_feature" in src and "ai_escalation" in src
        assert "ai_draft" in src and "openDraftDesk" in src
        # The AI commands are declared BEFORE the view list → first results.
        results_body = src.split("get paletteResults()")[1].split("paletteHandleKey")[0]
        assert results_body.index("aiCommands") < results_body.index("const views")

    def test_today_brief_frontend(self):
        """The Today card keeps the deterministic shell + gains the ONE
        narrative call; loadTodayNarrative fires wherever the card renders."""
        today = self._read(TODAY_HTML)
        assert "PMO Copilot Briefing" in today  # house brand pin holds
        assert "todayNarrative" in today
        planning = self._read(PLANNING_JS)
        assert "loadTodayNarrative" in planning
        load_body = planning.split("async loadToday()")[1].split("async loadTodayNarrative")[0]
        assert "this.loadTodayNarrative()" in load_body
