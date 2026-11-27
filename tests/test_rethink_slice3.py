"""Tests for the final AI & Copilot Rethink slice — TDD.

1. Drift Radar (PM capability #3) — a deterministic compute (per in-flight
   release: target vs planned-finish drift + the critical-path items causing
   it + one rules-based suggested move), consumed from schedule.py, surfaced
   in the Today Brief (GET /api/today) and the release view
   (GET /api/projects/{id}/releases/drift). The copilot's fast path answers
   drift questions from the release_readiness bundle with ZERO LLM tokens.
2. Interview re-homing — point-of-work launchers: the RAID tab starts the
   risk interview, the Releases tab the release-planning interview, the
   approval detail the escalation interview (the engine + endpoints
   unchanged; the in-panel fallback list stays).
"""
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import app.models  # noqa: F401
from app.models.approval import ApprovalRequest, ApprovalStep
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.release import Release
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.services import copilot as copilot_service
from app.services import grounding

REPO = Path(__file__).resolve().parents[1]
PROJECT_DETAIL = REPO / "app/templates/pmo/views/project_detail.html"
TODAY_HTML = REPO / "app/templates/pmo/views/today.html"
APPROVAL_MODALS = REPO / "app/templates/components/approval_modals.html"
COPILOT_DRAWER = REPO / "app/templates/pmo/shell/copilot_drawer.html"
COPILOT_JS = REPO / "app/static/js/app/domains/copilot.js"
PROJECTS_JS = REPO / "app/static/js/app/domains/projects.js"
APP_JS = REPO / "app/static/js/app/pmo-app.js"
INDEX_HTML = REPO / "app/templates/index.html"


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
def drift_world(db):
    """Tenant + project + an in-flight release running past its target: one
    critical item ends past the target, and a gate approval waits."""
    tenant = Tenant(name="S3 Drift Co", slug="s3-drift-co", plan="enterprise")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    admin = _make_admin(db, "test@pmo.test")
    admin.active_tenant_id = tenant.id
    db.add(TenantMembership(user_id=admin.id, tenant_id=tenant.id, role="owner"))
    db.commit()
    db.refresh(admin)

    project = Project(name="S3 Drift Cloud", client_id=1, tenant_id=tenant.id,
                      project_manager_id=admin.id, status="Active")
    db.add(project)
    db.commit()
    db.refresh(project)

    # The one scheduled item — a single node is always on the critical path
    # (zero float), and its planned end is 8 days past the release target.
    item = BacklogItem(
        tenant_id=tenant.id, project_id=project.id, title="Drift item",
        epic="Core", current_phase="Development", status="In Progress",
        start_date=date.today() - timedelta(days=20),
        end_date=date.today() + timedelta(days=3),
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    target = (date.today() - timedelta(days=5)).isoformat()
    release = Release(tenant_id=tenant.id, project_id=project.id,
                      version="1.2.0", name="Drift release",
                      status="In Progress", target_date=target)
    db.add(release)
    db.commit()
    db.refresh(release)

    approval = ApprovalRequest(
        tenant_id=tenant.id, project_id=project.id,
        title="Drift gate approval", request_type="phase_gate",
        status="Pending",
        created_at=(datetime.utcnow() - timedelta(days=4)).isoformat(),
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)
    step = ApprovalStep(tenant_id=tenant.id, request_id=approval.id,
                        step_order=1, role_name="Tech Lead", status="Pending")
    db.add(step)
    db.commit()

    return {"tenant": tenant, "admin": admin, "project": project,
            "item": item, "release": release, "approval": approval}


@pytest.fixture()
def clean_world(db):
    """Tenant + project with one on-track release — an empty radar."""
    tenant = Tenant(name="S3 Calm Co", slug="s3-calm-co", plan="enterprise")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    admin = _make_admin(db, "s3-calm@pmo.test")
    admin.active_tenant_id = tenant.id
    db.add(TenantMembership(user_id=admin.id, tenant_id=tenant.id, role="owner"))
    db.commit()
    project = Project(name="S3 Calm Cloud", client_id=1, tenant_id=tenant.id,
                      project_manager_id=admin.id, status="Active")
    db.add(project)
    db.commit()
    db.refresh(project)
    release = Release(tenant_id=tenant.id, project_id=project.id,
                      version="2.0.0", name="Calm release", status="Planning",
                      target_date=(date.today() + timedelta(days=30)).isoformat())
    db.add(release)
    db.commit()
    return {"tenant": tenant, "admin": admin, "project": project,
            "release": release}


@pytest.fixture()
def ai_configured(monkeypatch):
    """Mock the per-tenant AI config (no live calls). Patch the router namespace."""
    import app.routers.ai as ai_router

    monkeypatch.setattr(ai_router, "get_ai_config",
                        lambda db, tid: {"api_key": "k", "base_url": "u", "model": "m"})


# ════════════════════ 1. The drift-radar compute ════════════════════

class TestDriftRadarCompute:
    """Deterministic: same data in, same records out. The LLM never runs."""

    def test_drifted_release_is_flagged_with_causes_and_move(self, db, drift_world):
        """Per in-flight release: drift days vs target + the critical-path
        items causing it + one rules-based suggested move."""
        w = drift_world
        radar = grounding.drift_radar(db, w["tenant"], [w["project"].id])
        assert radar["bundle"] == "drift_radar"
        assert radar["counts"]["drifted_releases"] == 1
        rec = radar["records"][0]
        assert rec["entity_type"] == "release" and rec["entity_id"] == w["release"].id
        assert rec["project_id"] == w["project"].id
        assert rec["project_name"] == w["project"].name
        assert rec["target_date"] == w["release"].target_date
        # plan drift: window end (today+3) vs target (today-5) = 8 days
        assert rec["plan_drift_days"] == 8
        assert rec["days_past_target"] == 5
        assert rec["drift_days"] == 8
        # the critical-path item causing it
        assert len(rec["causing_items"]) == 1
        cause = rec["causing_items"][0]
        assert cause["entity_type"] == "backlog_item"
        assert cause["entity_id"] == w["item"].id
        assert cause["end_date"] > rec["target_date"]
        # the escalation rule fires first (a gate approval is pending)
        assert "escalate" in rec["suggested_move"].lower()
        assert "Drift gate approval" in rec["suggested_move"]
        assert "Tech Lead" in rec["suggested_move"]
        # the radar computes — notes label the deterministic floor
        assert radar["notes"] and "RULES-based" in radar["notes"][-1]

    def test_compute_is_deterministic(self, db, drift_world):
        """Same data in, same records out — no LLM, no clock drift in the
        computed fields within a run."""
        w = drift_world
        first = grounding.drift_radar(db, w["tenant"], [w["project"].id])
        second = grounding.drift_radar(db, w["tenant"], [w["project"].id])
        assert first["records"] == second["records"]
        assert first["counts"] == second["counts"]

    def test_critical_path_move_names_the_items(self, db, drift_world):
        """No pending gate → the critical-path rule names the items."""
        w = drift_world
        w["approval"].status = "Approved"
        db.commit()
        radar = grounding.drift_radar(db, w["tenant"], [w["project"].id])
        move = radar["records"][0]["suggested_move"]
        assert "Drift item" in move
        assert "critical path" in move.lower()
        assert "re-scope" in move.lower()

    def test_shipped_and_cancelled_releases_are_out_of_scope(self, db, drift_world):
        """Shipped (the ladder's done set) and Cancelled releases never flag."""
        w = drift_world
        w["release"].status = "Post-Release"  # in the ladder's done set
        db.commit()
        assert grounding.drift_radar(db, w["tenant"], [w["project"].id])["counts"]["drifted_releases"] == 0
        w["release"].status = "Cancelled"
        db.commit()
        assert grounding.drift_radar(db, w["tenant"], [w["project"].id])["counts"]["drifted_releases"] == 0

    def test_on_target_release_is_not_flagged(self, db, clean_world):
        """A release the plan meets is outside the radar."""
        w = clean_world
        radar = grounding.drift_radar(db, w["tenant"], [w["project"].id])
        assert radar["records"] == []
        assert radar["counts"]["drifted_releases"] == 0
        assert radar["counts"]["releases_scanned"] == 1

    def test_unparseable_target_is_never_drift(self, db, clean_world):
        """A free-text target skips the line (schedule.py's rule)."""
        w = clean_world
        w["release"].target_date = "when it's ready"
        db.commit()
        radar = grounding.drift_radar(db, w["tenant"], [w["project"].id])
        assert radar["records"] == []

    def test_empty_scope_yields_an_empty_radar(self, db, drift_world):
        """A project with no releases — an empty radar, never an error."""
        w = drift_world
        bare = Project(name="S3 Bare Cloud", client_id=1,
                       tenant_id=w["tenant"].id, status="Active")
        db.add(bare)
        db.commit()
        db.refresh(bare)
        empty = grounding.drift_radar(db, w["tenant"], [bare.id])
        assert empty["records"] == []
        assert empty["counts"]["drifted_releases"] == 0
        assert empty["counts"]["releases_scanned"] == 0
        # An unscoped call over a tenant with no projects at all is empty too.
        other_tenant = Tenant(name="S3 Empty Co", slug="s3-empty-co")
        db.add(other_tenant)
        db.commit()
        db.refresh(other_tenant)
        assert grounding.drift_radar(db, other_tenant, None)["records"] == []

    def test_radar_is_tenant_scoped(self, db, drift_world, clean_world):
        """Tenant A's radar NEVER contains tenant B's releases — every model
        query rides tenant_scoped()."""
        radar = grounding.drift_radar(db, drift_world["tenant"], None)
        ids = [r["entity_id"] for r in radar["records"]]
        assert clean_world["release"].id not in ids
        assert radar["scope"]["tenant_id"] == drift_world["tenant"].id
        # The project-id scope hides the other tenant's project too.
        hidden = grounding.drift_radar(
            db, drift_world["tenant"], [clean_world["project"].id])
        assert hidden["records"] == []

    def test_tenant_wide_scope_covers_active_projects(self, db, drift_world):
        """project_ids=None (the Today Brief's scope) scans every ACTIVE
        project in the tenant."""
        radar = grounding.drift_radar(db, drift_world["tenant"], None)
        assert radar["scope"]["project_ids"] == [drift_world["project"].id]
        assert radar["counts"]["drifted_releases"] == 1


# ════════════════════ 2. The surfaces ════════════════════

class TestDriftSurfaces:
    """Today Brief Drift section + the release view's endpoint."""

    def test_today_carries_the_drift_section(self, client, auth_user, db, drift_world):
        """GET /api/today carries drift_radar — the card's Drift section."""
        resp = client.get("/api/today")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # The legacy keys stay; drift_radar is additive.
        for key in ("needs_you", "total_needs_you", "counts", "briefing"):
            assert key in body
        radar = body["drift_radar"]
        assert radar["counts"]["drifted_releases"] == 1
        rec = radar["records"][0]
        assert rec["entity_id"] == drift_world["release"].id
        assert rec["drift_days"] == 8
        assert rec["causing_items"] and rec["suggested_move"]

    def test_release_view_serves_the_drift_radar(self, client, auth_user, db, drift_world):
        """GET /api/projects/{id}/releases/drift — the release view's payload."""
        w = drift_world
        resp = client.get(f"/api/projects/{w['project'].id}/releases/drift")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["bundle"] == "drift_radar"
        assert body["counts"]["drifted_releases"] == 1
        rec = body["records"][0]
        assert rec["entity_id"] == w["release"].id
        assert rec["drift_days"] == 8
        assert rec["causing_items"][0]["entity_id"] == w["item"].id
        assert "escalate" in rec["suggested_move"].lower()

    def test_release_drift_requires_an_existing_project(self, client, auth_user, db):
        resp = client.get("/api/projects/99999/releases/drift")
        assert resp.status_code == 404

    def test_release_drift_404s_for_an_invisible_project(self, client, auth_user, db, drift_world):
        """Another tenant's project is invisible — 404, never a leak."""
        other = Project(name="S3 Other Cloud", client_id=1,
                        tenant_id=drift_world["tenant"].id + 1000, status="Active")
        db.add(other)
        db.commit()
        resp = client.get(f"/api/projects/{other.id}/releases/drift")
        assert resp.status_code == 404

    def test_release_drift_requires_auth(self, anon_client):
        resp = anon_client.get("/api/projects/1/releases/drift")
        assert resp.status_code in (401, 403)


# ════════════════════ 3. The fast path answers drift ════════════════════

class TestFastPathDrift:
    """Drift questions are lookups — the release_readiness bundle, zero LLM."""

    def test_whats_drifted_is_a_fast_lookup(self, client, auth_headers, drift_world,
                                            ai_configured, monkeypatch, db):
        """mode=auto + "what's drifted?" → the fast path: a deterministic
        digest from the release_readiness bundle, ZERO _call_llm calls."""
        def _no_llm(*a, **k):
            raise AssertionError("the fast path must not call the LLM")

        monkeypatch.setattr(copilot_service, "_call_llm", _no_llm)
        resp = client.post(
            "/api/ai/copilot/chat",
            json={"question": "what's drifted?",
                  "project_id": drift_world["project"].id},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["mode"] == "lookup"
        assert body["degraded"] is False
        assert body["bundles_used"] == ["release_readiness"]
        # The digest names the drifted release from the bundle's drift rows.
        assert "past the target" in body["answer"].lower()
        assert f"Release {drift_world['release'].id}" in body["answer"]

    def test_drifted_releases_phrase_is_a_fast_lookup(self, client, auth_headers,
                                                      drift_world, ai_configured,
                                                      monkeypatch):
        def _no_llm(*a, **k):
            raise AssertionError("the fast path must not call the LLM")

        monkeypatch.setattr(copilot_service, "_call_llm", _no_llm)
        resp = client.post(
            "/api/ai/copilot/chat",
            json={"question": "which releases have drifted releases pending?"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "lookup"

    def test_lookup_without_a_project_still_answers(self, client, auth_headers,
                                                    drift_world, ai_configured,
                                                    monkeypatch):
        """The fast path runs portfolio-wide when no project is open."""
        def _no_llm(*a, **k):
            raise AssertionError("the fast path must not call the LLM")

        monkeypatch.setattr(copilot_service, "_call_llm", _no_llm)
        resp = client.post(
            "/api/ai/copilot/chat",
            json={"question": "what's drifted?"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "lookup"
        assert body["bundles_used"] == ["release_readiness"]


# ════════════════════ 4. Point-of-work launchers (statics) ════════════════════

class TestLauncherStatics:
    """The interview launchers moved to the point of work — the engine and
    endpoints unchanged, the in-panel fallback list intact."""

    def test_risks_view_launches_the_risk_interview(self):
        """The RAID tab's button starts the risk interview pre-scoped."""
        src = PROJECT_DETAIL.read_text()
        assert '@click="copilotStartRiskIntake()"' in src
        # It lives in the RAID section (after the tab's content start).
        raid_section = src.index('x-show="projectTab===\'risks\'"')
        launcher = src.index('@click="copilotStartRiskIntake()"', raid_section)
        assert launcher > raid_section
        assert "Add risk with AI" in src[launcher - 400:launcher + 800]

    def test_releases_view_launches_the_release_interview(self):
        """The Releases tab's button starts the release-planning interview."""
        src = PROJECT_DETAIL.read_text()
        assert '@click="copilotStartReleaseIntake()"' in src
        assert "Plan with AI" in src

    def test_approval_detail_launches_the_escalation_interview(self):
        """The approval detail's button starts the escalation interview."""
        src = APPROVAL_MODALS.read_text()
        assert '@click="copilotStartEscalationIntake()"' in src
        assert "Escalate with AI" in src
        js = COPILOT_JS.read_text()
        assert "copilotStartEscalationIntake()" in js
        assert "interviewStart('escalation'" in js
        # The open approval is pre-selected in the picker.
        assert "_interviewPresetApprovalId" in js

    def test_in_panel_fallback_list_stays(self):
        """The drawer's capability fallback keeps every guided capability —
        kickoff intake stays reachable via the fallback + the capture box."""
        drawer = COPILOT_DRAWER.read_text()
        for call in ("openCopilotIntake()", "interviewStart('project')",
                     "interviewStart('feature')", "interviewStart('risk')",
                     "interviewStart('release')", "interviewStart('escalation')"):
            assert call in drawer
        # The engine endpoints are untouched (the JS still calls them).
        js = COPILOT_JS.read_text()
        for path in ("/ai/interview/${this.interviewSession.session_id}/${path}",
                     "/ai/interview/${this.interviewSession.session_id}/finish",
                     "/ai/interview/${this.interviewSession.session_id}/apply",
                     "/ai/interview/${this.interviewSession.session_id}/back",
                     "/ai/interview/${flow}/start"):
            assert path in js

    def test_drift_surfaces_statics(self):
        """The Today Brief Drift section + the release-view banner markup."""
        today = TODAY_HTML.read_text()
        assert "today?.drift_radar?.records" in today
        assert "openDriftRelease(row)" in today
        assert "Suggested move" in today
        detail = PROJECT_DETAIL.read_text()
        assert "releaseDrift(rel.id)" in detail
        assert "Critical path" in detail
        projects_js = PROJECTS_JS.read_text()
        for name in ("loadDriftRadar", "releaseDrift", "openDriftRelease"):
            assert name in projects_js
        # The Releases tab's lazy loader fetches the radar.
        planning_js = (REPO / "app/static/js/app/domains/planning.js").read_text()
        assert "releases: ['releases', 'driftRadar']" in planning_js
        assert "case 'driftRadar': this.loadDriftRadar(); break;" in planning_js

    def test_css_version_parity(self):
        """House cache-bust rule: one ?v= across the JS graph + the CSS link."""
        app_js = APP_JS.read_text()
        js_versions = set(__import__("re").findall(
            r"from '\./[a-z_/]+\.js\?v=([a-z0-9]+)'", app_js))
        assert js_versions == {"20261126d"}, f"the JS graph must pin 20261126d, found {js_versions}"
        index = INDEX_HTML.read_text()
        link = __import__("re").search(r"tailwind\.compiled\.css\?v=([a-z0-9]+)", index)
        assert link and link.group(1) == "20261126d"
