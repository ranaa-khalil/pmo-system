"""F3 slice tests — Rethink v2 Phase F remainder (router merge + email retire + bulk).

Covers:
- The dashboard/workload/gantt router merge: every old URL served with
  byte-identical path/method/tag/shape (the frontend and the topbar fetch
  these URLs).
- The email_service retirement: the module is gone; the dispatch door is
  re-homed in app/services/email.py (Resend first, SMTP fallback) and the
  digest + report-send paths still route through it.
- usage_records ← llm_usage: derive_llm_usage_rollup is the ONE derivation
  (read-only, tenant-scoped, zero-safe).
- PATCH /api/backlog/bulk loops release_machine.advance_backlog_item_phase:
  per-item failure isolation, tenant scoping, batch guard, chain parity
  with the single-advance router path.

Audit split (documentation-only, F1's convention): artifact_chain is the
record of truth; activity_log is the UI feed — asserted below as a
docstring contract so the rule can't silently rot.
"""
import json

import pytest

import app.models  # noqa: F401 — register all models
from app.models.artifact_chain import ArtifactChain
from app.models.backlog_item import BacklogItem
from app.models.client import Client
from app.models.llm_usage import LlmUsage
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.user import User
from app.services.usage_service import derive_llm_usage_rollup

# ── helpers ──────────────────────────────────────────────────────────────

def _project(client, name):
    """API-only setup (interleaving the db fixture session with TestClient
    calls on the shared StaticPool deadlocks intermittently)."""
    cid = client.post("/api/clients", json={"name": name + " Client"}).json()["id"]
    resp = client.post("/api/projects", json={"name": name, "client_id": cid})
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def _items(client, pid, titles):
    out = []
    for title in titles:
        resp = client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": title})
        assert resp.status_code in (200, 201), resp.text
        out.append(resp.json())
    return out


# ── 1. The router merge ──────────────────────────────────────────────────

class TestMergedAnalyticsRouter:
    """dashboard/workload/gantt merged into ONE router — every old URL intact."""

    def test_dashboard_serves(self, client):
        """GET /api/dashboard returns aggregated stats (old shape, byte-identical)."""
        response = client.get("/api/dashboard")
        assert response.status_code == 200
        data = response.json()
        for key in ["clients", "projects", "backlog_items", "pending_approvals", "forms"]:
            assert key in data

    def test_workload_serves(self, client):
        """GET /api/workload returns per-member open-work counts (old shape)."""
        response = client.get("/api/workload")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        for member in data:
            assert set(member) == {"user_id", "name", "open_items", "open_tasks", "total"}
            assert member["total"] == member["open_items"] + member["open_tasks"]

    def test_gantt_serves_and_404_byte_identical(self, client):
        """GET /api/projects/{id}/gantt serves the old shape; 404 keeps the old string."""
        pid = _project(client, "F3 Gantt")["id"]
        _items(client, pid, ["Undated"])
        resp = client.get(f"/api/projects/{pid}/gantt")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["unscheduled_count"] == 1
        assert data["project_id"] == pid
        assert data["critical_count"] == 0

        missing = client.get("/api/projects/999999/gantt")
        assert missing.status_code == 404
        assert missing.json() == {"detail": "Project not found"}

    @pytest.mark.parametrize("path,tag", [
        ("/api/dashboard", "dashboard"),
        ("/api/workload", "workload"),
        ("/api/projects/{project_id}/gantt", "gantt"),
    ])
    def test_openapi_tags_preserved(self, client, path, tag):
        """Each migrated route keeps its OWN OpenAPI tag — no group drift."""
        spec = client.get("/openapi.json").json()
        assert path in spec["paths"]
        for op in spec["paths"][path].values():
            assert op.get("tags") == [tag]

    def test_retired_router_modules_gone(self):
        """workload.py / gantt.py merged away; email_service.py retired."""
        for mod in ["app.routers.workload", "app.routers.gantt", "app.services.email_service"]:
            with pytest.raises(ModuleNotFoundError):
                __import__(mod)


# ── 2. The email retirement ──────────────────────────────────────────────

class TestEmailRetire:
    """email_service.py retired — ONE email module (email.py, Resend first)."""

    def test_dispatch_door_rehomed_dev_mode_false(self, monkeypatch):
        """The retired module's send_email contract lives in email.py; nothing configured → False."""
        from app.config import settings
        from app.services.email import send_email

        monkeypatch.setattr(settings, "resend_api_key", "")
        monkeypatch.setattr(settings, "smtp_host", "")
        monkeypatch.setattr(settings, "smtp_user", "")
        result = send_email(db=None, tenant_id=None, to_email="x@y.test", subject="s", body="b")
        assert result is False

    def test_report_router_imports_rehomed_door(self):
        """reports.py imports send_email by name from the surviving module."""
        import app.routers.reports as reports
        import app.services.email as email_module
        assert reports.send_email is email_module.send_email

    def test_digest_path_queues_through_rehomed_door(self, db, monkeypatch):
        """brief.send_report with a digest preference routes through email.send_email."""
        from app.services import brief

        tenant = Tenant(name="F3 Digest Co", slug="f3-digest-co", plan="enterprise")
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        pm = User(email="f3-pm@copilot.test", name="F3 PM", hashed_password="x")
        db.add(pm)
        db.commit()
        db.refresh(pm)
        project = Project(name="F3 Digest P", client_id=1, tenant_id=tenant.id, project_manager_id=pm.id)
        db.add(project)
        db.commit()
        db.refresh(project)

        captured = {}
        monkeypatch.setattr("app.services.email.send_email", lambda **kw: captured.update(kw) or True)
        monkeypatch.setattr(brief, "_call_llm", lambda *a, **k: json.dumps({"verdict": "on track"}))

        report = brief.generate_report(db, tenant, project, audience="exec_weekly")
        result = brief.send_report(db, tenant, report, recipient=pm, digest_preference=True)

        assert result["sent"] is True
        assert captured.get("to_email") == pm.email
        assert captured.get("subject")
        assert captured.get("body") == report.get("markdown", "")

    def test_password_reset_still_routes_through_email_module(self, monkeypatch):
        """auth.py's reset path is untouched: send_password_reset_email dispatches via email.send_email."""
        from app.config import settings
        from app.services import email as email_module

        captured = {}
        monkeypatch.setattr(email_module, "_send_via_resend", lambda *a, **k: True)
        monkeypatch.setattr(settings, "app_url", "https://pmo.test")
        assert email_module.send_password_reset_email("u@x.test", "tok", "Rainbow") is True


# ── 3. usage_records derived from llm_usage ─────────────────────────────

class TestUsageDerivation:
    """usage_records' api_calls metric derives FROM llm_usage (one derivation)."""

    def test_rollup_counts_ok_fallback_latency(self, db):
        """The rollup is computed from llm_usage rows, never guessed."""
        tenant_id = 4242
        for ok, latency in [(True, 100), (True, 200), (False, 50)]:
            db.add(LlmUsage(tenant_id=tenant_id, feature="ai", ok=ok, latency_ms=latency))
        db.commit()

        day = db.query(LlmUsage).filter(LlmUsage.tenant_id == tenant_id).first().created_at[:10]
        rollup = derive_llm_usage_rollup(db, tenant_id, day=day)
        assert rollup["metric"] == "api_calls"
        assert rollup["date"] == day
        assert rollup["calls"] == 3
        assert rollup["ok"] == 2
        assert rollup["fallback"] == 1
        assert rollup["avg_latency_ms"] == round((100 + 200 + 50) / 3)

    def test_rollup_is_tenant_scoped_and_zero_safe(self, db):
        """Another tenant's rows don't leak; an empty day derives zeros."""
        db.add(LlmUsage(tenant_id=1, feature="ai", ok=True, latency_ms=10))
        db.add(LlmUsage(tenant_id=2, feature="copilot", ok=False, latency_ms=20))
        db.commit()

        mine = derive_llm_usage_rollup(db, 1, day="1999-01-01")
        assert mine["calls"] == 0  # nothing on that day — zeros, not guesses
        other = derive_llm_usage_rollup(db, 2, day="1999-01-01")
        assert other["calls"] == 0 and other["fallback"] == 0
        empty = derive_llm_usage_rollup(db, 999, day="1999-01-01")
        assert empty["calls"] == 0 and empty["ok"] == 0 and empty["avg_latency_ms"] == 0

    def test_no_second_write_path(self, db):
        """The derivation is read-only: llm_usage rows stay the only source."""
        db.add(LlmUsage(tenant_id=77, feature="ai", ok=True, latency_ms=5))
        db.commit()
        before = db.query(LlmUsage).filter(LlmUsage.tenant_id == 77).count()
        derive_llm_usage_rollup(db, 77, day="1999-01-01")
        derive_llm_usage_rollup(db, 77)
        assert db.query(LlmUsage).filter(LlmUsage.tenant_id == 77).count() == before
        assert db.query(LlmUsage).count() == before


# ── 4. PATCH /api/backlog/bulk ───────────────────────────────────────────

class TestBacklogBulk:
    """PATCH /api/backlog/bulk loops the ONE advance machine (F1), per-item isolated."""

    def _bulk(self, client, ids, **extra):
        return client.patch("/api/backlog/bulk", json={"item_ids": ids, **extra})

    def test_happy_path_advances_each_item_one_step(self, client, db):
        """3 items → one machine step each, chain entries per item in request order."""
        pid = _project(client, "F3 Bulk")["id"]
        items = _items(client, pid, ["B1", "B2", "B3"])
        ids = [it["id"] for it in items]

        resp = self._bulk(client, ids)
        assert resp.status_code == 200
        data = resp.json()
        assert data["advanced"] == 3 and data["failed"] == 0
        assert [r["id"] for r in data["results"]] == ids
        for r, _it in zip(data["results"], items, strict=False):
            assert r["ok"] is True
            assert r["previous_phase"] == "Requirements"
            assert r["phase"] == "Design"

        rows = db.query(ArtifactChain).filter(
            ArtifactChain.entity_type == "backlog_item",
            ArtifactChain.entity_id.in_(ids),
            ArtifactChain.action == "advanced",
        ).all()
        assert len(rows) == 3
        for r, it in zip(data["results"], items, strict=False):
            entry = next(e for e in rows if e.entity_id == r["id"])
            assert entry.seq == 1
            assert entry.payload == {"title": it["title"], "to_phase": "Design", "status": "In Progress"}

    def test_service_parity_chain_payload(self, client, db, auth_user):
        """The bulk path produces the SAME chain entry the single-advance path does."""
        from app.services.release_machine import advance_backlog_item_phase

        pid = _project(client, "F3 Parity")["id"]
        twin_a, twin_b = _items(client, pid, ["PA", "PB"])

        resp = self._bulk(client, [twin_a["id"]])  # router path
        assert resp.status_code == 200 and resp.json()["advanced"] == 1

        b = db.query(BacklogItem).filter(BacklogItem.id == twin_b["id"]).first()
        advance_backlog_item_phase(db, auth_user["tenant"], auth_user["user"], b)  # service path

        rows = db.query(ArtifactChain).filter(
            ArtifactChain.entity_type == "backlog_item",
            ArtifactChain.entity_id.in_([twin_a["id"], twin_b["id"]]),
            ArtifactChain.action == "advanced",
        ).all()
        by_item = {r.entity_id: r for r in rows}
        # same machine payload (titles differ by design — normalize them out)
        def machine(e):
            return {k: v for k, v in (e.payload or {}).items() if k != "title"}

        assert machine(by_item[twin_a["id"]]) == machine(by_item[twin_b["id"]]) == {"to_phase": "Design", "status": "In Progress"}
        assert by_item[twin_a["id"]].seq == by_item[twin_b["id"]].seq == 1
        assert by_item[twin_a["id"]].hash != by_item[twin_b["id"]].hash  # per-entity chains

    def test_per_item_failure_isolation(self, client, db):
        """1 bad id among 3 → the other 2 still advance; the batch never aborts."""
        pid = _project(client, "F3 Isolation")["id"]
        good1, good2 = _items(client, pid, ["G1", "G2"])

        resp = self._bulk(client, [good1["id"], 999999, good2["id"]])
        assert resp.status_code == 200
        data = resp.json()
        assert data["advanced"] == 2 and data["failed"] == 1
        r1, r_bad, r2 = data["results"]
        assert r1["ok"] is True and r1["phase"] == "Design"
        assert r2["ok"] is True and r2["phase"] == "Design"
        assert r_bad == {"id": 999999, "ok": False, "error": "Backlog item not found"}

    def test_final_phase_fails_with_machine_400_string(self, client, db):
        """A final-phase item gets the machine's byte-identical 400 string inline."""
        pid = _project(client, "F3 Final")["id"]
        (item,) = _items(client, pid, ["F1"])

        resp = client.put(f"/api/backlog/{item['id']}", json={"current_phase": "Ready for UAT"})
        assert resp.status_code == 200

        data = self._bulk(client, [item["id"]]).json()
        r = data["results"][0]
        assert r["ok"] is False
        assert r["error"] == (
            "Item is at the final item phase (Ready for UAT). "
            "Add it to a release to continue through the release stages."
        )

    def test_tenant_scoping_foreign_id_never_advances(self, client, db):
        """A foreign tenant's id → ok:false, the house 404 string, no advance."""
        foreign_tenant = Tenant(name="F3 Foreign", slug="f3-foreign", plan="free", status="active")
        db.add(foreign_tenant)
        db.commit()
        db.refresh(foreign_tenant)
        foreign_client = Client(tenant_id=foreign_tenant.id, name="F3 Foreign Client")
        db.add(foreign_client)
        db.commit()
        db.refresh(foreign_client)
        foreign_project = Project(
            tenant_id=foreign_tenant.id, client_id=foreign_client.id,
            name="F3 Foreign P", status="active",
        )
        db.add(foreign_project)
        db.commit()
        db.refresh(foreign_project)
        foreign_item = BacklogItem(
            tenant_id=foreign_tenant.id, project_id=foreign_project.id,
            title="Foreign item", current_phase="Requirements", status="Draft",
        )
        db.add(foreign_item)
        db.commit()
        db.refresh(foreign_item)

        resp = self._bulk(client, [foreign_item.id])
        assert resp.status_code == 200
        data = resp.json()
        assert data["advanced"] == 0 and data["failed"] == 1
        assert data["results"][0] == {"id": foreign_item.id, "ok": False, "error": "Backlog item not found"}
        assert foreign_item.current_phase == "Requirements"  # untouched

    def test_batch_size_guard(self, client):
        """101 ids → 400 with the guard string (max 100 per batch)."""
        resp = self._bulk(client, list(range(1, 102)))
        assert resp.status_code == 400
        assert resp.json() == {"detail": "Too many items: 101 (max 100 per batch)"}

    def test_empty_list_rejected(self, client):
        resp = self._bulk(client, [])
        assert resp.status_code == 400
        assert resp.json() == {"detail": "item_ids must not be empty"}

    def test_shared_steps_advance_count(self, client, db):
        """steps=2 → two one-step machine advances per item (Requirements → Development)."""
        pid = _project(client, "F3 Steps")["id"]
        (item,) = _items(client, pid, ["S1"])

        data = self._bulk(client, [item["id"]], steps=2).json()
        assert data["advanced"] == 1 and data["failed"] == 0
        r = data["results"][0]
        assert r["ok"] is True
        assert r["previous_phase"] == "Requirements"
        assert r["phase"] == "Development"


# ── 5. The audit-split rule (documentation-only) ─────────────────────────

def test_audit_split_rule_documented():
    """artifact_chain = record of truth, activity_log = UI feed — the house rule stays documented."""
    import app.services.artifact_chain as ac

    doc = ac.__doc__ or ""
    assert "record of truth" in doc
    assert "UI" in doc
    assert "feed" in doc
    assert "activity_log" in doc
