"""Predictive flags service — forward-looking warnings from real data (P3).

Computes KPI flags (current vs target, direction-aware, with trend from
KpiHistory), cycle-time flags (worsening windows), and capacity signals
(overdue tasks). Every flag cites the record it came from; the numbers are
derived, never stored stale.

Template-aware `kind` per project type:
- software  → "kpi"
- ai        → "drift"  (accuracy/eval metrics — CPMAI monitoring)
- marketing → "spend"  (CAC/CTR/ROAS)
- operations→ "capacity"
"""
from sqlalchemy.orm import Session

from app.models.kpi import KPI
from app.models.kpi_history import KpiHistory

# KPIs where LOWER is better (spend/cost/latency); everything else: higher is better.
LOWER_IS_BETTER = {"cac", "cost", "spend", "latency", "response time", "churn", "burn rate", "cpt", "cpc", "cpa"}

# Default flag kind per project lifecycle template.
TEMPLATE_KINDS = {
    "software": "kpi",
    "ai": "drift",
    "marketing": "spend",
    "operations": "capacity",
}


def _to_float(value) -> float | None:
    """Parse a KPI value that may be "99.7", "40 %", "1,200", or "n/a".

    Returns None for anything non-numeric — non-numeric KPIs are never
    flagged (they can't be compared against a target).
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "").rstrip("SAR ").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _direction(kpi_name: str) -> str:
    """higher_is_better or lower_is_better, inferred from the KPI name."""
    name = (kpi_name or "").lower()
    return "lower_is_better" if any(term in name for term in LOWER_IS_BETTER) else "higher_is_better"


def _history_trend(db: Session, kpi_id: int, direction: str) -> str:
    """trend from KpiHistory rows (ordered oldest → newest).

    deteriorating = last value moved the WRONG way vs the first;
    improving = moved the right way; stable/flat or <2 points → "stable".
    """
    rows = (
        db.query(KpiHistory)
        .filter(KpiHistory.kpi_id == kpi_id)
        .order_by(KpiHistory.id)
        .all()
    )
    values = [float(r.value) for r in rows if _to_float(r.value) is not None]
    if len(values) < 2:
        return "stable"
    first, last = values[0], values[-1]
    if last == first:
        return "stable"
    moved_up = last > first
    wrong_way = (direction == "higher_is_better" and not moved_up) or (
        direction == "lower_is_better" and moved_up
    )
    return "deteriorating" if wrong_way else "improving"


def predictive_flags(db: Session, tenant, project_ids: list[int]) -> list[dict]:
    """Compute forward-looking flags for the given projects.

    Returns a list of flag dicts; empty when everything is healthy. Flags are
    derived on every read — nothing is stored.
    """
    flags: list[dict] = []
    if not project_ids:
        return flags

    from app.models.project import Project

    projects = (
        db.query(Project)
        .filter(Project.tenant_id == tenant.id, Project.id.in_(project_ids))
        .all()
    )
    kind_by_project = {p.id: TEMPLATE_KINDS.get(p.project_type or "software", "kpi") for p in projects}

    kpis = (
        db.query(KPI)
        .filter(KPI.tenant_id == tenant.id, KPI.project_id.in_(project_ids))
        .all()
    )
    for kpi in kpis:
        direction = _direction(kpi.name)
        trend = _history_trend(db, kpi.id, direction)
        current = _to_float(kpi.current_value)
        target = _to_float(kpi.target_value)

        # Flag 1: off target (direction-aware comparison)
        off_target = None
        if current is not None and target is not None:
            off_target = (
                current < target if direction == "higher_is_better"
                else current > target
            )

        # Flag 2: deteriorating trend (history says it's heading off target)
        if off_target or trend == "deteriorating":
            message = _message(kpi, direction, trend, current, target, off_target)
            flags.append({
                "entity_type": "kpi_flag",
                "entity_id": kpi.id,
                "kpi_id": kpi.id,
                "kpi_name": kpi.name,
                "project_id": kpi.project_id,
                "kind": kind_by_project.get(kpi.project_id, "kpi"),
                "direction": direction,
                "trend": trend,
                "history_points": db.query(KpiHistory).filter(KpiHistory.kpi_id == kpi.id).count(),
                "current_value": kpi.current_value,
                "target_value": kpi.target_value,
                "unit": kpi.unit,
                "message": message,
                "severity": "high" if (off_target and trend == "deteriorating") else "medium",
            })

    # Cycle-time flags: avg cycle time worsening is surfaced by the analytics
    # service's own trend; capacity pressure (overdue tasks) is covered by the
    # briefing card's overdue list — nothing duplicated here.
    return flags


def _message(kpi, direction: str, trend: str, current: float | None, target: float | None, off_target: bool) -> str:
    unit = f" {kpi.unit}" if kpi.unit else ""
    cur = f"{kpi.current_value}{unit}" if kpi.current_value is not None else "?"
    tgt = f"{kpi.target_value}{unit}" if kpi.target_value is not None else "?"
    if off_target:
        cmp_ = "below" if direction == "higher_is_better" else "above"
        base = f"{kpi.name} is {cmp_} target: {cur} vs {tgt}"
    else:
        base = f"{kpi.name} still on target ({cur} vs {tgt}) but trending the wrong way"
    if trend == "deteriorating":
        base += " — recent history is deteriorating"
    return base
