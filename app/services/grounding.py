"""Grounding bundles — the deterministic data spine under every copilot answer.

Rethink slice 2 (AI & Copilot Rethink §7, Layer 1): pure services shaped like
app/services/schedule.py — deterministic, LLM-free, tenant-scoped through the
ONE seam (app/services/scope.py), returning RECORDS not prose. Every record
carries entity_type/entity_id/title (+ computed fields) so answers cite real
records; counts{} carries the shape of the data and notes[] the computed-state
labels.

Bundles (call order = BUNDLES):
  - project_health      identity + per-project schedule + aging items +
                        overdue tasks + predictive flags
  - release_readiness   gate deliverables + pending approvals + incomplete
                        release items + plan-vs-target drift (schedule.py)
  - risk_exposure       UNCAPPED open risks (the old 15-cap lived only in
                        build_context's prompt view)
  - stakeholder_map     stakeholders with RACI roles per project
  - backlog_shape       epic → features tree + shape counts

Bundle contract (§7): {bundle, scope, records[], counts{}, notes[]} — records[]
is the flat entity-backed view (every record: entity_type/entity_id/title +
a "section" tag); "sections" is an additive key: the legacy build_context
sections the facade assembles from (services/copilot.py build_context is a
facade over these bundles, byte-identical payload). Every entity read goes
through tenant_scoped() — this extraction is the RLS tightening point; the
only hand-written queries left are the seam's documented exclusions (column
tuple-rows, the global users table) plus one explicit tenant filter on the
activity-log movement scan, whose entity ids are per-table and collide across
tenants.
"""
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog
from app.models.approval import ApprovalRequest, ApprovalStep
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.release import Release, ReleaseItem
from app.models.risk import PROBABILITY_LEVELS, SEVERITY_LEVELS, Risk
from app.models.stakeholder import Stakeholder
from app.models.user import User
from app.models.user_task import UserTask
from app.services.scope import tenant_scoped

# Bundle registry — the names copilot_chat routes to (intent rules + facade).
BUNDLES = (
    "project_health",
    "release_readiness",
    "risk_exposure",
    "stakeholder_map",
    "backlog_shape",
)

# Items sitting in a phase longer than this are "aging" (carved from
# services/copilot.py — same threshold, same entries).
AGING_THRESHOLD_DAYS = 7

# Task statuses that make a task live/overdue-able (carved verbatim).
OVERDUE_STATUSES = ["Pending", "In Progress"]

# Backlog item statuses that mean the work is complete (release readiness).
DONE_STATUSES = ("Done", "Approved")

# The legacy build_context cap on the prompt view of open risks (the facade
# keeps byte-identical context; the risk_exposure BUNDLE itself is uncapped).
LEGACY_RISK_CAP = 15


# ── Scope resolution ──────────────────────────────────────────────────────


def assigned_project_ids(db: Session, user: User | None, tenant) -> list[int]:
    """Projects where the user is PM or holds a RACI role assignment —
    same filtering as app/routers/dashboard.py (carved from services/copilot.py)."""
    from app.models.role_assignment import RoleAssignment

    if user is None:
        return []
    tid = tenant.id
    ids: set[int] = set()
    for (pid,) in db.query(Project.id).filter(
        Project.tenant_id == tid, Project.project_manager_id == user.id,
    ).all():
        ids.add(pid)
    for (pid,) in db.query(RoleAssignment.project_id).filter(
        RoleAssignment.user_id == user.id,
    ).all():
        p = tenant_scoped(db, Project, tid).filter(Project.id == pid).first()
        if p:
            ids.add(pid)
    return sorted(ids)


def resolve_project_ids(db: Session, user: User | None, tenant, project_id: int | None) -> list[int]:
    """The bundle scope: one visible project, or every assigned project.

    A project_id the user can't see (other tenant) yields [] — the same
    empty-context rule build_context always applied."""
    if project_id is not None:
        project = tenant_scoped(db, Project, tenant.id).filter(
            Project.id == project_id,
        ).first()
        return [project.id] if project else []
    return assigned_project_ids(db, user, tenant)


# ── Bundle dispatcher ─────────────────────────────────────────────────────


def get_bundle(
    db: Session,
    name: str,
    user: User | None,
    tenant,
    project_ids: list[int],
    project_id: int | None = None,
) -> dict:
    """Run one grounding bundle by name. Unknown names raise ValueError."""
    builder = _BUILDERS.get(name)
    if builder is None:
        raise ValueError(f"Unknown grounding bundle: {name}")
    return builder(db, user, tenant, project_ids, project_id=project_id)


def get_bundles(
    db: Session,
    names: list[str],
    user: User | None,
    tenant,
    project_ids: list[int],
    project_id: int | None = None,
) -> list[dict]:
    """Run the named bundles in registry order (deduped, unknown names skipped)."""
    wanted = [n for n in BUNDLES if n in set(names)]
    return [
        get_bundle(db, name, user, tenant, project_ids, project_id=project_id)
        for name in wanted
    ]


# ── Assembly + views ──────────────────────────────────────────────────────


def assemble(bundles: list[dict]) -> dict:
    """Merge bundle sections into the legacy build_context dict shape.

    The facade contract: same keys, same shapes, same ordering the copilot
    prompt/citation code has always consumed. open_risks keeps the legacy
    15-cap here (prompt view); the risk_exposure bundle's records stay
    uncapped for the digest renderer.
    """
    ctx = {
        "projects": [], "project_identity": None, "portfolio_identity": None,
        "pending_approvals": [], "aging_items": [], "overdue_tasks": [],
        "at_risk_releases": [], "open_risks": [], "predictive_flags": [],
        "epic_tree": {}, "schedule": None, "schedules": [],
    }
    for bundle in bundles:
        sections = bundle.get("sections") or {}
        for key in ("projects", "pending_approvals", "aging_items",
                    "overdue_tasks", "at_risk_releases", "predictive_flags"):
            ctx[key] = ctx[key] + list(sections.get(key) or [])
        ctx["open_risks"] = (ctx["open_risks"] + list(sections.get("open_risks") or []))[:LEGACY_RISK_CAP]
        if sections.get("project_identity") is not None and ctx["project_identity"] is None:
            ctx["project_identity"] = sections["project_identity"]
        if sections.get("portfolio_identity"):
            ctx["portfolio_identity"] = list(sections["portfolio_identity"])
        if sections.get("epic_tree"):
            ctx["epic_tree"].update(sections["epic_tree"])
        if sections.get("schedule") is not None and ctx["schedule"] is None:
            ctx["schedule"] = sections["schedule"]
        if sections.get("schedules"):
            ctx["schedules"] = ctx["schedules"] + list(sections["schedules"])
    return ctx


def bundle_records(bundles: list[dict]) -> list[dict]:
    """Flat entity-backed records across bundles — every record carries
    entity_type/entity_id/title (+ its section tag). Records that are shells
    without ids (epic nodes, predictive flags) stay out of the flat view."""
    records: list[dict] = []
    for bundle in bundles:
        records.extend(bundle.get("records") or [])
    return records


def bundle_registry(bundles: list[dict]) -> dict:
    """(entity_type, entity_id) → record for every entry in the given bundles —
    the validation registry for answers rendered from them (same shape
    services/copilot.py _context_registry produces)."""
    registry: dict = {}
    for record in bundle_records(bundles):
        etype, eid = record.get("entity_type"), record.get("entity_id")
        if etype is None or eid is None:
            continue
        registry.setdefault(
            (etype, eid),
            {
                "entity_type": etype,
                "entity_id": eid,
                "title": record.get("title") or "",
                "project_id": record.get("project_id"),
            },
        )
    return registry


# ── Bundle builders ───────────────────────────────────────────────────────


def project_health(
    db: Session, user: User | None, tenant, project_ids: list[int],
    project_id: int | None = None,
) -> dict:
    """Identity + per-project schedule + aging items + overdue tasks +
    predictive flags — the orientation bundle."""
    tid = tenant.id
    uid = user.id if user is not None else None
    sections = {
        "projects": [], "project_identity": None, "portfolio_identity": None,
        "aging_items": [], "overdue_tasks": [], "predictive_flags": [],
        "schedule": None, "schedules": [],
    }

    if not project_ids:
        return _shell("project_health", user, tenant, project_ids, project_id,
                      sections=sections,
                      counts={"projects": 0, "aging_items": 0, "overdue_tasks": 0,
                              "critical_items": 0, "unscheduled_items": 0,
                              "predictive_flags": 0},
                      notes=["no assigned projects — nothing is visible to the copilot"])

    projects = tenant_scoped(db, Project, tid).filter(
        Project.id.in_(project_ids),
    ).order_by(Project.id).all()

    sections["projects"] = [
        {"entity_type": "project", "entity_id": p.id, "title": p.name, "status": p.status}
        for p in projects
    ]

    # ── Project identity: what the copilot needs to be project-specific ───
    if project_id is not None:
        # Scoped: full identity for the one project the user has open.
        sections["project_identity"] = _identity_for(db, projects[0], with_activity=True)
    else:
        # Portfolio: identity for EVERY assigned project (up to 5) so the
        # copilot is relevant across the whole portfolio — not just the
        # first-assigned project. Features summary comes from the backlog.
        sections["portfolio_identity"] = [_identity_for(db, p, with_activity=False) for p in projects[:5]]

    # ── Aging items: last movement per item from the activity log ────────
    aging_items = []
    items = tenant_scoped(db, BacklogItem, tid).filter(
        BacklogItem.project_id.in_(project_ids),
        BacklogItem.status.in_(["In Progress", "Blocked", "Draft"]),
    ).all()
    last_movement = {}
    # entity_id is a per-table id and collides across tenants — the tenant
    # filter here is the tightening this extraction adds (column tuple-row
    # queries are otherwise a documented seam exclusion).
    for (entity_id, latest) in db.query(
        ActivityLog.entity_id, ActivityLog.created_at,
    ).filter(
        ActivityLog.tenant_id == tid,
        ActivityLog.entity_type == "backlog_item",
        ActivityLog.action.in_(["advanced", "updated", "assigned"]),
    ).order_by(ActivityLog.created_at.desc()).all():
        if entity_id not in last_movement:
            last_movement[entity_id] = latest

    for item in items:
        last = last_movement.get(item.id) or item.created_at
        days = _days_since(last)
        if days >= AGING_THRESHOLD_DAYS:
            aging_items.append({
                "entity_type": "backlog_item", "entity_id": item.id,
                "title": item.title, "project_id": item.project_id,
                "phase": item.current_phase, "status": item.status,
                "epic": item.epic, "days_in_phase": days,
            })
    aging_items.sort(key=lambda e: -e["days_in_phase"])
    sections["aging_items"] = aging_items

    # ── Overdue tasks assigned to this user ──────────────────────────────
    today = date.today()
    task_query = tenant_scoped(db, UserTask, tid).filter(
        UserTask.status.in_(OVERDUE_STATUSES),
        UserTask.project_id.in_(project_ids),
    )
    if user is not None:
        task_query = task_query.filter(UserTask.assigned_to == uid)
    tasks = task_query.all()
    overdue_tasks = []
    for t in tasks:
        if t.due_date:
            try:
                due = t.due_date if isinstance(t.due_date, date) else date.fromisoformat(str(t.due_date))
            except ValueError:
                continue
            if due < today:
                overdue_tasks.append({
                    "entity_type": "user_task", "entity_id": t.id,
                    "record_type": "Task",
                    "title": t.title, "project_id": t.project_id,
                    "due_date": str(t.due_date), "days_overdue": (today - due).days,
                    "status": t.status, "priority": t.priority,
                })
    overdue_tasks.sort(key=lambda e: -e["days_overdue"])
    sections["overdue_tasks"] = overdue_tasks

    # ── Schedule (Copilot P1): the ask sees the item Gantt ───────────────
    # The SAME compute the Gantt API serves (app/services/schedule.py) —
    # planned windows, CPM critical path, release targets and the
    # plan-vs-target drift. ADDITIONAL grounded context: entries carry
    # entity_type/entity_id so answers still cite "Item 3"/"Release 1".
    if project_id is not None:
        sections["schedule"] = _schedule_for(db, projects[0], tid)
    else:
        sections["schedules"] = [_schedule_for(db, p, tid) for p in projects[:5]]

    # ── Predictive flags (P3): KPI off-target / deteriorating trend ──────
    # Derived on read from KPI.current_value + KpiHistory — template-aware
    # kind (drift for AI, spend for marketing, capacity for operations).
    from app.services import predictive
    predictive_flags = predictive.predictive_flags(db, tenant, project_ids)
    sections["predictive_flags"] = predictive_flags

    schedules = ([sections["schedule"]] if sections["schedule"] else []) + list(sections["schedules"])
    counts = {
        "projects": len(projects),
        "aging_items": len(aging_items),
        "overdue_tasks": len(overdue_tasks),
        "critical_items": sum(s.get("critical_count", 0) for s in schedules),
        "unscheduled_items": sum(s.get("unscheduled_count", 0) for s in schedules),
        "predictive_flags": len(predictive_flags),
    }
    notes = [
        "critical path is CPM (zero float against planned windows) — computed, never a manual flag",
        f"aging = {AGING_THRESHOLD_DAYS}+ days since last movement",
        "overdue = due date in the past on a Pending/In Progress task",
        "predictive flags are computed from KPI values + history",
    ]
    bundle = _shell("project_health", user, tenant, project_ids, project_id,
                    sections=sections, counts=counts, notes=notes)
    bundle["records"] = _flatten(sections)
    return bundle


def release_readiness(
    db: Session, user: User | None, tenant, project_ids: list[int],
    project_id: int | None = None,
) -> dict:
    """Gate deliverables + pending approvals + incomplete release items +
    plan-vs-target drift — the release-check bundle."""
    tid = tenant.id
    today = date.today()
    sections = {
        "pending_approvals": [], "at_risk_releases": [],
        "release_items": [], "release_drift": [], "gate_deliverables": {},
    }

    if not project_ids:
        return _shell("release_readiness", user, tenant, project_ids, project_id,
                      sections=sections,
                      counts={"pending_approvals": 0, "at_risk_releases": 0,
                              "incomplete_items": 0, "drifted_releases": 0},
                      notes=["no assigned projects — nothing is visible to the copilot"])

    # ── Pending approvals in the user's projects ─────────────────────────
    approvals = tenant_scoped(db, ApprovalRequest, tid).filter(
        ApprovalRequest.status == "Pending",
        ApprovalRequest.project_id.in_(project_ids),
    ).order_by(ApprovalRequest.id.desc()).all()

    pending_approvals = []
    for a in approvals:
        step = tenant_scoped(db, ApprovalStep, tid).filter(
            ApprovalStep.request_id == a.id,
            ApprovalStep.status == "Pending",
        ).order_by(ApprovalStep.step_order).first()
        pending_approvals.append({
            "entity_type": "approval_request", "entity_id": a.id,
            "record_type": "Approval",
            "title": a.title, "project_id": a.project_id,
            "request_type": a.request_type, "target_phase": a.target_phase,
            "awaiting_role": step.role_name if step else None,
            "days_pending": _days_since(a.created_at),
        })
    sections["pending_approvals"] = pending_approvals

    # ── At-risk releases: pending approval or past target date ───────────
    # Ladder-aware filter (the dynamic release lifecycle): a release is a
    # candidate unless its phase is in ITS OWN project's ladder done-set —
    # the old hardcoded V-cycle statuses made a template-stage release
    # invisible to at-risk. Releases per tenant are few and the built-in
    # lookups are dict hits, so this stays a Python-side filter.
    at_risk_releases = []
    releases = tenant_scoped(db, Release, tid).filter(
        Release.project_id.in_(project_ids),
    ).all()
    done_cache: dict = {}
    projects_by_id = {}
    if releases:
        projects_by_id = {
            p.id: p for p in tenant_scoped(db, Project, tid).filter(
                Project.id.in_({r.project_id for r in releases}),
            ).all()
        }
    from app.services.lifecycle import release_done_phases
    for rel in releases:
        if rel.status == "Cancelled":
            continue  # terminal, outside the gate path
        p_type = getattr(projects_by_id.get(rel.project_id), "project_type", None)
        if p_type not in done_cache:
            done_cache[p_type] = release_done_phases(db, tid, p_type)
        if rel.status in done_cache[p_type]:
            continue  # shipped (at its ladder's live stage or beyond)
        reasons = []
        if rel.target_date:
            try:
                target = rel.target_date if isinstance(rel.target_date, date) else date.fromisoformat(str(rel.target_date))
                if target < today:
                    reasons.append(f"target date {rel.target_date} passed")
            except ValueError:
                pass
        if any(a["project_id"] == rel.project_id for a in pending_approvals):
            reasons.append("has a pending gate approval")
        if reasons:
            at_risk_releases.append({
                "entity_type": "release", "entity_id": rel.id,
                "record_type": "Release",
                "title": f"{rel.version} {rel.name}".strip(),
                "project_id": rel.project_id, "status": rel.status,
                "reasons": reasons,
            })
    sections["at_risk_releases"] = at_risk_releases

    # ── Gate deliverables: what the lifecycle says the gate needs ────────
    # Template data, not entity records — it rides sections + the release
    # records as the readiness checklist per gate phase.
    from app.services.lifecycle import gate_deliverables
    gate_map: dict = {}
    for p_type in sorted({getattr(p, "project_type", None) for p in projects_by_id.values()}, key=lambda t: str(t or "")):
        gate_map[str(p_type or "")] = gate_deliverables(p_type)
    for rel in at_risk_releases:
        project = projects_by_id.get(rel["project_id"])
        checklist = gate_map.get(str(getattr(project, "project_type", None) or ""))
        if checklist:
            rel["gate_deliverables"] = checklist.get(rel.get("target_phase") or rel["status"], None)
    sections["gate_deliverables"] = gate_map

    # ── Incomplete release items: the bundled work not done yet ──────────
    release_items = []
    if releases:
        rows = (
            tenant_scoped(db, ReleaseItem, tid)
            .filter(ReleaseItem.release_id.in_([r.id for r in releases]))
            .all()
        )
        item_ids = {ri.backlog_item_id for ri in rows}
        items_by_id = {}
        if item_ids:
            items_by_id = {
                i.id: i for i in tenant_scoped(db, BacklogItem, tid).filter(
                    BacklogItem.id.in_(item_ids),
                ).all()
            }
        for ri in rows:
            item = items_by_id.get(ri.backlog_item_id)
            if item is None or item.status in DONE_STATUSES:
                continue
            release_items.append({
                "entity_type": "release_item", "entity_id": ri.id,
                "record_type": "Item",
                "title": item.title,
                "release_id": ri.release_id,
                "backlog_item_id": item.id,
                "status": item.status,
                "phase": item.current_phase,
                "project_id": item.project_id,
            })
    sections["release_items"] = release_items

    # ── Drift: the plan-vs-target comparison from app/services/schedule.py ─
    drift_rows = []
    drifted = 0
    from app.services.schedule import project_schedule
    drift_projects = sorted({rel.project_id for rel in releases})[:5]
    for pid in drift_projects:
        project = projects_by_id.get(pid)
        gantt = project_schedule(db, pid, tid, getattr(project, "project_type", None))
        for r in gantt.get("releases", []):
            if not r.get("drift_days"):
                continue
            drifted += 1
            drift_rows.append({
                "entity_type": "release", "entity_id": r["id"],
                "record_type": "Release",
                "title": f"{r['version']} {r['name']}".strip(),
                "status": r["status"], "target_date": r["target_date"],
                "drift_days": r["drift_days"], "live_stage": r["live_stage"],
                "project_id": pid,
            })
    sections["release_drift"] = drift_rows

    counts = {
        "pending_approvals": len(pending_approvals),
        "at_risk_releases": len(at_risk_releases),
        "incomplete_items": len(release_items),
        "drifted_releases": drifted,
    }
    notes = [
        "at-risk is computed (overdue target or pending gate) — never a manual flag",
        "drift compares the plan's last end date with the release target (CPM compute, not manual)",
        f"incomplete = a bundled item whose status is not in {DONE_STATUSES}",
    ]
    bundle = _shell("release_readiness", user, tenant, project_ids, project_id,
                    sections=sections, counts=counts, notes=notes)
    bundle["records"] = _flatten(sections)
    return bundle


def risk_exposure(
    db: Session, user: User | None, tenant, project_ids: list[int],
    project_id: int | None = None,
) -> dict:
    """UNCAPPED open risks with computed scores — the exposure bundle."""
    tid = tenant.id
    sections = {"open_risks": []}

    if not project_ids:
        return _shell("risk_exposure", user, tenant, project_ids, project_id,
                      sections=sections,
                      counts={"open_risks": 0, "high_risks": 0, "by_status": {}},
                      notes=["no assigned projects — nothing is visible to the copilot"])

    # UNCAPPED on purpose: the old .limit(15) hid the tail of the register.
    # (The legacy cap lives only in build_context's assembled prompt view.)
    risks = tenant_scoped(db, Risk, tid).filter(
        Risk.project_id.in_(project_ids),
        Risk.status != "Closed",
    ).order_by(Risk.id.desc()).all()
    open_risks = []
    for r in risks:
        score = _risk_score(r.severity, r.probability)
        open_risks.append({
            "entity_type": "risk", "entity_id": r.id,
            "record_type": "Risk",
            "title": r.title, "project_id": r.project_id,
            "severity": r.severity, "probability": r.probability,
            "score": score, "status": r.status,
            "owner_id": r.owner_id, "source": r.source,
        })
    sections["open_risks"] = open_risks

    by_status: dict = {}
    for r in open_risks:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    counts = {
        "open_risks": len(open_risks),
        "high_risks": sum(1 for r in open_risks if r["score"] >= 12),
        "by_status": by_status,
    }
    notes = [
        "score = severity level × probability level (computed)",
        "uncapped: every open risk on the assigned projects is in records[]",
    ]
    bundle = _shell("risk_exposure", user, tenant, project_ids, project_id,
                    sections=sections, counts=counts, notes=notes)
    bundle["records"] = _flatten(sections)
    return bundle


def stakeholder_map(
    db: Session, user: User | None, tenant, project_ids: list[int],
    project_id: int | None = None,
) -> dict:
    """Stakeholders with their RACI roles — the who-is-who bundle."""
    tid = tenant.id
    sections = {"stakeholders": []}

    if not project_ids:
        return _shell("stakeholder_map", user, tenant, project_ids, project_id,
                      sections=sections,
                      counts={"stakeholders": 0, "accountable": 0, "responsible": 0},
                      notes=["no assigned projects — nothing is visible to the copilot"])

    rows = tenant_scoped(db, Stakeholder, tid).filter(
        Stakeholder.project_id.in_(project_ids),
    ).order_by(Stakeholder.id).all()
    stakeholders = []
    for s in rows:
        stakeholders.append({
            "entity_type": "stakeholder", "entity_id": s.id,
            "record_type": "Stakeholder",
            "title": s.name, "project_id": s.project_id,
            "role_name": s.role_name, "raci_type": s.raci_type,
            "email": s.email, "company": s.company,
        })
    sections["stakeholders"] = stakeholders

    raci = [s["raci_type"] or "I" for s in stakeholders]
    counts = {
        "stakeholders": len(stakeholders),
        "accountable": raci.count("A") + raci.count("Accountable"),
        "responsible": raci.count("R") + raci.count("Responsible"),
    }
    notes = ["RACI roles are the register's own values (A/R/C/I and full labels)"]
    bundle = _shell("stakeholder_map", user, tenant, project_ids, project_id,
                    sections=sections, counts=counts, notes=notes)
    bundle["records"] = _flatten(sections)
    return bundle


def backlog_shape(
    db: Session, user: User | None, tenant, project_ids: list[int],
    project_id: int | None = None,
) -> dict:
    """Epic → features tree + shape counts — the scope bundle."""
    tid = tenant.id
    sections = {"epic_tree": {}}

    if not project_ids:
        return _shell("backlog_shape", user, tenant, project_ids, project_id,
                      sections=sections,
                      counts={"items": 0, "epics": 0, "by_status": {}, "by_phase": {}},
                      notes=["no assigned projects — nothing is visible to the copilot"])

    epic_tree = _epic_tree(db, tid, project_ids)
    sections["epic_tree"] = epic_tree

    items = tenant_scoped(db, BacklogItem, tid).filter(
        BacklogItem.project_id.in_(project_ids),
    ).all()
    by_status: dict = {}
    by_phase: dict = {}
    by_epic: dict = {}
    for item in items:
        by_status[item.status] = by_status.get(item.status, 0) + 1
        by_phase[item.current_phase] = by_phase.get(item.current_phase, 0) + 1
        epic = item.epic or "Ungrouped"
        node = by_epic.setdefault(epic, {"total": 0, "done": 0})
        node["total"] += 1
        if item.status in DONE_STATUSES:
            node["done"] += 1

    counts = {
        "items": len(items),
        "epics": len(by_epic),
        "by_status": by_status,
        "by_phase": by_phase,
        "by_epic": by_epic,
    }
    notes = ["counts are the backlog's own rows — nothing derived or guessed"]
    bundle = _shell("backlog_shape", user, tenant, project_ids, project_id,
                    sections=sections, counts=counts, notes=notes)
    bundle["records"] = _flatten(sections)
    return bundle


_BUILDERS = {
    "project_health": project_health,
    "release_readiness": release_readiness,
    "risk_exposure": risk_exposure,
    "stakeholder_map": stakeholder_map,
    "backlog_shape": backlog_shape,
}


# ── Drift Radar (Rethink §3 #3) ───────────────────────────────────────────
# PM capability #3: "Weekly, per release: target vs planned-finish drift +
# the critical-path items causing it + one suggested move. Deterministic
# compute; the LLM only narrates. Surfaces in Today Brief and the release
# view — not on request." The compute stands alone (project_schedule is the
# ONE drift source, consumed — never re-implemented); every surface renders
# its records, and the suggested move is RULES-based, never LLM-authored.


def drift_radar(
    db: Session, tenant, project_ids: list[int] | None = None,
    project_id: int | None = None,
) -> dict:
    """Per in-flight release: drift days vs target + the critical-path items
    causing it + one rules-based suggested move.

    Scope: the given projects (the release view's one project), or — when
    none are given — every ACTIVE project in the tenant (the Today Brief's
    cross-project scope, the same filter build_today applies). In-flight
    only: Cancelled and shipped releases (the ladder's done set — the same
    ladder-aware filter release_readiness's at-risk applies) are outside the
    radar. Deterministic: same data in, same records out.
    """
    tid = tenant.id
    today = date.today()
    if not project_ids:
        project_ids = [
            p.id for p in tenant_scoped(db, Project, tid).filter(
                Project.status == "Active",
            ).all()
        ]
    if not project_ids:
        return _radar_shell(tid, [], [], notes=["no projects — nothing is in flight"])

    projects_by_id = {
        p.id: p for p in tenant_scoped(db, Project, tid).filter(
            Project.id.in_(project_ids),
        ).all()
    }
    releases = tenant_scoped(db, Release, tid).filter(
        Release.project_id.in_(project_ids),
    ).all()
    if not releases:
        return _radar_shell(tid, sorted(project_ids), [],
                            counts={"releases_scanned": 0},
                            notes=["no releases on the scoped projects"])

    # In-flight filter — ladder-aware (the same rule release_readiness's
    # at-risk applies): Cancelled is terminal; a release whose status is in
    # ITS project ladder's done set has shipped.
    from app.services.lifecycle import release_done_phases
    done_cache: dict = {}
    in_flight = []
    for rel in releases:
        if rel.status == "Cancelled":
            continue  # terminal, outside the gate path
        p_type = getattr(projects_by_id.get(rel.project_id), "project_type", None)
        if p_type not in done_cache:
            done_cache[p_type] = release_done_phases(db, tid, p_type)
        if rel.status in done_cache[p_type]:
            continue  # shipped (at its ladder's live stage or beyond)
        in_flight.append(rel)
    if not in_flight:
        return _radar_shell(tid, sorted(project_ids), [],
                            counts={"releases_scanned": len(releases)},
                            notes=["every release is shipped or cancelled — nothing in flight"])

    # ONE project_schedule run per project with in-flight releases — the SAME
    # compute the Gantt API serves (schedule.py: CPM forward/backward pass +
    # the plan-vs-target drift). Consumed, never re-implemented here.
    from app.services.schedule import project_schedule

    gantts: dict = {}
    for pid in sorted({r.project_id for r in in_flight}):
        p = projects_by_id.get(pid)
        gantts[pid] = project_schedule(db, pid, tid, getattr(p, "project_type", None))

    pending_by_project = _pending_gates_by_project(db, tid, list(gantts))

    records = []
    for rel in sorted(in_flight, key=lambda r: (r.project_id, r.id)):
        target = None
        try:
            target = rel.target_date if isinstance(rel.target_date, date) else date.fromisoformat(str(rel.target_date))
        except (TypeError, ValueError):
            continue  # free-text target — no line, never drift (schedule.py's rule)
        gantt = gantts[rel.project_id]
        release_row = next(
            (r for r in gantt.get("releases", []) if r["id"] == rel.id), None)
        plan_drift = 0
        if release_row and release_row.get("drift_days"):
            plan_drift = release_row["drift_days"]  # planned finish vs target (schedule.py)
        days_late = max((today - target).days, 0)   # today vs target (real-time lateness)
        drift_days = max(plan_drift, days_late)
        if drift_days <= 0:
            continue
        causing = _drift_causes(gantt, target)
        move = _drift_move(
            drift_days, plan_drift, causing,
            pending_by_project.get(rel.project_id) or [],
        )
        records.append({
            "entity_type": "release", "entity_id": rel.id,
            "record_type": "Release",
            "title": f"{rel.version} {rel.name}".strip(),
            "project_id": rel.project_id,
            "project_name": projects_by_id[rel.project_id].name,
            "status": rel.status,
            "target_date": str(rel.target_date),
            "planned_finish": gantt.get("end"),
            "plan_drift_days": plan_drift,
            "days_past_target": days_late,
            "drift_days": drift_days,
            "causing_items": causing,
            "suggested_move": move,
        })
    # Worst drift first — the Today Brief's top row is the one to work.
    records.sort(key=lambda r: (-r["drift_days"], r["entity_id"]))
    return _radar_shell(tid, sorted(project_ids), records,
                        counts={"releases_scanned": len(releases)})


def _radar_shell(tid: int, project_ids: list[int], records: list[dict],
                 counts: dict | None = None, notes: list[str] | None = None) -> dict:
    """The drift radar's envelope: {bundle, scope, records[], counts{}, notes[]}."""
    return {
        "bundle": "drift_radar",
        "scope": {"tenant_id": tid, "project_ids": list(project_ids)},
        "records": records,
        "counts": {"drifted_releases": len(records), **(counts or {})},
        "notes": notes if notes is not None else [
            "drift = max(planned finish vs target, today vs target) on an in-flight release — computed from schedule.py, never a manual flag",
            "causes = CPM critical-path items whose planned end is past the target (zero float)",
            "the suggested move is RULES-based (escalate the pending gate / reassign the critical path / re-target) — never LLM-authored",
        ],
    }


def _drift_causes(gantt: dict, target: date) -> list[dict]:
    """The critical-path items whose planned end is past the target — the
    items causing the drift (zero float against the planned windows)."""
    causes = []
    for it in gantt.get("items", []):
        if not it.get("is_critical") or not it.get("end_date"):
            continue
        try:
            end = (it["end_date"] if isinstance(it["end_date"], date)
                   else date.fromisoformat(str(it["end_date"])))
        except (TypeError, ValueError):
            continue
        if end > target:
            causes.append({
                "entity_type": "backlog_item", "entity_id": it["id"],
                "record_type": "Item",
                "title": it["title"], "status": it["status"],
                "phase": it["current_phase"],
                "end_date": str(it["end_date"]),
                "days_past_target": (end - target).days,
            })
    causes.sort(key=lambda c: (-c["days_past_target"], c["entity_id"]))
    return causes[:3]


def _drift_move(drift_days: int, plan_drift: int, causing: list[dict],
                pending: list[dict]) -> str:
    """One rules-based suggested move (first rule wins; never LLM-authored):
    1. a pending gate approval on the project → escalate it (gates hold
       everything behind them — the Today briefing's own advice);
    2. critical-path items past the target → reassign or re-scope;
    3. the window itself overruns with no critical item over → re-scope the
       tail item or re-target;
    4. the target passed while the plan ends before it → re-target or ship.
    """
    if pending:
        gate = pending[0]
        role = gate.get("awaiting_role") or "the assigned approver"
        return (f"Approval \"{gate['title']}\" pending {gate['days_pending']} days "
                f"with {role} — escalate")
    if causing:
        names = ", ".join(f"\"{c['title']}\"" for c in causing[:2])
        return f"Items {names} on the critical path end past the target — reassign or re-scope"
    if plan_drift > 0:
        return (f"The plan window ends {plan_drift} days past the target with no "
                "critical-path item over — re-scope the tail item or re-target the release")
    return (f"Target passed {drift_days} days ago with the plan ending before it — "
            "re-target the release or ship what is ready")


def _pending_gates_by_project(db: Session, tid: int, project_ids: list[int]) -> dict:
    """Oldest-first pending gate approvals per project — the drift radar's
    escalation suspect (the same compute release_readiness's pending block
    applies, grouped by project)."""
    if not project_ids:
        return {}
    approvals = tenant_scoped(db, ApprovalRequest, tid).filter(
        ApprovalRequest.status == "Pending",
        ApprovalRequest.project_id.in_(project_ids),
    ).order_by(ApprovalRequest.created_at, ApprovalRequest.id).all()
    by_project: dict = {}
    for a in approvals:
        step = tenant_scoped(db, ApprovalStep, tid).filter(
            ApprovalStep.request_id == a.id,
            ApprovalStep.status == "Pending",
        ).order_by(ApprovalStep.step_order).first()
        by_project.setdefault(a.project_id, []).append({
            "entity_type": "approval_request", "entity_id": a.id,
            "title": a.title,
            "awaiting_role": step.role_name if step else None,
            "days_pending": _days_since(a.created_at),
        })
    return by_project


# ── Shared computed pieces (carved from services/copilot.py build_context) ─


def _shell(
    name: str, user: User | None, tenant, project_ids: list[int],
    project_id: int | None, sections: dict, counts: dict, notes: list[str],
) -> dict:
    """The bundle contract envelope: {bundle, scope, records, counts, notes}
    (+ sections: the legacy assembly view for the build_context facade)."""
    return {
        "bundle": name,
        "scope": {
            "project_ids": list(project_ids),
            "project_id": project_id,
            "user_id": user.id if user is not None else None,
            "tenant_id": tenant.id,
        },
        "records": [],
        "counts": counts,
        "notes": notes,
        "sections": sections,
    }


def _flatten(sections: dict) -> list[dict]:
    """Entity-backed records from the section view, each tagged with its
    section. Walks one level into the nested lists the copilot's citation
    registry has always walked (schedule critical_items/releases, epic
    features). Entries without both entity_type and entity_id (predictive
    flags, epic nodes) are shells — they stay out of records[]."""
    records: list[dict] = []

    def _walk(entry, section: str) -> None:
        if not isinstance(entry, dict):
            return
        if entry.get("entity_type") is not None and entry.get("entity_id") is not None:
            rec = dict(entry)
            rec.setdefault("section", section)
            records.append(rec)
        for key in ("features", "critical_items", "releases"):
            for nested in entry.get(key) or []:
                _walk(nested, section)

    for section, value in sections.items():
        entries = value.values() if isinstance(value, dict) else value
        for entry in entries or []:
            if section == "epic_tree" and isinstance(entry, dict):
                _walk(entry, section)  # epic nodes: no id, but features count
            else:
                _walk(entry, section)
    return records


def _identity_for(db: Session, p: Project, with_activity: bool) -> dict:
    """Identity block for one project: description, client, PM, vision,
    milestones — everything the copilot needs to discuss THIS project."""
    from app.models.milestone import Milestone
    from app.models.project_vision import ProjectVision
    from app.models.roadmap import Roadmap

    tid = p.tenant_id
    manager = (
        db.query(User).filter(User.id == p.project_manager_id).first()
        if p.project_manager_id else None
    )
    vision_row = tenant_scoped(db, ProjectVision, tid).filter(
        ProjectVision.project_id == p.id,
    ).first()
    p_milestones = (
        tenant_scoped(db, Milestone, tid)
        .join(Roadmap, Milestone.roadmap_id == Roadmap.id)
        .filter(Roadmap.project_id == p.id)
        .order_by(Milestone.id)
        .limit(6)
        .all()
    )
    identity = {
        "entity_type": "project",
        "entity_id": p.id,
        "title": p.name,
        "status": p.status,
        "description": p.description or "",
        "project_type": p.project_type or "",
        "client": p.client.name if p.client else None,
        "manager": manager.name if manager else None,
        "vision": vision_row.statement if vision_row else None,
        "milestones": [
            {"title": m.title, "target_date": str(m.target_date) if m.target_date else None, "status": m.status}
            for m in p_milestones if m.title
        ],
        "scoped": with_activity,
    }
    if with_activity:
        recent_activity = (
            db.query(ActivityLog)
            .filter(
                ActivityLog.project_id == p.id,
                ActivityLog.action.in_(["created", "applied", "advanced", "updated", "approved", "rejected"]),
            )
            .order_by(ActivityLog.id.desc())
            .limit(10)
            .all()
        )
        identity["recent_activity"] = [
            {"summary": a.summary, "action": a.action, "entity": a.entity_type}
            for a in recent_activity if a.summary
        ]
    return identity


def _schedule_for(db: Session, p: Project, tid: int) -> dict:
    """One project's schedule block — the SAME compute the Gantt API serves
    (app/services/schedule.py), wrapped with entity tags for citations."""
    from app.services.schedule import project_schedule

    gantt = project_schedule(db, p.id, tid, p.project_type)
    critical = [
        {
            "entity_type": "backlog_item", "entity_id": it["id"],
            "record_type": "Item",
            "title": it["title"], "phase": it["current_phase"],
            "status": it["status"], "project_id": p.id,
        }
        for it in gantt["items"] if it.get("is_critical")
    ][:10]
    releases = [
        {
            "entity_type": "release", "entity_id": r["id"],
            "record_type": "Release",
            "title": f"{r['version']} {r['name']}".strip(),
            "status": r["status"], "target_date": r["target_date"],
            "project_id": p.id,
            "drift_days": r["drift_days"], "live_stage": r["live_stage"],
        }
        for r in gantt["releases"]
    ]
    return {
        "entity_type": "project", "entity_id": p.id, "title": p.name,
        "window_start": gantt["start"], "window_end": gantt["end"],
        "planned_finish": gantt["end"],
        "critical_count": gantt["critical_count"],
        "unscheduled_count": gantt["unscheduled_count"],
        "critical_items": critical,
        "releases": releases,
    }


def _epic_tree(db: Session, tid: int, project_ids: list[int]) -> dict:
    """Epic → features map for intake verdicts and backlog questions."""
    items = tenant_scoped(db, BacklogItem, tid).filter(
        BacklogItem.project_id.in_(project_ids),
    ).order_by(BacklogItem.id).all()
    tree: dict[str, dict] = {}
    for item in items:
        epic = item.epic or "Ungrouped"
        node = tree.setdefault(epic, {"entity_type": "epic", "title": epic, "features": []})
        node["features"].append({
            "entity_type": "backlog_item", "entity_id": item.id,
            "title": item.title, "phase": item.current_phase,
            "status": item.status, "item_type": item.item_type,
            "project_id": item.project_id,  # deep links for validated citations
        })
    return tree


def _risk_score(severity: str, probability: str) -> int:
    """Risk score = severity level × probability level; unknown strings score 0."""
    return SEVERITY_LEVELS.get(severity, 0) * PROBABILITY_LEVELS.get(probability, 0)


def _days_since(value) -> int:
    """Days since a datetime/string timestamp; 0 when unparseable.

    Handles offset-naive and offset-aware datetimes (Postgres returns
    timezone-aware values; utcnow() is naive) — compare in UTC.
    """
    if value is None:
        return 0
    if isinstance(value, datetime):
        now = datetime.now(value.tzinfo) if value.tzinfo else datetime.utcnow()
        return (now - value).days
    if isinstance(value, date):
        return (date.today() - value).days
    s = str(value)
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(s[:26] if ".%f" in fmt else s[:19] if "%H" in fmt else s[:10], fmt)
            return (datetime.utcnow() - parsed).days if "%H" in fmt else (date.today() - parsed.date()).days
        except ValueError:
            continue
    return 0
