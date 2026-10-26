"""Self-proposing automation (P4.2) — mine patterns, propose rules, scan coverage.

mine_rules(db, tenant) scans approvals + tasks + ActivityLog for repeated
patterns (3+ occurrences within the window) and proposes AutomationRule rows
(source="mined") with evidence. Rules are NEVER auto-enabled — a human
enables with one click. coverage_scan() reports which cold-start triggers
have no rule yet and what each would match today.
"""
import logging
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog
from app.models.approval import ApprovalRequest
from app.models.automation_rule import AutomationRule
from app.models.user_task import UserTask
from app.services.rules_engine import _hours_since, _parse_created

logger = logging.getLogger("app.automation_mining")

# A pattern needs at least this many occurrences to be a rule, not noise
MIN_PATTERN_OCCURRENCES = 3

# Cold-start rule templates: trigger → (name, description, conditions, actions)
COLD_START_TEMPLATES = {
    "approval_aging": {
        "name": "Gate aging reminder",
        "description": "Notify the gate owner when an approval sits pending past 48h",
        "conditions": {"hours_in_gate": 48},
        "actions": [{"type": "notify", "role": "gate_owner"}],
    },
    "task_overdue": {
        "name": "Overdue task escalation",
        "description": "Create a High-priority escalation task when a task is 1+ day overdue",
        "conditions": {"days_overdue": 1},
        "actions": [{"type": "create_task", "title_prefix": "Escalate: "}],
    },
    "item_sent_back": {
        "name": "Send-back notification",
        "description": "Notify the actor when a backlog item is sent back a phase",
        "conditions": {"within_hours": 24},
        "actions": [{"type": "notify", "role": "actor"}],
    },
}


def _existing_triggers(db: Session, tenant) -> set[str]:
    return {
        r.trigger
        for r in db.query(AutomationRule).filter(AutomationRule.tenant_id == tenant.id).all()
    }


def _aging_matches(db: Session, tenant) -> list:
    """All pending approvals older than 48h (no mining threshold)."""
    approvals = (
        db.query(ApprovalRequest)
        .filter(ApprovalRequest.tenant_id == tenant.id, ApprovalRequest.status == "Pending")
        .all()
    )
    return [a for a in approvals if _hours_since(a.created_at) >= 48]


def _aging_evidence(db: Session, tenant) -> dict | None:
    """Pending approvals older than 48h — the approval_aging pattern."""
    aged = _aging_matches(db, tenant)
    if len(aged) < MIN_PATTERN_OCCURRENCES:
        return None
    return {
        "matches": len(aged),
        "window": "all pending",
        "sample": [a.title for a in aged[:5]],
        "pattern": f"{len(aged)} approvals pending > 48h",
    }


def _overdue_evidence(db: Session, tenant) -> dict | None:
    """Tasks overdue by 1+ days — the task_overdue pattern."""
    tasks = (
        db.query(UserTask)
        .filter(
            UserTask.tenant_id == tenant.id,
            UserTask.status != "Completed",
            UserTask.due_date.isnot(None),
        )
        .all()
    )
    overdue = [t for t in tasks if (date.today() - t.due_date).days >= 1]
    if len(overdue) < MIN_PATTERN_OCCURRENCES:
        return None
    return {
        "matches": len(overdue),
        "window": "open tasks",
        "sample": [t.title for t in overdue[:5]],
        "pattern": f"{len(overdue)} tasks overdue by 1+ days",
    }


def _sent_back_evidence(db: Session, tenant) -> dict | None:
    """Items sent back within the last 14 days — the item_sent_back pattern."""
    since = datetime.utcnow() - timedelta(days=14)
    logs = (
        db.query(ActivityLog)
        .filter(
            ActivityLog.tenant_id == tenant.id,
            ActivityLog.entity_type == "backlog_item",
            ActivityLog.summary.like("%sent back%"),
        )
        .all()
    )
    recent = []
    for log in logs:
        dt = _parse_created(log.created_at)
        if dt and dt.replace(tzinfo=None) >= since:
            recent.append(log)
    if len(recent) < MIN_PATTERN_OCCURRENCES:
        return None
    return {
        "matches": len(recent),
        "window": "last 14 days",
        "sample": [log.summary[:120] for log in recent[:5]],
        "pattern": f"{len(recent)} send-backs in 14 days",
    }


_MINERS = {
    "approval_aging": _aging_evidence,
    "task_overdue": _overdue_evidence,
    "item_sent_back": _sent_back_evidence,
}


def mine_rules(db: Session, tenant) -> list[AutomationRule]:
    """Scan for patterns; persist proposed rules (source=mined, enabled=False).

    Skips triggers that already have any rule for the tenant — one rule per
    trigger, and the human edits conditions before enabling.
    """
    existing = _existing_triggers(db, tenant)
    proposed = []
    for trigger, miner in _MINERS.items():
        if trigger in existing:
            continue
        evidence = miner(db, tenant)
        if not evidence:
            continue
        template = COLD_START_TEMPLATES[trigger]
        rule = AutomationRule(
            tenant_id=tenant.id,
            name=template["name"],
            description=template["description"],
            trigger=trigger,
            conditions=dict(template["conditions"]),
            actions=[dict(a) for a in template["actions"]],
            source="mined",
            evidence=evidence,
            enabled=False,  # never auto-enabled
        )
        db.add(rule)
        proposed.append(rule)
    if proposed:
        db.commit()
    return proposed


def coverage_scan(db: Session, tenant) -> dict:
    """Which cold-start triggers lack a rule, and what each would match today.

    Returns {"gaps": [{trigger, name, would_match, sample}], "covered": [triggers]}.
    would_match counts raw occurrences (no mining threshold) — the scan shows
    potential even below the 3-occurrence mining bar.
    """
    existing = _existing_triggers(db, tenant)
    gaps = []
    covered = []
    for trigger, template in COLD_START_TEMPLATES.items():
        if trigger in existing:
            covered.append(trigger)
            continue
        if trigger == "approval_aging":
            matches = _aging_matches(db, tenant)
            sample = [a.title for a in matches[:3]]
        else:
            evidence = _MINERS[trigger](db, tenant)
            matches = evidence or {"matches": 0}
            sample = (evidence or {}).get("sample", [])[:3]
        gaps.append({
            "trigger": trigger,
            "name": template["name"],
            "description": template["description"],
            "would_match": len(matches) if isinstance(matches, list) else matches.get("matches", 0),
            "sample": sample,
        })
    return {"gaps": gaps, "covered": covered}
