"""Static UI tests for Rethink v2 phase C2 — the rail drives both boards.

The frontend used to hardcode the Software phase vocabulary in JS literals
(backlog.js itemPhases/releasePhases/phases) plus two hand-mapped release
buckets ("In Release"/"Released") — on any non-Software project the boards
rendered wrong lanes, the stepper broke and the advance button hid. C1
shipped GET /api/projects/{id}/backlog/rail (the EFFECTIVE phases: built-in
overridden by the tenant template); C2 makes the frontend read it.

These tests are static (file-level) by design: they pin the CONTRACT that
no phase vocabulary is hardcoded in the frontend JS/templates, that the
rail loader is lazy, that both boards build from the rail, that the phase
filter is multi-select (OR within the axis) and that the fallback path
(observed phases) exists. The behavioral advance/backlog tests stay in
their own files untouched.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKLOG_JS = REPO / "app" / "static" / "js" / "app" / "domains" / "backlog.js"
WORK_HTML = REPO / "app" / "templates" / "pmo" / "views" / "work.html"
PROJECT_DETAIL = REPO / "app" / "templates" / "pmo" / "views" / "project_detail.html"
ITEM_DRAWER = REPO / "app" / "templates" / "components" / "item_drawer.html"
PROJECTS_JS = REPO / "app" / "static" / "js" / "app" / "domains" / "projects.js"
PLANNING_JS = REPO / "app" / "static" / "js" / "app" / "domains" / "planning.js"


def _read(path: Path) -> str:
    assert path.exists(), f"missing file: {path}"
    return path.read_text(encoding="utf-8")


def _fn_body(js: str, name: str) -> str:
    """A JS method/getter body — matched at its DEFINITION (`name(params) {`),
    never at a call site (calls are preceded by `.` or not followed by `{`)."""
    m = re.search(r"(?<![\w.])" + re.escape(name) + r"\s*\([^()]*\)\s*\{", js)
    assert m, f"{name} not found in backlog.js"
    start = js.index("{", m.start())
    depth = 0
    for i in range(start, len(js)):
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
            if depth == 0:
                return js[m.start() : i + 1]
    return js[m.start() :]


# ── 1. the hardcoded phase literals are GONE ─────────────────────────────


def test_hardcoded_item_phase_array_gone():
    js = _read(BACKLOG_JS)
    assert "itemPhases: [" not in js
    assert "'Requirements', 'Design', 'Development', 'Testing', 'Ready for UAT'" not in js


def test_hardcoded_release_phase_array_gone():
    js = _read(BACKLOG_JS)
    assert "releasePhases: [" not in js
    assert "['UAT', 'Pre-Release', 'Release', 'Post-Release', 'Retrospective']" not in js


def test_hardcoded_nine_phase_array_gone():
    js = _read(BACKLOG_JS)
    assert "phases: ['Requirements'" not in js
    assert "'UAT', 'Pre-Release', 'Release', 'Post-Release', 'Retrospective'" not in js


def test_hand_mapped_release_buckets_gone():
    js = _read(BACKLOG_JS)
    # the two hand-mapped buckets and their counts getter
    assert "phaseFilter === 'In Release'" not in js
    assert "phaseFilter === 'Released'" not in js
    assert "releaseFilterCounts" not in js


def test_vocabulary_is_rail_backed_getters_not_literals():
    js = _read(BACKLOG_JS)
    # the SAME names survive as getters (the drawer, planning.js and the
    # templates read them) — but their only source is the rail cache
    assert "get itemPhases()" in js
    assert "get releasePhases()" in js
    assert "get phases()" in js
    for name in ("itemPhases", "releasePhases", "phases"):
        body = _fn_body(js, f"get {name}")
        assert "railForProject" in body, f"{name} must read the rail"
        assert "is_release_stage" in body or "observedPhaseNames" in body


# ── 2. the rail loader exists + is lazy ──────────────────────────────────


def test_rail_loader_exists_and_hits_the_endpoint():
    js = _read(BACKLOG_JS)
    assert "loadBacklogRail(" in js
    assert "/backlog/rail" in js
    body = _fn_body(js, "loadBacklogRail")
    assert "this.api('GET'" in body


def test_rail_loader_caches_per_project():
    js = _read(BACKLOG_JS)
    assert "railCache: {}" in js
    body = _fn_body(js, "loadBacklogRail")
    assert "railCache[pid]" in body
    # early return when cached (no refetch), in-flight guard
    assert "return this.railCache[pid]" in body
    assert "railLoading[pid]" in body


def test_rail_loader_is_lazy_not_in_any_burst():
    # the openProject burst must NOT prefetch the rail — the restored Backlog
    # tab loads it lazily via planning.js's projectTabLoaders map (backlog →
    # backlogRail, first show); no x-effect prefetch on the project page; the
    # Work board fetches it lazily per project (workRailPhaseNames)
    projects = _read(PROJECTS_JS)
    assert "loadBacklogRail" not in projects
    detail = _read(PROJECT_DETAIL)
    assert "loadBacklogRail" not in detail, "no x-effect prefetch on the project page"
    js = _read(BACKLOG_JS)
    union = _fn_body(js, "workRailPhaseNames")
    assert "loadBacklogRail(pid)" in union  # the lazy per-project fetch remains
    planning = _read(PLANNING_JS)
    assert "backlog: ['backlogRail']" in planning  # the map fires it on first show


# ── 3. both boards build from the rail ───────────────────────────────────


def test_project_board_builds_from_rail():
    js = _read(BACKLOG_JS)
    body = _fn_body(js, "buildBacklogBoard")
    assert "railForProject" in body
    assert "is_release_stage" in body
    assert "observedPhaseNames" in body  # the fallback
    assert "this.itemPhases.map" not in body  # no derived-literal read


def test_work_board_builds_from_rail_union():
    js = _read(BACKLOG_JS)
    body = _fn_body(js, "buildWorkBoard")
    assert "workRailPhaseNames" in body
    union = _fn_body(js, "workRailPhaseNames")
    assert "railCache[pid]" in union
    assert "loadBacklogRail(pid)" in union  # lazy per-project fetch
    assert "is_release_stage" in union
    assert "observedPhaseNames" in union  # the fallback
    assert "this.itemPhases" not in union


def test_work_html_lanes_still_bind_the_board_columns():
    # work.html is untouched (byte-identical) — its board lanes come from the
    # JS-built workBoardColumns, which now read the rail
    html = _read(WORK_HTML)
    assert 'x-for="lane in workBoardColumns"' in html
    assert "workViewMode === 'timeline'" in html  # Timeline view untouched
    assert "workViewMode === 'list'" in html  # List view untouched


def test_project_page_hosts_the_board_again():
    # Rana's correction: the C2 rail-driven board is BACK on the project page
    # (Phase E had folded it into Work); the ONE store is shared — the board's
    # lanes come from backlogBoardColumns (the rail-backed getters in
    # backlog.js), the fetch is lazy via the projectTabLoaders map
    detail = _read(PROJECT_DETAIL)
    assert 'x-for="col in backlogBoardColumns"' in detail
    assert "phaseDotColor(col.phase)" in detail
    assert "loadBacklogRail" not in detail  # no x-effect prefetch — the map fires it


def test_project_board_builder_keeps_the_rail_contract():
    # buildBacklogBoard (backlog.js) is untouched — its rail contract stays; the
    # ONE Work view's board (buildWorkBoard) builds from the rail union
    js = _read(BACKLOG_JS)
    body = _fn_body(js, "buildBacklogBoard")
    assert "railForProject" in body
    assert "is_release_stage" in body
    assert "observedPhaseNames" in body  # the fallback
    assert "this.itemPhases.map" not in body  # no derived-literal read


# ── 4. multi-select phase filter (OR within the axis) ────────────────────


def test_phase_filter_stays_multi_select_after_the_fold():
    # Rethink v2 Phase E: the phase chips lived on the project page's backlog
    # tab (removed) — the multi-select axis itself is untouched in backlog.js
    # (getters, saved views and the work board still read it)
    js = _read(BACKLOG_JS)
    assert "phaseFilter: []" in js
    body = _fn_body(js, "get filteredBacklogItems")
    assert "phaseFilter.length" in body
    assert "selected.includes(i.current_phase)" in body  # OR within the axis


def test_toggle_phase_filter_toggles_array_membership():
    js = _read(BACKLOG_JS)
    body = _fn_body(js, "togglePhaseFilter")
    assert "cur.includes(phase)" in body
    assert "cur.filter(p => p !== phase)" in body
    assert "cur.concat(phase)" in body
    assert "phaseFilterActive(phase)" in _fn_body(js, "phaseFilterActive")


def test_phase_chips_are_back_on_the_project_page():
    # Rana's correction: the FILTER chip row (the rail-backed phase chips with
    # the toggle bindings) is BACK on the restored Backlog tab; the rail-backed
    # getters it reads live in backlog.js, and the item drawer's stepper keeps
    # its own (legitimate) itemPhases x-for
    detail = _read(PROJECT_DETAIL)
    assert "togglePhaseFilter(phase)" in detail
    assert "phaseFilterActive(phase)" in detail
    assert 'x-for="phase in releasePhases"' in detail
    js = _read(BACKLOG_JS)
    assert "get itemPhases()" in js and "get releasePhases()" in js


def test_filters_and_with_the_other_axes():
    # search + group-by AND with the phase axis downstream (existing getters)
    js = _read(BACKLOG_JS)
    grouped = _fn_body(js, "get backlogGrouped")
    epic = _fn_body(js, "get backlogByEpic")
    for body in (grouped, epic):
        assert "filteredBacklogItems" in body  # phase axis applied first
        assert "backlogSearch" in body  # search ANDs after


def test_saved_views_roundtrip_the_multi_select():
    js = _read(BACKLOG_JS)
    save = _fn_body(js, "saveCurrentView")
    apply_ = _fn_body(js, "applyView")
    clear = _fn_body(js, "clearActiveView")
    assert "join(',')" in save
    assert "split(',')" in apply_  # legacy single-phase views still apply
    assert "this.phaseFilter = []" in clear


# ── 5. the fallback path (no rail → observed phases) ─────────────────────


def test_observed_phase_names_fallback_exists():
    js = _read(BACKLOG_JS)
    body = _fn_body(js, "observedPhaseNames")
    assert "current_phase" in body
    # never a hardcoded list inside the fallback
    assert "Requirements" not in body
    assert "Development" not in body


def test_fallback_used_by_context_getters():
    js = _read(BACKLOG_JS)
    for name in ("get itemPhases", "get phases"):
        assert "observedPhaseNames" in _fn_body(js, name)


# ── 6. stepper + move menu + advance button read the effective phases ────


def test_advance_button_guards_are_effective_phase_checks():
    detail = _read(PROJECT_DETAIL)
    # the backlog list rows are gone with the tab (Phase E) — the item drawer's
    # footer advance guard remains
    assert "canAdvanceItem(viewingBacklogItem?.current_phase)" in detail
    # the hardcoded Software guard is gone
    assert "item.current_phase !== 'Ready for UAT'" not in detail
    js = _read(BACKLOG_JS)
    body = _fn_body(js, "canAdvanceItem")
    assert "this.itemPhases" in body
    assert "phases.length - 1" in body  # hides at the LAST rail phase


def test_stepper_and_move_menu_render_effective_phases():
    # item_drawer.html is byte-identical (not this slice's file) — it reads
    # the itemPhases getter, which is now rail-backed
    drawer = _read(ITEM_DRAWER)
    assert 'x-for="ph in itemPhases"' in drawer  # move menu
    assert 'x-for="(ph, idx) in itemPhases"' in drawer  # stepper
    planning = _read(PLANNING_JS)
    assert "this.itemPhases" in planning  # work drawer stepper/advance reads the getter
    js = _read(BACKLOG_JS)
    assert "get itemPhases()" in js  # served by the rail-backed getter


def test_release_stage_guards_read_the_rail():
    # drag/quick-add release guards now check the rail's real stages
    js = _read(BACKLOG_JS)
    for name in ("dropToPhase", "quickAdd"):
        assert "this.releasePhases.includes" in _fn_body(js, name)
