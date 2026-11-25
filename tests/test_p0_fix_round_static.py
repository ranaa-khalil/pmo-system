"""Static pins + functional tests for the 2026-11-25 P0/P1 fix round.

Pins the verified fixes from the QA + PM reviews — each was re-verified
against HEAD before applying. Assert the exact code shape so a regression
reverts the test with it:

- R1  the two release download routes resolve the tenant from the
      query-param token user (both 500'd live with a NameError: the body
      referenced `current_tenant` without receiving it; window.open carries
      no Authorization header, so the get_current_tenant DEPENDENCY would
      401 before the route body ran — the shared user-keyed resolver is the
      get_current_tenant core, keyed on the token-derived user).
- R2  items_past_development is its own bucket — it was a copy of the
      Testing bucket (items_in_or_past_testing), and Done items never
      satisfied the In Progress gate.
- C1  the copilot advance_item op routes through the ONE advance machine
      (release_machine.advance_backlog_item_phase): a no-op advance
      (target == current phase) was a false success with an ActivityLog row
      and NO artifact-chain entry.
- C2  the copilot assign_user op checks assignee tenant membership — a
      cross-tenant user id executed as a real assignment.
- B1  the user-facing Copilot brand is unified to the drawer's
      "PMO Copilot" ("Copilot Briefing" chip, projects empty state, verdict
      chip, risk labels).
- J1  copilotNewTopic() toggles the drawer ONCE (two toggles visibly closed
      and reopened it); the scope greeting is re-seeded, not re-toggled.
- V1  the JS import-graph ?v= pins and the CSS link pin bump together
      (house cache-bust rule — test_css_version_parity pins the equality).
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RELEASES_PY = REPO / "app/routers/releases.py"
TENANT_PY = REPO / "app/services/tenant.py"
COPILOT_PY = REPO / "app/services/copilot.py"
TODAY_HTML = REPO / "app/templates/pmo/views/today.html"
PROJECTS_HTML = REPO / "app/templates/pmo/views/projects.html"
PROJECT_DETAIL_HTML = REPO / "app/templates/pmo/views/project_detail.html"
DRAWER_HTML = REPO / "app/templates/pmo/shell/copilot_drawer.html"
COPILOT_JS = REPO / "app/static/js/app/domains/copilot.js"
APP_JS = REPO / "app/static/js/app/pmo-app.js"
INDEX_HTML = REPO / "app/templates/index.html"

JS_VERSION = "20261125a"

PAST_DEVELOPMENT_TAIL = ('i.get("is_done") or i.get("current_phase") in '
                         '("Testing", "Ready for UAT", "UAT", "Pre-Release", '
                         '"Release", "Post-Release", "Retrospective")')


def _read(path: Path) -> str:
    assert path.exists(), f"{path.name} missing"
    return path.read_text(encoding="utf-8")


def _route_body(src: str, name: str) -> str:
    """A route function body: from its def line to the next top-level block."""
    m = re.search(rf"^def {name}\(.*?(?=^def |^@|^class |\Z)", src, re.S | re.M)
    assert m, f"{name} missing"
    return m.group(0)


def _fn_body(src: str, name: str) -> str:
    """A method body inside the Alpine store: `name() { ... },`."""
    m = re.search(rf"^\s*{name}\([^)]*\) {{\n(.*?)^\s*}},?$", src, re.S | re.M)
    assert m, f"{name} missing"
    return m.group(0)


# ── R1 — the download routes resolve the tenant from the token user ──────


def test_r1_download_notes_resolves_the_tenant_from_the_token_user():
    """download_release_notes had no `current_tenant` — live 500 (NameError)."""
    body = _route_body(_read(RELEASES_PY), "download_release_notes")
    assert "resolve_tenant_for_user(db, current_user)" in body, (
        "the route must resolve the tenant from the token-derived user"
    )


def test_r1_signoff_pdf_resolves_the_tenant_from_the_token_user():
    """download_signoff_pdf had no `current_tenant` — live 500 (NameError)."""
    body = _route_body(_read(RELEASES_PY), "download_signoff_pdf")
    assert "resolve_tenant_for_user(db, current_user)" in body, (
        "the route must resolve the tenant from the token-derived user"
    )


def test_r1_download_routes_keep_the_query_token_auth():
    """window.open cannot send headers — the query-param token must stay."""
    src = _read(RELEASES_PY)
    for name in ("download_release_notes", "download_signoff_pdf"):
        body = _route_body(src, name)
        assert "if not token:" in body, f"{name} lost the query-token gate"
        assert "get_current_user(token, db)" in body, f"{name} lost the token auth"


def test_r1_resolver_is_the_dependency_core():
    """get_current_tenant delegates to the same resolver — one source of truth."""
    src = _read(TENANT_PY)
    body = _route_body(src, "get_current_tenant")
    assert "return resolve_tenant_for_user(db, current_user)" in body, (
        "the dependency must share the resolver's rules (no second copy)"
    )


# ── R2 — items_past_development is its own bucket ─────────────────────────


def test_r2_items_past_development_is_its_own_bucket():
    """The bucket was a copy of the Testing bucket and ignored Done items."""
    body = _route_body(_read(RELEASES_PY), "_compute_phase_gates")
    assert PAST_DEVELOPMENT_TAIL in body, (
        "items_past_development must count Done items and phases past Development"
    )


# ── C1 — the copilot advance op routes through the advance machine ───────


def test_c1_advance_item_routes_through_the_advance_machine():
    """The op must use release_machine.advance_backlog_item_phase — the same
    path as the backlog advance route — so the artifact-chain entry lands."""
    src = _read(COPILOT_PY)
    body = _route_body(src, "_execute_op")
    start = body.find('if kind == "advance_item":')
    end = body.find('if kind == "assign_user":')
    assert start != -1 and end != -1, "advance_item block missing"
    advance = body[start:end]
    assert "advance_backlog_item_phase(db, tenant, user, item)" in advance, (
        "the advance must go through the ONE advance machine"
    )


def test_c1_advance_item_writes_no_private_activity_log():
    """The machine owns the audit — a second ActivityLog write doubled rows."""
    src = _read(COPILOT_PY)
    body = _route_body(src, "_execute_op")
    start = body.find('if kind == "advance_item":')
    end = body.find('if kind == "assign_user":')
    advance = body[start:end]
    assert "db.add(ActivityLog(" not in advance, (
        "the copilot must not write its own ActivityLog — the machine logs"
    )
    assert "item.current_phase = " not in advance, (
        "no direct phase assignment — the machine decides the next phase"
    )


def test_c1_advance_item_rejects_when_no_next_phase_exists():
    """Release-level phases and the final item phase must fail clearly —
    a no-op advance was a false success ('advanced Pre-Release → Pre-Release')."""
    src = _read(COPILOT_PY)
    body = _route_body(src, "_execute_op")
    start = body.find('if kind == "advance_item":')
    end = body.find('if kind == "assign_user":')
    advance = body[start:end]
    assert "RELEASE_PHASES" in advance, "release-level guard missing"
    assert "eff[\"release_stages\"]" in advance, "effective release-stages guard missing"
    assert "no next phase" in advance, "final-phase guard missing"


# ── C2 — the assign op checks assignee tenant membership ─────────────────


def test_c2_assign_user_checks_tenant_membership():
    """A cross-tenant user id executed as a real assignment."""
    src = _read(COPILOT_PY)
    body = _route_body(src, "_execute_op")
    start = body.find('if kind == "assign_user":')
    end = body.find('if kind == "create_risk":')
    assign = body[start:end]
    assert "TenantMembership" in assign, "membership check missing"
    assert "TenantMembership.tenant_id == tenant.id" in assign, (
        "the assignee must be a member of the ITEM's tenant"
    )
    assert assign.find("TenantMembership") < assign.find("item.assigned_to = "), (
        "the membership check must run before the write"
    )


# ── B1 — the user-facing Copilot brand is unified ────────────────────────


def test_b1_today_uses_the_house_brand():
    """The briefing chip read 'Copilot Briefing' — the drawer says PMO Copilot."""
    src = _read(TODAY_HTML)
    assert "PMO Copilot Briefing" in src, "Today's chip must carry the house brand"
    assert ">Copilot Briefing<" not in src, "the split spelling is back"


def test_b1_projects_empty_state_uses_the_house_brand():
    src = _read(PROJECTS_HTML)
    assert "Start with Copilot" not in src, "bare brand is back"
    assert "with the Copilot" not in src, "bare brand is back"
    assert "Start with PMO Copilot" in src


def test_b1_project_detail_uses_the_house_brand():
    src = _read(PROJECT_DETAIL_HTML)
    assert ">Copilot<" not in src, "the verdict chip must carry the house brand"
    assert "via Copilot " not in src, "the risk labels must carry the house brand"


def test_b1_drawer_labels_use_the_house_brand():
    src = _read(DRAWER_HTML)
    assert ">Copilot asks<" not in src, "the interview label must carry the house brand"


# ── J1 — copilotNewTopic toggles once ────────────────────────────────────


def test_j1_new_topic_toggles_the_drawer_once():
    """Two toggles visibly closed and reopened the drawer."""
    body = _fn_body(_read(COPILOT_JS), "copilotNewTopic")
    assert body.count("toggleCopilot()") <= 1, "the drawer must toggle once"
    assert "seedCopilotGreeting()" in body, "the scope greeting must be re-seeded"


def test_j1_toggle_seeds_the_greeting_through_the_shared_helper():
    """One greeting — toggle and new-topic share the seed, no copy."""
    src = _read(COPILOT_JS)
    toggle = _fn_body(src, "toggleCopilot")
    assert "seedCopilotGreeting()" in toggle, "toggle must seed via the helper"
    assert src.count("I'm your AI PMO officer") == 1, "the greeting text must be defined once"


# ── V1 — the version pins bump together ──────────────────────────────────


def test_v1_version_pins_bump_together():
    """House cache-bust rule: one ?v= across the JS graph + the CSS link."""
    app_js = _read(APP_JS)
    js_versions = set(re.findall(r"from '\./domains/[a-z_]+\.js\?v=([a-z0-9]+)'", app_js))
    assert js_versions == {JS_VERSION}, f"the JS graph must pin {JS_VERSION}, found {js_versions}"
    index = _read(INDEX_HTML)
    link = re.search(r"tailwind\.compiled\.css\?v=([a-z0-9]+)", index)
    assert link and link.group(1) == JS_VERSION, "the CSS link pin must match the JS version"


# ── Functional regressions ────────────────────────────────────────────────


def _copilot_propose_confirm(client, headers, op):
    """Propose one explicit op (no LLM) and confirm it. Returns (resp, body)."""
    propose = client.post(
        "/api/ai/copilot/propose",
        json={"intent": "op", "operations": [op]},
        headers=headers,
    )
    assert propose.status_code == 200, propose.text
    proposal_id = propose.json()["proposal_id"]
    resp = client.post(f"/api/ai/copilot/proposals/{proposal_id}/confirm", headers=headers)
    return resp, resp.json()


def test_f1_copilot_advance_lands_the_artifact_chain_entry(client, auth_headers, db):
    """propose+confirm advance → the chain entry lands and the log reads the
    real transition (was: no-op success, no chain entry)."""
    from app.models.activity_log import ActivityLog
    from app.models.backlog_item import BacklogItem
    from app.models.project import Project
    from app.models.tenant import Tenant

    # The client fixture's tenant: the authed super_admin's active tenant.
    tenant = db.query(Tenant).first()
    project = Project(name="P0 Advance P", client_id=1, tenant_id=tenant.id)
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

    resp, body = _copilot_propose_confirm(
        client, auth_headers, {"op": "advance_item", "item_id": item.id}
    )
    assert resp.status_code == 200, resp.text
    assert body["executed"], f"the advance op should execute: {body}"
    assert body["executed"][0]["result"]["phase"] == "Testing"

    db.expire_all()
    advanced = db.query(BacklogItem).filter(BacklogItem.id == item.id).first()
    assert advanced.current_phase == "Testing"

    # The artifact-chain entry landed (it never did on the old path).
    chain = client.get(f"/api/artifacts/backlog_item/{item.id}", headers=auth_headers)
    assert chain.status_code == 200, chain.text
    entries = chain.json() if isinstance(chain.json(), list) else chain.json().get("entries", [])
    adv = [e for e in entries if e.get("action") == "advanced"]
    assert adv, "no artifact-chain entry for the advance"
    assert adv[-1]["payload"]["to_phase"] == "Testing"

    # The log reads the real transition, not a no-op.
    log = (
        db.query(ActivityLog)
        .filter(
            ActivityLog.entity_type == "backlog_item",
            ActivityLog.entity_id == item.id,
            ActivityLog.action == "advanced",
        )
        .order_by(ActivityLog.id.desc())
        .first()
    )
    assert log is not None, "no activity row for the advance"
    assert "Testing" in log.summary and "Testing → Testing" not in log.summary


def test_f1_copilot_advance_rejects_when_no_next_phase(client, auth_headers, db):
    """An item at its final item phase must FAIL, not no-op."""
    from app.models.backlog_item import BacklogItem
    from app.models.project import Project
    from app.models.tenant import Tenant

    tenant = db.query(Tenant).first()
    project = Project(name="P0 Final P", client_id=1, tenant_id=tenant.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    item = BacklogItem(
        tenant_id=tenant.id, project_id=project.id, title="Ready item",
        epic="Auth", current_phase="Ready for UAT", status="In Progress",
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    resp, body = _copilot_propose_confirm(
        client, auth_headers, {"op": "advance_item", "item_id": item.id}
    )
    assert resp.status_code == 200, resp.text
    assert not body["executed"], "a final-phase item must not advance"
    assert body["failed"], f"a clear failure is required: {body}"
    assert "no next phase" in body["failed"][0]["error"]

    db.expire_all()
    assert db.query(BacklogItem).filter(BacklogItem.id == item.id).first().current_phase == "Ready for UAT"
    # And no chain entry: nothing happened.
    chain = client.get(f"/api/artifacts/backlog_item/{item.id}", headers=auth_headers)
    entries = chain.json() if isinstance(chain.json(), list) else chain.json().get("entries", [])
    assert not [e for e in entries if e.get("action") == "advanced"]


def test_f2_copilot_assign_user_rejects_cross_tenant(client, auth_headers, db):
    """A user from ANOTHER tenant must be rejected, not assigned."""
    from app.models.backlog_item import BacklogItem
    from app.models.project import Project
    from app.models.tenant import Tenant, TenantMembership
    from app.models.user import User
    from app.services.auth import hash_password

    tenant = db.query(Tenant).first()
    project = Project(name="P0 Assign P", client_id=1, tenant_id=tenant.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    item = BacklogItem(
        tenant_id=tenant.id, project_id=project.id, title="Unassigned",
        epic="Auth", current_phase="Development", status="In Progress",
    )
    db.add(item)
    # A stranger who belongs to a DIFFERENT tenant only.
    other = Tenant(name="Other Co", slug="other-co", plan="team", status="active")
    db.add(other)
    db.commit()
    db.refresh(other)
    stranger = User(
        email="stranger@pmo.test", name="Stranger",
        hashed_password=hash_password("StrangerPass123!"),
        system_role="member", active_tenant_id=other.id,
    )
    db.add(stranger)
    db.commit()
    db.refresh(stranger)
    db.add(TenantMembership(user_id=stranger.id, tenant_id=other.id, role="owner"))
    db.commit()

    resp, body = _copilot_propose_confirm(
        client, auth_headers,
        {"op": "assign_user", "item_id": item.id, "assignee_id": stranger.id},
    )
    assert resp.status_code == 200, resp.text
    assert not body["executed"], "the cross-tenant assignment must be rejected"
    assert body["failed"], f"a clear rejection is required: {body}"
    assert "not a member of this tenant" in body["failed"][0]["error"]

    db.expire_all()
    assert db.query(BacklogItem).filter(BacklogItem.id == item.id).first().assigned_to is None


def test_f2_copilot_assign_user_accepts_a_tenant_member(client, auth_headers, db):
    """Same-tenant members still assign (the check rejects, never blocks)."""
    from app.models.backlog_item import BacklogItem
    from app.models.project import Project
    from app.models.tenant import Tenant, TenantMembership
    from app.models.user import User
    from app.services.auth import hash_password

    tenant = db.query(Tenant).first()
    project = Project(name="P0 Assign OK P", client_id=1, tenant_id=tenant.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    item = BacklogItem(
        tenant_id=tenant.id, project_id=project.id, title="Assignable",
        epic="Auth", current_phase="Development", status="In Progress",
    )
    db.add(item)
    member = User(
        email="teammate@pmo.test", name="Teammate",
        hashed_password=hash_password("TeammatePass123!"),
        system_role="member", active_tenant_id=tenant.id,
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    db.add(TenantMembership(user_id=member.id, tenant_id=tenant.id, role="member"))
    db.commit()

    resp, body = _copilot_propose_confirm(
        client, auth_headers,
        {"op": "assign_user", "item_id": item.id, "assignee_id": member.id},
    )
    assert resp.status_code == 200, resp.text
    assert body["executed"], f"a tenant member must be assignable: {body}"
    db.expire_all()
    assert db.query(BacklogItem).filter(BacklogItem.id == item.id).first().assigned_to == member.id


def test_f3_download_endpoints_return_200_with_query_token(client, anon_client, auth_headers, db):
    """GET /download-notes and /signoff-pdf return 200 via the query-param
    token alone (both were live 500s: NameError: current_tenant)."""
    from app.models.project import Project
    from app.models.release import Release
    from app.models.tenant import Tenant

    tenant = db.query(Tenant).first()
    project = Project(name="P0 Download P", client_id=1, tenant_id=tenant.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    release = Release(
        tenant_id=tenant.id, project_id=project.id,
        version="1.0.0", name="Launch", status="In Progress",
    )
    db.add(release)
    db.commit()
    db.refresh(release)

    generated = client.post(f"/api/releases/{release.id}/generate-notes", headers=auth_headers)
    assert generated.status_code == 200, generated.text

    token = auth_headers["Authorization"].split(" ", 1)[1]

    notes = anon_client.get(f"/api/releases/{release.id}/download-notes?token={token}")
    assert notes.status_code == 200, notes.text[:200]
    assert "wordprocessingml" in notes.headers.get("content-type", "")

    pdf = anon_client.get(f"/api/releases/{release.id}/signoff-pdf?token={token}")
    assert pdf.status_code == 200, pdf.text[:200]
    assert pdf.headers.get("content-type", "").startswith("application/pdf")
