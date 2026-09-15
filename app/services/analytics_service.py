"""Advanced analytics service — release-level metrics for business PMO.

Provides:
- velocity_per_release: items completed per release
- burndown: remaining items over time within a release
- cumulative_flow: item count by phase over time
- cycle_time: average time from creation to "Ready for UAT"
- phase_distribution: current items by phase
- kpi_trend: KPI value snapshots over time
"""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.backlog_item import BacklogItem
from app.models.kpi import KPI
from app.models.release import Release, ReleaseItem
from app.models.usage_record import UsageRecord


def velocity_per_release(db: Session, tenant_id: int, project_id: int = None) -> list:
    """Items completed per release (velocity across releases)."""
    q = db.query(Release).filter(Release.tenant_id == tenant_id)
    if project_id:
        q = q.filter(Release.project_id == project_id)

    releases = q.order_by(Release.created_at.asc()).all()
    result = []
    for r in releases:
        items = db.query(ReleaseItem).filter(ReleaseItem.release_id == r.id, ReleaseItem.tenant_id == tenant_id).all()
        total = len(items)
        done = sum(1 for ri in items if ri.backlog_item and ri.backlog_item.status == "Done")
        result.append({
            "release_id": r.id,
            "version": r.version,
            "name": r.name,
            "status": r.status,
            "total_items": total,
            "completed_items": done,
            "velocity": done,
            "progress_pct": round(done / total * 100) if total else 0,
        })
    return result


def burndown_data(db: Session, tenant_id: int, release_id: int) -> list:
    """Burndown: remaining items over time within a release.

    Uses ReleaseItem creation dates and backlog item status changes
    to estimate the burndown curve.
    """
    release = db.query(Release).filter(Release.id == release_id, Release.tenant_id == tenant_id).first()
    if not release:
        return []

    items = db.query(ReleaseItem).filter(
        ReleaseItem.release_id == release_id,
        ReleaseItem.tenant_id == tenant_id,
    ).all()

    if not items:
        return []

    # Build a timeline from release creation to now (or release date)
    start = release.created_at.date() if release.created_at else datetime.utcnow().date()
    end = datetime.strptime(release.release_date, "%Y-%m-%d").date() if release.release_date else datetime.utcnow().date()
    if end < start:
        end = datetime.utcnow().date()

    total = len(items)
    timeline = []
    current = start
    while current <= end:
        # Count items that were NOT yet "Done" by this date
        remaining = total  # Simplified: all items start as "remaining"
        # For a more accurate burndown, we'd need to track status change timestamps
        # For now, use a linear ideal burndown + actual remaining
        day_num = (current - start).days
        total_days = max(1, (end - start).days)
        ideal_remaining = max(0, total - (total * day_num / total_days))

        # Actual: count items where backlog_item.status == "Done" AND
        # the item was added before this date
        done_by_now = sum(
            1 for ri in items
            if ri.backlog_item
            and ri.backlog_item.status == "Done"
            and ri.added_at and ri.added_at.date() <= current
        ) if hasattr(items[0], 'added_at') else 0

        actual_remaining = total - done_by_now if done_by_now else total - int(ideal_remaining)

        timeline.append({
            "date": current.isoformat(),
            "ideal": round(ideal_remaining, 1),
            "actual": actual_remaining,
        })
        current += timedelta(days=1)

    return timeline


def cumulative_flow(db: Session, tenant_id: int, project_id: int) -> list:
    """Cumulative flow: item count by phase over time.

    Uses UsageRecord snapshots if available, otherwise calculates current state.
    """
    # Get usage history for backlog_items
    records = db.query(UsageRecord).filter(
        UsageRecord.tenant_id == tenant_id,
        UsageRecord.metric == "backlog_items",
    ).order_by(UsageRecord.date.asc()).all()

    if records:
        return [{"date": r.date, "total": r.count} for r in records]

    # Fallback: return current phase distribution
    items = db.query(BacklogItem).filter(
        BacklogItem.project_id == project_id,
        BacklogItem.tenant_id == tenant_id,
    ).all()

    phases = {}
    for item in items:
        phases[item.current_phase] = phases.get(item.current_phase, 0) + 1

    return [{"date": datetime.utcnow().date().isoformat(), "phases": phases, "total": len(items)}]


def cycle_time(db: Session, tenant_id: int, project_id: int = None) -> dict:
    """Average cycle time: creation → Ready for UAT (in days)."""
    q = db.query(BacklogItem).filter(
        BacklogItem.tenant_id == tenant_id,
        BacklogItem.current_phase.in_(["Ready for UAT", "Released"]),
    )
    if project_id:
        q = q.filter(BacklogItem.project_id == project_id)

    items = q.all()
    if not items:
        return {"avg_cycle_time_days": 0, "items_measured": 0, "min_days": 0, "max_days": 0}

    cycle_times = []
    for item in items:
        if item.created_at:
            # Use updated_at as proxy for when it reached "Ready for UAT"
            end_date = item.updated_at or datetime.utcnow()
            cycle = (end_date - item.created_at).days
            if cycle >= 0:
                cycle_times.append(cycle)

    if not cycle_times:
        return {"avg_cycle_time_days": 0, "items_measured": 0, "min_days": 0, "max_days": 0}

    return {
        "avg_cycle_time_days": round(sum(cycle_times) / len(cycle_times), 1),
        "items_measured": len(cycle_times),
        "min_days": min(cycle_times),
        "max_days": max(cycle_times),
    }


def phase_distribution(db: Session, tenant_id: int, project_id: int = None) -> dict:
    """Current distribution of backlog items by phase."""
    q = db.query(BacklogItem).filter(BacklogItem.tenant_id == tenant_id)
    if project_id:
        q = q.filter(BacklogItem.project_id == project_id)

    items = q.all()
    phases = {}
    for item in items:
        phases[item.current_phase] = phases.get(item.current_phase, 0) + 1

    return {
        "total": len(items),
        "phases": phases,
    }


def kpi_trend(db: Session, tenant_id: int, project_id: int) -> list:
    """KPI values snapshot for trend analysis.

    Returns current KPI values. For historical trends, a KpiSnapshot
    model would need to be created (future enhancement).
    """
    kpis = db.query(KPI).filter(KPI.project_id == project_id, KPI.tenant_id == tenant_id).all()
    return [
        {
            "id": k.id,
            "name": k.name,
            "category": k.category,
            "current_value": float(k.current_value) if k.current_value else 0,
            "target_value": float(k.target_value) if k.target_value else 0,
            "unit": k.unit,
            "progress_pct": min(100, int(
                (float(k.current_value) / float(k.target_value) * 100)
                if k.target_value and float(k.target_value) > 0 else 0
            )),
        }
        for k in kpis
    ]


def project_analytics_summary(db: Session, tenant_id: int, project_id: int) -> dict:
    """Get a complete analytics summary for a project."""
    return {
        "velocity": velocity_per_release(db, tenant_id, project_id),
        "cycle_time": cycle_time(db, tenant_id, project_id),
        "phase_distribution": phase_distribution(db, tenant_id, project_id),
        "cumulative_flow": cumulative_flow(db, tenant_id, project_id),
        "kpi_trend": kpi_trend(db, tenant_id, project_id),
    }
