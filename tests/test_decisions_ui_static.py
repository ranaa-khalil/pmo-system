"""Static analysis of the Rethink v2 Phase B1 Decisions panel.

The decisions view (templates/pmo/views/decisions.html, route === 'decisions')
is the first-class UI over the shipped decision-records API
(routers/decisions.py): the filter row (server ?q= search across
title/decision/rationale, project select, source chips manual|gate|ai, status
chips active|superseded — chips-not-tabs), list rows (title, source chip,
made_at, project, status chip, made_by), the + New Decision button, and the
slide-over drawer (view ↔ edit swap, lineage, supersede, delete). Its JS
lives in static/js/app/domains/decisions.js and must call the SAME endpoints
the API tests prove behave (test_decisions.py).

The loader follows the navigate() per-view pattern without touching core.js
(outside this slice's file ownership): the view's route watcher triggers
loadDecisions() on the first navigation — the same "navigation loads the
panel" contract test_officer_status_loads_last_runs asserts for core.js.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DECISIONS_HTML = REPO / "app/templates/pmo/views/decisions.html"
DECISIONS_JS = REPO / "app/static/js/app/domains/decisions.js"
PLANNING = REPO / "app/static/js/app/domains/planning.js"
PMO_APP = REPO / "app/static/js/app/pmo-app.js"
INDEX = REPO / "app/templates/index.html"


def _read(path: Path) -> str:
    assert path.exists(), f"{path.name} missing"
    return path.read_text(encoding="utf-8")


def test_decisions_view_exists_and_rides_the_decisions_route():
    """The panel is a first-class view, included by index, x-show on the route."""
    src = _read(DECISIONS_HTML)
    index = _read(INDEX)
    assert "pmo/views/decisions.html" in index
    assert 'x-show="route === \'decisions\'"' in src
    # x-cloak discipline: the hidden view (and its drawer) never flash at boot
    assert "x-cloak" in src


def test_decisions_view_has_the_filter_row():
    """Server ?q= search + project select + source/status chips-not-tabs."""
    src = _read(DECISIONS_HTML)
    assert 'x-model="decisionSearch"' in src
    assert '@input="onDecisionSearchInput()"' in src
    assert 'x-model="decisionProjectFilter"' in src
    # source chips: manual | gate | ai (chips-not-tabs — buttons, not tab UI)
    for source in ("manual", "gate", "ai"):
        assert f"id: '{source}'" in src
    # status chips: active | superseded
    for status in ("active", "superseded"):
        assert f"id: '{status}'" in src
    assert '<button @click="setDecisionSourceFilter' in src
    assert '<button @click="setDecisionStatusFilter' in src
    assert 'role="tab' not in src, "chips-not-tabs — no tablist markup"


def test_decisions_view_lists_the_row_facts():
    """Rows carry title, source chip, made_at, project, status chip, made_by."""
    src = _read(DECISIONS_HTML)
    assert 'x-text="d.title"' in src
    assert "decisionSourceChipClass(d.source)" in src
    assert "decisionDate(d.made_at)" in src
    assert "decisionProjectName(d.project_id)" in src
    assert "decisionStatusChipClass(d.status)" in src
    assert "decisionMadeBy(d.made_by)" in src


def test_decisions_new_decision_button_opens_the_drawer_form():
    """+ New Decision → the drawer's new mode → POST /api/decisions → 201."""
    src = _read(DECISIONS_HTML)
    js = _read(DECISIONS_JS)
    assert '@click="startNewDecision()"' in src
    create = re.search(r"async createDecision\(\) \{.*?\n\},", js, re.S)
    assert create, "createDecision missing from decisions.js"
    assert "api('POST', '/decisions', payload)" in create.group(0)


def test_decisions_drawer_is_a_slide_over_not_a_modal():
    """§8 rule 6: 520px right slide-over, Esc + click-out close, full-width phone."""
    src = _read(DECISIONS_HTML)
    assert "max-w-[520px]" in src, "drawer is not the 520px slide-over"
    assert '@keydown.escape.window="closeDecision()"' in src
    assert '@click="closeDecision()"' in src  # click-out backdrop
    assert 'x-show="selectedDecision || decisionNew"' in src
    assert "w-full max-w-[520px]" in src  # full-width on phone


def test_decisions_drawer_calls_the_record_endpoints():
    """GET one + lineage; edit PUTs content-only; supersede POSTs; DELETE."""
    js = _read(DECISIONS_JS)
    assert "api('GET', `/decisions${qs}`)" in js, "the list must hit GET /api/decisions"
    detail = re.search(r"async loadDecisionDetail\(id\) \{.*?\n\},", js, re.S)
    assert detail, "loadDecisionDetail missing from decisions.js"
    assert "api('GET', `/decisions/${id}`)" in detail.group(0)
    edit = re.search(r"async saveDecisionEdit\(\) \{.*?\n\},", js, re.S)
    assert edit, "saveDecisionEdit missing from decisions.js"
    assert "api('PUT', `/decisions/${d.id}`" in edit.group(0)
    sup = re.search(r"async confirmSupersede\(\) \{.*?\n\},", js, re.S)
    assert sup, "confirmSupersede missing from decisions.js"
    assert "api('POST', `/decisions/${d.id}/supersede`" in sup.group(0)
    delete = re.search(r"async deleteDecision\(\) \{.*?\n\},", js, re.S)
    assert delete, "deleteDecision missing from decisions.js"
    assert "api('DELETE', `/decisions/${d.id}`)" in delete.group(0)


def test_decisions_edit_is_content_only():
    """made_at/made_by are immutable — the edit form carries content fields only."""
    js = _read(DECISIONS_JS)
    edit = re.search(r"startDecisionEdit\(\) \{.*?\n\},", js, re.S)
    assert edit, "startDecisionEdit missing from decisions.js"
    form = edit.group(0)
    for field in ("title", "decision", "rationale", "alternatives"):
        assert field in form
    assert "made_at" not in form and "made_by" not in form, \
        "made_at/made_by are immutable — never in the edit form"
    html = _read(DECISIONS_HTML)
    assert "immutable" in html, "the read-only facts row must label made_at/made_by immutable"


def test_decisions_lineage_links_render():
    """The drawer shows the chained predecessor, the approval link, the item link."""
    src = _read(DECISIONS_HTML)
    assert "openDecisionById(decisionPredecessor.id)" in src
    assert '@click="openApprovalProject()"' in src
    assert "data-item-id" in src
    assert "decisionSuccessors" in src
    js = _read(DECISIONS_JS)
    assert "api('GET', `/approvals/${row.approval_request_id}`)" in js
    # the item link routes to Work first — the item drawer lives inside that view
    item = re.search(r"openDecisionItem\(\) \{.*?\n\},", js, re.S)
    assert item, "openDecisionItem missing from decisions.js"
    assert "navigate('work')" in item.group(0)
    assert "openItemRef(id)" in item.group(0)


def test_decisions_delete_is_permission_gated():
    """DELETE surfaces the API's 403 message — hide-or-toast, never silent."""
    js = _read(DECISIONS_JS)
    delete = re.search(r"async deleteDecision\(\) \{.*?\n\},", js, re.S)
    assert delete, "deleteDecision missing from decisions.js"
    assert "showToast(e.message || 'Failed to delete decision', 'error')" in delete.group(0)


def test_decisions_empty_states_have_next_actions():
    """Both empty states name the next action with a button."""
    src = _read(DECISIONS_HTML)
    assert "No decisions recorded yet" in src
    assert "Nothing matches these filters" in src
    assert '@click="clearDecisionFilters()"' in src
    # the whole-panel empty state's button opens the drawer's new mode
    assert src.count('@click="startNewDecision()"') >= 2


def test_decisions_navigation_loads_the_panel():
    """The first navigation triggers loadDecisions() — the per-view loader."""
    html = _read(DECISIONS_HTML)
    assert re.search(r"\$watch\('route'.*?loadDecisions\(\)", html, re.S), \
        "the decisions view must load on navigate (route watcher)"
    js = _read(DECISIONS_JS)
    assert "decisionsLoaded: false," in js
    assert "api('GET', `/decisions${qs}`)" in js


def test_decisions_nav_item_is_registered():
    """The workspace nav chip + pageTitle mapping live in planning.js."""
    planning = _read(PLANNING)
    assert re.search(
        r"\{ id: 'decisions', label: 'Decisions', group: 'workspace', icon: '<svg",
        planning,
    ), "the Decisions nav item is missing from planning.js navItems"
    assert "decisions: 'Decisions'" in planning


def test_decisions_domain_is_merged_into_the_store():
    """decisions.js is imported and listed in the DOMAINS array."""
    pmo = _read(PMO_APP)
    assert "from './domains/decisions.js?v=" in pmo
    assert re.search(r"const DOMAINS = \[.*\bdecisions\b", pmo, re.S)


def test_decisions_class_strings_are_literal():
    """Carry-forward guard (ADR-07): chip classes come from literal mapping tables."""
    js = _read(DECISIONS_JS)
    for fam in ("bg", "text", "border", "rounded"):
        assert not re.search(r"['\"]" + fam + r"-['\"]\s*\+", js), f"composes '{fam}-' with +"
        assert not re.search(r"`[^`]*" + fam + r"-\$\{", js), f"composes '{fam}-' with ${{}}"
    assert "decisionSourceChipClass(source)" in js
    assert "decisionStatusChipClass(status)" in js
