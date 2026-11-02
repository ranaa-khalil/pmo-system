"""Agent Library API — NL rule generation + manual automation-rule CRUD.

NL → rule mapping is deterministic (keyword-based, no LLM): unmetered,
testable, and human-gated — the draft is previewed and saved explicitly.
Rules are never auto-enabled; a human flips enabled=True.
"""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.automation_rule import RULE_ACTIONS, RULE_TRIGGERS, AutomationRule
from app.models.tenant import Tenant
from app.models.user import User
from app.services.notifications import log_activity
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api/automation", tags=["agents"])

# Roles the parser recognizes in NL descriptions
_KNOWN_ROLES = [
    "gate owner", "release manager", "product owner", "tech lead",
    "qa lead", "devops lead", "dev lead", "security officer", "stakeholder", "pm",
]


class RuleGenerate(BaseModel):
    description: str


class RuleCreate(BaseModel):
    name: str
    trigger: str
    conditions: dict | None = None
    actions: list = None
    description: str | None = None
    enabled: bool = False


class RuleUpdate(BaseModel):
    name: str | None = None
    trigger: str | None = None
    conditions: dict | None = None
    actions: list = None
    description: str | None = None
    enabled: bool | None = None


def _extract_hours(text: str) -> int | None:
    m = re.search(r"(\d+)\s*hour", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*day", text)
    if m:
        return int(m.group(1)) * 24
    return None


def generate_rule_draft(description: str) -> dict:
    """Deterministic NL → rule draft (keyword mapping over the shared vocabulary)."""
    text = (description or "").lower()
    trigger = None
    conditions = None

    hours = _extract_hours(text)
    if ("approval" in text or "gate" in text) and ("stuck" in text or "aging" in text or "sitting" in text or hours is not None):
        trigger = "approval_aging"
        conditions = {"hours_in_gate": hours if hours is not None else 48}
    elif "overdue" in text or ("task" in text and "due" in text and "past" in text):
        trigger = "task_overdue"
    elif "sent back" in text or "sent-back" in text or "rejected" in text:
        trigger = "item_sent_back"
    elif "blocked" in text or "blocker" in text:
        trigger = "item_blocked"
    elif "kpi" in text:
        trigger = "kpi_off_target"
    elif "release" in text and ("advance" in text or "move" in text or "phase" in text):
        trigger = "release_advanced"

    actions = []
    for role in _KNOWN_ROLES:
        if role in text:
            actions.append({
                "type": "notify",
                "role": "gate_owner" if role == "gate owner" else role.title().replace("Pm", "PM"),
            })
            break
    if "task" in text and ("create" in text or "escalate" in text or "follow" in text):
        actions.append({"type": "create_task"})
    if "flag" in text or "briefing" in text:
        actions.append({"type": "flag"})
    if not actions:
        actions = [{"type": "notify"}]

    return {
        "name": (description or "").strip()[:100],
        "trigger": trigger,
        "conditions": conditions,
        "actions": actions,
        "source": "manual",
        "nl_description": description,
    }


def _rule_payload(rule: AutomationRule) -> dict:
    return {
        "id": rule.id,
        "name": rule.name,
        "description": rule.description,
        "trigger": rule.trigger,
        "conditions": rule.conditions,
        "actions": rule.actions,
        "source": rule.source,
        "enabled": rule.enabled,
        "fire_count": rule.fire_count,
        "last_fired_at": rule.last_fired_at,
        "created_at": rule.created_at,
    }


@router.post("/generate")
def generate_rule(
    body: RuleGenerate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """NL description → rule draft (preview only — save explicitly)."""
    text = (body.description or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Describe the automation in plain language")
    draft = generate_rule_draft(text)
    if not draft["trigger"]:
        raise HTTPException(
            status_code=422,
            detail=(
                "Couldn't map that to a trigger. Try mentioning one of: "
                + ", ".join(RULE_TRIGGERS)
            ),
        )
    return draft


@router.get("/rules")
def list_rules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    rules = db.query(AutomationRule).filter(
        AutomationRule.tenant_id == current_tenant.id
    ).order_by(AutomationRule.created_at.desc()).all()
    return [_rule_payload(r) for r in rules]


@router.post("/rules", status_code=201)
def create_rule(
    body: RuleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Create a rule. Never auto-enabled: enabled must be requested explicitly."""
    if body.trigger not in RULE_TRIGGERS:
        raise HTTPException(status_code=400, detail=f"trigger must be one of: {RULE_TRIGGERS}")
    if not body.actions:
        raise HTTPException(status_code=400, detail="At least one action is required")
    for action in body.actions:
        if not isinstance(action, dict) or action.get("type") not in RULE_ACTIONS:
            raise HTTPException(status_code=400, detail=f"action types must be from: {RULE_ACTIONS}")
    rule = AutomationRule(
        tenant_id=current_tenant.id,
        name=(body.name or "").strip() or "Untitled agent",
        description=body.description,
        trigger=body.trigger,
        conditions=body.conditions,
        actions=body.actions,
        source="manual",
        enabled=bool(body.enabled),  # human-gated: explicit only
        created_by=current_user.id,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    log_activity(db, current_user.id, current_user.name, None,
                 "automation_rule", rule.id, "created",
                 f"Created agent: {rule.name[:80]}")
    return _rule_payload(rule)


@router.put("/rules/{rule_id}")
def update_rule(
    rule_id: int,
    body: RuleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    rule = db.query(AutomationRule).filter(
        AutomationRule.id == rule_id, AutomationRule.tenant_id == current_tenant.id
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    if body.trigger is not None and body.trigger not in RULE_TRIGGERS:
        raise HTTPException(status_code=400, detail=f"trigger must be one of: {RULE_TRIGGERS}")
    updates = body.model_dump(exclude_unset=True)
    for field, val in updates.items():
        setattr(rule, field, val)
    db.commit()
    db.refresh(rule)
    return _rule_payload(rule)


@router.delete("/rules/{rule_id}")
def delete_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    rule = db.query(AutomationRule).filter(
        AutomationRule.id == rule_id, AutomationRule.tenant_id == current_tenant.id
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()
    return {"detail": "Rule deleted"}
