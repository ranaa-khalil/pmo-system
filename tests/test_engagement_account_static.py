"""Static analysis of the Rethink v2 Phase B3 engagement account review.

The client detail view (templates/pmo/views/client_detail.html,
route === 'client-detail') is the consultant's ACCOUNT REVIEW over the
shipped engagements API (routers/engagements.py): an engagements section at
the top — one card per engagement (name, status chip active|paused|closed,
dates, contract_value verbatim, pmo lead, projects rollup chips that open the
project, per-project health chips with their why strings), the empty state
with the next-action note, and lazy loading (the view-root x-effect fetches
when the client-detail first shows — never part of any burst). Its JS lives
in static/js/app/domains/engagements.js and must call the SAME endpoints the
API tests prove behave (tests/test_engagements.py).

Slice rules encoded here: the existing client fields/editing stay in place,
engagement create/edit UI is a later slice (render-only), and contract_value
(a currency-agnostic string) renders verbatim — never formatted as a number.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLIENT_HTML = REPO / "app/templates/pmo/views/client_detail.html"
ENGAGEMENTS_JS = REPO / "app/static/js/app/domains/engagements.js"
PMO_APP = REPO / "app/static/js/app/pmo-app.js"


def _read(path: Path) -> str:
    assert path.exists(), f"{path.name} missing"
    return path.read_text(encoding="utf-8")


def test_engagement_domain_is_merged_into_the_store():
    """engagements.js is imported and listed in the DOMAINS array."""
    pmo = _read(PMO_APP)
    assert "from './domains/engagements.js'" in pmo
    assert re.search(r"const DOMAINS = \[.*\bengagements\b", pmo, re.S)


def test_client_detail_lazy_loads_the_account_review_on_the_view_root():
    """The view-root x-effect fetches engagements when the view first shows."""
    src = _read(CLIENT_HTML)
    assert 'x-effect="route === \'client-detail\' && selectedClient && loadClientEngagements()"' in src
    js = _read(ENGAGEMENTS_JS)
    assert "engagementsLoading: false," in js
    # the loader guards: no fetch without a selected client
    loader = re.search(r"async loadClientEngagements\(\) \{.*?\n\},", js, re.S)
    assert loader, "loadClientEngagements missing from engagements.js"
    assert "if (!this.selectedClient) return;" in loader.group(0)


def test_engagements_list_hits_the_scoped_list_endpoint():
    """The list must hit GET /api/engagements?client_id= (the tenant-scoped route)."""
    js = _read(ENGAGEMENTS_JS)
    assert "api('GET', `/engagements?client_id=${this.selectedClient.id}" in js, \
        "the list must hit GET /api/engagements scoped to the client"
    # the projects rollup lives on the detail endpoint
    detail = re.search(r"async loadEngagementDetail\(id\) \{.*?\n\},", js, re.S)
    assert detail, "loadEngagementDetail missing from engagements.js"
    assert "api('GET', `/engagements/${id}`)" in detail.group(0)


def test_engagement_health_hits_the_computed_health_endpoint():
    """Per-project health: GET /api/projects/{id}/health — lazy, keyed by id."""
    js = _read(ENGAGEMENTS_JS)
    health = re.search(r"async loadEngagementProjectHealth\(projectId\) \{.*?\n\},", js, re.S)
    assert health, "loadEngagementProjectHealth missing from engagements.js"
    assert "api('GET', `/projects/${projectId}/health`)" in health.group(0)
    # lazy-once per project id (the coverage guard pattern)
    assert "if (!projectId || this.engagementHealth[projectId]) return;" in health.group(0)


def test_engagement_cards_render_the_row_facts():
    """Cards carry name, status chip, dates, contract value, lead, rollup."""
    src = _read(CLIENT_HTML)
    assert 'x-text="e.name"' in src
    assert "engagementStatusChipClass(e.status)" in src
    assert "engagementDate(e.start_date)" in src
    assert "engagementLead(e.pmo_lead_id)" in src
    assert "x-text=\"e.projects?.count ?? 0\"" in src
    assert "engagementStatusDotClass(e.status)" in src


def test_engagement_status_chip_map_is_the_lifecycle():
    """active = emerald, paused = amber, closed = ink (tokens palette)."""
    js = _read(ENGAGEMENTS_JS)
    chip = re.search(r"engagementStatusChipClass\(status\) \{.*?\n\},", js, re.S)
    assert chip, "engagementStatusChipClass missing from engagements.js"
    body = chip.group(0)
    assert "active: 'bg-emerald-50" in body
    assert "paused: 'bg-amber-50" in body
    assert "closed: 'bg-ink-100" in body


def test_contract_value_renders_verbatim():
    """contract_value is a currency-agnostic String — never formatted as a number."""
    src = _read(CLIENT_HTML)
    assert 'x-text="e.contract_value"' in src, "contract_value must render verbatim via x-text"
    js = _read(ENGAGEMENTS_JS)
    for formatter in (r"Number\(", r"toFixed\(", r"toLocaleString\(", r"Intl\."):
        assert not re.search(formatter, js), \
            f"contract_value is a string — {formatter} formatting is forbidden here"


def test_rollup_chips_open_the_project():
    """Each rollup chip navigates with the house openProjectById pattern."""
    src = _read(CLIENT_HTML)
    assert '@click="openProjectById(proj.id)"' in src
    assert 'x-text="proj.name"' in src


def test_health_chips_render_why_strings_non_empty_and_amber_for_warnings():
    """Why chips render all four sub-scores, non-empty only; warnings go amber."""
    src = _read(CLIENT_HTML)
    for key in ("schedule", "approvals", "tasks", "kpis"):
        assert f"engagementHealth[proj.id].why?.{key} || []).filter(c => c)" in src, \
            f"the {key} why chips must render non-empty strings only"
    # amber for warnings — the B2 conditions (pending gates / overdue / below target)
    assert "engagementHealth[proj.id].pending_approvals > 0 ? 'bg-amber-50" in src
    assert "engagementHealth[proj.id].overdue_tasks > 0 ? 'bg-amber-50" in src
    assert "engagementHealth[proj.id].kpis_below_target > 0 ? 'bg-amber-50" in src
    # gate aging renders next to the approval chips
    assert "engagementHealth[proj.id].gate_aging > 0" in src


def test_engagement_empty_state_names_the_next_action():
    """No engagements → the note says the API opens them (create form later)."""
    src = _read(CLIENT_HTML)
    assert "No engagements yet for this client." in src
    assert "via the API" in src


def test_no_engagement_create_or_edit_ui():
    """Render-only slice: the create form (and edit UI) is a later slice."""
    src = _read(CLIENT_HTML)
    js = _read(ENGAGEMENTS_JS)
    assert "engagementNewForm" not in src and "engagementEditForm" not in src
    assert "api('POST', '/engagements'" not in js
    assert "api('PUT', '/engagements/" not in js
    assert "api('DELETE', '/engagements/" not in js


def test_existing_client_fields_and_editing_survive():
    """Additive only: the client info card, edit entry and projects grid stay."""
    src = _read(CLIENT_HTML)
    assert '@click="backToClients()"' in src
    assert 'x-text="selectedClient?.name"' in src
    assert "@click=\"openClientModal(selectedClient)\"" in src
    assert "x-text=\"selectedClient?.contact_name || '—'\"" in src
    assert "x-text=\"selectedClient?.contact_email || '—'\"" in src
    assert '@click="openProjectModal({ client_id: selectedClient?.id })"' in src
    assert "@click=\"openProject(p)\"" in src


def test_lazy_fetch_is_never_part_of_a_burst():
    """The engagements fan-out lives in its own lazy loader, not openProject."""
    js = _read(ENGAGEMENTS_JS)
    assert "openProject(" not in js, "engagements.js must not join the openProject burst"
    assert "loadVision" not in js and "loadKPIs" not in js


def test_engagements_class_strings_are_literal():
    """Carry-forward guard (ADR-07): chip classes come from literal mapping tables."""
    js = _read(ENGAGEMENTS_JS)
    for fam in ("bg", "text", "border", "rounded"):
        assert not re.search(r"['\"]" + fam + r"-['\"]\s*\+", js), f"composes '{fam}-' with +"
        assert not re.search(r"`[^`]*" + fam + r"-\$\{", js), f"composes '{fam}-' with ${{}}"
    assert "engagementStatusChipClass(status)" in js
    assert "engagementStatusDotClass(status)" in js
