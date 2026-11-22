"""KPI coverage — the both-direction proof that KPIs have work beneath them.

compute_coverage answers two questions at once:

- Forward (KPI → its work): for every KPI, the backlog items that carry it
  (BacklogItem.kpi_id), so each target can show the work underneath it.
- Reverse (item → its KPI): which project items are orphans (kpi_id NULL)
  and which KPIs have no work at all — the gaps that separate a PMO from a
  task tracker.

coverage_pct is the share of KPIs with ≥1 linked item; it is null when the
project has no KPIs (never invented as 100). Tenant-scoped everywhere: both
KPI.tenant_id and BacklogItem.tenant_id are filtered, so another tenant's
KPIs or items never leak into — or inflate — the numbers (their linkage
never counts).

Batched: three queries total regardless of KPI count (the KPIs, all linked
items in one IN query, the unlinked orphan pool once) — the `_work_items`
pattern from routers/today.py, never N+1 per KPI.
"""
from sqlalchemy.orm import Session

from app.models.backlog_item import BacklogItem
from app.models.kpi import KPI


def compute_coverage(db: Session, tenant_id: int, project_id: int) -> dict:
    """Both-direction KPI coverage for one project: KPI → its items, item → its KPI.

    Returns the coverage percentage (null when the project has no KPIs), the
    per-KPI work blocks, the orphan item count + sample, and the count of
    KPIs with zero work beneath them.
    """
    # 1. The project's KPIs (tenant-scoped — a foreign tenant's KPI pointing
    #    at this project id is invisible here).
    kpis = (
        db.query(KPI)
        .filter(KPI.project_id == project_id, KPI.tenant_id == tenant_id)
        .order_by(KPI.id)
        .all()
    )
    kpi_ids = [k.id for k in kpis]

    # 2. ALL linked items in one query, bucketed by kpi_id in Python —
    #    tenant-scoped so a foreign tenant's item linked to one of these
    #    KPIs never counts as its work.
    items_by_kpi: dict[int, list[BacklogItem]] = {}
    if kpi_ids:
        linked = (
            db.query(BacklogItem)
            .filter(BacklogItem.kpi_id.in_(kpi_ids), BacklogItem.tenant_id == tenant_id)
            .order_by(BacklogItem.created_at.desc(), BacklogItem.id.desc())
            .all()
        )
        for it in linked:
            items_by_kpi.setdefault(it.kpi_id, []).append(it)

    # 3. The orphan pool: this project's items with no KPI at all. One query
    #    yields both the count and the newest-first sample for the UI chips.
    orphans = (
        db.query(BacklogItem)
        .filter(
            BacklogItem.project_id == project_id,
            BacklogItem.kpi_id.is_(None),
            BacklogItem.tenant_id == tenant_id,
        )
        .order_by(BacklogItem.created_at.desc(), BacklogItem.id.desc())
        .all()
    )

    kpi_blocks = [
        {
            "id": k.id,
            "name": k.name,
            "category": k.category,
            "target_value": k.target_value,
            "current_value": k.current_value,
            "unit": k.unit,
            "item_count": len(items_by_kpi.get(k.id, [])),
            "items": [
                {"id": it.id, "title": it.title, "current_phase": it.current_phase, "status": it.status}
                for it in items_by_kpi.get(k.id, [])
            ],
        }
        for k in kpis
    ]

    with_work = sum(1 for block in kpi_blocks if block["item_count"] > 0)

    return {
        "project_id": project_id,
        "kpi_total": len(kpis),
        "kpis_with_work": with_work,
        # No KPIs → no coverage to report: null, never an invented 100.
        "coverage_pct": round(with_work / len(kpis) * 100) if kpis else None,
        "kpis_without_work": len(kpis) - with_work,
        "kpis": kpi_blocks,
        "unlinked_items": len(orphans),
        "unlinked_sample": [
            {"id": it.id, "title": it.title, "current_phase": it.current_phase}
            for it in orphans[:10]
        ],
    }
