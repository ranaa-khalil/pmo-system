"""Copilot P1 — schedule-aware ask (TDD).

The ask rung was blind to the schedule: build_context had no gantt/CPM, no
release windows, no planned-vs-target drift, so "what's blocking the
release?" was answered from phases and statuses only. The schedule block
reads the SAME compute the Gantt API serves (app/services/schedule.py —
planned windows, CPM critical path, release targets, drift) and is
ADDITIONAL grounded context: entries carry entity_type/entity_id so answers
still cite "Item 3"/"Release 1", and computed states are labeled computed
(zero-float CPM, plan-vs-target comparison — not manual flags).
"""
from datetime import date

import pytest

import app.models  # noqa: F401 — register all models
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.release import Release
from app.models.tenant import Tenant
from app.models.user import User
from app.services.copilot import build_context, summarize_context


def _iso(day: int) -> str:
    return f"2026-11-{day:02d}"


@pytest.fixture()
def world(db):
    """A tenant, a PM, and a scheduled project: A → B → C chain (critical),
    a parallel floater X, an undated item U, and a release past its target."""
    tenant = Tenant(name="Schedule Test Co", slug="schedule-test-co")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    pm = User(email="pm@schedule.test", name="PM", hashed_password="x")
    dev = User(email="dev@schedule.test", name="Dev", hashed_password="x")
    db.add_all([pm, dev])
    db.commit()
    db.refresh(pm)

    p1 = Project(name="PNU Cloud", client_id=1, tenant_id=tenant.id, project_manager_id=pm.id)
    p2 = Project(name="CloudGate", client_id=1, tenant_id=tenant.id, project_manager_id=pm.id)
    db.add_all([p1, p2])
    db.commit()
    db.refresh(p1)

    a = BacklogItem(tenant_id=tenant.id, project_id=p1.id, title="SSO login",
                    epic="Auth", current_phase="Development", status="In Progress",
                    start_date=date(2026, 11, 1), end_date=date(2026, 11, 3))
    b = BacklogItem(tenant_id=tenant.id, project_id=p1.id, title="SSO UI",
                    epic="Auth", current_phase="Requirements", status="Draft",
                    start_date=date(2026, 11, 4), end_date=date(2026, 11, 6))
    c = BacklogItem(tenant_id=tenant.id, project_id=p1.id, title="SSO release prep",
                    epic="Auth", current_phase="Requirements", status="Draft",
                    start_date=date(2026, 11, 7), end_date=date(2026, 11, 9))
    x = BacklogItem(tenant_id=tenant.id, project_id=p1.id, title="Billing page",
                    epic="Billing", current_phase="Requirements", status="Draft",
                    start_date=date(2026, 11, 4), end_date=date(2026, 11, 6))
    u = BacklogItem(tenant_id=tenant.id, project_id=p1.id, title="Undated idea",
                    epic="Parking", current_phase="Requirements", status="Draft")
    db.add_all([a, b, c, x, u])
    db.commit()
    for item in (a, b, c, x, u):
        db.refresh(item)
    b.depends_on.append(a)
    c.depends_on.append(b)
    x.depends_on.append(a)
    db.commit()

    # Release bundled to the project: target BEFORE the plan's last end
    # (Nov 9) — the plan-vs-commitment drift the ask must see.
    rel = Release(tenant_id=tenant.id, project_id=p1.id, version="1.0.0",
                  name="PNU Cloud", target_date=_iso(5))
    db.add(rel)
    db.commit()
    db.refresh(rel)

    return {"tenant": tenant, "pm": pm, "dev": dev, "p1": p1, "p2": p2,
            "a": a, "b": b, "c": c, "x": x, "u": u, "rel": rel}


def test_scoped_context_includes_schedule_block(db, world):
    """project_id set → the context carries the project's schedule block."""
    ctx = build_context(db, world["pm"], world["tenant"], project_id=world["p1"].id)
    s = ctx["schedule"]
    assert s is not None
    assert s["entity_type"] == "project" and s["entity_id"] == world["p1"].id
    assert s["window_start"] == "2026-11-01"
    assert s["window_end"] == "2026-11-09"
    assert s["planned_finish"] == "2026-11-09"
    assert s["unscheduled_count"] == 1  # the undated item, never guessed
    assert s["critical_count"] == 3     # A → B → C chain, zero float


def test_schedule_block_carries_critical_items_with_sources(db, world):
    """Grounding rule: critical items are typed entries, never bare ids."""
    ctx = build_context(db, world["pm"], world["tenant"], project_id=world["p1"].id)
    items = ctx["schedule"]["critical_items"]
    ids = {i["entity_id"] for i in items}
    assert {world["a"].id, world["b"].id, world["c"].id} <= ids
    assert world["x"].id not in ids  # the floater has float — not critical
    for i in items:
        assert i["entity_type"] == "backlog_item"
        assert i["record_type"] == "Item"
        assert i["title"] and i["phase"]


def test_schedule_block_carries_release_drift(db, world):
    """Release windows + drift: the plan runs past the target."""
    ctx = build_context(db, world["pm"], world["tenant"], project_id=world["p1"].id)
    releases = ctx["schedule"]["releases"]
    assert len(releases) == 1
    r = releases[0]
    assert r["entity_type"] == "release" and r["entity_id"] == world["rel"].id
    assert r["target_date"] == _iso(5)
    assert r["drift_days"] == 4  # plan ends Nov 9, target Nov 5
    assert "live_stage" in r and "status" in r


def test_future_target_has_no_drift(db, world):
    """A target the plan meets early drifts nothing — no invented drift."""
    world["rel"].target_date = "2027-01-31"
    db.commit()
    ctx = build_context(db, world["pm"], world["tenant"], project_id=world["p1"].id)
    assert ctx["schedule"]["releases"][0]["drift_days"] is None


def test_unscheduled_project_schedule_is_empty_not_guessed(db, world):
    """No dated items → an empty block, never a guessed window."""
    ctx = build_context(db, world["pm"], world["tenant"], project_id=world["p2"].id)
    s = ctx["schedule"]
    assert s is not None
    assert s["planned_finish"] is None
    assert s["critical_items"] == []
    assert s["critical_count"] == 0
    assert s["unscheduled_count"] == 0  # p2 has no items at all


def test_portfolio_context_includes_compact_schedules(db, world):
    """No project open → one compact schedule line per assigned project."""
    ctx = build_context(db, world["pm"], world["tenant"])
    schedules = ctx["schedules"]
    assert schedules and ctx["schedule"] is None
    ids = {s["entity_id"] for s in schedules}
    assert {world["p1"].id, world["p2"].id} <= ids
    p1_block = next(s for s in schedules if s["entity_id"] == world["p1"].id)
    assert p1_block["planned_finish"] == "2026-11-09"
    assert p1_block["releases"][0]["drift_days"] == 4


@pytest.fixture()
def foreign_project(db, world):
    """A project in ANOTHER tenant — invisible to world['pm'] and world['dev']."""
    other = Tenant(name="Other Tenant", slug="other-tenant")
    db.add(other)
    db.commit()
    db.refresh(other)
    p = Project(name="Secret Project", client_id=1, tenant_id=other.id)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def test_foreign_project_yields_no_schedule(db, world, foreign_project):
    """A project the user can't see is an empty context — schedule included."""
    ctx = build_context(db, world["pm"], world["tenant"], project_id=foreign_project.id)
    assert ctx["schedule"] is None
    assert ctx["projects"] == []


def test_every_schedule_entry_has_a_source(db, world):
    ctx = build_context(db, world["pm"], world["tenant"], project_id=world["p1"].id)
    s = ctx["schedule"]
    for entry in (s["critical_items"] + s["releases"]):
        assert "entity_type" in entry and "entity_id" in entry


# ── summarize_context renders the schedule for the LLM prompt ─────────────


def test_summary_renders_the_schedule_section(db, world):
    ctx = build_context(db, world["pm"], world["tenant"], project_id=world["p1"].id)
    text = summarize_context(ctx)
    assert "PROJECT SCHEDULE" in text
    assert "computed from the item Gantt" in text      # labeled as computed
    assert "not manual flags" in text
    assert "planned finish 2026-11-09" in text
    assert "unscheduled items: 1" in text


def test_summary_cites_critical_items_and_drift(db, world):
    ctx = build_context(db, world["pm"], world["tenant"], project_id=world["p1"].id)
    text = summarize_context(ctx)
    assert "critical path (3 items, zero float)" in text
    assert f"Item {world['a'].id}: SSO login" in text   # typed, never bare id
    assert f"Release {world['rel'].id}" in text
    assert "target 2026-11-05" in text
    assert "4 days past the release target" in text


def test_summary_portfolio_renders_schedule_lines(db, world):
    ctx = build_context(db, world["pm"], world["tenant"])
    text = summarize_context(ctx)
    assert "SCHEDULE PER PROJECT" in text
    assert "computed from the item Gantt" in text
    assert "planned finish 2026-11-09" in text
    assert "4 days past the target" in text


def test_summary_without_schedule_stays_clean(db, world, foreign_project):
    """A context with no schedule (foreign project) doesn't render one."""
    ctx = build_context(db, world["pm"], world["tenant"], project_id=foreign_project.id)
    assert "PROJECT SCHEDULE" not in summarize_context(ctx)


def test_prompt_window_wording_notes_the_plan_vs_target(db, world):
    """The drift line names both sides: the plan's finish and the target."""
    ctx = build_context(db, world["pm"], world["tenant"], project_id=world["p1"].id)
    text = summarize_context(ctx)
    assert "planned window 2026-11-01 → 2026-11-09" in text
