"""Static analysis of the Rethink v2 Phase B2 project overview surfaces.

The project detail overview (templates/pmo/views/project_detail.html,
projectTab === 'overview') now renders the health-why and coverage backends
that always computed server-side but appeared nowhere:

- under each health sub-score, its `why` chip(s) from
  GET /api/projects/{id}/health, plus the additive gate_aging chip next to
  the approval sub-score ("oldest gate 6d");
- a KPI Coverage card from GET /api/projects/{id}/coverage: the coverage %
  big number (or "No KPIs yet" when the project has no KPIs — never an
  invented 100), the kpis_with_work / kpi_total line, the kpis_without_work
  chip, and the unlinked orphan chips, each jumping to the backlog tab.

Its JS lives in static/js/app/domains/projects.js and must call the SAME
endpoint the API tests prove behave (test_coverage.py). The fetch is LAZY:
the overview loads coverage when the tab first shows (x-effect wiring) and
openProject's burst (planning.js) must never call it. The health payload's
15 legacy keys + additive gate_aging/why keep their backend parity test in
test_health.py (test_response_key_parity_additive_only) — not duplicated here.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROJECT_DETAIL = REPO / "app/templates/pmo/views/project_detail.html"
PROJECTS_JS = REPO / "app/static/js/app/domains/projects.js"
PLANNING_JS = REPO / "app/static/js/app/domains/planning.js"


def _read(path: Path) -> str:
    assert path.exists(), f"{path.name} missing"
    return path.read_text(encoding="utf-8")


def _health_card(src: str) -> str:
    card = re.search(r"<!-- Project Health Card -->.*?<!-- Vision banner -->", src, re.S)
    assert card, "Project Health card missing from project_detail.html"
    return card.group(0)


def _coverage_card(src: str) -> str:
    card = re.search(r"<!-- KPI Coverage \(Rethink v2 Phase B2\).*?<!-- Vision banner -->", src, re.S)
    assert card, "KPI Coverage card missing from project_detail.html"
    return card.group(0)


def test_health_card_renders_why_chips_under_every_subscore():
    """Each sub-score (schedule/approvals/tasks/kpis) carries its why chips."""
    src = _read(PROJECT_DETAIL)
    card = _health_card(src)
    for sub in ("schedule", "approvals", "tasks", "kpis"):
        assert f"why?.{sub}" in card, f"why chips missing for {sub}"
        assert f"'why-{sub}-'" in card, f"why chip loop missing for {sub}"


def test_why_chips_render_only_non_empty_strings():
    """Some chips may be null/empty — the render filters them out."""
    src = _read(PROJECT_DETAIL)
    card = _health_card(src)
    assert card.count(".filter(c => c)") >= 4, "empty chips are not filtered per sub-score"


def test_why_chips_use_the_small_chip_palette():
    """Small text-[11px] chips: amber for warnings, ink for neutral."""
    src = _read(PROJECT_DETAIL)
    card = _health_card(src)
    assert "text-[11px]" in card
    assert "bg-amber-50 text-amber-700" in card, "warning chips must be amber"
    assert "bg-ink-100 text-ink-500" in card, "neutral chips must be ink"
    assert card.count("rounded-full") >= 4


def test_gate_aging_renders_next_to_the_approval_subscore():
    """The additive gate_aging key renders an 'oldest gate Nd' chip when > 0."""
    src = _read(PROJECT_DETAIL)
    card = _health_card(src)
    assert "gate_aging" in card, "gate_aging never rendered"
    gate = re.search(r"gate aging \(B2\).*?</div>", card, re.S)
    assert gate, "gate aging chip block missing"
    assert "projectHealth?.gate_aging > 0" in gate.group(0), "gate chip must hide when 0"
    assert "'oldest gate ' + projectHealth?.gate_aging + 'd'" in gate.group(0)


def test_coverage_card_exists_in_the_overview():
    """The overview carries the KPI Coverage card between health and vision."""
    src = _read(PROJECT_DETAIL)
    card = _coverage_card(src)
    assert "KPI Coverage" in card
    assert "projectCoverage" in card


def test_coverage_card_shows_no_kpis_yet_when_pct_is_null():
    """coverage_pct is null when the project has no KPIs — never a fake 100."""
    src = _read(PROJECT_DETAIL)
    card = _coverage_card(src)
    assert "No KPIs yet" in card
    assert "coverage_pct == null" in card


def test_coverage_card_shows_with_work_ratio_and_without_work_chip():
    """kpis_with_work / kpi_total line + the kpis_without_work count chip."""
    src = _read(PROJECT_DETAIL)
    card = _coverage_card(src)
    assert "kpis_with_work" in card and "kpi_total" in card
    assert "kpis_without_work" in card
    assert "KPIs without work" in card or "KPI without work" in card


def test_orphan_chips_link_to_the_backlog_tab():
    """Up to 10 unlinked_sample titles as chips, each opening the backlog tab."""
    src = _read(PROJECT_DETAIL)
    card = _coverage_card(src)
    assert "unlinked_sample" in card
    orphans = re.search(r"Orphan items.*?</div>\s*</div>", card, re.S)
    assert orphans, "orphan chip block missing"
    block = orphans.group(0)
    assert "projectTab='backlog'" in block, "orphan chips must open the backlog tab"
    assert "item.title" in block


def test_loadcoverage_calls_the_coverage_endpoint():
    """loadCoverage (projects.js) calls GET /api/projects/{id}/coverage."""
    js = _read(PROJECTS_JS)
    load = re.search(r"async loadCoverage\(\) \{.*?\n\},", js, re.S)
    assert load, "loadCoverage missing from projects.js"
    assert "api('GET', `/projects/${this.selectedProject.id}/coverage`)" in load.group(0)


def test_coverage_fetch_is_lazy_once():
    """The fetch guards so one project loads coverage once (lazy-once)."""
    js = _read(PROJECTS_JS)
    load = re.search(r"async loadCoverage\(\) \{.*?\n\},", js, re.S)
    assert load, "loadCoverage missing from projects.js"
    body = load.group(0)
    assert "coverageLoadedFor" in body, "no lazy-once guard"
    assert "if (!this.selectedProject) return;" in body


def test_coverage_state_defaults_in_projects_js():
    """The coverage state lives in projects.js with null defaults."""
    js = _read(PROJECTS_JS)
    assert re.search(r"projectCoverage: null,", js)
    assert re.search(r"coverageLoadedFor: null,", js)


def test_overview_wires_coverage_lazily_on_first_show():
    """The overview section carries the lazy x-effect wiring."""
    src = _read(PROJECT_DETAIL)
    overview = re.search(
        r"<!-- Overview tab — Connected Traceability Dashboard -->.*?<!-- Project Health Card -->",
        src, re.S,
    )
    assert overview, "overview section missing"
    assert "x-effect" in overview.group(0), "overview must lazily trigger loadCoverage"
    assert "loadCoverage()" in overview.group(0)


def test_coverage_is_never_in_the_openproject_burst():
    """openProject (planning.js) must not fetch coverage — the overview does."""
    js = _read(PLANNING_JS)
    burst = re.search(r"async openProject\(project\) \{.*?\n\},", js, re.S)
    assert burst, "openProject missing from planning.js"
    assert "loadCoverage" not in burst.group(0), "coverage belongs in the lazy overview load"
