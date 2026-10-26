"""Velocity/sprint planning — Business-plan gated feature.

compute_velocity derives velocity from completed backlog items per sprint
window (Committed phase + Done status = finished work). recommend_scope
projects how many items fit the next sprint. The endpoint is gated behind
`sprint_planning` (Business plan+) — Free/Team receive 403 with an upgrade
message. Numbers are derived, never stored.

Note: backlog_items.updated_at is a VARCHAR on legacy rows and DATE-casts are
unreliable across SQLite/Postgres, so the date bucketing is done in Python —
the DB only filters project/status/phase (indexed, type-safe); unparseable
timestamps are excluded, never a 500.
"""
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.backlog_item import BacklogItem
from app.models.project import Project


def _parse_date(value):
    """Parse a timestamp/date in any stored shape; None when unparseable."""
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


def compute_velocity(db: Session, project: Project, sprint_days: int = 14) -> dict:
    """Completed items per recent sprint window + the rolling average.

    Derived on the fly from the backlog's Done/Committed items; no stored
    sprint state required for v1.
    """
    today = date.today()
    done_items = db.query(BacklogItem).filter(
        BacklogItem.project_id == project.id,
        BacklogItem.status == "Done",
        BacklogItem.current_phase == "Committed",
    ).all()
    total_done = len(done_items)

    sprints: list[dict] = []
    for i in range(3):  # last 3 sprint windows
        end = today - timedelta(days=i * sprint_days)
        start = end - timedelta(days=sprint_days)
        count = 0
        for item in done_items:
            when = _parse_date(item.updated_at)
            if when is not None and start <= when < end:
                count += 1
        sprints.append({"sprint": f"S-{i + 1}", "completed": count})

    completed = [s["completed"] for s in sprints if s["completed"] > 0]
    average = round(sum(completed) / len(completed), 1) if completed else 0.0

    return {
        "sprint_days": sprint_days,
        "sprints": sprints,
        "total_done": total_done,
        "average": average,
    }


def recommend_scope(db: Session, project: Project, sprint_days: int = 14) -> dict:
    """How many items fit the next sprint (the rolling average)."""
    velocity = compute_velocity(db, project, sprint_days)
    recommended = int(velocity["average"]) if velocity["average"] else 0
    return {
        "recommended_items": recommended,
        "basis": "average of completed items per sprint",
        "velocity": velocity,
    }
