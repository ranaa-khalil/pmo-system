"""Today service — the R1 spine.

build_today(db, tenant, user): the needs-you aggregate (approvals pending on
the user's approval steps, blocked items, overdue work, escalated risks) +
a 3-line briefing with a verdict. Deterministic, tenant-scoped, capped rows.

build_brief(db, project): template-based narrative from live data (no LLM in
R1 — the nightly AI rewrite lands in R3).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models.approval import ApprovalRequest, ApprovalStep
from app.models.backlog_item import BacklogItem
from app.models.project import Project

MAX_ROWS = 8
OPEN_STATUSES = ("Draft", "To Do", "In Progress", "Blocked", "Review")
OVERDUE_MONTH = "2026-01"  # target_release values earlier than the current month


def _current_month() -> str:
    return date.today().strftime("%Y-%m")


def _project_names(db: Session, tenant_id: int) -> dict[int, str]:
    rows = db.query(Project).filter(Project.tenant_id == tenant_id).all()
    return {p.id: p.name for p in rows}


def build_today(db: Session, tenant, user) -> dict:
    """The needs-you aggregate for one user's tenant."""
    tenant_id = tenant.id
    projects = db.query(Project).filter(Project.tenant_id == tenant_id, Project.status == "Active").all()
    project_ids = [p.id for p in projects]
    names = {p.id: p.name for p in projects}
    rows: list[dict] = []

    # 1. Approvals pending on the user's steps
    pending_steps = (
        db.query(ApprovalStep, ApprovalRequest)
        .join(ApprovalRequest, ApprovalStep.request_id == ApprovalRequest.id)
        .filter(
            ApprovalRequest.tenant_id == tenant_id,
            ApprovalRequest.status == "Pending",
            ApprovalStep.approver_id == user.id,
            ApprovalStep.status == "Pending",
        )
        .all()
    )
    for _step, req in pending_steps:
        rows.append({
            "kind": "approval",
            "title": req.title,
            "why": f"Gate approval waiting on you ({req.request_type})",
            "project_id": req.project_id,
            "project": names.get(req.project_id, ""),
            "ref_id": req.id,
            "approval_id": req.id,
        })

    if project_ids:
        items = db.query(BacklogItem).filter(BacklogItem.project_id.in_(project_ids)).all()
        month = _current_month()
        for it in items:
            if it.status == "Blocked":
                rows.append({
                    "kind": "blocked",
                    "title": it.title,
                    "why": "Blocked — needs unblocking or a decision",
                    "project_id": it.project_id,
                    "project": names.get(it.project_id, ""),
                    "ref_id": it.id,
                })
            elif it.status in ("In Progress", "Review") and it.target_release and it.target_release < month:
                rows.append({
                    "kind": "overdue",
                    "title": it.title,
                    "why": f"Target release {it.target_release} has passed",
                    "project_id": it.project_id,
                    "project": names.get(it.project_id, ""),
                    "ref_id": it.id,
                })

    # Deterministic order: approval > blocked > overdue, then by ref id
    kind_rank = {"approval": 0, "blocked": 1, "overdue": 2}
    rows.sort(key=lambda r: (kind_rank.get(r["kind"], 9), r["ref_id"]))
    counts = {k: sum(1 for r in rows if r["kind"] == k) for k in ("approval", "blocked", "overdue")}

    briefing = _briefing(rows, counts)
    return {
        "needs_you": rows[:MAX_ROWS],
        "total_needs_you": len(rows),
        "counts": counts,
        "briefing": briefing,
    }


def _briefing(rows: list[dict], counts: dict) -> dict:
    total = sum(counts.values())
    if total == 0:
        verdict = "on_track"
        lines = [
            "All projects are clear — nothing is waiting on you.",
            "No blocked or overdue work in any active project.",
            "Capture something new, or enjoy the quiet.",
        ]
    elif counts.get("blocked", 0) >= 3 or counts.get("overdue", 0) >= 5:
        verdict = "at_risk"
    else:
        verdict = "needs_attention"
    if total > 0:
        parts = []
        if counts.get("approval"):
            parts.append(f"{counts['approval']} approval{'s' if counts['approval'] != 1 else ''} waiting on you")
        if counts.get("blocked"):
            parts.append(f"{counts['blocked']} blocked item{'s' if counts['blocked'] != 1 else ''}")
        if counts.get("overdue"):
            parts.append(f"{counts['overdue']} overdue")
        top = rows[0]
        lines = [
            f"{total} thing{'s' if total != 1 else ''} need{'s' if total == 1 else ''} you: " + ", ".join(parts) + ".",
            f"Top of the list: {top['title']} ({top['project']}) — {top['why'].lower().rstrip('.')}",
            "Work the approvals first — gates hold everything behind them.",
        ]
    return {"verdict": verdict, "lines": lines}


def build_brief(db: Session, project: Project) -> dict:
    """Template-based narrative from live data — deterministic (R1)."""
    items = db.query(BacklogItem).filter(BacklogItem.project_id == project.id).all()
    total = len(items)
    by_phase: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for it in items:
        by_phase[it.current_phase] = by_phase.get(it.current_phase, 0) + 1
        by_status[it.status] = by_status.get(it.status, 0) + 1

    done = by_status.get("Done", 0) + by_status.get("Approved", 0)
    blocked = by_status.get("Blocked", 0)
    in_progress = by_status.get("In Progress", 0)

    sentences = [f"{project.name}: {total} items across {len(by_phase)} phase{'s' if len(by_phase) != 1 else ''}."]
    phase_parts = [f"{n} in {phase}" for phase, n in sorted(by_phase.items(), key=lambda kv: -kv[1])[:3]]
    if phase_parts:
        sentences.append("Distribution: " + ", ".join(phase_parts) + ".")
    health = []
    if done:
        health.append(f"{done} done")
    if in_progress:
        health.append(f"{in_progress} in flight")
    if blocked:
        health.append(f"{blocked} blocked")
    sentences.append("Health: " + (", ".join(health) + "." if health else "nothing started yet."))
    if blocked:
        sentences.append(f"{blocked} blocked item{'s' if blocked != 1 else ''} need{'s' if blocked == 1 else ''} attention this week.")

    return {
        "narrative": " ".join(sentences),
        "stats": {"total": total, "by_phase": by_phase, "by_status": by_status},
        "generated_at": datetime.utcnow().isoformat(),
        "source": "template_v0",
    }
