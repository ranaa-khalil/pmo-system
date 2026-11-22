"""Static analysis of the Rethink v2 Phase D2 project cockpit (Phase E adjusted).

The project page's DEFAULT landing is now the COCKPIT (projectTab defaults to
'cockpit' when a project opens) — one viewport of decision inputs, not a
rebuild of every tab:

- the VERDICT BAR: the health composite + why chips (B2's rendering, flattened
  by the projectVerdictChips getter) + the additive gate_aging chip, and four
  tiles — next release, open gates, open RAID, coverage % — each a button into
  its surface (releases / the ONE approvals inbox / risks / KPIs tabs);
- WHAT NEEDS YOU: the /today needs-you aggregate (server-computed "waiting on
  you", project-scoped) + aging High/Critical risks from the RAID payload,
  each row 1-click into its surface (the approval detail / item drawer / risks
  tab);
- the NARRATIVE LINE: the project's latest activity from the loaded activity
  payload (a one-line read, not a feed);
- FOUR ACTION CARDS with live counts, each into its surface — Work goes to the
  ONE Work view pre-filtered to this project (the house setWorkProjectFilter
  pattern; the backlog is never re-hosted here), and Work's chip is the Time
  tab's deep-link (the project's timeline in the ONE Work view).

The state: #/p/{id}/{tab} in the URL (history.replaceState on change, read on
openProject, boot deep-link via the root x-effect) + the last-visited tab per
project in localStorage as the fallback. Rethink v2 Phase E: the removed tabs'
hashes degrade gracefully to the cockpit (the watcher guards invalid tabs).

The lazy loaders: openProject keeps ONLY the cockpit's needs (health + the
counts the verdict bar/action cards need + the project identity) — the other
9 deep-admin tabs load their datasets the FIRST time the tab shows
(projectTabLoaders → ensureProjectTabData, one lazy-once flag per dataset).
B2's coverage card was absorbed into the cockpit (its data/behavior survive).

Rethink v2 Phase E (this file's adjustments): the Overview, Vision, Backlog,
Time and Approvals tabs folded away — the bar is cockpit + 9 deep-admin tabs;
the verdict bar's why chips are the health card's cockpit home (the flattened
read of the same payload); the coverage card's orphan chips deep-link into the
ONE Work view; the rail-driven board lives only on the Work route.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROJECT_DETAIL = REPO / "app/templates/pmo/views/project_detail.html"
PLANNING_JS = REPO / "app/static/js/app/domains/planning.js"


def _read(path: Path) -> str:
    assert path.exists(), f"{path.name} missing"
    return path.read_text(encoding="utf-8")


def _fn_body(src: str, name: str) -> str:
    body = re.search(rf"(?:get {name}\(\) \{{|async {name}\([^)]*\) \{{|{name}\([^)]*\) \{{)(.*?\n\}},)", src, re.S)
    assert body, f"{name} missing"
    return body.group(0)


def _cockpit_section(src: str) -> str:
    section = re.search(
        r"<!-- Cockpit tab \(Rethink v2 Phase D2\).*?<!-- KPIs tab -->", src, re.S,
    )
    assert section, "cockpit section missing from project_detail.html"
    return section.group(0)


def _loaders_table(js: str) -> str:
    table = re.search(r"projectTabLoaders: \{(.*?)\n    \},", js, re.S)
    assert table, "projectTabLoaders missing"
    return table.group(1)


def _openproject_body(js: str) -> str:
    body = re.search(r"async openProject\(project\) \{.*?\n\},", js, re.S)
    assert body, "openProject missing from planning.js"
    return body.group(0)


# ── 1. the cockpit is the DEFAULT landing ────────────────────────────────


def test_project_tab_defaults_to_the_cockpit():
    """projectTab's default is 'cockpit' — the cockpit is the landing."""
    js = _read(PLANNING_JS)
    assert re.search(r"projectTab: 'cockpit',", js), "projectTab must default to 'cockpit'"


def test_openproject_resolves_the_cockpit_as_the_fallback():
    """?tab= → last-visited → 'cockpit'."""
    body = _openproject_body(_read(PLANNING_JS))
    assert "readProjectTabFromUrl(project.id)" in body, "openProject must read ?tab="
    assert "lastProjectTab(project.id)" in body, "openProject must read the last-visited tab"
    assert "|| 'cockpit'" in body, "the cockpit must be the fallback tab"


def test_the_cockpit_tab_button_is_first_in_the_tab_row():
    """Cockpit is the FIRST tab button; the five folded tabs are gone."""
    src = _read(PROJECT_DETAIL)
    row = re.search(r"<!-- Tabs -->.*?<!-- Cockpit tab", src, re.S)
    assert row, "tabs row missing"
    assert "projectTab='cockpit'" in row.group(0), "Cockpit tab button missing"
    buttons = re.findall(r"projectTab='([a-z-]+)'", row.group(0))
    assert buttons[0] == "cockpit", "the Cockpit tab must be first"
    for gone in ("overview", "vision", "backlog", "time", "approvals"):
        assert gone not in buttons, f"the {gone} tab button must be removed"


def test_the_cockpit_section_exists():
    """The cockpit renders before the KPIs tab in the template."""
    src = _read(PROJECT_DETAIL)
    section = _cockpit_section(src)
    assert 'x-show="projectTab===\'cockpit\'"' in section


# ── 2. the verdict bar ───────────────────────────────────────────────────


def test_verdict_bar_renders_the_health_composite_and_why_chips():
    """Health score + status + B2's why chips (flattened) in the cockpit."""
    section = _cockpit_section(_read(PROJECT_DETAIL))
    assert "Verdict" in section
    assert "healthColor(projectHealth?.health_score)" in section
    assert "projectVerdictChips" in section
    js = _read(PLANNING_JS)
    chips = _fn_body(js, "get projectVerdictChips")
    for sub in ("schedule", "approvals", "tasks", "kpis"):
        assert f"h.why?.{sub}" in chips, f"why chips missing for {sub}"


def test_verdict_bar_renders_the_gate_aging_chip():
    """The additive gate_aging chip renders in the verdict bar."""
    section = _cockpit_section(_read(PROJECT_DETAIL))
    assert "gate_aging" in section
    assert "'oldest gate ' + projectHealth?.gate_aging + 'd'" in section


def test_verdict_tiles_navigate_to_their_surfaces():
    """Next release → releases, gates → the ONE approvals inbox, RAID → risks,
    coverage → KPIs."""
    section = _cockpit_section(_read(PROJECT_DETAIL))
    assert "setProjectTab('releases')" in section
    assert "openApprovalInbox()" in section, "gates open the ONE approvals inbox"
    assert "setProjectTab('risks')" in section
    assert "setProjectTab('kpis')" in section
    js = _read(PLANNING_JS)
    assert _fn_body(js, "get projectPendingGates"), "open gates count missing"
    assert _fn_body(js, "get projectNextRelease"), "next release missing"
    assert _fn_body(js, "get projectOpenRaidCount"), "open RAID count missing"


# ── 3. what needs you + narrative + action cards ─────────────────────────


def test_needs_you_rows_render_from_the_today_aggregate_and_raid():
    """Gates/blocked/overdue come from the loaded /today payload (project-scoped),
    aging High/Critical risks from the RAID payload — no extra store."""
    js = _read(PLANNING_JS)
    needs = _fn_body(js, "get projectNeedsYou")
    assert "today?.needs_you" in needs, "the /today aggregate is the needs-you source"
    assert "selectedProject.id" in needs, "rows must be project-scoped"
    assert "High" in needs and "Critical" in needs, "aging risks missing"
    section = _cockpit_section(_read(PROJECT_DETAIL))
    assert "projectNeedsYou" in section
    assert "openCockpitRow(row)" in section, "each row must 1-click into its surface"


def test_needs_you_rows_open_their_surface_in_one_click():
    """gates → the approval detail, risks → risks tab, items → the item drawer."""
    js = _read(PLANNING_JS)
    open_row = _fn_body(js, "openCockpitRow")
    assert "openApproval({ id: row.ref_id })" in open_row, "gates open the approval detail"
    assert "setProjectTab('risks')" in open_row
    assert "viewBacklogItem(known)" in open_row, "items open in the item drawer"


def test_narrative_line_reads_the_activity_payload():
    """One line: actor · action · when, from the loaded activity payload."""
    js = _read(PLANNING_JS)
    last = _fn_body(js, "get projectLastActivity")
    assert "activityFeed" in last, "the narrative reads the loaded activity feed"
    assert "projectNarrative" in last, "the lazy fallback feeds the same line"
    section = _cockpit_section(_read(PROJECT_DETAIL))
    assert "Last activity" in section
    assert "user_name" in section
    assert "formatTimeAgo(projectLastActivity.created_at)" in section


def test_narrative_fallback_is_lazy_once_per_project():
    """A quiet project fetches its own last entry once (guarded)."""
    js = _read(PLANNING_JS)
    load = _fn_body(js, "loadProjectNarrative")
    assert "`/activity?project_id=${this.selectedProject.id}&limit=1`" in load
    assert "narrativeLoadedFor" in load, "no lazy-once guard"


def test_four_action_cards_with_live_counts():
    """Work / Ship / Risk & Decisions / Plan & docs, each with a count bound."""
    section = _cockpit_section(_read(PROJECT_DETAIL))
    assert "Four action cards" in section
    for label in (">Work<", ">Ship<", ">Risk & Decisions<", ">Plan & docs<"):
        assert label in section, f"action card {label} missing"
    assert "backlogItems.length" in section, "Work card count"
    assert "projectReleases.length" in section, "Ship + Plan & docs counts"
    assert "projectRiskDecisionCount" in section, "Risk & Decisions card count"


def test_work_card_uses_the_house_prefilter_pattern():
    """Work → the ONE Work view pre-filtered (setWorkProjectFilter + navigate);
    the cockpit never re-hosts the backlog or calls loadWork."""
    js = _read(PLANNING_JS)
    open_work = _fn_body(js, "openWorkWithProject")
    assert "setWorkProjectFilter(String(this.selectedProject.id))" in open_work
    assert "this.navigate('work')" in open_work
    section = _cockpit_section(_read(PROJECT_DETAIL))
    assert "openWorkWithProject()" in section
    assert "loadWork" not in section, "the cockpit must not re-host the backlog"
    assert "workItems" not in section, "the cockpit must not re-host the work board"


def test_decisions_panel_opens_with_the_project_prefilter():
    """Risk & Decisions' sub-link sets decisionProjectFilter, then navigates."""
    js = _read(PLANNING_JS)
    open_dec = _fn_body(js, "openDecisionsPanel")
    assert "decisionProjectFilter = String(this.selectedProject.id)" in open_dec
    assert "this.navigate('decisions')" in open_dec
    section = _cockpit_section(_read(PROJECT_DETAIL))
    assert "openDecisionsPanel()" in section


# ── 4. ?tab= state (URL + localStorage) ──────────────────────────────────


def test_tab_state_uses_a_hash_and_replacestate():
    """syncProjectTabUrl writes #/p/{id}/{tab} via history.replaceState."""
    js = _read(PLANNING_JS)
    sync = _fn_body(js, "syncProjectTabUrl")
    assert "history.replaceState" in sync, "tab changes must replaceState"
    assert "'#/p/'" in sync, "hash-based state"
    assert re.search(r"#\\\/p\\\/", _fn_body(js, "readProjectTabFromUrl")), \
        "readProjectTabFromUrl must parse #/p/{id}/{tab}"


def test_openproject_reads_the_tab_back_from_the_url():
    """?tab= round-trips: readProjectTabFromUrl honors the same project's tab."""
    js = _read(PLANNING_JS)
    read = _fn_body(js, "readProjectTabFromUrl")
    assert "m[1] === String(projectId)" in read, "the URL tab applies to its own project"
    assert "isValidProjectTab(m[2])" in read, "unknown tabs must be rejected"


def test_boot_deeplink_opens_a_shared_project_tab():
    """A pasted #/p/{id}/{tab} opens that project + tab after login."""
    js = _read(PLANNING_JS)
    deep = _fn_body(js, "tryProjectDeepLink")
    assert "openProjectById(projectId)" in deep
    assert "consumeProjectHash()" in deep, "the hash is consumed first (no re-fire loop)"
    assert _fn_body(js, "consumeProjectHash"), "hash consumption missing"


def test_last_visited_tab_persists_per_project():
    """localStorage map (pmo_project_tabs) is written and read back."""
    js = _read(PLANNING_JS)
    assert "'pmo_project_tabs'" in _fn_body(js, "persistProjectTab")
    assert "'pmo_project_tabs'" in _fn_body(js, "lastProjectTab")
    watchers = _fn_body(js, "bindProjectTabWatchers")
    assert "this.$watch('projectTab'" in watchers, "tab changes must persist"


def test_back_to_projects_consumes_the_hash():
    """A stale #/p/{id}/{tab} must not re-deep-link after closing a project."""
    js = _read(PLANNING_JS)
    back = _fn_body(js, "backToProjects")
    assert "consumeProjectHash()" in back


def test_removed_tab_hashes_degrade_to_the_cockpit():
    """Removed tabs (overview/vision/backlog/time/approvals) are invalid —
    the watcher resets direct assignments to the cockpit (Rethink v2 Phase E)."""
    js = _read(PLANNING_JS)
    watchers = _fn_body(js, "bindProjectTabWatchers")
    assert "isValidProjectTab(tab)" in watchers, "invalid tabs must be guarded"
    assert "this.projectTab = 'cockpit'" in watchers, "degrade to the cockpit"
    table = _loaders_table(js)
    for gone in ("overview", "vision", "backlog", "time", "approvals"):
        assert not re.search(rf"^\s+{gone}: \[", table, re.M), f"{gone} must leave the loaders map"


# ── 5. the lazy loaders ──────────────────────────────────────────────────


def test_openproject_burst_is_at_most_eight_loaders():
    """openProject keeps ONLY the cockpit's needs — 5 loader calls, not 17."""
    body = _openproject_body(_read(PLANNING_JS))
    loaders = re.findall(r"this\.(load[A-Z]\w+)\(", body)
    assert len(loaders) <= 8, f"openProject burst too big: {len(loaders)} loaders"
    assert set(loaders) == {"loadProjectHealth", "loadReleases", "loadApprovals",
                            "loadRisks", "loadBacklog"}, \
        f"unexpected cockpit loaders: {sorted(loaders)}"
    for gone in ("loadForms", "loadTraceability", "loadPersonas", "loadTestAccounts",
                 "loadInfrastructure", "loadGithubBoardConfig", "loadGithubSyncStatus",
                 "loadBrdCoverage", "loadStakeholders", "loadVision", "loadKPIs",
                 "loadRoadmaps", "loadCoverage"):
        assert f"this.{gone}(" not in body, f"{gone} still fires on openProject"


def test_every_tab_maps_to_lazy_datasets():
    """projectTabLoaders covers the v2 9 (+ the cockpit); coverage stays out of
    the burst (Rethink v2 Phase E)."""
    js = _read(PLANNING_JS)
    body = _loaders_table(js)
    for tab in ("cockpit", "kpis", "roadmap", "docs", "risks", "releases",
                "stakeholders", "infrastructure", "github", "env"):
        assert re.search(rf"^\s+{tab}: \[", body, re.M), f"no lazy datasets for {tab}"
    for gone in ("overview", "vision", "backlog", "time", "approvals"):
        assert not re.search(rf"^\s+{gone}: \[", body, re.M), f"{gone} must be gone"


def test_each_tabs_loader_fires_on_first_show():
    """ensureProjectTabData guards per dataset; runProjectTabLoader covers them."""
    js = _read(PLANNING_JS)
    ensure = _fn_body(js, "ensureProjectTabData")
    assert "projectTabLoaded[ds]" in ensure, "one lazy-once flag per dataset"
    assert "projectLoadedFor" in ensure, "flags must reset per project"
    runner = _fn_body(js, "runProjectTabLoader")
    table = _loaders_table(js)
    datasets = set(re.findall(r"'([a-zA-Z]+)'", table))
    for ds in datasets:
        assert f"case '{ds}':" in runner, f"dataset {ds} never loads"
    assert "loadCoverage" in runner, "coverage loads lazily with the cockpit"


def test_the_root_effect_wires_the_lazy_loaders():
    """The project-detail section's x-effect routes through projectRouteEffect."""
    src = _read(PROJECT_DETAIL)
    root = re.search(r'x-show="route === \'project-detail\' && selectedProject".*?>', src, re.S)
    assert root, "project-detail root missing"
    assert 'x-effect="projectRouteEffect()"' in root.group(0)


def test_lazy_loaders_keep_the_same_loader_implementations():
    """Only the TIMING changed — every loader keeps its endpoint (spot checks);
    coverage loads with the cockpit's first show (the loaders map, not an
    overview x-effect — the Overview tab folded away in Phase E)."""
    js = _read(PLANNING_JS)
    assert "async loadBrdCoverage(projectId) {" in js
    assert "`/projects/${projectId}/brd-coverage`" in js
    table = _loaders_table(js)
    cockpit = re.search(r"^\s+cockpit: \[(.*?)\]", table, re.M).group(1)
    assert "'coverage'" in cockpit, "coverage loads lazily with the cockpit"


# ── 6. B2 / C2 survival (Phase E adjusted) ───────────────────────────────


def test_b2_health_chips_survive_in_the_verdict_bar():
    """The deep-admin overview's full health card folded away — its why-chips
    data survives flattened in the cockpit's verdict bar (same payload, one
    compact row). The per-sub-score card is gone with the Overview tab."""
    src = _read(PROJECT_DETAIL)
    section = _cockpit_section(src)
    assert "Project Health Card" not in src[src.index("<!-- KPIs tab -->"):src.index("<!-- Roadmap tab -->")], \
        "the overview's health card must be gone"
    assert "projectVerdictChips" in section, "the verdict bar carries the why chips"
    js = _read(PLANNING_JS)
    chips = _fn_body(js, "get projectVerdictChips")
    assert "h.why?.schedule" in chips and "h.why?.approvals" in chips


def test_b2_coverage_card_was_absorbed_into_the_cockpit():
    """The coverage card (with its orphan chips) lives in the cockpit now —
    the orphan chips deep-link into the ONE Work view (the Backlog tab folded
    away in Phase E)."""
    src = _read(PROJECT_DETAIL)
    section = _cockpit_section(src)
    assert "KPI Coverage" in section
    assert "unlinked_sample" in section
    assert "openWorkWithProject()" in section, "orphan chips deep-link into Work"
    assert "projectTab='backlog'" not in section, "the Backlog tab is gone"
    after_cockpit = src[src.index("<!-- KPIs tab -->"):]
    assert "KPI Coverage" not in after_cockpit, "the coverage card must not duplicate"


def test_c2_backlog_rail_lives_on_the_work_board_only():
    """Phase E: the project page no longer hosts the rail-driven board — the
    x-effect and its columns are gone; the rail data flows to the Work board
    (backlog.js's buildWorkBoard keeps the rail assertions in the rail tests)."""
    src = _read(PROJECT_DETAIL)
    assert "loadBacklogRail" not in src, "the project page must not fetch the rail"
    assert "backlogBoardColumns" not in src, "the project-page board is gone"
    js = _read(PLANNING_JS)
    burst = _openproject_body(js)
    assert "loadBacklogRail" not in burst, "the rail must not join the openProject burst"


def test_cockpit_uses_the_house_palette_only():
    """Chips-not-tabs, Tailwind literal strings, the indigo→violet light tokens."""
    section = _cockpit_section(_read(PROJECT_DETAIL))
    for cls in ("surface", "rounded-2xl", "border-ink-200/60", "text-ink-800",
                "bg-amber-50", "bg-ink-100", "text-ink-500", "rounded-full"):
        assert cls in section, f"house class {cls} missing"
    assert "tab-active" not in section, "the cockpit uses cards, not tabs"
