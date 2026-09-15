"""Usage tracking service — count metrics per tenant and enforce quotas.

Provides:
- record_usage(): snapshot current usage for a tenant (called periodically)
- get_usage(): get current usage counts
- check_quota(): verify a tenant can add more of a resource
- get_quota_headers(): return X-Quota-* headers for API responses
"""
from datetime import date as _date

from fastapi import HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.release import Release
from app.models.tenant import PLAN_LIMITS, Tenant, TenantMembership
from app.models.usage_record import (
    METRIC_BACKLOG_ITEMS,
    METRIC_PROJECTS,
    METRIC_RELEASES,
    METRIC_USERS,
    UsageRecord,
)


def _today() -> str:
    return _date.today().isoformat()


def get_usage_counts(db: Session, tenant_id: int) -> dict:
    """Get current usage counts for a tenant."""
    return {
        METRIC_USERS: db.query(TenantMembership).filter(TenantMembership.tenant_id == tenant_id).count(),
        METRIC_PROJECTS: db.query(Project).filter(Project.tenant_id == tenant_id).count(),
        METRIC_RELEASES: db.query(Release).filter(Release.tenant_id == tenant_id).count(),
        METRIC_BACKLOG_ITEMS: db.query(BacklogItem).filter(BacklogItem.tenant_id == tenant_id).count(),
    }


def get_limits(plan: str) -> dict:
    """Get plan limits for a tenant."""
    plan_limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    return {
        METRIC_USERS: plan_limits["users"],
        METRIC_PROJECTS: plan_limits["projects"],
        METRIC_RELEASES: 999999,  # No explicit limit on releases
        METRIC_BACKLOG_ITEMS: 999999,  # No explicit limit on backlog items
    }


def record_usage(db: Session, tenant_id: int):
    """Snapshot current usage for a tenant. Called periodically (e.g., daily).

    Creates or updates usage records for today.
    """
    counts = get_usage_counts(db, tenant_id)
    today = _today()

    for metric, count in counts.items():
        record = db.query(UsageRecord).filter(
            UsageRecord.tenant_id == tenant_id,
            UsageRecord.metric == metric,
            UsageRecord.date == today,
        ).first()

        if record:
            record.count = count
        else:
            record = UsageRecord(
                tenant_id=tenant_id,
                metric=metric,
                count=count,
                date=today,
            )
            db.add(record)

    db.commit()


def check_quota(db: Session, tenant: Tenant, metric: str) -> bool:
    """Check if a tenant can add one more of the given metric.

    Returns True if within quota, raises HTTPException if over quota.
    """
    limits = get_limits(tenant.plan)
    limit = limits.get(metric, 999999)

    if limit >= 999999:
        return True

    counts = get_usage_counts(db, tenant.id)
    current = counts.get(metric, 0)

    if current >= limit:
        raise HTTPException(
            status_code=403,
            detail=f"Quota exceeded: {metric} limit is {limit} (current: {current}). "
                   f"Upgrade your plan to add more.",
        )

    return True


def get_quota_headers(db: Session, tenant: Tenant) -> dict:
    """Return X-Quota-* headers for API responses."""
    counts = get_usage_counts(db, tenant.id)
    limits = get_limits(tenant.plan)

    headers = {}
    for metric in [METRIC_USERS, METRIC_PROJECTS, METRIC_RELEASES, METRIC_BACKLOG_ITEMS]:
        limit = limits.get(metric, 999999)
        current = counts.get(metric, 0)
        if limit < 999999:
            headers[f"X-Quota-{metric.replace('_', '-').title()}"] = f"{current}/{limit}"
    return headers


def get_usage_history(db: Session, tenant_id: int, days: int = 30) -> dict:
    """Get usage history for the last N days (for charts)."""
    from sqlalchemy import desc
    records = db.query(UsageRecord).filter(
        UsageRecord.tenant_id == tenant_id,
    ).order_by(desc(UsageRecord.date)).limit(days * 5).all()  # 5 metrics per day

    # Group by metric
    history = {}
    for r in records:
        if r.metric not in history:
            history[r.metric] = []
        history[r.metric].append({"date": r.date, "count": r.count})

    # Sort each metric's history by date
    for metric in history:
        history[metric].sort(key=lambda x: x["date"])

    return history
