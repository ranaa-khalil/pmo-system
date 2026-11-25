"""Usage tracking service — count metrics per tenant and enforce quotas.

Provides:
- record_usage(): snapshot current usage for a tenant (called periodically)
- get_usage(): get current usage counts
- check_quota(): verify a tenant can add more of a resource
- check_storage_quota(): verify an incoming upload fits the storage quota
- get_quota_headers(): return X-Quota-* headers for API responses
- derive_llm_usage_rollup(): the LLM-call rollup derived FROM llm_usage

Derivation convention (Rethink v2 Phase F3): usage_records and llm_usage
are INDEPENDENT tables (daily quota snapshots vs one row per LLM call),
so llm_usage is the record of truth for LLM calls — the ``api_calls``
metric in usage_records (METRIC_API_CALLS, defined but never written)
would be DERIVED via derive_llm_usage_rollup(), never written by a second
path. One row source (services/llm.py per-call), one derivation (here).

FR-T6 counters (AI / storage / portal) are metered from existing tables:
- ai_calls: llm_usage rows for the calendar month (one row per call, ok or
  fallback alike)
- storage_bytes: SUM(item_proofs.file_size) — uploaded proof bytes
- portals: clients with an enabled portal (views/tokens are not recorded
  anywhere — the portal JWT is stateless — so this is the countable state)
"""
from datetime import date as _date

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.backlog_item import BacklogItem
from app.models.client import Client
from app.models.project import Project
from app.models.release import Release
from app.models.tenant import Tenant, TenantMembership
from app.models.usage_record import (
    METRIC_AI_CALLS,
    METRIC_API_CALLS,
    METRIC_BACKLOG_ITEMS,
    METRIC_CLIENTS,
    METRIC_PORTALS,
    METRIC_PROJECTS,
    METRIC_RELEASES,
    METRIC_STORAGE_BYTES,
    METRIC_USERS,
    UsageRecord,
)

UNLIMITED = 999999  # count-metric sentinel — NEVER used for storage bytes


def _today() -> str:
    return _date.today().isoformat()


def ai_calls_this_month(db: Session, tenant_id: int) -> int:
    """LLM calls this calendar month — metered FROM llm_usage (one row per
    call, ok or fallback alike). created_at is a String timestamp; the LIKE
    prefix is the same pattern derive_llm_usage_rollup uses per-day."""
    from app.models.llm_usage import LlmUsage

    prefix = _date.today().strftime("%Y-%m")
    return db.query(LlmUsage).filter(
        LlmUsage.tenant_id == tenant_id,
        LlmUsage.created_at.like(f"{prefix}%"),
    ).count()


def storage_bytes_used(db: Session, tenant_id: int) -> int:
    """Sum of uploaded proof bytes — metered FROM item_proofs.file_size.
    Pre-column rows and URL-only proofs carry NULL and contribute 0."""
    from app.models.proof import ItemProof

    row = db.query(func.coalesce(func.sum(ItemProof.file_size), 0)).filter(
        ItemProof.tenant_id == tenant_id,
    ).one()
    return int(row[0] or 0)


def portals_enabled(db: Session, tenant_id: int) -> int:
    """Active client portals — metered FROM clients (the only portal state in
    existing tables: portal views/tokens are not recorded anywhere, the JWT
    is stateless). Same gate get_portal_client enforces at read time."""
    return db.query(Client).filter(
        Client.tenant_id == tenant_id,
        Client.portal_enabled == True,  # noqa: E712
        Client.portal_passcode_hash.isnot(None),
    ).count()


def get_usage_counts(db: Session, tenant_id: int) -> dict:
    """Get current usage counts for a tenant."""
    return {
        METRIC_USERS: db.query(TenantMembership).filter(TenantMembership.tenant_id == tenant_id).count(),
        METRIC_PROJECTS: db.query(Project).filter(Project.tenant_id == tenant_id).count(),
        METRIC_CLIENTS: db.query(Client).filter(Client.tenant_id == tenant_id).count(),
        METRIC_RELEASES: db.query(Release).filter(Release.tenant_id == tenant_id).count(),
        METRIC_BACKLOG_ITEMS: db.query(BacklogItem).filter(BacklogItem.tenant_id == tenant_id).count(),
        # FR-T6 counters (AI / storage / portal)
        METRIC_AI_CALLS: ai_calls_this_month(db, tenant_id),
        METRIC_STORAGE_BYTES: storage_bytes_used(db, tenant_id),
        METRIC_PORTALS: portals_enabled(db, tenant_id),
    }


def _limit(value, default: int) -> int:
    """None (absent or JSON null) means unlimited; a set value wins."""
    return default if value is None else int(value)


def get_limits(tenant: Tenant) -> dict:
    """Get plan limits for a tenant — reads from tenant.limits JSON column
    (propagated from the assigned Plan, not configurable per-tenant).

    Count metrics use UNLIMITED (999999); storage bytes use None — the count
    sentinel is only ~1MB in bytes and would shadow every real storage limit.
    """
    import json as _json
    limits = _json.loads(tenant.limits) if tenant.limits else {}
    return {
        METRIC_USERS: _limit(limits.get("max_users"), UNLIMITED),
        METRIC_PROJECTS: _limit(limits.get("max_projects"), UNLIMITED),
        METRIC_CLIENTS: _limit(limits.get("max_clients"), UNLIMITED),
        METRIC_RELEASES: UNLIMITED,  # No limit on releases
        METRIC_BACKLOG_ITEMS: UNLIMITED,  # No limit on backlog items
        # FR-T6 counters (AI / storage / portal)
        METRIC_AI_CALLS: _limit(limits.get("max_ai_calls"), UNLIMITED),
        METRIC_STORAGE_BYTES: limits.get("max_storage_bytes"),  # None = unlimited
        METRIC_PORTALS: _limit(limits.get("max_portals"), UNLIMITED),
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


def _human_bytes(n: int) -> str:
    """Human-readable byte size for quota messages and headers."""
    n = int(n or 0)
    for unit, factor in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if n >= factor:
            return f"{n / factor:.1f} {unit}"
    return f"{n} B"


def check_quota(db: Session, tenant: Tenant, metric: str) -> bool:
    """Check if a tenant can add one more of the given metric.

    Returns True if within quota, raises HTTPException if over quota.
    """
    if metric == METRIC_STORAGE_BYTES:
        # Bytes: the count sentinel (999999) is ~1MB and would shadow every
        # real storage limit — storage enforces through its own check.
        check_storage_quota(db, tenant, 0)
        return True

    limits = get_limits(tenant)
    limit = limits.get(metric, UNLIMITED)

    if limit >= UNLIMITED:
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


def check_storage_quota(db: Session, tenant: Tenant, incoming_bytes: int) -> None:
    """Raise 403 when an incoming upload would exceed the storage quota.

    Bytes metered FROM item_proofs.file_size; unlimited is None/absent
    (never the 999999 count sentinel, which is only ~1MB in bytes).
    """
    limit = get_limits(tenant).get(METRIC_STORAGE_BYTES)
    if limit is None:
        return
    current = storage_bytes_used(db, tenant.id)
    if current + incoming_bytes > int(limit):
        raise HTTPException(
            status_code=403,
            detail=f"Quota exceeded: storage limit is {_human_bytes(limit)} "
                   f"(used: {_human_bytes(current)}); this upload adds "
                   f"{_human_bytes(incoming_bytes)}. Upgrade your plan for more storage.",
        )


def get_quota_headers(db: Session, tenant: Tenant) -> dict:
    """Return X-Quota-* headers for API responses."""
    counts = get_usage_counts(db, tenant.id)
    limits = get_limits(tenant)

    headers = {}
    for metric in [
        METRIC_USERS, METRIC_PROJECTS, METRIC_CLIENTS, METRIC_RELEASES,
        METRIC_BACKLOG_ITEMS, METRIC_AI_CALLS, METRIC_PORTALS, METRIC_STORAGE_BYTES,
    ]:
        limit = limits.get(metric, None if metric == METRIC_STORAGE_BYTES else UNLIMITED)
        current = counts.get(metric, 0)
        if metric == METRIC_STORAGE_BYTES:
            if limit is not None:
                headers[f"X-Quota-{metric.replace('_', '-').title()}"] = (
                    f"{_human_bytes(current)}/{_human_bytes(limit)}"
                )
        elif limit is not None and limit < UNLIMITED:
            headers[f"X-Quota-{metric.replace('_', '-').title()}"] = f"{current}/{limit}"
    return headers


def get_usage_history(db: Session, tenant_id: int, days: int = 30) -> dict:
    """Get usage history for the last N days (for charts)."""
    from sqlalchemy import desc
    records = db.query(UsageRecord).filter(
        UsageRecord.tenant_id == tenant_id,
    ).order_by(desc(UsageRecord.date)).limit(days * 8).all()  # 8 metrics per day (5 base + FR-T6 AI/storage/portal)

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


def derive_llm_usage_rollup(db: Session, tenant_id: int, day: str | None = None) -> dict:
    """Derive the per-day LLM-call rollup FROM llm_usage — the ONE derivation.

    Rethink v2 Phase F3: ``usage_records derived from llm_usage``. llm_usage
    is the record of truth for LLM calls (one row per call, written by
    services/llm.py); the ``api_calls`` metric in usage_records
    (METRIC_API_CALLS — defined but never written anywhere) is DERIVED from
    those rows here instead of being written by a second path. Read-only:
    no writes, no migration, no second source of truth.

    Returns: {metric: 'api_calls', date, calls, ok, fallback,
    avg_latency_ms} for the tenant's llm_usage rows on ``day`` (today when
    omitted); a day with no rows derives zeros, never guesses.
    """
    from app.models.llm_usage import LlmUsage

    day = day or _today()
    rows = (
        db.query(LlmUsage)
        .filter(
            LlmUsage.tenant_id == tenant_id,
            LlmUsage.created_at.like(f"{day}%"),
        )
        .order_by(LlmUsage.id)
        .all()
    )
    calls = len(rows)
    ok = sum(1 for r in rows if r.ok)
    avg_latency = round(sum(r.latency_ms for r in rows) / calls) if calls else 0
    return {
        "metric": METRIC_API_CALLS,
        "date": day,
        "calls": calls,
        "ok": ok,
        "fallback": calls - ok,
        "avg_latency_ms": avg_latency,
    }
