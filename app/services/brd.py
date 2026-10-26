"""BRD depth (P4.3) — requirements → epics → features coverage report.

build_brd_coverage walks the project's traceability chain: the intake drafts
that promised epics/features, the backlog items they produced, and the gaps
in both directions — promised-but-never-created requirements (draft epics
with no items) and created-but-never-traced items (no intake source).
"""
import json
import logging

from sqlalchemy.orm import Session

from app.models.ai_interaction import AiInteraction
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.tenant import Tenant

logger = logging.getLogger("app.brd")


def _promised_epics(db: Session, tenant: Tenant, project: Project) -> dict[str, list[str]]:
    """Epics promised by the project's applied intake drafts → feature titles."""
    drafts = (
        db.query(AiInteraction)
        .filter(
            AiInteraction.tenant_id == tenant.id,
            AiInteraction.project_id == project.id,
            AiInteraction.kind == "intake",
        )
        .order_by(AiInteraction.id.desc())
        .limit(20)
        .all()
    )
    promised: dict[str, list[str]] = {}
    for row in drafts:
        # The draft tree lives in `answer` (stored at finish) or `proposal`
        for raw in (row.answer, row.proposal):
            if not raw:
                continue
            try:
                draft = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if not isinstance(draft, dict) or "epics" not in draft:
                continue
            for epic in draft.get("epics", []):
                name = epic.get("name") or "Ungrouped"
                features = [f.get("title", "") for f in epic.get("features", []) if f.get("title")]
                bucket = promised.setdefault(name, [])
                for title in features:
                    if title not in bucket:
                        bucket.append(title)
    return promised


def build_brd_coverage(db: Session, tenant: Tenant, project: Project) -> dict:
    """The requirements → epics → features traceability report.

    Returns:
        epics: per-epic {epic, feature_count, traced (all items intake-sourced),
               items (titles)}
        requirement_gaps: draft-promised epics that produced no backlog items
        summary: totals (items, untraced, promised epics, gap count)
    """
    items = (
        db.query(BacklogItem)
        .filter(BacklogItem.project_id == project.id, BacklogItem.tenant_id == tenant.id)
        .order_by(BacklogItem.epic, BacklogItem.id)
        .all()
    )

    by_epic: dict[str, list[BacklogItem]] = {}
    for item in items:
        by_epic.setdefault(item.epic or "Ungrouped", []).append(item)

    def _is_traced(item: BacklogItem) -> bool:
        return bool(item.description) and "[Source: Intake draft" in item.description

    epics = []
    untraced = 0
    for epic_name, epic_items in sorted(by_epic.items()):
        epic_untraced = sum(1 for i in epic_items if not _is_traced(i))
        untraced += epic_untraced
        epics.append({
            "epic": epic_name,
            "feature_count": len(epic_items),
            "traced": epic_untraced == 0,
            "items": [i.title for i in epic_items],
            "phases": sorted({i.current_phase for i in epic_items}),
        })

    # Requirement gaps: draft-promised epics with zero items in this project
    promised = _promised_epics(db, tenant, project)
    gaps = []
    for epic_name, features in promised.items():
        if epic_name not in by_epic:
            gaps.append({"epic": epic_name, "promised_features": features})

    return {
        "project_id": project.id,
        "epics": epics,
        "requirement_gaps": gaps,
        "summary": {
            "total_items": len(items),
            "total_epics": len(by_epic),
            "untraced_items": untraced,
            "promised_epics": len(promised),
            "requirement_gap_count": len(gaps),
        },
    }
