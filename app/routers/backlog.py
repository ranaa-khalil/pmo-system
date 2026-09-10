"""Backlog API router — business requirements following the 9-phase process."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.backlog_item import BacklogItem, PHASES
from app.services.notifications import log_activity, notify_item_sent_back
from app.schemas.backlog import (
    BacklogItemCreate,
    BacklogItemUpdate,
    BacklogItemResponse,
    DependencyAdd,
)
from app.services.github import GitHubService
from app.config import settings

router = APIRouter(prefix="/api", tags=["backlog"])


def _auto_export_to_github(db: Session, item: BacklogItem):
    """Auto-export a backlog item to GitHub when it reaches the configured trigger phase.

    Uses the project's GitHubBoardConfig if available, otherwise falls back to
    the project's github_repo field with basic issue creation.
    """
    from app.models.github_board_config import GitHubBoardConfig
    from datetime import datetime, timezone

    project = db.query(Project).filter(Project.id == item.project_id).first()
    if not project:
        return

    # Check for board config
    config = db.query(GitHubBoardConfig).filter(
        GitHubBoardConfig.project_id == item.project_id
    ).first()

    # Determine the repo to use
    if config and config.repo:
        repo = config.repo
    elif project.github_repo:
        repo = project.github_repo
    else:
        return  # No repo configured

    # If auto_export is explicitly disabled, skip
    if config and not config.auto_export:
        return

    # If config exists, check if the current phase matches the trigger
    if config and config.export_trigger_phase:
        if item.current_phase != config.export_trigger_phase:
            return

    # Parse labels
    labels = ["from-pmo"]
    if config and config.default_labels:
        labels = [l.strip() for l in config.default_labels.split(",") if l.strip()]

    gh = GitHubService(token=settings.github_token or None)
    try:
        issue = gh.export_backlog_item(
            repo=repo,
            title=item.title,
            description=item.description or "",
            priority=item.priority,
            item_type=item.item_type,
            epic=item.epic,
            primary_actor=item.primary_actor,
            story_points=item.story_points,
            acceptance_criteria=item.acceptance_criteria,
            dependencies_text=item.dependencies,
            pmo_item_id=item.id,
            labels=labels,
            title_prefix=config.issue_title_prefix if config else None,
            project_node_id=config.project_node_id if config else None,
            include_acceptance_criteria=config.include_acceptance_criteria if config else True,
            include_dependencies=config.include_dependencies if config else True,
        )
        if issue:
            item.github_issue_number = issue["number"]
            item.github_issue_url = issue.get("html_url", "")
            item.github_synced_at = datetime.now(timezone.utc).isoformat()
    finally:
        gh.close()


@router.post("/projects/{project_id}/backlog", response_model=BacklogItemResponse, status_code=201)
def create_backlog_item(
    project_id: int,
    item: BacklogItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new backlog item for a project."""
    if not db.query(Project).filter(Project.id == project_id).first():
        raise HTTPException(status_code=404, detail="Project not found")
    if item.project_id != project_id:
        raise HTTPException(status_code=400, detail="project_id mismatch")
    db_item = BacklogItem(**item.model_dump())
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item


@router.get("/projects/{project_id}/backlog", response_model=List[BacklogItemResponse])
def list_backlog_items(
    project_id: int,
    phase: Optional[str] = Query(None, description="Filter by phase"),
    status: Optional[str] = Query(None, description="Filter by status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List backlog items for a project, optionally filtered by phase or status."""
    query = db.query(BacklogItem).filter(BacklogItem.project_id == project_id)
    if phase:
        query = query.filter(BacklogItem.current_phase == phase)
    if status:
        query = query.filter(BacklogItem.status == status)
    return query.order_by(BacklogItem.created_at.desc()).all()


@router.put("/backlog/{item_id}", response_model=BacklogItemResponse)
def update_backlog_item(
    item_id: int,
    item_update: BacklogItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a backlog item. If phase changes to Development, sync to GitHub."""
    item = db.query(BacklogItem).filter(BacklogItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Backlog item not found")

    old_phase = item.current_phase
    updates = item_update.model_dump(exclude_unset=True)

    for field, val in updates.items():
        setattr(item, field, val)

    # GitHub sync: when item enters Development, create issue if not already synced
    if item.current_phase == "Development" and old_phase != "Development" and not item.github_issue_number:
        _auto_export_to_github(db, item)

    db.commit()
    db.refresh(item)
    return item


@router.post("/backlog/{item_id}/advance", response_model=BacklogItemResponse)
def advance_backlog_phase(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Advance a backlog item to the next item-level phase.

    Items advance through: Requirements → Design → Development → Testing → Ready for UAT.
    After Ready for UAT, items must be bundled into a release — the release then
    goes through UAT → Pre-Release → Release → Post-Release → Retrospective.
    """
    from app.models.backlog_item import ITEM_PHASES

    item = db.query(BacklogItem).filter(BacklogItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Backlog item not found")

    current_idx = ITEM_PHASES.index(item.current_phase) if item.current_phase in ITEM_PHASES else 0

    # Items cannot advance beyond "Ready for UAT" on their own
    if current_idx >= len(ITEM_PHASES) - 1:
        raise HTTPException(
            status_code=400,
            detail="Item is Ready for UAT. Add it to a release to continue through UAT, Pre-Release, and Release phases.",
        )

    item.current_phase = ITEM_PHASES[current_idx + 1]
    if item.status == "Draft":
        item.status = "In Progress"

    # GitHub sync on entering Development
    if item.current_phase == "Development" and not item.github_issue_number:
        _auto_export_to_github(db, item)

    db.commit()
    db.refresh(item)

    log_activity(db, current_user.id, current_user.name, item.project_id,
                 "backlog_item", item.id, "advanced",
                 f"Advanced '{item.title}' to {item.current_phase}")

    return item


@router.post("/backlog/{item_id}/send-back", response_model=BacklogItemResponse)
def send_back_to_development(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send a backlog item back from Testing to Development (rework).

    Only items currently in Testing can be sent back. Sets status to 'In Progress'
    and phase to 'Development'.
    """
    item = db.query(BacklogItem).filter(BacklogItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Backlog item not found")

    if item.current_phase != "Testing":
        raise HTTPException(
            status_code=400,
            detail=f"Only items in Testing can be sent back to Development. Current phase: {item.current_phase}",
        )

    item.current_phase = "Development"
    item.status = "In Progress"
    db.commit()
    db.refresh(item)

    log_activity(db, current_user.id, current_user.name, item.project_id,
                 "backlog_item", item.id, "sent_back",
                 f"Sent back '{item.title}' from Testing to Development")

    return item


@router.delete("/backlog/{item_id}", status_code=204)
def delete_backlog_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a backlog item."""
    item = db.query(BacklogItem).filter(BacklogItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Backlog item not found")
    db.delete(item)
    db.commit()


# ─────────────────────────────────────────────────────────────
# Dependency management — link backlog items to each other
# ─────────────────────────────────────────────────────────────

@router.post("/backlog/{item_id}/dependencies", response_model=BacklogItemResponse)
def add_dependency(
    item_id: int,
    dep: DependencyAdd,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark item_id as depending on depends_on_id (item_id cannot start until depends_on_id is done)."""
    item = db.query(BacklogItem).filter(BacklogItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Backlog item not found")

    target = db.query(BacklogItem).filter(BacklogItem.id == dep.depends_on_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Dependency target item not found")

    # Prevent self-dependency
    if item_id == dep.depends_on_id:
        raise HTTPException(status_code=400, detail="An item cannot depend on itself")

    # Prevent circular dependency (simple check: if target already depends on item, it's circular)
    if item in target.depends_on:
        raise HTTPException(status_code=400, detail="Circular dependency detected — the target item already depends on this item")

    # Prevent duplicate
    if target in item.depends_on:
        raise HTTPException(status_code=400, detail="Dependency already exists")

    item.depends_on.append(target)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/backlog/{item_id}/dependencies/{depends_on_id}", response_model=BacklogItemResponse)
def remove_dependency(
    item_id: int,
    depends_on_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a dependency link."""
    item = db.query(BacklogItem).filter(BacklogItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Backlog item not found")

    target = db.query(BacklogItem).filter(BacklogItem.id == depends_on_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Dependency target item not found")

    if target not in item.depends_on:
        raise HTTPException(status_code=404, detail="Dependency not found")

    item.depends_on.remove(target)
    db.commit()
    db.refresh(item)
    return item


@router.get("/projects/{project_id}/backlog/available-dependencies/{exclude_id}", response_model=List[BacklogItemResponse])
def list_available_dependencies(
    project_id: int,
    exclude_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List backlog items in a project that can be used as dependencies (excludes the item itself and its existing dependencies)."""
    item = db.query(BacklogItem).filter(BacklogItem.id == exclude_id).first()
    existing_dep_ids = {d.id for d in item.depends_on} if item else set()
    existing_dep_ids.add(exclude_id)

    items = (
        db.query(BacklogItem)
        .filter(BacklogItem.project_id == project_id)
        .filter(~BacklogItem.id.in_(existing_dep_ids))
        .order_by(BacklogItem.created_at.desc())
        .all()
    )
    return items
