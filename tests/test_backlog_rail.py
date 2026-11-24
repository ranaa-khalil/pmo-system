"""Rethink v2 Phase C1 — the effective-template source + GET /backlog/rail.

The phase vocabulary used to live in THREE places (lifecycle_templates rows,
the backlog_item.py ITEM_PHASES/RELEASE_PHASES constants, hardcoded JS) and
the advance guards read the PYTHON CONSTANTS — so a tenant's custom ADLC
template could never drive the advance chain (the template was decorative,
"the phases part is not connected").

These tests pin the ONE effective source:
- get_effective_lifecycle(): built-in phases (backlog_item.py constants,
  byte-identical for tenants without a template row) OVERRIDDEN by the
  tenant's TenantLifecycleTemplate row when one exists;
- GET /projects/{id}/backlog/rail: that vocabulary + per-phase gate info
  shaped for the frontend rail;
- the advance guards (backlog item + release) re-pointed to the same source:
  a tenant's custom ADLC template finally DRIVES the advance chain, and
  phases outside the effective set are rejected (normalised to the
  template's first phase, never advanced into).
"""
import app.models  # noqa: F401
from app.models.backlog_item import ITEM_PHASES, RELEASE_PHASES, BacklogItem
from app.models.client import Client
from app.models.lifecycle_template import TenantLifecycleTemplate
from app.models.project import Project
from app.models.release import Release
from app.models.tenant import Tenant
from app.services.lifecycle import get_effective_lifecycle

# ── helpers ──────────────────────────────────────────────────────────────

def _project(client, name="Rail P", project_type="software"):
    cid = client.post("/api/clients", json={"name": f"C {name}"}).json()["id"]
    return client.post("/api/projects", json={
        "name": name, "client_id": cid, "project_type": project_type,
    }).json()


def _tenant_template(db, tenant_id, project_type="adlc"):
    """A custom ADLC template whose phases differ from the Software defaults
    AND from the built-in ADLC vocabulary."""
    row = TenantLifecycleTemplate(
        tenant_id=tenant_id,
        project_type=project_type,
        name="Tenant ADLC",
        item_phases=["Discovery", "Guardrail Review", "Agent Build", "Ready for Release"],
        release_stages=["Intent Review", "Scenario Validation", "Live Monitoring"],
        gate_deliverables={
            "Discovery": ["Intent spec"],
            "Guardrail Review": ["Guardrail policy"],
            "Agent Build": ["Agent run log"],
            "Ready for Release": ["Rollback plan"],
        },
        gate_roles={
            "Discovery": "Product Manager",
            "Guardrail Review": "Tech Lead",
            "Agent Build": "Tech Lead",
            "Ready for Release": "DevOps Lead",
        },
        fields=[],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _db_item(db, tenant_id, pid, phase, title="Agent task"):
    item = BacklogItem(tenant_id=tenant_id, project_id=pid, title=title, current_phase=phase)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


# ── the effective-template source (service level) ────────────────────────

class TestEffectiveLifecycleSource:
    def test_builtin_fallback_is_byte_identical_to_constants(self, db, auth_user):
        """A tenant WITHOUT a template row gets the built-in vocabulary —
        for software, byte-identical to backlog_item.py's constants."""
        eff = get_effective_lifecycle(db, auth_user["tenant"].id, "software")
        assert eff["item_phases"] == ITEM_PHASES
        assert eff["release_stages"] == RELEASE_PHASES
        assert eff["source"] == "builtin"

    def test_unknown_type_falls_back_to_software(self, db, auth_user):
        eff = get_effective_lifecycle(db, auth_user["tenant"].id, "no-such-type")
        assert eff["item_phases"] == ITEM_PHASES
        assert eff["source"] == "builtin"

    def test_tenant_template_overrides_everything(self, db, auth_user):
        row = _tenant_template(db, auth_user["tenant"].id)
        eff = get_effective_lifecycle(db, auth_user["tenant"].id, "adlc")
        assert eff["item_phases"] == row.item_phases
        assert eff["release_stages"] == row.release_stages
        assert eff["gate_deliverables"] == row.gate_deliverables
        assert eff["gate_roles"] == row.gate_roles
        assert eff["source"] == "template"

    def test_template_only_applies_to_its_type(self, db, auth_user):
        """The row overrides 'adlc' only — software keeps the constants."""
        _tenant_template(db, auth_user["tenant"].id)
        eff = get_effective_lifecycle(db, auth_user["tenant"].id, "software")
        assert eff["item_phases"] == ITEM_PHASES
        assert eff["source"] == "builtin"


# ── the rail endpoint ────────────────────────────────────────────────────

class TestBacklogRail:
    def test_builtin_fallback_matches_constants(self, client):
        """No template row → the built-in rail: the constants verbatim."""
        pid = _project(client)["id"]
        client.post(f"/api/projects/{pid}/backlog", json={
            "project_id": pid, "title": "A", "item_type": "Feature",
        })
        resp = client.get(f"/api/projects/{pid}/backlog/rail")
        assert resp.status_code == 200
        body = resp.json()
        assert body["project_id"] == pid
        assert body["source"] == "builtin"
        assert body["item_types"] == ["Feature"]
        names = [p["name"] for p in body["phases"]]
        assert names == ITEM_PHASES + RELEASE_PHASES
        for i, p in enumerate(body["phases"]):
            assert p["order"] == i
            assert p["is_release_stage"] is (i >= len(ITEM_PHASES))
        # Built-in software gate info rides along (from the built-in template)
        requirements = body["phases"][0]
        assert requirements["gate"]["deliverables"] == ["BRD", "Requirements traceability matrix"]
        assert requirements["gate"]["roles"] == ["Product Manager"]
        # Release stages have no gate mapping → null
        assert body["phases"][len(ITEM_PHASES)]["gate"] is None

    def test_tenant_template_overrides_phases_and_gates(self, client, db, auth_user):
        pid = _project(client, project_type="adlc")["id"]
        row = _tenant_template(db, auth_user["tenant"].id)
        client.post(f"/api/projects/{pid}/backlog", json={
            "project_id": pid, "title": "B", "item_type": "Bug",
        })
        resp = client.get(f"/api/projects/{pid}/backlog/rail")
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "template"
        names = [p["name"] for p in body["phases"]]
        assert names == row.item_phases + row.release_stages
        assert body["item_types"] == ["Bug"]
        # Gate deliverables + roles come from the tenant's template row
        first = body["phases"][0]
        assert first["name"] == "Discovery"
        assert first["gate"] == {"deliverables": ["Intent spec"], "roles": ["Product Manager"]}
        # Release stages flagged, no gate
        release_stage = body["phases"][len(row.item_phases)]
        assert release_stage["name"] == "Intent Review"
        assert release_stage["is_release_stage"] is True
        assert release_stage["gate"] is None

    def test_template_project_is_not_its_builtin(self, client, db, auth_user):
        """An adlc project with a template row does NOT serve the built-in
        ADLC phases — the override wins."""
        _tenant_template(db, auth_user["tenant"].id)
        pid = _project(client, project_type="adlc")["id"]
        names = [p["name"] for p in client.get(f"/api/projects/{pid}/backlog/rail").json()["phases"]]
        assert "Tooling & Guardrails" not in names  # built-in ADLC phase
        assert "Discovery" in names  # template phase

    def test_foreign_tenant_project_404(self, client, db):
        other = Tenant(name="Other Rail", slug="other-rail", plan="team")
        db.add(other)
        db.commit()
        db.refresh(other)
        oc = Client(name="Other rail client", tenant_id=other.id)
        db.add(oc)
        db.commit()
        db.refresh(oc)
        other_project = Project(tenant_id=other.id, client_id=oc.id, name="Hidden rail")
        db.add(other_project)
        db.commit()
        db.refresh(other_project)

        resp = client.get(f"/api/projects/{other_project.id}/backlog/rail")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Project not found"

    def test_missing_project_404(self, client):
        resp = client.get("/api/projects/999999/backlog/rail")
        assert resp.status_code == 404

    def test_anon_401(self, anon_client):
        resp = anon_client.get("/api/projects/1/backlog/rail")
        assert resp.status_code == 401


# ── THE ADLC TEST: the tenant template drives the advance chain ──────────

class TestTemplateDrivesAdvance:
    """The bug the user feels: a tenant's custom ADLC template could never
    drive the advance chain because the guard checked the Python constants /
    built-in vocabulary. Now the template row drives it."""

    def test_custom_adlc_template_walks_its_own_phases(self, client, db, auth_user):
        pid = _project(client, project_type="adlc")["id"]
        row = _tenant_template(db, auth_user["tenant"].id)
        item = _db_item(db, auth_user["tenant"].id, pid, row.item_phases[0])

        # Walk the TEMPLATE's ladder — impossible before C1, when the guard
        # only knew the built-in vocabulary and reset the item instead.
        for expected in row.item_phases[1:]:
            resp = client.post(f"/api/backlog/{item.id}/advance")
            assert resp.status_code == 200, resp.text
            assert resp.json()["current_phase"] == expected
        assert "Discovery" not in row.item_phases[1:]  # sanity: template phases

        # At the final template phase → 400 naming the template's phase
        resp = client.post(f"/api/backlog/{item.id}/advance")
        assert resp.status_code == 400
        assert row.item_phases[-1] in resp.json()["detail"]

    def test_phase_outside_effective_set_is_rejected(self, client, db, auth_user):
        """A Software phase on a template project is outside the effective
        set — the guard normalises it to the template's first phase instead
        of advancing into a foreign phase."""
        pid = _project(client, project_type="adlc")["id"]
        row = _tenant_template(db, auth_user["tenant"].id)
        item = _db_item(db, auth_user["tenant"].id, pid, "Design")

        resp = client.post(f"/api/backlog/{item.id}/advance")
        assert resp.status_code == 200
        assert resp.json()["current_phase"] == row.item_phases[0]

    def test_template_release_stage_item_is_not_reset(self, client, db, auth_user):
        """An item parked on one of the template's release stages belongs to
        the release workflow — advancing must not move it."""
        pid = _project(client, project_type="adlc")["id"]
        row = _tenant_template(db, auth_user["tenant"].id)
        item = _db_item(db, auth_user["tenant"].id, pid, row.release_stages[0])

        resp = client.post(f"/api/backlog/{item.id}/advance")
        assert resp.status_code == 200
        assert resp.json()["current_phase"] == row.release_stages[0]

    def test_release_advance_walks_template_release_stages(self, client, db, auth_user):
        """A release parked on a template release stage advances along the
        TEMPLATE's ladder (the V-cycle stays the built-in fallback)."""
        pid = _project(client, project_type="adlc")["id"]
        row = _tenant_template(db, auth_user["tenant"].id)
        release = Release(
            tenant_id=auth_user["tenant"].id, project_id=pid,
            version="1.0.0", name="R", status=row.release_stages[0],
        )
        db.add(release)
        db.commit()
        db.refresh(release)

        resp = client.post(f"/api/releases/{release.id}/advance")
        assert resp.status_code == 200
        assert resp.json()["status"] == row.release_stages[1]

    def test_release_at_final_template_stage_400(self, client, db, auth_user):
        pid = _project(client, project_type="adlc")["id"]
        row = _tenant_template(db, auth_user["tenant"].id)
        release = Release(
            tenant_id=auth_user["tenant"].id, project_id=pid,
            version="1.0.1", name="R2", status=row.release_stages[-1],
        )
        db.add(release)
        db.commit()
        db.refresh(release)

        resp = client.post(f"/api/releases/{release.id}/advance")
        assert resp.status_code == 400
        assert row.release_stages[-1] in resp.json()["detail"]

    def test_release_without_template_keeps_v_cycle(self, client, db, auth_user):
        """No template row → an unknown status still 400s (built-in V-cycle
        vocabulary unchanged)."""
        pid = _project(client)["id"]
        release = Release(
            tenant_id=auth_user["tenant"].id, project_id=pid,
            version="1.0.2", name="R3", status="Not a phase",
        )
        db.add(release)
        db.commit()
        db.refresh(release)

        resp = client.post(f"/api/releases/{release.id}/advance")
        assert resp.status_code == 400
        assert "Unknown status" in resp.json()["detail"]


# ── built-in tenants unchanged ───────────────────────────────────────────

class TestBuiltinAdvanceUnchanged:
    def test_builtin_adlc_still_walks_builtin_phases(self, client):
        """No template row → the built-in ADLC vocabulary drives the advance
        (byte-identical to pre-C1 behavior)."""
        pid = _project(client, project_type="adlc")["id"]
        bid = client.post(f"/api/projects/{pid}/backlog", json={
            "project_id": pid, "title": "X",
        }).json()["id"]
        assert client.post(f"/api/backlog/{bid}/advance").json()["current_phase"] == "Tooling & Guardrails"
        resp = client.post(f"/api/backlog/{bid}/advance")
        assert resp.status_code == 200
        assert resp.json()["current_phase"] == "Agent Build"

    def test_builtin_software_final_phase_400_unchanged(self, client):
        pid = _project(client)["id"]
        bid = client.post(f"/api/projects/{pid}/backlog", json={
            "project_id": pid, "title": "Y",
        }).json()["id"]
        client.put(f"/api/backlog/{bid}", json={"current_phase": "Ready for UAT"})
        resp = client.post(f"/api/backlog/{bid}/advance")
        assert resp.status_code == 400
        assert "final item phase" in resp.json()["detail"]
