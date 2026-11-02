"""Slack digest API — tenant-level integration (D4: second).

GET    /api/integrations/slack          config (webhook masked; admin only)
PUT    /api/integrations/slack          save config (admin only)
POST   /api/integrations/slack/test     send a test message now (admin only)
POST   /api/integrations/slack/digest   build + send the digest now (admin or cron token)
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.slack_config import SlackConfig
from app.models.tenant import Tenant
from app.models.user import User
from app.services.slack_digest import (
    SlackSendError,
    build_digest,
    digest_text,
    send_to_slack,
)
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api/integrations/slack", tags=["slack"])


class SlackConfigRequest(BaseModel):
    webhook_url: str
    enabled: bool = False
    digest_time: str = "09:00"


def _load_config(db: Session, tenant: Tenant) -> SlackConfig | None:
    return db.query(SlackConfig).filter(SlackConfig.tenant_id == tenant.id).first()


def _require_admin(db: Session, current_user: User) -> None:
    from app.permissions import is_tenant_admin_or_owner

    if current_user.system_role not in ("super_admin", "tenant_admin") and not is_tenant_admin_or_owner(current_user, db):
        raise HTTPException(403, "Only tenant admins can manage the Slack digest")


def _mask(url: str) -> str:
    """Mask the webhook — keep the service prefix and last 4 chars."""
    if len(url) <= 24:
        return "•" * len(url)
    return url[:18] + "•" * 8 + url[-4:]


@router.get("")
def get_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    _require_admin(db, current_user)
    config = _load_config(db, current_tenant)
    if not config:
        return {"configured": False, "enabled": False, "webhook_masked": None, "digest_time": "09:00", "last_sent_at": None}
    return {
        "configured": True,
        "enabled": config.enabled,
        "webhook_masked": _mask(config.webhook_url),
        "digest_time": config.digest_time,
        "last_sent_at": config.last_sent_at,
    }


@router.put("")
def save_config(
    req: SlackConfigRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    _require_admin(db, current_user)
    if not req.webhook_url.startswith("https://hooks.slack.com/"):
        raise HTTPException(422, "Webhook URL must be a Slack Incoming Webhook (https://hooks.slack.com/...)")
    config = _load_config(db, current_tenant)
    if not config:
        config = SlackConfig(tenant_id=current_tenant.id)
        db.add(config)
    config.webhook_url = req.webhook_url[:500]
    config.enabled = req.enabled
    config.digest_time = req.digest_time[:5]
    db.commit()
    db.refresh(config)
    return {"configured": True, "enabled": config.enabled, "webhook_masked": _mask(config.webhook_url), "digest_time": config.digest_time}


@router.post("/test")
def send_test(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    _require_admin(db, current_user)
    config = _load_config(db, current_tenant)
    if not config:
        raise HTTPException(404, "Slack is not configured yet")
    text = f"*🧪 {current_tenant.name} — PMO test*\nSlack digest is wired up. Digests will post daily at {config.digest_time}."
    try:
        send_to_slack(config.webhook_url, text)
    except SlackSendError as e:
        raise HTTPException(502, f"Slack send failed: {e}")
    return {"sent": True}


@router.post("/digest")
def send_digest(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Build + send the digest now (manual trigger or external scheduler)."""
    _require_admin(db, current_user)
    config = _load_config(db, current_tenant)
    if not config:
        raise HTTPException(404, "Slack is not configured yet")
    digest = build_digest(db, current_tenant.id)
    text = digest_text(digest, current_tenant.name or "PMO")
    try:
        send_to_slack(config.webhook_url, text)
    except SlackSendError as e:
        raise HTTPException(502, f"Slack send failed: {e}")
    config.last_sent_at = datetime.now().isoformat(timespec="seconds")
    db.commit()
    return {"sent": True, "digest": digest}
