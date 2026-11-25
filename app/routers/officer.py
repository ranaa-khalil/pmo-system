"""Officer API — the beat's status surface for the settings screen (route 10).

GET /api/officer/status — scheduler enabled/running, per-job next/last run,
the tenant's automation rules (count + enabled) and the rules master switch
(rules_enabled, default ON). Tenant-gated like every router.

PUT /api/officer/rules — {"enabled": bool} — one click off/on for the
tenant's automation rules. Writes the rules_enabled KV; the hourly sweep,
/scan and the RAID template seeding all respect it.

POST /api/officer/scan — run the rules sweep NOW for this tenant
(draft-producing: notifications + escalation tasks only, never executing).
No-ops while the tenant's rules are off.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.automation_rule import AutomationRule
from app.models.tenant import Tenant
from app.models.tenant_setting import SETTING_RULES_ENABLED
from app.models.user import User
from app.services.officer import ensure_rule_templates
from app.services.rules_engine import evaluate_rules
from app.services.scope import tenant_scoped
from app.services.settings_service import rules_enabled, set_setting
from app.services.tenant import get_current_tenant
from app.worker import JOBS, scheduler_status

router = APIRouter(prefix="/api/officer", tags=["officer"])
logger = logging.getLogger("app.officer")


@router.get("/status")
def officer_status(
    db: Session = Depends(get_db),
    current_tenant: Tenant = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    sched = scheduler_status()
    rules_total = (
        tenant_scoped(db, AutomationRule, current_tenant.id)
        .count()
    )
    rules_on_count = (
        tenant_scoped(db, AutomationRule, current_tenant.id)
        .filter(AutomationRule.enabled.is_(True))
        .count()
    )
    return {
        "scheduler": sched,
        "jobs": list(JOBS.keys()),
        "rules": {"total": rules_total, "enabled": rules_on_count},
        "rules_enabled": rules_enabled(db, current_tenant.id),
    }


@router.put("/rules")
def officer_rules_toggle(
    body: dict,
    db: Session = Depends(get_db),
    current_tenant: Tenant = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """One click off/on for the tenant's automation rules (default ON)."""
    enabled = body.get("enabled") if isinstance(body, dict) else None
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=422, detail='body must be {"enabled": bool}')
    set_setting(db, current_tenant.id, SETTING_RULES_ENABLED, "1" if enabled else "0")
    db.commit()
    logger.info(
        "Officer rules turned %s for tenant %s", "on" if enabled else "off", current_tenant.id
    )
    return {"rules_enabled": enabled}


@router.post("/scan")
def officer_scan(
    db: Session = Depends(get_db),
    current_tenant: Tenant = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """Run the rules sweep now for this tenant — draft-producing only."""
    if not rules_enabled(db, current_tenant.id):
        return {"rules": "off", "evaluated": 0, "fired": 0, "details": []}
    ensure_rule_templates(db, current_tenant)
    return evaluate_rules(db, current_tenant)
