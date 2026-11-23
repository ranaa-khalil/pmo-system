"""Static analysis of the Rethink v2 Phase B2 project overview surfaces
(Phase E adjusted).

The project detail overview (templates/pmo/views/project_detail.html) rendered
the health-why and coverage backends that always computed server-side but
appeared nowhere:

- under each health sub-score, its `why` chip(s) from
  GET /api/projects/{id}/health, plus the additive gate_aging chip
  ("oldest gate 6d");
- a KPI Coverage card from GET /api/projects/{id}/coverage: the coverage %
  big number (or "No KPIs yet" when the project has no KPIs — never an
  invented 100), the kpis_with_work / kpi_total line, the kpis_without_work
  chip, and the unlinked orphan chips, each jumping to the backlog tab.

Rethink v2 Phase E folded the overview tab away — NOTHING deleted as data:
the why chips + gate aging survive flattened in the cockpit's VERDICT BAR
(the projectVerdictChips getter builds them from the same health payload's
why lists; the bar renders them as one compact chip row), and the KPI
Coverage card (orphans included) moved into the cockpit. The per-sub-score
chip-loop markup is gone with the card — the data path (the health payload's
why keys) is the same. This file's assertions follow the surfaces to their
Phase E homes.

Its JS lives in static/js/app/domains/projects.js and must call the SAME
endpoint the API tests prove behave (test_coverage.py). The fetch is LAZY:
the cockpit's loaders entry (projectTabLoaders.coverage in planning.js) fires
it on the cockpit's first show (runProjectTabLoader) and openProject's burst
must never call it. The health payload's 15 legacy keys + additive
gate_aging/why keep their backend parity test in test_health.py
(test_response_key_parity_additive_only) — not duplicated here.
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


def _verdict_bar(src: str) -> str:
    """The cockpit's verdict bar — the B2 why chips' Phase E home."""
    bar = re.search(r"<!-- Verdict bar -->.*?<!-- Each number is a button into its surface -->", src, re.S)
    assert bar, "Verdict bar missing from project_detail.html"
    return bar.group(0)


def _coverage_card(src: str) -> str:
    """The KPI Coverage card — the cockpit's last card since Phase E."""
    cockpit = re.search(r"<!-- Cockpit tab \(Rethink v2 Phase D2\).*?<!-- KPIs tab -->", src, re.S)
    assert cockpit, "cockpit section missing from project_detail.html"
    card = re.search(r"<!-- KPI Coverage \(Rethink v2 Phase B2\).*", cockpit.group(0), re.S)
    assert card, "KPI Coverage card missing from project_detail.html"
    return card.group(0)


def _getter_body(js: str, name: str) -> str:
    body = re.search(rf"get {name}\(\) \{{(.*?)\n\}},", js, re.S)
    assert body, f"{name} missing"
    return body.group(1)


# ── 1. the why chips (B2) — flattened into the cockpit's verdict bar ─────


def test_verdict_chips_build_from_the_health_why_lists():
    """Each sub-score (schedule/approvals/tasks/kpis) carries its why chips —
    the getter reads them from the same health payload (Phase E: the markup
    moved from the overview card into the getter + the verdict bar)."""
    js = _read(PLANNING_JS)
    getter = _getter_body(js, "projectVerdictChips")
    for sub in ("schedule", "approvals", "tasks", "kpis"):
        assert f"h.why?.{sub}" in getter, f"why chips missing for {sub}"


def test_why_chips_render_only_non_empty_strings():
    """Some chips may be null/empty — the getter filters them out."""
    js = _read(PLANNING_JS)
    getter = _getter_body(js, "projectVerdictChips")
    assert getter.count("if (c)") >= 1, "empty chips are not filtered in the getter"
    assert "(list || [])" in getter, "null why lists must not throw"


def test_why_chips_use_the_small_chip_palette():
    """Small text-[11px] chips: amber for warnings, ink for neutral."""
    src = _read(PROJECT_DETAIL)
    bar = _verdict_bar(src)
    assert "text-[11px]" in bar
    assert "bg-amber-50 text-amber-700" in bar, "warning chips must be amber"
    assert "bg-ink-100 text-ink-500" in bar, "neutral chips must be ink"
    assert bar.count("rounded-full") >= 4
    assert "projectVerdictChips" in bar, "the bar renders the getter's chips"


def test_gate_aging_renders_in_the_verdict_bar():
    """The additive gate_aging key renders an 'oldest gate Nd' chip when > 0."""
    src = _read(PROJECT_DETAIL)
    bar = _verdict_bar(src)
    assert "gate_aging" in bar, "gate_aging never rendered"
    gate = re.search(r"gate aging \(B2\).*?</span>", bar, re.S)
    assert gate, "gate aging chip block missing"
    block = gate.group(0)
    assert "projectHealth?.gate_aging > 0" in block, "gate chip must hide when 0"
    assert "'oldest gate ' + projectHealth?.gate_aging + 'd'" in block


# ── 2. the KPI Coverage card (B2) — in the cockpit since Phase E ─────────


def test_coverage_card_exists_in_the_cockpit():
    """Phase E: the cockpit carries the KPI Coverage card (the overview tab
    folded away)."""
    src = _read(PROJECT_DETAIL)
    card = _coverage_card(src)
    assert "KPI Coverage" in card
    assert "projectCoverage" in card
    cockpit = re.search(r"<!-- Cockpit tab.*?<!-- KPIs tab -->", src, re.S)
    assert cockpit, "cockpit section missing"
    assert "KPI Coverage" in cockpit.group(0), "the card must live in the cockpit"


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


def test_orphan_chips_open_the_specific_item():
    """Phase E, re-pointed by the UX sweep: chips no longer open the generic
    Work view (that lost the specific orphan item the user tapped) — each
    chip opens the ONE drawer on that exact item."""
    src = _read(PROJECT_DETAIL)
    card = _coverage_card(src)
    assert "unlinked_sample" in card
    orphans = re.search(r"Orphan items.*?</div>\s*</div>", card, re.S)
    assert orphans, "orphan chip block missing"
    block = orphans.group(0)
    assert "openWorkItem(item)" in block, "orphan chips open the specific item in the drawer"
    assert "openWorkWithProject()" not in block, "the generic Work jump is retired"
    assert "projectTab='backlog'" not in block, "the Backlog tab is gone"
    assert "item.title" in block


# ── 3. the lazy wiring (projects.js + the cockpit's loaders entry) ───────


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


def test_coverage_loads_lazily_with_the_cockpit():
    """Phase E: the cockpit's loaders entry (projectTabLoaders.coverage) fires
    loadCoverage on the cockpit's first show — no overview x-effect left."""
    js = _read(PLANNING_JS)
    table = re.search(r"projectTabLoaders: \{(.*?)\n    \},", js, re.S)
    assert table, "projectTabLoaders missing"
    cockpit = re.search(r"^\s+cockpit: \[(.*?)\]", table.group(1), re.M)
    assert cockpit and "'coverage'" in cockpit.group(1), "cockpit must lazily load coverage"
    src = _read(PROJECT_DETAIL)
    assert "loadCoverage" not in src, "no x-effect prefetch on the project page"


def test_coverage_is_never_in_the_openproject_burst():
    """openProject (planning.js) must not fetch coverage — the lazy load does."""
    js = _read(PLANNING_JS)
    burst = re.search(r"async openProject\(project\) \{.*?\n\},", js, re.S)
    assert burst, "openProject missing from planning.js"
    assert "loadCoverage" not in burst.group(0), "coverage belongs in the lazy load"
