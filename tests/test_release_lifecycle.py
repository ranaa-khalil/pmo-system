"""The dynamic release lifecycle — tests (Release Lifecycle Dynamic Design §3).

Pins the design's contract, each re-verified against HEAD:

- Ladder resolution (§3.2): release_lifecycle() is the ONE release-stage
  ladder per tenant + project type — the software family walks the 7-phase
  V-cycle byte-identically (the 4 live releases), the other built-ins and
  tenant template rows use their complete release_stages; a tenant row wins
  over the built-in.
- Gates are MANDATORY (§3.3): every stage transition of every built-in
  template carries a RACI gate — the gate-free advance branch is DELETED,
  so a gate-free transition cannot exist.
- Save-time validation (§3.3/FR-R2): a template whose non-final release
  stages lack gate_roles is refused with a 400 — a template that bypasses
  governance cannot be saved.
- Released → Post-Release is reachable (§3.6, QA finding 2 closed): the
  guard that made it unreachable is deleted; the advance creates the DevOps
  Lead confirm gate and the stale Pending Post-Release approval completes.
- Direct status PUTs restricted (§3.7, QA finding 3 closed): forward moves
  400 with the gate-path message; in-ladder backward/same-stage writes land;
  Cancelled stays allowed.
- release_date stamps at each built-in's live_stage (§3.2/§3.4); creation
  starts at S1 (§3.8/FR-R1); zero schema migration — the old hardcoded
  V-cycle states keep working byte-identically (§3.10).
"""
from datetime import date
from pathlib import Path

import pytest

import app.models  # noqa: F401
from app.models.approval import ApprovalRequest, ApprovalStep
from app.models.lifecycle_template import TenantLifecycleTemplate
from app.models.project import Project
from app.models.release import Release
from app.services.lifecycle import (
    LIFECYCLE_TEMPLATES,
    SOFTWARE_RELEASE_GATES,
    get_effective_lifecycle,
    release_done_phases,
    release_lifecycle,
    release_sync_done_phases,
)
from app.services.release_machine import advance_release_phase

REPO = Path(__file__).resolve().parent.parent
LIFECYCLE_PY = REPO / "app/services/lifecycle.py"
MACHINE_PY = REPO / "app/services/release_machine.py"
RELEASES_PY = REPO / "app/routers/releases.py"
LIFECYCLE_ROUTER_PY = REPO / "app/routers/lifecycle.py"
STATS_PY = REPO / "app/services/stats.py"
MODEL_PY = REPO / "app/models/release.py"

BUILTIN_KEYS = ["software", "ai", "marketing", "operations", "sdlc", "adlc", "hybrid"]


def _read(path: Path) -> str:
    assert path.exists(), f"{path.name} missing"
    return path.read_text(encoding="utf-8")


# ── Static pins — the house shape ────────────────────────────────────────


def test_static_machine_walks_the_dynamic_ladder():
    """release_machine imports the ladder resolvers from services.lifecycle —
    the hardcoded V_CYCLE/PHASE_GATE_ROLES references are gone."""
    src = _read(MACHINE_PY)
    assert "release_lifecycle" in src and "release_gate" in src
    assert "from app.services.lifecycle import" in src
    assert "V_CYCLE" not in src, "the machine must read the resolved ladder, not a hardcoded V-cycle"
    assert "PHASE_GATE_ROLES" not in src, "the machine must use release_gate, not a hardcoded table"


def test_static_gate_free_advance_branch_is_deleted():
    """The gate-free template fallback (advance directly when no gate) is
    REJECTED and deleted — every stage transition creates its RACI approval."""
    src = _read(MACHINE_PY)
    assert "No gate for this phase" not in src, "the gate-free advance branch is back"
    assert '{"id": release.id, "status": release.status, "message": f"Advanced to {next_phase}"}' not in src, (
        "the gate-free direct-advance return is back"
    )
    assert "release_gate(" in src


def test_static_releases_router_retires_the_hardcoded_ladder():
    """V_CYCLE / PHASE_GATE_ROLES retired from the router (moved verbatim to
    services/lifecycle.py); the PUT gate-path 400 is present."""
    src = _read(RELEASES_PY)
    assert "V_CYCLE = [" not in src
    assert "PHASE_GATE_ROLES" not in src
    assert "Status changes only through the gate path: POST /api/releases/{id}/advance" in src
    assert "RELEASE_LIFECYCLE_SOFTWARE" in src


def test_static_software_gates_moved_verbatim():
    """The software release-gate data lives in lifecycle.py verbatim — the
    'Released' entry is live again as the Released → Post-Release gate."""
    src = _read(LIFECYCLE_PY)
    assert 'RELEASE_LIFECYCLE_SOFTWARE = [' in src
    assert '"Released":     ("DevOps Lead",     "Confirm deployment success and begin monitoring"' in src
    assert SOFTWARE_RELEASE_GATES["Released"][0] == "DevOps Lead"


def test_static_template_save_validates_gate_coverage():
    """create_tenant_template calls the gate-coverage validator and 400s —
    a template that bypasses governance cannot be saved."""
    src = _read(LIFECYCLE_ROUTER_PY)
    assert "missing_release_gate_roles(" in src
    assert "bypasses governance cannot be saved" in src


def test_static_done_vocabulary_sites_are_template_derived():
    """The 5 hardcoded done-vocabulary sites read the template-derived helper
    (releases.py ×4 + stats.py; the model's dead constant is deleted)."""
    rel_src = _read(RELEASES_PY)
    assert rel_src.count('["Pre-Release", "Release", "Post-Release", "Retrospective"]') == 0, (
        "a hardcoded done list is back in releases.py"
    )
    assert "release_done_phases(" in rel_src
    stats_src = _read(STATS_PY)
    assert "DONE_PHASES = [" not in stats_src
    assert "release_done_phases" in stats_src
    model_src = _read(MODEL_PY)
    assert "RELEASE_STATUSES" not in model_src


def test_static_release_date_stamps_at_the_ladder_live_stage():
    """release_date is stamped iff the next phase == ladder["live_stage"] —
    the two hardcoded 'Released' literals are gone."""
    src = _read(MACHINE_PY)
    assert 'ladder["live_stage"]' in src
    assert src.count('if next_phase == "Released"') == 0


# ── Ladder resolution (§3.2) ─────────────────────────────────────────────


def _project(db, auth_user, name, project_type=None):
    project = Project(name=name, client_id=1, tenant_id=auth_user["tenant"].id)
    if project_type:
        project.project_type = project_type
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def test_ladder_software_is_the_v_cycle_byte_identical(db, auth_user):
    """Software family (software, sdlc, hybrid, unknown, None) resolves the
    7-phase V-cycle with live_stage Released — byte-identical for the 4 live
    releases."""
    tenant = auth_user["tenant"]
    for project_type in ("software", "sdlc", "hybrid", "unknown-type", None):
        ladder = release_lifecycle(db, tenant.id, project_type)
        assert ladder["source"] == "builtin"
        assert ladder["stages"] == [
            "Planning", "In Progress", "Testing", "UAT",
            "Pre-Release", "Released", "Post-Release",
        ]
        assert ladder["live_stage"] == "Released"


def test_ladder_non_software_builtins_use_their_complete_stages(db, auth_user):
    """ai/marketing/operations/adlc release_stages are already complete
    end-to-end ladders — the ladder is that list, with their authored live
    stage."""
    tenant = auth_user["tenant"]
    expected_live = {
        "ai": ("Model Deployment", 6),
        "marketing": ("Launch", 6),
        "operations": ("Verification", 5),
        "adlc": ("Agent Deployment", 5),
    }
    for key, (live, n_stages) in expected_live.items():
        ladder = release_lifecycle(db, tenant.id, key)
        assert ladder["source"] == "builtin"
        assert ladder["stages"] == LIFECYCLE_TEMPLATES[key]["release_stages"]
        assert len(ladder["stages"]) == n_stages
        assert ladder["live_stage"] == live


def test_ladder_tenant_row_wins_over_builtin(db, auth_user):
    """A tenant template row authors the complete release ladder — it wins
    over the built-in."""
    tenant = auth_user["tenant"]
    row = TenantLifecycleTemplate(
        tenant_id=tenant.id, project_type="software",
        name="Tenant Ladder",
        item_phases=["Discovery", "Build"],
        release_stages=["S1", "S2", "S3"],
        gate_deliverables={"S1": ["Spec"]},
        gate_roles={"S1": "Product Manager", "S2": "Tech Lead"},
        fields=[],
    )
    db.add(row)
    db.commit()

    ladder = release_lifecycle(db, tenant.id, "software")
    assert ladder["source"] == "template"
    assert ladder["stages"] == ["S1", "S2", "S3"]
    # live stage: "Released" absent → the final stage
    assert ladder["live_stage"] == "S3"


def test_done_phases_software_verbatim_and_template_derived(db, auth_user):
    """The display done set and the item-sync tuple: software keeps today's
    verbatim lists; other ladders count from their live stage onward."""
    tenant = auth_user["tenant"]
    assert release_done_phases(db, tenant.id, "software") == [
        "Pre-Release", "Release", "Post-Release", "Retrospective",
    ]
    assert release_sync_done_phases(db, tenant.id, "software") == (
        "Release", "Post-Release", "Retrospective",
    )
    assert release_done_phases(db, tenant.id, "ai") == [
        "Model Deployment", "Post-Deployment Monitoring",
    ]
    assert release_sync_done_phases(db, tenant.id, "ai") == (
        "Model Deployment", "Post-Deployment Monitoring",
    )


# ── Gates are mandatory (§3.3) ───────────────────────────────────────────


def test_gate_on_every_transition_of_every_builtin_template(db, auth_user):
    """Property-style sweep over LIFECYCLE_TEMPLATES: every non-final stage of
    every built-in yields a gate with a role — a gate-free transition cannot
    exist (the mechanism is inviolable)."""
    tenant = auth_user["tenant"]
    for key in BUILTIN_KEYS:
        ladder = release_lifecycle(db, tenant.id, key)
        eff = get_effective_lifecycle(db, tenant.id, key)
        stages = ladder["stages"]
        for stage in stages[:-1]:
            role, desc, checklist = release_gate_checked(stage, eff)
            assert role, f"{key}: stage {stage!r} has no gate role"
            assert desc, f"{key}: stage {stage!r} has no gate description"
            assert checklist, f"{key}: stage {stage!r} has no gate checklist"


def release_gate_checked(stage, eff):
    from app.services.lifecycle import release_gate
    return release_gate(stage, eff)


def test_authored_gate_tables_map_the_non_software_builtins(db, auth_user):
    """The §3.14 authored tables: roles match the doc's gate table."""
    tenant = auth_user["tenant"]
    expectations = {
        "ai": {
            "Business Understanding": "Product Manager",
            "Data Readiness & Processing": "Data/ML Lead",
            "Model Development & Training": "Tech Lead",
            "Evaluation": "Product Manager",
            "Model Deployment": "DevOps Lead",
        },
        "marketing": {
            "Briefing": "Product Manager",
            "Content Production": "Content Lead",
            "Launch": "Product Manager",
        },
        "operations": {
            "Intake": "Product Manager",
            "Execution": "Operations Lead",
            "Verification": "Product Manager",
        },
        "adlc": {
            "Intent Review": "Product Manager",
            "Scenario Validation": "Tech Lead",
            "Agent Deployment": "DevOps Lead",
            "Live Monitoring": "Tech Lead",
        },
    }
    for key, table in expectations.items():
        eff = get_effective_lifecycle(db, tenant.id, key)
        for stage, role in table.items():
            got_role, _, _ = release_gate_checked(stage, eff)
            assert got_role == role, f"{key}/{stage}: {got_role!r} != {role!r}"


def test_template_save_400s_ungated_templates(client):
    """A template whose non-final release stages lack gate_roles is refused
    with a 400 listing the missing stages; a gated template saves."""
    ungated = client.post("/api/lifecycle/templates", json={
        "project_type": "research",
        "name": "Research (ungated)",
        "item_phases": ["Discover", "Deliver"],
        "release_stages": ["Intake", "Fieldwork", "Published"],
        "gate_deliverables": {},
        "gate_roles": {},  # no gate roles — bypasses governance
        "fields": [],
    })
    assert ungated.status_code == 400
    assert "Gate roles are required" in ungated.json()["detail"]
    assert "Intake" in ungated.json()["detail"]
    assert "Fieldwork" in ungated.json()["detail"]

    gated = client.post("/api/lifecycle/templates", json={
        "project_type": "research",
        "name": "Research (gated)",
        "item_phases": ["Discover", "Deliver"],
        "release_stages": ["Intake", "Fieldwork", "Published"],
        "gate_deliverables": {},
        "gate_roles": {"Intake": "Product Manager", "Fieldwork": "Tech Lead"},
        "fields": [],
    })
    assert gated.status_code == 201, gated.text


# ── Released → Post-Release reachable (§3.6) ─────────────────────────────


def test_advance_at_released_creates_the_post_release_gate(db, auth_user):
    """Released is a normal ladder stage: the advance creates the DevOps Lead
    confirm gate (dead code under the old guards — live again) and the
    approval completes the move."""
    tenant, user = auth_user["tenant"], auth_user["user"]
    project = _project(db, auth_user, "Released P")

    release = Release(tenant_id=tenant.id, project_id=project.id, version="9.0.0", name="RM", status="Released")
    db.add(release)
    db.commit()
    db.refresh(release)

    first = advance_release_phase(db, tenant, user, release)
    assert first["approval_status"] == "created"
    assert first["pending_role"] == "DevOps Lead"
    assert first["target_phase"] == "Post-Release"
    assert "Confirm deployment success and begin monitoring" in str(
        db.query(ApprovalRequest).filter(ApprovalRequest.id == first["approval_id"]).first().description
    )
    db.refresh(release)
    assert release.status == "Released"  # the gate keeps the release in place


def test_stale_pending_post_release_approval_completes(db, auth_user):
    """The stale Pending Post-Release approval auto-created under the old
    guard becomes completable: its target_phase matches, the Approved branch
    reuses it, and the release lands in Post-Release."""
    tenant, user = auth_user["tenant"], auth_user["user"]
    project = _project(db, auth_user, "Stale P")

    release = Release(tenant_id=tenant.id, project_id=project.id, version="9.1.0", name="RS", status="Released")
    db.add(release)
    db.commit()
    db.refresh(release)

    stale = ApprovalRequest(
        tenant_id=tenant.id, project_id=project.id,
        title="Release 9.1.0: Released → Post-Release",
        request_type="release", requested_by=user.id,
        release_id=release.id, target_phase="Post-Release",
        status="Pending",
    )
    db.add(stale)
    db.commit()

    # The machine reports the pending approval (no new one is created)
    pending = advance_release_phase(db, tenant, user, release)
    assert pending["approval_status"] == "pending"
    assert pending["approval_id"] == stale.id

    # Approving the stale step completes the move
    stale.status = "Approved"
    db.commit()
    done = advance_release_phase(db, tenant, user, release)
    assert done["approval_status"] == "approved"
    db.refresh(release)
    assert release.status == "Post-Release"
    assert release.release_date is None  # Post-Release is not the live stage


def test_approve_gate_stamps_release_date_at_the_live_stage(client, db, auth_user):
    """The approve endpoint's AUTO-ADVANCE stamps release_date at the
    release's RESOLVED ladder live stage — literally 'Released' only for the
    software family (§3.4: the ladder owns the semantics, not the handler)."""
    tenant, user = auth_user["tenant"], auth_user["user"]
    project = _project(db, auth_user, "Stamp P")

    release = Release(tenant_id=tenant.id, project_id=project.id, version="9.2.0", name="RA", status="Pre-Release")
    db.add(release)
    db.commit()
    db.refresh(release)

    gate = advance_release_phase(db, tenant, user, release)
    assert gate["approval_status"] == "created"
    assert gate["target_phase"] == "Released"  # the Pre-Release gate → live stage

    step = db.query(ApprovalStep).filter(
        ApprovalStep.request_id == gate["approval_id"], ApprovalStep.status == "Pending"
    ).first()
    resp = client.post(f"/api/approvals/{gate['approval_id']}/steps/{step.id}/approve")
    assert resp.status_code == 200
    db.refresh(release)
    assert release.status == "Released"  # the approve endpoint moves the release
    assert release.release_date == date.today().isoformat()  # stamped at the live stage

    # a non-live target does NOT stamp: Testing is not the software live stage
    release2 = Release(tenant_id=tenant.id, project_id=project.id, version="9.2.1", name="RB", status="In Progress")
    db.add(release2)
    db.commit()
    db.refresh(release2)
    gate2 = advance_release_phase(db, tenant, user, release2)
    assert gate2["approval_status"] == "created"
    step2 = db.query(ApprovalStep).filter(
        ApprovalStep.request_id == gate2["approval_id"], ApprovalStep.status == "Pending"
    ).first()
    resp2 = client.post(f"/api/approvals/{gate2['approval_id']}/steps/{step2.id}/approve")
    assert resp2.status_code == 200
    db.refresh(release2)
    assert release2.status == "Testing"
    assert release2.release_date is None  # Testing is not the live stage


# ── Direct status PUTs restricted (§3.7) ─────────────────────────────────


def test_put_forward_status_is_the_gate_bypass_closed(client, db, auth_user):
    """A forward status PUT 400s with the exact gate-path message (QA
    finding 3: the release moved Released → Post-Release directly)."""
    tenant = auth_user["tenant"]
    project = _project(db, auth_user, "PUT P")
    release = Release(tenant_id=tenant.id, project_id=project.id, version="2.0.0", name="RP", status="UAT")
    db.add(release)
    db.commit()
    db.refresh(release)

    resp = client.put(f"/api/releases/{release.id}", json={"status": "Pre-Release"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == (
        "Status changes only through the gate path: POST /api/releases/{id}/advance"
    )
    db.refresh(release)
    assert release.status == "UAT"  # nothing moved


def test_put_backward_and_cancelled_status_lands(client, db, auth_user):
    """In-ladder backward/same-stage writes land (re-plan, rollback, legacy
    import); Cancelled stays allowed (terminal, outside the gate path);
    an unknown status 400s."""
    tenant = auth_user["tenant"]
    project = _project(db, auth_user, "PUT B P")
    release = Release(tenant_id=tenant.id, project_id=project.id, version="2.1.0", name="RB", status="UAT")
    db.add(release)
    db.commit()
    db.refresh(release)

    backward = client.put(f"/api/releases/{release.id}", json={"status": "Testing"})
    assert backward.status_code == 200
    assert backward.json()["status"] == "Testing"

    same = client.put(f"/api/releases/{release.id}", json={"status": "Testing"})
    assert same.status_code == 200  # same-stage parking

    cancelled = client.put(f"/api/releases/{release.id}", json={"status": "Cancelled"})
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "Cancelled"

    unknown = client.put(f"/api/releases/{release.id}", json={"status": "Not a phase"})
    assert unknown.status_code == 400
    assert "Unknown status" in unknown.json()["detail"]


# ── release_date stamps at the live stage (§3.2/§3.4) ────────────────────


@pytest.mark.parametrize("key", BUILTIN_KEYS)
def test_release_date_stamps_at_each_builtin_live_stage(db, auth_user, key):
    """The Approved branch stamps release_date iff the target phase is the
    ladder's live_stage — for every built-in."""
    tenant, user = auth_user["tenant"], auth_user["user"]
    project = _project(db, auth_user, f"Live {key}", project_type=key)
    ladder = release_lifecycle(db, tenant.id, key)
    stages = ladder["stages"]
    live = ladder["live_stage"]
    prev_stage = stages[stages.index(live) - 1]

    release = Release(tenant_id=tenant.id, project_id=project.id, version="1.0.0", name="RL", status=prev_stage)
    db.add(release)
    db.commit()
    db.refresh(release)

    approved = ApprovalRequest(
        tenant_id=tenant.id, project_id=project.id,
        title=f"Release 1.0.0: {prev_stage} → {live}",
        request_type="release", requested_by=user.id,
        release_id=release.id, target_phase=live,
        status="Approved",
    )
    db.add(approved)
    db.commit()

    result = advance_release_phase(db, tenant, user, release)
    assert result["approval_status"] == "approved"
    db.refresh(release)
    assert release.status == live
    assert release.release_date == date.today().isoformat(), (
        f"{key}: release_date must stamp at the live stage {live!r}"
    )


def test_release_date_does_not_stamp_past_the_live_stage(db, auth_user):
    """A post-live transition (software: Released → Post-Release) does NOT
    stamp release_date — the semantics are unchanged."""
    tenant, user = auth_user["tenant"], auth_user["user"]
    project = _project(db, auth_user, "Post-live P")
    release = Release(tenant_id=tenant.id, project_id=project.id, version="1.1.0", name="RP", status="Released")
    db.add(release)
    db.commit()
    db.refresh(release)

    approved = ApprovalRequest(
        tenant_id=tenant.id, project_id=project.id,
        title="Release 1.1.0: Released → Post-Release",
        request_type="release", requested_by=user.id,
        release_id=release.id, target_phase="Post-Release",
        status="Approved",
    )
    db.add(approved)
    db.commit()

    advance_release_phase(db, tenant, user, release)
    db.refresh(release)
    assert release.status == "Post-Release"
    assert release.release_date is None


# ── Creation starts at S1 (§3.8) + back-compat (§3.10) ───────────────────


def test_creation_starts_at_s1(client, db, auth_user):
    """create_release sets status = ladder.stages[0] explicitly — software
    "Planning" (byte-identical), ai its first stage, a tenant row its S1."""
    tenant = auth_user["tenant"]

    cid = client.post("/api/clients", json={"name": "C S1"}).json()["id"]
    sw = client.post("/api/projects", json={"name": "S1 SW", "client_id": cid, "project_type": "software"}).json()
    ai = client.post("/api/projects", json={"name": "S1 AI", "client_id": cid, "project_type": "ai"}).json()

    assert client.post(f"/api/projects/{sw['id']}/releases", json={
        "version": "1.0.0", "name": "R1",
    }).json()["status"] == "Planning"

    assert client.post(f"/api/projects/{ai['id']}/releases", json={
        "version": "1.0.0", "name": "R2",
    }).json()["status"] == LIFECYCLE_TEMPLATES["ai"]["release_stages"][0]

    row = TenantLifecycleTemplate(
        tenant_id=tenant.id, project_type="marketing",
        name="Tenant Marketing",
        item_phases=["Discover"],
        release_stages=["Kickoff", "Launch", "Wrapped"],
        gate_deliverables={},
        gate_roles={"Kickoff": "Product Manager", "Launch": "Product Manager"},
        fields=[],
    )
    db.add(row)
    db.commit()

    mk = client.post("/api/projects", json={"name": "S1 MK", "client_id": cid, "project_type": "marketing"}).json()
    assert client.post(f"/api/projects/{mk['id']}/releases", json={
        "version": "1.0.0", "name": "R3",
    }).json()["status"] == "Kickoff"  # the row's S1


def test_backcompat_release_on_the_old_hardcoded_lifecycle(client, db, auth_user):
    """A release created under the old hardcoded V-cycle (statuses set before
    this change) keeps working byte-identically: its statuses resolve on the
    ladder, the advance creates the same RACI gates, and get_release's
    payload keys/shapes are unchanged."""
    tenant = auth_user["tenant"]
    project = _project(db, auth_user, "Back-compat P")
    release = Release(tenant_id=tenant.id, project_id=project.id, version="3.0.0", name="RC", status="In Progress")
    db.add(release)
    db.commit()
    db.refresh(release)

    # The advance creates the same Tech Lead gate the hardcoded table had
    result = advance_release_phase(db, tenant, auth_user["user"], release)
    assert result["approval_status"] == "created"
    assert result["pending_role"] == "Tech Lead"
    assert result["target_phase"] == "Testing"

    # get_release: keys unchanged, the software v_cycle keeps its authored
    # descriptions/colors, and the ladder indexes resolve
    detail = client.get(f"/api/releases/{release.id}").json()
    for key in ("v_cycle_index", "v_cycle_progress", "next_phase", "v_cycle", "phase_gates"):
        assert key in detail
    assert detail["v_cycle_index"] == 1
    assert detail["next_phase"] == "Testing"
    assert [v["phase"] for v in detail["v_cycle"]] == [
        "Planning", "In Progress", "Testing", "UAT",
        "Pre-Release", "Released", "Post-Release",
    ]
    assert detail["v_cycle"][0] == {
        "phase": "Planning", "description": "Requirements gathered, items selected", "color": "brand",
    }
    assert [g["phase"] for g in detail["phase_gates"]] == [
        "Planning", "In Progress", "Testing", "UAT", "Pre-Release", "Released",
    ]
    by_phase = {g["phase"]: g for g in detail["phase_gates"]}
    assert by_phase["In Progress"]["role"] == "Tech Lead"
    assert by_phase["Released"]["role"] == "DevOps Lead"  # the revived gate
