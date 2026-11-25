"""Project schedule compute — the ONE item-Gantt source (CPM + releases + drift).

Extracted from the dashboard router (the same service-layer pattern the
stats handler uses) so the Gantt API and the Copilot's schedule-aware ask
read the same numbers from one place: planned windows, the dependency DAG,
the full CPM forward/backward pass (ES/EF/LS/LF, float, is_critical), the
release targets (Timeline P1) and the plan-vs-commitment drift. The route
keeps the tenant scoping and the 404; everything downstream of it is here.
"""
from datetime import date as date_type

from sqlalchemy.orm import Session

from app.models.backlog_item import BacklogItem, backlog_dependencies
from app.models.release import Release, ReleaseItem
from app.services.scope import tenant_scoped


def project_schedule(
    db: Session, project_id: int, tenant_id: int, project_type: str | None
) -> dict:
    """Item-level Gantt data: scheduled window, dependencies, CPM float/critical.

    Byte-identical to what the router returned when the compute lived there —
    the frontend and the Copilot consume the same payload.
    """
    from app.services.lifecycle import release_lifecycle

    items = db.query(BacklogItem).filter(BacklogItem.project_id == project_id).all()
    scheduled = {
        it.id: it for it in items
        if it.start_date and it.end_date and it.start_date <= it.end_date
    }
    if not scheduled:
        return {
            "project_id": project_id,
            "start": None,
            "end": None,
            "items": [],
            "unscheduled_count": len(items),
            "critical_count": 0,
            "releases": [],
            "drift": None,
        }

    # Dependency edges (only where both ends are scheduled)
    rows = db.query(
        backlog_dependencies.c.dependent_id, backlog_dependencies.c.depends_on_id
    ).filter(
        backlog_dependencies.c.dependent_id.in_(list(scheduled.keys())),
        backlog_dependencies.c.depends_on_id.in_(list(scheduled.keys())),
    ).all()
    deps = {iid: [] for iid in scheduled}      # id -> items it depends on
    blocks = {iid: [] for iid in scheduled}    # id -> items that depend on it
    for dependent_id, depends_on_id in rows:
        deps[dependent_id].append(depends_on_id)
        blocks[depends_on_id].append(dependent_id)

    # Day offsets from the project window start
    window_start = min(it.start_date for it in scheduled.values())
    window_end = max(it.end_date for it in scheduled.values())

    # Release targets (Timeline P1): the project's releases are the commitment
    # layer on the item Gantt — each target date renders as a key-date line,
    # and the drift chip flags a plan running past it. target_date is a free
    # string (ISO "2026-09-30" from the forms); unparseable values skip the
    # line and never drift. The ladder is DYNAMIC (release_lifecycle) — each
    # release carries the ladder's live_stage.
    ladder = release_lifecycle(db, tenant_id, project_type)
    release_rows = []
    release_targets = {}  # release_id -> parsed target date
    drift = None
    for r in tenant_scoped(db, Release, tenant_id).filter(
        Release.project_id == project_id
    ).all():
        release_rows.append({
            "id": r.id,
            "version": r.version,
            "name": r.name,
            "status": r.status,
            "target_date": r.target_date,
            "live_stage": ladder["live_stage"],
            "drift_days": None,
        })
        try:
            release_targets[r.id] = date_type.fromisoformat(r.target_date)
        except (TypeError, ValueError):
            continue  # free-text date — no line, no drift
        past = (window_end - release_targets[r.id]).days
        if past > 0:
            release_rows[-1]["drift_days"] = past
            if drift is None or past > drift["drift_days"]:
                drift = {
                    "release_id": r.id,
                    "version": r.version,
                    "target_date": r.target_date,
                    "drift_days": past,
                }

    # Item-level drift (Timeline P1): an item runs past the release target
    # when its planned end is past the target of a release it's bundled to.
    item_releases = {}  # backlog_item_id -> [release_id]
    if release_targets:
        for rid, iid in db.query(
            ReleaseItem.release_id, ReleaseItem.backlog_item_id
        ).filter(ReleaseItem.release_id.in_(list(release_targets.keys()))).all():
            item_releases.setdefault(iid, []).append(rid)

    def offset(d: date_type) -> int:
        return (d - window_start).days

    durations = {iid: offset(it.end_date) - offset(it.start_date) + 1 for iid, it in scheduled.items()}  # inclusive days
    durations = {iid: max(dur, 1) for iid, dur in durations.items()}  # min 1 day

    # Kahn topological sort — cycle-safe
    indegree = {iid: len(set(deps[iid])) for iid in scheduled}
    queue = sorted([iid for iid, deg in indegree.items() if deg == 0])
    order = []
    seen_deps = {iid: set(deps[iid]) for iid in scheduled}
    while queue:
        iid = queue.pop(0)
        order.append(iid)
        for nxt in sorted(set(blocks[iid])):
            seen_deps[nxt].discard(iid)
            if not seen_deps[nxt] and nxt not in order:
                queue.append(nxt)
    in_cycle = set(scheduled) - set(order)  # cycle members: no CPM numbers

    # Forward pass: early start/finish
    es = {}
    ef = {}
    for iid in order:
        preds = [ef[p] for p in set(deps[iid]) if p in ef]
        es[iid] = max(preds) if preds else 0
        ef[iid] = es[iid] + durations[iid]
    project_finish = max(ef.values()) if ef else 0

    # Backward pass: late start/finish
    lf = {}
    ls = {}
    for iid in reversed(order):
        succs = [ls[s] for s in set(blocks[iid]) if s in ls]
        lf[iid] = min(succs) if succs else project_finish
        ls[iid] = lf[iid] - durations[iid]

    result_items = []
    critical_count = 0
    for it in items:
        base = {
            "id": it.id,
            "title": it.title,
            "current_phase": it.current_phase,
            "status": it.status,
            "priority": it.priority,
            "epic": it.epic,
            "start_date": str(it.start_date) if it.start_date else None,
            "end_date": str(it.end_date) if it.end_date else None,
            "actual_start_date": str(it.actual_start_date) if it.actual_start_date else None,
            "actual_end_date": str(it.actual_end_date) if it.actual_end_date else None,
            "depends_on": sorted(d.id for d in (it.depends_on or [])),
            "blocks": sorted(blocks.get(it.id, [])),
        }
        # Drift flag (Timeline P1): the item runs past the release target of
        # a release it's bundled to.
        item_drift = None
        for rid in item_releases.get(it.id, []):
            target = release_targets[rid]
            if it.end_date and it.end_date > target:
                d = (it.end_date - target).days
                if item_drift is None or d > item_drift["drift_days"]:
                    item_drift = {
                        "release_id": rid,
                        "target_date": target.isoformat(),
                        "drift_days": d,
                    }
        base["past_release"] = item_drift is not None
        base["release_drift"] = item_drift
        if it.id in scheduled and it.id not in in_cycle:
            f = ls[it.id] - es[it.id]
            if f == 0:
                critical_count += 1
            base.update({
                "duration": durations[it.id],
                "early_start": es[it.id],
                "early_finish": ef[it.id],
                "late_start": ls[it.id],
                "late_finish": lf[it.id],
                "float": f,
                "is_critical": f == 0,
            })
        else:
            base.update({"duration": None, "float": None, "is_critical": False})
        result_items.append(base)

    return {
        "project_id": project_id,
        "start": str(window_start),
        "end": str(window_end),
        "total_days": (window_end - window_start).days + 1,
        "items": result_items,
        "unscheduled_count": len(items) - len(scheduled),
        "critical_count": critical_count,
        "releases": release_rows,
        "drift": drift,
    }
