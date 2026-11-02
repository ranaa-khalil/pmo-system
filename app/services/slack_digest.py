"""Slack digest service — builds and sends the PMO digest (D4: second).

The digest summarizes tenant-wide delivery state:
  * Progress — backlog items by status
  * RAID — open risks / assumptions / issues / dependencies
  * Time — hours logged this week
  * Releases — shipped this month

send_to_slack posts a Block Kit payload to the tenant's Incoming Webhook
URL with plain urllib — no external dependency. Network failures raise
SlackSendError so callers can surface them.
"""
import json
import logging
import urllib.request
from datetime import date, datetime, timedelta

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.release import Release
from app.models.risk import Risk
from app.models.time_entry import TimeEntry

logger = logging.getLogger("app.slack_digest")


class SlackSendError(Exception):
    pass


def build_digest(db: Session, tenant_id: int) -> dict:
    """Build the digest payload (dict) for a tenant — pure read, no sends."""
    project_ids = [
        p.id for p in db.query(Project.id).filter(Project.tenant_id == tenant_id).all()
    ]
    if not project_ids:
        return {"sections": [], "totals": {"items": 0, "raids": 0, "week_hours": 0.0}}

    # Progress — items by status
    status_rows = (
        db.query(BacklogItem.status, sa_func.count(BacklogItem.id))
        .filter(BacklogItem.project_id.in_(project_ids))
        .group_by(BacklogItem.status)
        .all()
    )
    progress = dict(status_rows)

    # RAID — open items by kind
    raid_rows = (
        db.query(Risk.kind, sa_func.count(Risk.id))
        .filter(
            Risk.project_id.in_(project_ids),
            Risk.status.in_(["Open", "In Progress", "Blocked", "Draft"]),
        )
        .group_by(Risk.kind)
        .all()
    )
    raid = dict(raid_rows)

    # Time — hours logged this week (since Monday)
    monday = date.today() - timedelta(days=date.today().weekday())
    week_hours = (
        db.query(sa_func.coalesce(sa_func.sum(TimeEntry.hours), 0))
        .filter(TimeEntry.project_id.in_(project_ids), TimeEntry.entry_date >= monday)
        .scalar()
    )

    # Releases — shipped this month
    month_start = date.today().replace(day=1)
    released = (
        db.query(Release)
        .filter(Release.project_id.in_(project_ids))
        .all()
    )
    shipped = [
        r for r in released
        if getattr(r, "shipped_at", None) and _parse_dt(r.shipped_at) >= month_start
    ]

    return {
        "progress": progress,
        "raid": raid,
        "week_hours": float(week_hours or 0.0),
        "releases_shipped": [{"name": r.name, "project_id": r.project_id} for r in shipped],
        "totals": {
            "items": sum(progress.values()),
            "raids": sum(raid.values()),
            "week_hours": float(week_hours or 0.0),
        },
    }


def _parse_dt(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def digest_text(digest: dict, tenant_name: str = "PMO") -> str:
    """Render the digest as Slack mrkdwn text."""
    lines = [f"*📊 {tenant_name} — Daily Digest*", ""]
    progress = digest.get("progress") or {}
    if progress:
        parts = [f"{status}: {count}" for status, count in sorted(progress.items())]
        lines.append("*Progress* — " + " · ".join(parts))
    raid = digest.get("raid") or {}
    if raid:
        parts = [f"{kind}: {count}" for kind, count in sorted(raid.items())]
        lines.append("*RAID open* — " + " · ".join(parts))
    week_hours = digest.get("week_hours") or 0.0
    if week_hours:
        lines.append(f"*Time* — {week_hours:.1f}h logged this week")
    shipped = digest.get("releases_shipped") or []
    if shipped:
        names = ", ".join(r["name"] for r in shipped[:5])
        lines.append(f"*Releases shipped this month* — {names}")
    totals = digest.get("totals") or {}
    lines.append("")
    lines.append(
        f"_{totals.get('items', 0)} items · {totals.get('raids', 0)} open RAID · {totals.get('week_hours', 0.0):.1f}h this week_"
    )
    return "\n".join(lines)


def send_to_slack(webhook_url: str, text: str, timeout: int = 10) -> None:
    """POST the digest to a Slack Incoming Webhook. Raises SlackSendError on failure."""
    payload = json.dumps({"text": text}).encode()
    req = urllib.request.Request(
        webhook_url, data=payload, headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status not in (200, 204):
                raise SlackSendError(f"Slack returned {resp.status}")
    except SlackSendError:
        raise
    except Exception as e:  # URLError, HTTPError, timeout
        raise SlackSendError(str(e)) from e
