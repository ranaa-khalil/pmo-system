"""Static pins for the 2026-11-24 QA sweep (backend B1-B5 + frontend F1-F10).

Every fix from the two read-only QA agents gets a pattern pin here, in the
test_project_cockpit_static.py style: assert the exact code shape that
implements the fix, so a regression reverts the test with it.

Backend (audit-trail P1s + shape/ruff P2s):
- B1  log_activity resolves tenant_id (project → user's active tenant) so
      every ActivityLog row matches GET /api/activity's tenant-scoped read.
- B2  create_release writes its audit row BEFORE the single atomic commit.
- B3  advance_backlog_item_phase + send_back_to_development commit AFTER the
      flush-only log_activity/append_artifact writes (live-only rollback).
- B4  health.py kpi_progress rows carry project_id/project_name (stats.py
      dashboard variant's shape).
- B5  releases.py drops the unused top-level `date` import (the local imports
      in _build_release_notes/_build_docx are the real users).

Frontend (Alpine store + template):
- F1  work items normalize current_phase ?? phase at load; the Work board's
      phase lanes read the tolerant form (the observedPhaseNames pattern).
- F2  the Work board container re-lanes via x-effect="buildWorkBoard()".
- F3  the release + approval modals are included at index level (outside the
      route-scoped views) so they render from every route.
- F4  every selectedWorkItem read in the drawer template is optional-chained.
- F5  clientsLoading/projectsLoading are declared in the initial state block.
- F6  tailwind-config.js guards the missing CDN global.
- F7  the copilot drawer's outer element is a plain x-show (no x-transition
      on the same element — the leave sequence can stick).
- F8  one source of truth for the sidebar: the dead visibleNavItems getter is
      gone; sidebar.html's !consultantView gate survives.
- F9  the advance toast announces the completed move, not the next step.
- F10 the house palette: no to-teal-600 (emerald→violet gradient instead).
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NOTIFICATIONS_PY = REPO / "app/services/notifications.py"
RELEASES_PY = REPO / "app/routers/releases.py"
RELEASE_MACHINE_PY = REPO / "app/services/release_machine.py"
BACKLOG_PY = REPO / "app/routers/backlog.py"
HEALTH_PY = REPO / "app/services/health.py"
PLANNING_JS = REPO / "app/static/js/app/domains/planning.js"
BACKLOG_JS = REPO / "app/static/js/app/domains/backlog.js"
TENANTS_JS = REPO / "app/static/js/app/domains/tenants.js"
TAILWIND_CONFIG_JS = REPO / "app/static/js/app/tailwind-config.js"
PMO_APP_JS = REPO / "app/static/js/app/pmo-app.js"
INDEX_HTML = REPO / "app/templates/index.html"
PROJECT_DETAIL = REPO / "app/templates/pmo/views/project_detail.html"
WORK_HTML = REPO / "app/templates/pmo/views/work.html"
ITEM_DRAWER = REPO / "app/templates/components/item_drawer.html"
APPROVAL_MODALS = REPO / "app/templates/components/approval_modals.html"
COPILOT_DRAWER = REPO / "app/templates/pmo/shell/copilot_drawer.html"
SIDEBAR = REPO / "app/templates/pmo/shell/sidebar.html"


def _read(path: Path) -> str:
    assert path.exists(), f"{path.name} missing"
    return path.read_text(encoding="utf-8")


def _py_body(src: str, name: str) -> str:
    """A top-level def body: from its def line to the next top-level block."""
    m = re.search(rf"^def {name}\(.*?(?=^def |^@|^class |\Z)", src, re.S | re.M)
    assert m, f"{name} missing"
    return m.group(0)


def _js_body(src: str, name: str) -> str:
    """A store method body — the test_project_cockpit_static._fn_body pattern."""
    m = re.search(
        rf"(?:get {name}\(\) \{{|async {name}\([^)]*\) \{{|{name}\([^)]*\) \{{)(.*?\n\}},)",
        src, re.S,
    )
    assert m, f"{name} missing"
    return m.group(0)


# ── B1 — log_activity resolves the tenant ────────────────────────────────


def test_b1_log_activity_takes_and_resolves_tenant_id():
    """The helper resolves tenant_id when not passed — project first, then user."""
    src = _read(NOTIFICATIONS_PY)
    body = _py_body(src, "log_activity")
    assert "tenant_id: int = None" in body, "tenant_id param missing"
    assert "if tenant_id is None:" in body, "resolution gate missing"
    assert "Project.tenant_id" in body, "project tenant resolution missing"
    assert "User.active_tenant_id" in body, "user tenant fallback missing"
    assert "tenant_id=tenant_id," in body, "the row must carry the resolved tenant"


def test_b1_activity_read_is_tenant_scoped():
    """GET /api/activity reads through the seam — the same tenant guarantee."""
    router = _read(REPO / "app/routers/notifications.py")
    assert "tenant_scoped(db, ActivityLog, current_tenant.id)" in router


# ── B2 — create_release: audit write inside the transaction ─────────────


def test_b2_create_release_logs_before_the_single_commit():
    """flush → log_activity → commit → return: the audit row can't roll back."""
    body = _py_body(_read(RELEASES_PY), "create_release")
    li = body.index("log_activity(")
    assert "db.flush()" in body[:li], "the ID must be assigned before the audit write"
    ci = body.index("db.commit()", li)
    assert "return db_release" in body[ci:], "the commit must precede the return"


# ── B3 — phase-move audit writes are committed ───────────────────────────


def test_b3_advance_commits_after_the_audit_writes():
    """append_artifact only flushes — a commit must follow it before return."""
    body = _py_body(_read(RELEASE_MACHINE_PY), "advance_backlog_item_phase")
    ai = body.index("append_artifact(")
    ri = body.index("return item", ai)
    assert "db.commit()" in body[ai:ri], "flush-only chain writes roll back live"


def test_b3_send_back_commits_after_the_audit_writes():
    """Same pattern on the rework path (backlog.py send-back)."""
    body = _py_body(_read(BACKLOG_PY), "send_back_to_development")
    ai = body.index("append_artifact(")
    ri = body.index("return item", ai)
    assert "db.commit()" in body[ai:ri], "flush-only chain writes roll back live"


# ── B4 — health kpi_progress row shape ───────────────────────────────────


def test_b4_health_kpi_progress_rows_carry_project_identity():
    """The rows match the stats.py dashboard variant's shape."""
    src = _read(HEALTH_PY)
    body = _py_body(src, "compute_project_health")
    assert '"project_id": project_id, "project_name": project_name,' in body
    assert "Project.name" in body, "project_name must come from the Project row"


# ── B5 — releases.py import hygiene ──────────────────────────────────────


def test_b5_releases_top_import_drops_unused_date():
    """The local imports in _build_release_notes/_build_docx are the real users."""
    src = _read(RELEASES_PY)
    head = src[:800]
    assert "from datetime import datetime" in head
    assert "from datetime import date," not in head


# ── F1 — work items carry a normalized current_phase ────────────────────


def test_f1_loadwork_normalizes_current_phase():
    """The /work payload's `phase` maps onto current_phase at the load point."""
    body = _js_body(_read(PLANNING_JS), "loadWork")
    assert "current_phase: i.current_phase ?? i.phase" in body


def test_f1_work_board_phase_lanes_read_the_tolerant_form():
    """buildWorkBoard never treats a /work row as a straggler by vocabulary."""
    src = _read(BACKLOG_JS)
    board = re.search(r"buildWorkBoard\(\) \{.*?\n\},", src, re.S)
    assert board, "buildWorkBoard missing"
    assert "(i.current_phase ?? i.phase ?? '') === phase" in board.group(0)
    assert "!known.has(i.current_phase ?? i.phase ?? '')" in board.group(0)


# ── F2 — the Work board re-lanes on its inputs ───────────────────────────


def test_f2_work_board_container_has_the_x_effect():
    """Same pattern as the per-project board (project_detail.html)."""
    src = _read(WORK_HTML)
    lines = [l for l in src.split("\n")
             if "workViewMode === 'board'" in l and "<div" in l]
    assert lines, "Work board container missing"
    assert any('x-effect="buildWorkBoard()"' in l for l in lines)


# ── F3 — release + approval modals live at index level ───────────────────


def test_f3_modals_included_outside_the_route_scoped_views():
    """index.html includes the modals next to the ONE item drawer."""
    src = _read(INDEX_HTML)
    assert "{% include 'components/approval_modals.html' %}" in src
    drawer_i = src.index("{% include 'components/item_drawer.html' %}")
    modals_i = src.index("{% include 'components/approval_modals.html' %}")
    fab_i = src.index("{% include 'pmo/modals/fab.html' %}")
    assert drawer_i < modals_i < fab_i, "modals must sit at index level, by the drawer"


def test_f3_both_modals_live_in_the_new_component():
    """selectedRelease + selectedApproval x-if templates in one file."""
    src = _read(APPROVAL_MODALS)
    assert 'x-if="selectedRelease"' in src
    assert 'x-if="selectedApproval"' in src
    assert "closeRelease()" in src and "closeApproval()" in src


def test_f3_project_detail_no_longer_hosts_the_modals():
    """The route-scoped root no longer contains either modal template."""
    src = _read(PROJECT_DETAIL)
    assert 'x-if="selectedRelease"' not in src
    assert 'x-if="selectedApproval"' not in src


# ── F4 — the drawer template never dereferences a torn-down item ────────


def test_f4_every_selectedworkitem_read_is_optional_chained():
    """Inner effects re-flush with selectedWorkItem=null after close."""
    src = _read(ITEM_DRAWER)
    bare = re.findall(r"selectedWorkItem\.", src)
    assert not bare, f"{len(bare)} bare selectedWorkItem reads remain"


# ── F5 — loading flags declared in the initial state ────────────────────


def test_f5_loading_flags_declared_before_first_render():
    """The x-if templates evaluate them at boot — they must exist up front."""
    src = _read(TENANTS_JS)
    state_i = src.index("clientsLoading: false,")
    assert "projectsLoading: false," in src[:state_i + 60]
    loaders_i = src.index("async loadClients(")
    assert state_i < loaders_i, "the flags must precede the loaders"


# ── F6 — the missing CDN global is guarded ───────────────────────────────


def test_f6_tailwind_config_guarded():
    """The global `tailwind` is gone since ADR-07 — guard the assignment."""
    src = _read(TAILWIND_CONFIG_JS)
    guard_i = src.index("if (typeof tailwind !== 'undefined') {")
    config_i = src.index("tailwind.config = {")
    assert guard_i < config_i, "the assignment must sit inside the guard"


# ── F7 — the copilot drawer closes for real ──────────────────────────────


def test_f7_copilot_outer_is_a_plain_x_show():
    """No x-transition on the same element as x-show (the leave-stick bug)."""
    src = _read(COPILOT_DRAWER)
    tag = re.search(r'<div x-show="copilotOpen"[^>]*>', src, re.S)
    assert tag, "copilot outer div missing"
    assert "x-transition" not in tag.group(0), "transition must not sit on the outer x-show"


# ── F8 — one source of truth for the sidebar ─────────────────────────────


def test_f8_dead_visibleNavItems_getter_is_gone():
    """sidebar.html's !consultantView gate is the surviving truth."""
    assert "get visibleNavItems" not in _read(PLANNING_JS)
    sidebar = _read(SIDEBAR)
    assert 'x-show="!consultantView"' in sidebar


# ── F9 — the advance toast confirms the move ─────────────────────────────


def test_f9_advance_toast_announces_the_completed_move():
    """'Phase advanced: {from} → {to}', not the next step's label."""
    body = _js_body(_read(PLANNING_JS), "advanceWorkItem")
    assert "this.showToast('Phase advanced: ' + from + ' → ' + next, 'success')" in body
    assert "workAdvanceLabel()" not in body.split("} catch")[0]


# ── F10 — house palette: teal is gone ────────────────────────────────────


def test_f10_no_teal_in_the_house_palette():
    """The stake-desk Approve gradient ends violet (emerald stays semantic)."""
    src = _read(PROJECT_DETAIL)
    assert "to-teal-600" not in src
    assert "from-emerald-500 to-violet-600" in src


# ── cache-bust consistency ───────────────────────────────────────────────


def test_pmo_app_imports_share_one_cache_bust_token():
    """Every domain import carries the same ?v= token (bump together)."""
    src = _read(PMO_APP_JS)
    tokens = set(re.findall(r"from '[^']+\?v=([0-9a-z]+)'", src))
    assert len(tokens) == 1, f"mixed cache-bust tokens: {sorted(tokens)}"
    assert tokens.pop() >= "20261123j", "the token must postdate the QA sweep"
