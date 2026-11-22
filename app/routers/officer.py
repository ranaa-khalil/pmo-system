"""Officer API — the beat's status surface for the settings screen (route 10).

GET /api/officer/status — scheduler enabled/running, per-job next/last run,
the tenant's automation rules (count + enabled). Tenant-gated like every
router.

POST /api/officer/scan — run the rules sweep NOW for this tenant
(draft-producing: notifications + escalation tasks only, never executing).
"""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.automation_rule import AutomationRule
from app.models.tenant import Tenant
from app.models.user import User
from app.services.officer import ensure_rule_templates
from app.services.rules_engine import evaluate_rules
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
        db.query(AutomationRule)
        .filter(AutomationRule.tenant_id == current_tenant.id)
        .count()
    )
    rules_enabled = (
        db.query(AutomationRule)
        .filter(AutomationRule.tenant_id == current_tenant.id)
        .filter(AutomationRule.enabled.is_(True))
        .count()
    )
    return {
        "scheduler": sched,
        "jobs": list(JOBS.keys()),
        "rules": {"total": rules_total, "enabled": rules_enabled},
    }


@router.post("/scan")
def officer_scan(
    db: Session = Depends(get_db),
    current_tenant: Tenant = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """Run the rules sweep now for this tenant — draft-producing only."""
    ensure_rule_templates(db, current_tenant)
    return evaluate_rules(db, current_tenant)
