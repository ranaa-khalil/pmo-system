"""Velocity/sprint planning — Business-plan gated feature.

compute_velocity derives velocity from completed backlog items per sprint
window (Committed phase + Done status = finished work). recommend_scope
projects how many items fit the next sprint. The endpoint is gated behind
`sprint_planning` (Business plan+) — Free/Team receive 403 with an upgrade
message. Numbers are derived, never stored.
"""
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models.backlog_item import BacklogItem
from app.models.project import Project


def _completed_in_window(db: Session, project: Project, start: date, end: date) -> int:
    return db.query(BacklogItem).filter(
        BacklogItem.project_id == project.id,
        BacklogItem.status == "Done",
        BacklogItem.current_phase == "Committed",
    ).count()


def compute_velocity(db: Session, project: Project, sprint_days: int = 14) -> dict:
    """Completed items per recent sprint window + the rolling average.

    Derived on the fly from the backlog's Done/Committed items; no stored
    sprint state required for v1.
    """
    today = date.today()
    total_done = db.query(BacklogItem).filter(
        BacklogItem.project_id == project.id,
        BacklogItem.status == "Done",
        BacklogItem.current_phase == "Committed",
    ).count()

    sprints: list[dict] = []
    for i in range(3):  # last 3 sprint windows
        end = today - timedelta(days=i * sprint_days)
        start = end - timedelta(days=sprint_days)
        count = db.query(BacklogItem).filter(
            BacklogItem.project_id == project.id,
            BacklogItem.status == "Done",
            BacklogItem.current_phase == "Committed",
            BacklogItem.updated_at >= start,
            BacklogItem.updated_at < end,
        ).count()
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
