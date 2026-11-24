"""Project health composite — computed score with visible inputs (R3).

compute_project_health is the single builder behind GET /api/projects/{id}/health
(one builder, two consumers: the notifications router today, aggregate/copilot
surfaces next). The 0-100 composite is the exact math the router always ran:
schedule (completed items ratio), approvals (-15 per pending gate), tasks
(-20 per overdue), kpis (on-target ratio) — averaged and mapped to status
thresholds/labels/colors.

R3 additions, both derived from real rows and never stored:

- gate_aging: the oldest pending gate's age in days. The ×15 per-gate count
  rule is unchanged; on top of it, once the oldest pending gate is past a
  3-day grace it costs 1 extra approval_score point per day, capped at 15.
  approval_score = max(0, 100 - pending×15 - aging_penalty).
- why: per sub-score, the inputs that moved it as short strings the UI renders
  as why-chips (e.g. ["2 gates pending · oldest 6d"]). Built from the same
  counts that produce the sub-scores — real data, never invented.

approval_requests.created_at is a VARCHAR timestamp (server_default now()), so
ages are parsed in Python with the same tolerance as velocity.py; unparseable
stamps contribute no aging and never a 500.
"""
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models.approval import ApprovalRequest
from app.models.backlog_item import BacklogItem
from app.models.kpi import KPI
from app.models.project import Project
from app.models.release import Release, ReleaseItem
from app.models.user_task import UserTask

# Gate aging: the oldest pending gate costs 1 approval_score point per day
# once it is past this grace window, capped at GATE_AGING_MAX_PENALTY.
GATE_AGING_GRACE_DAYS = 3
GATE_AGING_MAX_PENALTY = 15


def _parse_ts(value):
    """Parse a stored timestamp in any shape to a date; None when unparseable."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value)
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:26] if ".%f" in fmt else s[:19] if "%H" in fmt else s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _gate_aging(pending_rows: list, today: date) -> tuple:
    """(oldest pending gate's age in days, aging penalty) from real rows.

    Penalty = min(GATE_AGING_MAX_PENALTY, max(0, oldest_days - GATE_AGING_GRACE_DAYS));
    0 when nothing is pending or every stamp is unparseable. Ages never go
    negative (a clock-skewed future stamp reads as 0 days).
    """
    ages = []
    for row in pending_rows:
        created = _parse_ts(row.created_at)
        if created is None:
            continue
        ages.append(max(0, (today - created).days))
    oldest = max(ages) if ages else 0
    penalty = min(GATE_AGING_MAX_PENALTY, max(0, oldest - GATE_AGING_GRACE_DAYS))
    return oldest, penalty


def compute_project_health(db: Session, tenant_id: int, project_id: int) -> dict:
    """Composite project health (0-100) + sub-scores, gate aging and why-chips.

    The sub-score math and status mapping are the router's original formula,
    kept verbatim; `gate_aging` and `why` are additive. Existing keys keep
    their exact meaning (the overview card + tests consume them).
    """
    today = date.today()

    # Phase distribution
    items = db.query(BacklogItem).filter(BacklogItem.project_id == project_id, BacklogItem.tenant_id == tenant_id).all()
    phase_dist = {}
    for item in items:
        phase_dist[item.current_phase] = phase_dist.get(item.current_phase, 0) + 1

    total_items = len(items)
    # Original formula, kept as-is: an item counts as completed when it is in
    # "Ready for UAT" OR carries a target_release (precedence: any target_release
    # item is "completed" even in Development).
    completed_items = sum(1 for i in items if i.current_phase == "Ready for UAT" or i.target_release)

    # Active releases
    releases = db.query(Release).filter(Release.project_id == project_id, Release.tenant_id == tenant_id).all()
    active_releases = [r for r in releases if r.status not in ("Post-Release",)]
    releases_with_items = []
    for r in active_releases:
        release_items = db.query(ReleaseItem).filter(ReleaseItem.release_id == r.id, ReleaseItem.tenant_id == tenant_id).all()
        releases_with_items.append({
            "id": r.id,
            "version": r.version,
            "name": r.name,
            "status": r.status,
            "item_count": len(release_items),
            "progress": min(100, len(release_items) * 20),
        })

    # Pending approvals (rows, so gate aging can read the created_at stamps)
    pending_rows = db.query(ApprovalRequest).filter(
        ApprovalRequest.project_id == project_id,
        ApprovalRequest.status == "Pending",
        ApprovalRequest.tenant_id == tenant_id,
    ).all()
    pending_approvals = len(pending_rows)
    gate_aging, aging_penalty = _gate_aging(pending_rows, today)

    # Overdue tasks
    overdue_tasks = db.query(UserTask).filter(
        UserTask.project_id == project_id,
        UserTask.status != "Completed",
        UserTask.due_date < today,
        UserTask.tenant_id == tenant_id,
    ).count()

    # KPIs below target
    kpis = db.query(KPI).filter(KPI.project_id == project_id, KPI.tenant_id == tenant_id).all()
    kpis_below = 0
    kpi_progress = []
    # project_id/project_name match the stats.py dashboard variant's row shape
    project_name = db.query(Project.name).filter(Project.id == project_id).scalar() or "—"
    for k in kpis:
        try:
            target = float(k.target_value) if k.target_value else 0
            current = float(k.current_value) if k.current_value else 0
        except (ValueError, TypeError):
            target, current = 0, 0
        if target and current < target:
            kpis_below += 1
        pct = int((current / target * 100) if target else 0)
        kpi_progress.append({
            "id": k.id, "name": k.name, "current": current,
            "target": target, "unit": k.unit, "progress": min(100, pct),
            "project_id": project_id, "project_name": project_name,
        })

    # Composite health score (0-100)
    schedule_score = min(100, (completed_items / total_items * 100) if total_items else 100)
    approval_score = max(0, 100 - pending_approvals * 15 - aging_penalty)
    task_score = max(0, 100 - overdue_tasks * 20)
    kpi_score = (len(kpis) - kpis_below) / len(kpis) * 100 if kpis else 100
    health_score = int((schedule_score + approval_score + task_score + kpi_score) / 4)

    # Determine status
    if health_score >= 80:
        status = "Healthy"
        status_color = "emerald"
    elif health_score >= 60:
        status = "At Risk"
        status_color = "amber"
    elif health_score >= 40:
        status = "Warning"
        status_color = "orange"
    else:
        status = "Critical"
        status_color = "rose"

    # Why-inputs per sub-score — the real numbers that moved it, as chips
    if total_items:
        schedule_why = [f"{completed_items} of {total_items} items done"]
    else:
        schedule_why = ["no items yet"]
    if pending_approvals:
        approval_why = [
            f"{pending_approvals} gate{'s' if pending_approvals != 1 else ''} pending · oldest {gate_aging}d"
        ]
        if aging_penalty:
            approval_why.append(f"aging -{aging_penalty} pts")
    else:
        approval_why = ["no pending gates"]
    task_why = [f"{overdue_tasks} overdue"] if overdue_tasks else ["no overdue tasks"]
    if not kpis:
        kpi_why = ["no kpis tracked"]
    elif kpis_below:
        kpi_why = [f"{kpis_below} of {len(kpis)} below target"]
    else:
        kpi_why = [f"all {len(kpis)} on target"]

    return {
        "health_score": health_score,
        "status": status,
        "status_color": status_color,
        "schedule_score": int(schedule_score),
        "approval_score": int(approval_score),
        "task_score": int(task_score),
        "kpi_score": int(kpi_score),
        "total_items": total_items,
        "completed_items": completed_items,
        "phase_distribution": phase_dist,
        "active_releases": releases_with_items,
        "pending_approvals": pending_approvals,
        "overdue_tasks": overdue_tasks,
        "kpis_below_target": kpis_below,
        "kpi_progress": kpi_progress,
        "gate_aging": gate_aging,
        "why": {
            "schedule": schedule_why,
            "approvals": approval_why,
            "tasks": task_why,
            "kpis": kpi_why,
        },
    }
