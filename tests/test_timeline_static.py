"""Static pins for Timeline P1/P2 — release targets, drift, actuals (2026-11-25).

Pins the exact code shape so a regression reverts the test with it:

- T1  the gantt payload carries the commitment: releases[] (target_date +
      live_stage from the DYNAMIC ladder, release_lifecycle), the drift chip
      (window end vs release target) and per-item past_release flags for
      bundled items — computed in app/services/schedule.py (the ONE
      item-Gantt source, extracted from the dashboard router) and served by
      a route that only delegates.
- T2  actuals are machine-stamped: the advance machine (the ONE write
      point) stamps actual_start on the first advance and actual_end on
      Done; the release sync stamps actual_end where the software family's
      items actually reach Done. Set-when-None — never rewritten.
- T3  the columns ship through the idempotent migration (app/migrate.py
      COLUMNS entries) and the response schema — and stay OUT of
      BacklogItemUpdate (they are never user-edited).
- T4  the Work → Timeline item Gantt renders the release lane, the drift
      chip, per-row target lines, the actual bar and the legend; the
      planning domain exposes the three helpers.
- T5  the JS version pins bump together (house cache-bust rule) —
      enforced by test_css_version_parity + test_v1_version_pins_bump_together
      against the JS_VERSION constant here.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DASHBOARD_PY = REPO / "app/routers/dashboard.py"
SCHEDULE_PY = REPO / "app/services/schedule.py"
RELEASE_MACHINE_PY = REPO / "app/services/release_machine.py"
RELEASES_PY = REPO / "app/routers/releases.py"
MIGRATE_PY = REPO / "app/migrate.py"
BACKLOG_SCHEMAS_PY = REPO / "app/schemas/backlog.py"
WORK_HTML = REPO / "app/templates/pmo/views/work.html"
PLANNING_JS = REPO / "app/static/js/app/domains/planning.js"
APP_JS = REPO / "app/static/js/app/pmo-app.js"
INDEX_HTML = REPO / "app/templates/index.html"

JS_VERSION = "20261126a"


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


# ── T1 — the gantt payload carries the commitment ─────────────────────────


def test_t1_route_delegates_to_the_one_schedule_source():
    """The dashboard route keeps only the tenant scoping + 404 — the compute
    lives once in app/services/schedule.py (no third copy)."""
    body = _route_body(_read(DASHBOARD_PY), "project_gantt")
    assert "schedule_service.project_schedule(" in body, (
        "the route must delegate to the ONE schedule source"
    )
    assert "raise HTTPException(status_code=404" in body, "the 404 stays in the route"


def test_t1_gantt_lists_releases_with_the_dynamic_ladder():
    """Releases were invisible on the item Gantt — the payload must carry
    them with the DYNAMIC ladder's live_stage (release_lifecycle)."""
    body = _route_body(_read(SCHEDULE_PY), "project_schedule")
    assert "release_lifecycle(" in body, "the ladder must resolve dynamically"
    assert "live_stage" in body, "release rows must carry the live_stage"
    assert "Release.project_id == project_id" in body, "releases must scope to the project"
    assert "tenant_scoped(db, Release, tenant_id)" in body, "releases must scope to the tenant (the ONE scoping seam)"


def test_t1_gantt_computes_the_drift_chip():
    """The plan-vs-commitment drift was unflagged — window end vs target."""
    body = _route_body(_read(SCHEDULE_PY), "project_schedule")
    assert "window_end - release_targets[r.id]" in body, (
        "the drift compares the plan's last day against the release target"
    )
    assert '"drift_days"' in body, "the drift chip carries its size in days"
    assert "date_type.fromisoformat" in body, "free-text targets must not crash the parse"


def test_t1_gantt_flags_items_past_their_release():
    """Per-item drift: bundled items running past the release target."""
    body = _route_body(_read(SCHEDULE_PY), "project_schedule")
    assert "ReleaseItem" in body, "item drift reads the release_items link"
    assert '"past_release"' in body, "items carry the drift flag"
    assert "it.end_date > target" in body, "the flag compares the item's end to the target"


def test_t1_gantt_payload_keys_are_stable():
    """Empty projects keep the contract — releases/drift keys always exist."""
    body = _route_body(_read(SCHEDULE_PY), "project_schedule")
    assert '"releases": release_rows' in body and '"drift": drift' in body, (
        "the gantt payload must always carry releases + drift"
    )
    assert '"releases": [],' in body and '"drift": None,' in body, (
        "the empty-window early return keeps the same keys"
    )


# ── T2 — actuals are machine-stamped ──────────────────────────────────────


def test_t2_advance_machine_stamps_actual_start():
    """The advance machine is the ONE write point — first advance stamps
    the actual start."""
    body = _route_body(_read(RELEASE_MACHINE_PY), "advance_backlog_item_phase")
    assert "item.actual_start_date is None" in body, "set-when-None: never rewritten"
    assert "item.actual_start_date = today" in body, "first advance stamps the start"


def test_t2_advance_machine_stamps_actual_end_on_done():
    """Reaching Done stamps the actual end (operations ladder's terminal
    item phase, or a status a prior write already set)."""
    body = _route_body(_read(RELEASE_MACHINE_PY), "advance_backlog_item_phase")
    assert '(item.status == "Done" or item.current_phase == "Done")' in body, (
        "the end stamps when the item reaches Done"
    )
    assert "item.actual_end_date = today" in body


def test_t2_release_sync_stamps_actual_end():
    """The software family's items reach Done in the release sync — its
    twin stamp. Without it baseline-vs-actual never completes on live data."""
    body = _route_body(_read(RELEASES_PY), "_sync_release_items_to_phase")
    assert "item.actual_end_date is None" in body, "set-when-None"
    assert "item.actual_end_date =" in body, "Done items stamp their actual end"


# ── T3 — the columns ship through the migration + response schema ─────────


def test_t3_migration_adds_the_actual_columns():
    """Idempotent ALTERs follow the house COLUMNS pattern."""
    src = _read(MIGRATE_PY)
    assert '("backlog_items", "actual_start_date DATE")' in src
    assert '("backlog_items", "actual_end_date DATE")' in src


def test_t3_model_declares_the_actual_columns():
    from app.models.backlog_item import BacklogItem

    assert "actual_start_date" in BacklogItem.__table__.columns
    assert "actual_end_date" in BacklogItem.__table__.columns


def test_t3_response_schema_carries_actuals():
    src = _read(BACKLOG_SCHEMAS_PY)
    assert "actual_start_date: date | None = None" in src
    assert "actual_end_date: date | None = None" in src


def test_t3_update_schema_stays_machine_only():
    """Actuals are never user-edited — BacklogItemUpdate must not accept them."""
    src = _read(BACKLOG_SCHEMAS_PY)
    m = re.search(r"^class BacklogItemUpdate\(BaseModel\).*?(?=^class |\Z)", src, re.S | re.M)
    assert m, "BacklogItemUpdate missing"
    assert "actual_start_date" not in m.group(0), "actuals are machine-stamped, not edited"
    assert "actual_end_date" not in m.group(0), "actuals are machine-stamped, not edited"


# ── T4 — the item Gantt renders the commitment + the actuals ──────────────


def test_t4_work_gantt_renders_the_drift_chip():
    src = _read(WORK_HTML)
    assert 'x-show="ganttDrift()"' in src, "the drift chip renders on the header"
    assert "ganttDrift()?.drift_days" in src, "the chip shows the drift size"


def test_t4_work_gantt_renders_the_release_lines():
    src = _read(WORK_HTML)
    assert "ganttReleaseLines()" in src, "release targets render on the gantt"
    assert ">Releases</span>" in src, "a labeled release lane sits under the day header"
    assert "border-violet-400" in src, "target lines are visually distinct from bars"


def test_t4_work_gantt_renders_baseline_vs_actual():
    src = _read(WORK_HTML)
    assert "ganttActualBar(it)" in src, "the actual bar overlays the planned bar"
    assert "it.actual_start_date" in src, "the bar reads the machine-stamped actuals"
    assert ">Actual</span>" in src, "the legend names the actual bar"


def test_t4_planning_helpers_exist():
    src = _read(PLANNING_JS)
    for name in ("ganttReleaseLines", "ganttDrift", "ganttActualBar"):
        body = _fn_body(src, name)
        assert body, f"{name} missing"


# ── T5 — the version pins bump together ───────────────────────────────────


def test_t5_version_pins_bump_together():
    app_js = _read(APP_JS)
    js_versions = set(re.findall(r"from '\./[a-z_/]+\.js\?v=([a-z0-9]+)'", app_js))
    assert js_versions == {JS_VERSION}, f"the JS graph must pin {JS_VERSION}, found {js_versions}"
    index = _read(INDEX_HTML)
    link = re.search(r"tailwind\.compiled\.css\?v=([a-z0-9]+)", index)
    assert link and link.group(1) == JS_VERSION, "the CSS link pin must match the JS version"
