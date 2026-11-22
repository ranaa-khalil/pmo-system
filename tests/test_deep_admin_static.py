"""Static analysis of the Rethink v2 Phase E — deep admin 14 → 9.

The project page's deep admin shrinks from 14 tabs to 9 (plus the cockpit):
the Overview, Vision, Time and Approvals tabs fold away —
Backlog STAYS as a project-page tab (Rana's correction: the project page
keeps its backlog board — the rail-driven one, lazy via the loaders map).

- Backlog and Time become deep-links into the ONE Work view pre-filtered to
  this project (the house setWorkProjectFilter pattern — never a re-hosted
  backlog or board);
- Approvals folds into the ONE approvals inbox (Today's needs-you queue — the
  gate approvals waiting on you, each row opening the approval detail modal in
  one click); gates stay first-class in the cockpit's verdict bar — no
  duplicate queue;
- Vision folds into Plan depth (the Docs tab);
- the Overview folds into the cockpit (the verdict bar's health chips) and the
  KPIs tab (the Traceability Matrix — its KPI-centric deep-admin home).

Plus: the project page's task flows stay drawer-not-modal (the backlog item
drawer with its view ↔ edit swap; the ONE item drawer in Work); the
Infrastructure tab's 6 sub-tabs converge to filter chips in the one
segmented-control style; the Kickoff intake entry (the copilot drawer's
second, unintegrated AI intake) is unreachable from the project page — the
capture box (the ONE integrated intake) is the intake path.

NOTHING is deleted as data: every folded dataset keeps its loader, store key
and endpoint; only the UI panels and the tab buttons are removed. The removed
tabs' hashes degrade gracefully to the cockpit.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROJECT_DETAIL = REPO / "app/templates/pmo/views/project_detail.html"
PLANNING_JS = REPO / "app/static/js/app/domains/planning.js"
BACKLOG_JS = REPO / "app/static/js/app/domains/backlog.js"


def _read(path: Path) -> str:
    assert path.exists(), f"missing file: {path}"
    return path.read_text(encoding="utf-8")


def _fn_body(src: str, name: str) -> str:
    body = re.search(rf"(?:get {name}\(\) \{{|async {name}\([^)]*\) \{{|{name}\([^)]*\) \{{)(.*?\n\}},)", src, re.S)
    assert body, f"{name} missing"
    return body.group(0)


def _loaders_table(js: str) -> str:
    table = re.search(r"projectTabLoaders: \{(.*?)\n    \},", js, re.S)
    assert table, "projectTabLoaders missing"
    return table.group(1)


# ── 1. the tab set is the v2 9 (+ cockpit) ───────────────────────────────


def test_the_tab_bar_is_cockpit_plus_nine_deep_admin_tabs():
    """10 buttons: Cockpit, KPIs, Roadmap, Docs, RAID, Releases, Stakeholders,
    Infrastructure, GitHub Board, Env & Personas."""
    src = _read(PROJECT_DETAIL)
    row = re.search(r"<!-- Tabs -->.*?</div>\s*\n\s*<!-- Cockpit tab", src, re.S)
    assert row, "tabs row missing"
    buttons = re.findall(r"projectTab='([a-z-]+)'", row.group(0))
    assert buttons == ["cockpit", "kpis", "roadmap", "backlog", "docs", "risks", "releases",
                       "stakeholders", "infrastructure", "github", "env"], \
        f"unexpected tab set: {buttons}"


def test_the_folded_tabs_have_no_panels_left():
    """No x-show panel for overview/vision/time/approvals remains; the Backlog
    panel is RESTORED (Rana's correction — the project page keeps its board)."""
    src = _read(PROJECT_DETAIL)
    for gone in ("overview", "vision", "time", "approvals"):
        assert f"x-show=\"projectTab==='{gone}'\"" not in src, f"{gone} panel must be gone"
    assert "x-show=\"projectTab==='backlog'\"" in src, "the Backlog tab is restored"


def test_nothing_is_deleted_as_data():
    """Every folded dataset keeps its loader + store key (only the UI panels
    and the tab buttons are removed)."""
    js = _read(PLANNING_JS)
    for key in ("vision:", "traceability", "brdCoverage", "timeEntries", "timeSummary"):
        assert key in js, f"{key} must survive in planning.js"
    runner = _fn_body(js, "runProjectTabLoader")
    for ds in ("vision", "traceability", "time", "approvals", "backlog", "brdCoverage"):
        assert f"case '{ds}':" in runner, f"dataset {ds} keeps its loader case"


def test_kept_tabs_keep_their_loaders():
    """The kept deep-admin tabs still map to lazy datasets (Backlog restored
    — its map entry loads the rail on first show)."""
    js = _read(PLANNING_JS)
    table = _loaders_table(js)
    for tab, ds in (("kpis", "kpis"), ("roadmap", "roadmaps"), ("backlog", "backlogRail"),
                    ("docs", "releases"),
                    ("risks", "risks"), ("releases", "releases"),
                    ("stakeholders", "stakeholders"), ("infrastructure", "infrastructure"),
                    ("github", "githubConfig"), ("env", "personas")):
        entry = re.search(rf"^\s+{tab}: \[(.*?)\]", table, re.M)
        assert entry, f"no loaders for {tab}"
        assert f"'{ds}'" in entry.group(1), f"{tab} lost its {ds} dataset"


# ── 2. Backlog → the ONE Work view (deep-link, not a board) ──────────────


def test_backlog_folds_into_the_one_work_view():
    """Rana's correction: the Backlog tab is RESTORED on the project page (the
    rail-driven board, lazy via the projectTabLoaders map); the cockpit's Work
    card still deep-links into the ONE Work view pre-filtered (the house
    pattern) — both surfaces read the ONE store, never a re-host."""
    js = _read(PLANNING_JS)
    open_work = _fn_body(js, "openWorkWithProject")
    assert "setWorkProjectFilter(String(this.selectedProject.id))" in open_work
    assert "this.navigate('work')" in open_work
    src = _read(PROJECT_DETAIL)
    assert "openWorkWithProject()" in src, "the cockpit deep-links into Work"
    assert "backlogBoardColumns" in src, "the Backlog board is restored on the project page"
    assert "loadBacklogRail" not in src, "no x-effect prefetch — the loaders map fires it"
    assert "backlog: ['backlogRail']" in js, "the Backlog tab's lazy map entry"


def test_backlog_data_still_loads_for_the_cockpit():
    """loadBacklog stays in the openProject burst (the Work card count, the
    needs-you rows and the item drawer read backlogItems)."""
    js = _read(PLANNING_JS)
    burst = re.search(r"async openProject\(project\) \{.*?\n\},", js, re.S)
    assert burst, "openProject missing"
    burst = burst.group(0)
    assert "this.loadBacklog()" in burst, "backlog data still loads"


def test_backlog_item_drawer_survives_on_the_project_page():
    """The task flows stay drawer-not-modal: the backlog item drawer (view ↔
    edit swap) is the project page's task-flow surface."""
    src = _read(PROJECT_DETAIL)
    drawer = re.search(r'x-show="viewingBacklogItem".*?@keydown\.escape\.window="viewingBacklogItem = null"', src, re.S)
    assert drawer, "the backlog item drawer must survive"
    assert "backlogEditMode" in src, "the drawer keeps its edit swap"
    assert "canAdvanceItem(viewingBacklogItem?.current_phase)" in src, "the footer verbs stay"


# ── 3. Time → the ONE Work view's timeline (deep-link) ───────────────────


def test_time_folds_into_the_work_timeline():
    """The Time tab's deep-link: setWorkProjectFilter + setWorkViewMode
    ('timeline') + navigate — the Work action card's Timeline chip."""
    js = _read(PLANNING_JS)
    open_tl = _fn_body(js, "openWorkTimeline")
    assert "setWorkProjectFilter(String(this.selectedProject.id))" in open_tl
    assert "setWorkViewMode('timeline')" in open_tl
    assert "this.navigate('work')" in open_tl
    src = _read(PROJECT_DETAIL)
    assert "openWorkTimeline()" in src, "the cockpit carries the timeline chip"
    assert "projectTab==='time'" not in src, "the Time panel is gone"


def test_time_data_still_loads():
    """The time datasets keep their loader + store (nothing deleted as data);
    only the project page's hours panel is removed."""
    js = _read(PLANNING_JS)
    load = _fn_body(js, "loadTime")
    assert "time-entries" in load or "time" in load, "loadTime keeps its endpoints"
    for key in ("timeEntries: []", "timeSummary: []", "logTime(", "lockWeek("):
        assert key in js, f"{key} must survive"


# ── 4. Approvals → the ONE approvals inbox ───────────────────────────────


def test_approvals_fold_into_the_one_inbox():
    """The Approvals tab deep-links into the ONE approvals inbox (Today's
    needs-you queue) — no second approvals surface was built."""
    js = _read(PLANNING_JS)
    inbox = _fn_body(js, "openApprovalInbox")
    assert "this.navigate('today')" in inbox, "the inbox is Today's needs-you queue"
    src = _read(PROJECT_DETAIL)
    assert "openApprovalInbox()" in src, "the verdict bar's gates tile opens the inbox"


def test_no_second_approvals_surface():
    """No new approvals queue/list was built anywhere in the frontend — the
    approval detail modal (approve/reject/guest links) is the action surface."""
    src = _read(PROJECT_DETAIL)
    assert 'x-show="selectedApproval"' in src, "the approval detail modal survives"
    assert "approveStep(step.id)" in src and "rejectStep(step.id)" in src
    js = _read(PLANNING_JS)
    assert 'x-show="route === \'approvals\'"' not in _read(PLANNING_JS), "no approvals route"


def test_approval_rows_open_the_detail_in_one_click():
    """The cockpit's and Today's needs-you approval rows open the approval
    detail modal directly (the legacy 'open the project page' hack is gone)."""
    js = _read(PLANNING_JS)
    row = _fn_body(js, "openCockpitRow")
    assert "openApproval({ id: row.ref_id })" in row, "cockpit rows open the detail"
    today_row = _fn_body(js, "openWorkItemFromToday")
    assert "openApproval({ id: row.ref_id })" in today_row, "Today rows open the detail"
    assert "this.navigate('projects')" not in today_row, "no legacy projects-list hack"


def test_gates_stay_first_class_in_the_verdict_bar():
    """The verdict bar keeps the gates queue (count + aging) — no duplicate."""
    src = _read(PROJECT_DETAIL)
    section = re.search(r"<!-- Cockpit tab.*?<!-- KPIs tab -->", src, re.S)
    assert section, "cockpit section missing"
    section = section.group(0)
    assert "projectPendingGates.length" in section, "the open-gates count stays"
    assert "projectHealth?.gate_aging" in section, "the gate-aging chip stays"


def test_approval_data_still_loads():
    """loadApprovals stays in the openProject burst (the verdict bar's gates
    count and the needs-you rows read projectApprovals)."""
    js = _read(PLANNING_JS)
    burst = re.search(r"async openProject\(project\) \{.*?\n\},", js, re.S)
    assert burst, "openProject missing"
    burst = burst.group(0)
    assert "this.loadApprovals()" in burst, "approval data still loads"


# ── 5. Vision folds into Plan depth ──────────────────────────────────────


def test_vision_folds_into_the_docs_tab():
    """The Vision tab's content (statement + create/edit) lives in the Docs
    tab now — Plan depth; the vision loader fires with the docs tab."""
    src = _read(PROJECT_DETAIL)
    docs = re.search(r"<!-- Docs tab.*?<!-- PDF Viewer Modal", src, re.S)
    assert docs, "docs section missing"
    docs = docs.group(0)
    assert "Project Vision & Strategic Objectives" in docs, "the vision section is in Docs"
    assert "visionForm.statement" in docs, "the create/edit form survives"
    assert "renderMarkdown(vision?.statement)" in docs, "the statement renders"
    js = _read(PLANNING_JS)
    table = _loaders_table(js)
    docs_entry = re.search(r"^\s+docs: \[(.*?)\]", table, re.M)
    assert docs_entry and "'vision'" in docs_entry.group(1), "docs loads the vision dataset"


def test_vision_is_no_tab_anywhere():
    """No Vision tab button or panel remains."""
    src = _read(PROJECT_DETAIL)
    assert "projectTab='vision'" not in src
    assert "setProjectTab('vision')" not in src


# ── 6. the Overview folds into the cockpit + KPIs ────────────────────────


def test_overview_folds_into_the_cockpit_and_kpis():
    """The Overview tab is gone; its Traceability Matrix lives in the KPIs tab
    (its KPI-centric deep-admin home); coverage loads with the cockpit."""
    src = _read(PROJECT_DETAIL)
    assert "projectTab==='overview'" not in src, "the Overview panel is gone"
    kpis = re.search(r"<!-- KPIs tab -->.*?<!-- Roadmap tab -->", src, re.S)
    assert kpis, "kpis section missing"
    kpis = kpis.group(0)
    assert "Traceability Matrix" in kpis, "the matrix lives in KPIs"
    assert "traceability?.kpis" in kpis, "KPIs → backlog items survive"
    assert "unlinked_backlog" in kpis, "the unlinked warnings survive"
    js = _read(PLANNING_JS)
    table = _loaders_table(js)
    kpis_entry = re.search(r"^\s+kpis: \[(.*?)\]", table, re.M)
    assert kpis_entry and "'traceability'" in kpis_entry.group(1), "kpis loads traceability"


def test_overview_counts_live_in_the_cockpit_cards():
    """The overview's quick stats were its own duplicate — the action cards and
    verdict tiles carry the counts that matter."""
    src = _read(PROJECT_DETAIL)
    section = re.search(r"<!-- Cockpit tab.*?<!-- KPIs tab -->", src, re.S)
    assert section, "cockpit section missing"
    section = section.group(0)
    assert "backlogItems.length" in section and "projectReleases.length" in section


# ── 7. task modal → drawer (drawer-not-modal) ────────────────────────────


def test_no_inline_create_form_left_in_the_folded_flows():
    """Rana's correction: the Backlog tab's inline create form is BACK with the
    restored tab (Feature/Epic toggle + save); the drawer's new-item mode in
    Work remains the other create path — two surfaces, ONE store."""
    src = _read(PROJECT_DETAIL)
    assert "showBacklogForm" in src, "the inline create form is restored with the tab"
    assert "saveBacklogItem(false)" in src, "the inline save is restored with the tab"


def test_the_task_flows_use_drawers_not_modals():
    """The project page's task flows (view/edit backlog item) are the drawer
    pattern — a right-side slide-over with view ↔ edit swap, not a centered
    modal; the ONE item drawer in Work covers the rest."""
    src = _read(PROJECT_DETAIL)
    drawer = re.search(r'x-show="viewingBacklogItem"[^>]*>\s*<div class="absolute inset-0[^"]*"\s*@click="viewingBacklogItem = null"', src, re.S)
    assert drawer, "the drawer shell (scrim + Esc) must follow the slide-over pattern"
    assert 'x-show="viewingBacklogItem"' in src
    # the centered-modal flex pattern must not wrap the item drawer
    item_region = src[src.index('x-show="viewingBacklogItem"'):src.index("viewingBacklogItem = null\">") + 40]
    assert "items-center justify-center" not in item_region, "the item drawer is not a centered modal"


# ── 8. infra 6 sub-tabs → filter chips ───────────────────────────────────


def test_infra_subtabs_are_filter_chips():
    """The 6 sub-tabs converge to one chip row in the segmented-control style
    (chips-not-tabs lock) — the panels keep their infraSubTab state machine."""
    src = _read(PROJECT_DETAIL)
    chips = re.search(r"infraSubTab=f\.id", src)
    assert chips, "the infra filter chips are missing"
    for label in ("Overview", "Assets", "Secrets", "Environments", "Services", "Databases"):
        assert f"label: '{label}'" in src, f"chip {label} missing"
    # the one segmented-control style (the Work view's mode chips)
    assert "bg-gradient-to-r from-indigo-500 to-violet-500 text-white shadow-sm" in src
    # the old tab-active sub-tab bar is gone
    assert "infraSubTab='overview' ? 'tab-active" not in src
    # the panels keep their state machine
    for panel in ("overview", "assets", "secrets", "environments", "services", "databases"):
        assert f"x-show=\"infraSubTab==='{panel}'\"" in src, f"panel {panel} must keep its x-show"


def test_infra_chips_are_not_tab_buttons():
    """Chips-not-tabs: no border-b tab row and no tab-active class in the
    infrastructure chip row."""
    src = _read(PROJECT_DETAIL)
    chip_row = re.search(r"<!-- Filter chips \(Rethink v2 Phase E\).*?</template>\s*</div>", src, re.S)
    assert chip_row, "the infra chip row is missing"
    assert "tab-active" not in chip_row.group(0)
    assert "border-b" not in chip_row.group(0)


def test_env_tab_still_jumps_into_infra():
    """The env tab's 'Manage in Infrastructure →' jump keeps working with chips."""
    src = _read(PROJECT_DETAIL)
    assert "infraSubTab='environments'" in src, "the env → infra jump survives"


# ── 9. the intake redirect (Kickoff → the capture box) ───────────────────


def test_kickoff_intake_is_unreachable_from_the_project_page():
    """The copilot drawer's Kickoff tab is a second, unintegrated AI intake —
    the project page's only entry to it (openCopilotIntake) is gone with the
    Backlog tab; the capture box (the ONE integrated intake) is the path."""
    src = _read(PROJECT_DETAIL)
    assert "openCopilotIntake" not in src, "no entry to the unintegrated Kickoff intake"


def test_the_integrated_capture_paths_still_stand():
    """The capture box keeps its house includes (Work header, Today, the item
    drawer, the FAB) — untouched files, verified from the project page's side."""
    for rel, needle in (
        ("app/templates/pmo/views/work.html", "components/capture_box.html"),
        ("app/templates/pmo/views/today.html", "components/capture_box.html"),
        ("app/templates/pmo/modals/fab.html", "components/capture_box.html"),
        ("app/templates/components/item_drawer.html", "components/capture_box.html"),
    ):
        assert needle in _read(REPO / rel), f"capture box include missing in {rel}"


# ── 10. ?tab= still round-trips for the kept tabs ────────────────────────


def test_tab_state_roundtrips_for_the_kept_tabs():
    """isValidProjectTab is keyed on the loaders map — the kept tabs' hashes
    still round-trip; the removed tabs' hashes degrade to the cockpit."""
    js = _read(PLANNING_JS)
    valid = _fn_body(js, "isValidProjectTab")
    assert "projectTabLoaders[tab]" in valid, "validity is keyed on the loaders map"
    read = _fn_body(js, "readProjectTabFromUrl")
    assert "isValidProjectTab(m[2])" in read, "unknown/removed tabs are rejected"
    assert "consumeProjectHash" in _fn_body(js, "tryProjectDeepLink")
    watchers = _fn_body(js, "bindProjectTabWatchers")
    assert "this.projectTab = 'cockpit'" in watchers, "removed tabs degrade to the cockpit"
