"""Backlog API router — business requirements following the 9-phase process."""

from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.backlog import (
    BacklogItemBrief,
    BacklogItemCreate,
    BacklogItemResponse,
    BacklogItemUpdate,
    BoardReorder,
    DependencyAdd,
    SubitemTree,
)
from app.services.github import GitHubService
from app.services.notifications import log_activity
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api", tags=["backlog"])


def _auto_export_to_github(db: Session, item: BacklogItem, tenant_id: int):
    """Auto-export a backlog item to GitHub when it reaches the configured trigger phase.

    Uses the project's GitHubBoardConfig if available, otherwise falls back to
    the project's github_repo field with basic issue creation.
    """
    from datetime import datetime

    from app.models.github_board_config import GitHubBoardConfig

    project = db.query(Project).filter(Project.id == item.project_id, Project.tenant_id == tenant_id).first()
    if not project:
        return

    # Check for board config
    config = db.query(GitHubBoardConfig).filter(
        GitHubBoardConfig.project_id == item.project_id,
        GitHubBoardConfig.tenant_id == tenant_id,
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
            item.github_synced_at = datetime.now(UTC).isoformat()
    finally:
        gh.close()


@router.post("/projects/{project_id}/backlog", response_model=BacklogItemResponse, status_code=201)
def create_backlog_item(
    project_id: int,
    item: BacklogItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Create a new backlog item for a project.

    Dynamic: the item starts at the project's lifecycle template's first phase
    (Requirements for Software/SDLC/Hybrid, Agent Intent for ADLC), so a new
    ADLC project's items never begin on a Software phase by mistake.
    """
    if not db.query(Project).filter(Project.id == project_id, Project.tenant_id == current_tenant.id).first():
        raise HTTPException(status_code=404, detail="Project not found")
    if item.project_id != project_id:
        raise HTTPException(status_code=400, detail="project_id mismatch")
    if item.parent_item_id:
        parent = db.query(BacklogItem).filter(
            BacklogItem.id == item.parent_item_id,
            BacklogItem.tenant_id == current_tenant.id,
            BacklogItem.project_id == project_id,
        ).first()
        if not parent:
            raise HTTPException(status_code=400, detail="Parent item not found in this project")
        if parent.parent_item_id:
            raise HTTPException(status_code=400, detail="Sub-items cannot nest — one level only")
    payload = item.model_dump()
    if not payload.get("current_phase"):
        from app.services.lifecycle import item_phases

        project = db.query(Project).filter(Project.id == project_id).first()
        payload["current_phase"] = item_phases(getattr(project, "project_type", None))[0]
    db_item = BacklogItem(**payload, tenant_id=current_tenant.id)
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item


@router.get("/projects/{project_id}/backlog", response_model=list[BacklogItemResponse])
def list_backlog_items(
    project_id: int,
    phase: str | None = Query(None, description="Filter by phase"),
    status: str | None = Query(None, description="Filter by status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """List backlog items for a project, optionally filtered by phase or status."""
    query = db.query(BacklogItem).filter(BacklogItem.project_id == project_id, BacklogItem.tenant_id == current_tenant.id)
    if phase:
        query = query.filter(BacklogItem.current_phase == phase)
    if status:
        query = query.filter(BacklogItem.status == status)
    return query.order_by(BacklogItem.created_at.desc()).all()


@router.put("/backlog/board-order", response_model=None)
def reorder_backlog_board(
    order: BoardReorder,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Persist manual card order on the Kanban board.

    Body: {"order": [{"id": 34, "board_order": 0}, ...]} — one entry per card
    whose lane position changed. Positions are per-lane counters (0, 1, 2…).
    Every id is tenant-checked; the whole batch commits once.

    NOTE: registered ABOVE PUT /backlog/{item_id} so FastAPI matches the
    literal path first — a /backlog/{item_id:int} route would otherwise
    swallow "board-order" and 422 on int parsing.
    """
    if not order.order:
        return {"updated": 0}
    ids = [entry.id for entry in order.order]
    rows = db.query(BacklogItem).filter(
        BacklogItem.id.in_(ids), BacklogItem.tenant_id == current_tenant.id
    ).all()
    by_id = {row.id: row for row in rows}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise HTTPException(status_code=404, detail=f"Backlog items not found: {missing}")
    for entry in order.order:
        by_id[entry.id].board_order = entry.board_order
    db.commit()
    return {"updated": len(order.order)}


@router.put("/backlog/{item_id}", response_model=BacklogItemResponse)
def update_backlog_item(
    item_id: int,
    item_update: BacklogItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Update a backlog item. If phase changes to Development, sync to GitHub."""
    item = db.query(BacklogItem).filter(BacklogItem.id == item_id, BacklogItem.tenant_id == current_tenant.id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Backlog item not found")

    old_phase = item.current_phase
    updates = item_update.model_dump(exclude_unset=True)

    for field, val in updates.items():
        setattr(item, field, val)

    # GitHub sync: when item enters Development, create issue if not already synced
    if item.current_phase == "Development" and old_phase != "Development" and not item.github_issue_number:
        _auto_export_to_github(db, item, current_tenant.id)

    db.commit()
    db.refresh(item)
    return item


@router.post("/backlog/{item_id}/advance", response_model=BacklogItemResponse)
def advance_backlog_phase(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Advance a backlog item to the next phase of its project's lifecycle.

    Dynamic: the phase vocabulary comes from the project's lifecycle template
    (Software/SDLC/ADLC/Hybrid/AI/custom), not a hardcoded list. The release
    stages stay release-level for every template.
    """
    item = db.query(BacklogItem).filter(BacklogItem.id == item_id, BacklogItem.tenant_id == current_tenant.id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Backlog item not found")

    from app.models.backlog_item import RELEASE_PHASES
    from app.services.lifecycle import item_phases, release_stages

    project = db.query(Project).filter(Project.id == item.project_id).first()
    project_type = project.project_type if project else None

    # Items in release-level phases (UAT, Pre-Release, ...) are managed by the
    # release workflow — advancing must not reset them.
    if item.current_phase in RELEASE_PHASES:
        return item

    phases = item_phases(project_type)
    release_level = release_stages(project_type)
    if item.current_phase in release_level:
        return item
    if item.current_phase not in phases:
        # Legacy phase value from another template — normalise to the project's
        # template by jumping to its first phase.
        item.current_phase = phases[0]
        db.commit()
        db.refresh(item)
        return item

    current_idx = phases.index(item.current_phase)
    if current_idx >= len(phases) - 1:
        raise HTTPException(
            status_code=400,
            detail=f"Item is at the final item phase ({phases[-1]}). Add it to a release to continue through the release stages.",
        )

    item.current_phase = phases[current_idx + 1]
    if item.status == "Draft":
        item.status = "In Progress"

    # GitHub sync on entering the build phase for this template
    from app.services.lifecycle import GITHUB_SYNC_PHASES
    sync_phases = GITHUB_SYNC_PHASES.get(project_type or "software", ["Development"])
    if item.current_phase in sync_phases and not item.github_issue_number:
        _auto_export_to_github(db, item, current_tenant.id)

    db.commit()
    db.refresh(item)

    log_activity(db, current_user.id, current_user.name, item.project_id,
                 "backlog_item", item.id, "advanced",
                 f"Advanced '{item.title}' to {item.current_phase}")

    # Artifact Chain: the phase move is an immutable, hash-linked entry
    from app.services.artifact_chain import append_artifact
    append_artifact(
        db, current_tenant.id, "backlog_item", item.id, "advanced",
        actor_id=current_user.id, actor_name=current_user.name,
        payload={"title": item.title, "to_phase": item.current_phase, "status": item.status},
    )

    return item


@router.post("/backlog/{item_id}/send-back", response_model=BacklogItemResponse)
def send_back_to_development(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Send a backlog item back from Testing to Development (rework)."""
    item = db.query(BacklogItem).filter(BacklogItem.id == item_id, BacklogItem.tenant_id == current_tenant.id).first()
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

    # Artifact Chain: rework is an immutable, hash-linked entry
    from app.services.artifact_chain import append_artifact
    append_artifact(
        db, current_tenant.id, "backlog_item", item.id, "sent_back",
        actor_id=current_user.id, actor_name=current_user.name,
        payload={"title": item.title, "from_phase": "Testing", "to_phase": "Development"},
    )

    return item


@router.delete("/backlog/{item_id}", status_code=204)
def delete_backlog_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Delete a backlog item."""
    item = db.query(BacklogItem).filter(BacklogItem.id == item_id, BacklogItem.tenant_id == current_tenant.id).first()
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
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Mark item_id as depending on depends_on_id."""
    tid = current_tenant.id
    item = db.query(BacklogItem).filter(BacklogItem.id == item_id, BacklogItem.tenant_id == tid).first()
    if not item:
        raise HTTPException(status_code=404, detail="Backlog item not found")

    target = db.query(BacklogItem).filter(BacklogItem.id == dep.depends_on_id, BacklogItem.tenant_id == tid).first()
    if not target:
        raise HTTPException(status_code=404, detail="Dependency target item not found")

    # Prevent self-dependency
    if item_id == dep.depends_on_id:
        raise HTTPException(status_code=400, detail="An item cannot depend on itself")

    # Prevent circular dependency
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
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Remove a dependency link."""
    tid = current_tenant.id
    item = db.query(BacklogItem).filter(BacklogItem.id == item_id, BacklogItem.tenant_id == tid).first()
    if not item:
        raise HTTPException(status_code=404, detail="Backlog item not found")

    target = db.query(BacklogItem).filter(BacklogItem.id == depends_on_id, BacklogItem.tenant_id == tid).first()
    if not target:
        raise HTTPException(status_code=404, detail="Dependency target item not found")

    if target not in item.depends_on:
        raise HTTPException(status_code=404, detail="Dependency not found")

    item.depends_on.remove(target)
    db.commit()
    db.refresh(item)
    return item


@router.get("/projects/{project_id}/backlog/available-dependencies/{exclude_id}", response_model=list[BacklogItemResponse])
def list_available_dependencies(
    project_id: int,
    exclude_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """List backlog items in a project that can be used as dependencies."""
    tid = current_tenant.id
    item = db.query(BacklogItem).filter(BacklogItem.id == exclude_id, BacklogItem.tenant_id == tid).first()
    existing_dep_ids = {d.id for d in item.depends_on} if item else set()
    existing_dep_ids.add(exclude_id)

    items = (
        db.query(BacklogItem)
        .filter(BacklogItem.project_id == project_id, BacklogItem.tenant_id == tid)
        .filter(~BacklogItem.id.in_(existing_dep_ids))
        .order_by(BacklogItem.created_at.desc())
        .all()
    )
    return items


# ── Sub-issues (GitHub Boards parity) ────────────────────────

@router.get("/backlog/{item_id}/subitems", response_model=list[BacklogItemResponse])
def list_subitems(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """List an item's sub-items (one level deep)."""
    parent = db.query(BacklogItem).filter(BacklogItem.id == item_id, BacklogItem.tenant_id == current_tenant.id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Item not found")
    return db.query(BacklogItem).filter(
        BacklogItem.parent_item_id == item_id, BacklogItem.tenant_id == current_tenant.id,
    ).order_by(BacklogItem.created_at.asc()).all()


@router.get("/backlog/{item_id}/tree", response_model=SubitemTree)
def subitem_tree(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """An item with its sub-items and a progress rollup (done / total)."""
    parent = db.query(BacklogItem).filter(BacklogItem.id == item_id, BacklogItem.tenant_id == current_tenant.id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Item not found")
    children = db.query(BacklogItem).filter(
        BacklogItem.parent_item_id == item_id, BacklogItem.tenant_id == current_tenant.id,
    ).order_by(BacklogItem.created_at.asc()).all()
    done = sum(1 for c in children if c.status == "Done")
    total = len(children)
    return {
        "id": parent.id, "title": parent.title,
        "current_phase": parent.current_phase, "status": parent.status,
        "children": children,
        "rollup": {"total": total, "done": done, "pct": round(done / total * 100) if total else 0},
    }

@router.get("/backlog/{item_id}/backlinks", response_model=list[BacklogItemBrief])
def list_backlinks(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Items whose description references this one as #<id> (mention-style links)."""
    parent = db.query(BacklogItem).filter(BacklogItem.id == item_id, BacklogItem.tenant_id == current_tenant.id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Item not found")
    needle = f"#{item_id}"
    rows = db.query(BacklogItem).filter(
        BacklogItem.tenant_id == current_tenant.id,
        BacklogItem.project_id == parent.project_id,
        BacklogItem.id != item_id,
        BacklogItem.description.like(f"%{needle}%"),
    ).order_by(BacklogItem.created_at.desc()).all()
    return rows

@router.get("/projects/{project_id}/feature-tracker")
def feature_tracker(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Feature tracker rollup (Bayan build-tracker parity): features with
    acceptance-check results, build-task progress (sub-items), and
    depends-on / needed-by lineage."""
    project = db.query(Project).filter(
        Project.id == project_id, Project.tenant_id == current_tenant.id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    from app.models.acceptance_check import AcceptanceCheck
    from app.models.backlog_item import backlog_dependencies

    features = (
        db.query(BacklogItem)
        .filter(
            BacklogItem.project_id == project_id,
            BacklogItem.tenant_id == current_tenant.id,
            BacklogItem.item_type == "Feature",
        )
        .order_by(BacklogItem.epic.asc(), BacklogItem.board_order.asc(), BacklogItem.id.asc())
        .all()
    )
    feature_ids = [f.id for f in features]

    # Bulk checks rollup (1 query)
    checks_map = {}
    if feature_ids:
        rows = (
            db.query(
                AcceptanceCheck.item_id,
                AcceptanceCheck.result,
                sa_func.count(AcceptanceCheck.id),
            )
            .filter(AcceptanceCheck.item_id.in_(feature_ids))
            .group_by(AcceptanceCheck.item_id, AcceptanceCheck.result)
            .all()
        )
        for item_id, result, count in rows:
            checks_map.setdefault(item_id, {})[result] = count

    # Bulk build-task rollup (sub-items, 1 query)
    tasks_map = {}
    if feature_ids:
        rows = (
            db.query(
                BacklogItem.parent_item_id,
                BacklogItem.status,
                sa_func.count(BacklogItem.id),
            )
            .filter(BacklogItem.parent_item_id.in_(feature_ids))
            .group_by(BacklogItem.parent_item_id, BacklogItem.status)
            .all()
        )
        for parent_id, status, count in rows:
            tasks_map.setdefault(parent_id, {})[status] = count

    # Dependencies: depends-on + needed-by lineage (2 queries)
    deps_map, needed_map = {}, {}
    if feature_ids:
        rows = (
            db.query(backlog_dependencies.c.dependent_id, backlog_dependencies.c.depends_on_id)
            .filter(backlog_dependencies.c.dependent_id.in_(feature_ids))
            .all()
        )
        for dep_id, dep_on_id in rows:
            deps_map.setdefault(dep_id, []).append(dep_on_id)
        rows = (
            db.query(backlog_dependencies.c.depends_on_id, backlog_dependencies.c.dependent_id)
            .filter(backlog_dependencies.c.depends_on_id.in_(feature_ids))
            .all()
        )
        for dep_on_id, dep_id in rows:
            needed_map.setdefault(dep_on_id, []).append(dep_id)

    def _nums(mapping, item_id):
        d = mapping.get(item_id, {})
        total = sum(d.values())
        return d, total

    result = []
    for f in features:
        check_by_result, checks_total = _nums(checks_map, f.id)
        checks_passed = check_by_result.get("Pass", 0)
        task_by_status, tasks_total = _nums(tasks_map, f.id)
        tasks_done = task_by_status.get("Done", 0)
        result.append({
            "id": f.id,
            "epic": f.epic,
            "title": f.title,
            "used_by": f.primary_actor,
            "personas": f.personas,
            "goal": f.description,
            "status": f.status,
            "owner": f.assigned_to,
            "checks_passed": checks_passed,
            "checks_total": checks_total,
            "checks": {"Pass": checks_passed, "Fail": check_by_result.get("Fail", 0), "Not tested": check_by_result.get("Not tested", 0)},
            "tasks_done": tasks_done,
            "tasks_total": tasks_total,
            "progress": round(checks_passed / checks_total, 2) if checks_total else 0.0,
            "depends_on": deps_map.get(f.id, []),
            "needed_by": needed_map.get(f.id, []),
        })
    return result

@router.get("/projects/{project_id}/export/tracker.xlsx")
def export_tracker_xlsx(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Export the feature tracker as a styled xlsx (Features + Checklist sheets)."""
    project = db.query(Project).filter(
        Project.id == project_id, Project.tenant_id == current_tenant.id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    from app.models.acceptance_check import AcceptanceCheck
    from app.models.user import User as UserModel
    from app.services.tracker_export import build_tracker_workbook

    tracker = feature_tracker(project_id, db, current_user, current_tenant)
    feature_ids = [f["id"] for f in tracker]

    checks_by_item = {}
    if feature_ids:
        rows = (
            db.query(AcceptanceCheck)
            .filter(AcceptanceCheck.item_id.in_(feature_ids))
            .order_by(AcceptanceCheck.check_order.asc(), AcceptanceCheck.id.asc())
            .all()
        )
        for c in rows:
            checks_by_item.setdefault(c.item_id, []).append(
                {"id": c.id, "result": c.result, "text": c.text, "order": c.check_order}
            )

    tasks_by_item = {}
    if feature_ids:
        rows = (
            db.query(BacklogItem)
            .filter(BacklogItem.parent_item_id.in_(feature_ids))
            .order_by(BacklogItem.board_order.asc(), BacklogItem.id.asc())
            .all()
        )
        for t in rows:
            tasks_by_item.setdefault(t.parent_item_id, []).append(
                {"parent_item_id": t.parent_item_id, "order": t.board_order or 0,
                 "title": t.title, "status": t.status, "assigned_to": t.assigned_to}
            )

    owner_names = {}
    user_ids = {f.get("owner") for f in tracker if f.get("owner")}
    for tasks in tasks_by_item.values():
        user_ids.update(t.get("assigned_to") for t in tasks if t.get("assigned_to"))
    if user_ids:
        for u in db.query(UserModel).filter(UserModel.id.in_(user_ids)).all():
            owner_names[u.id] = u.name

    content = build_tracker_workbook(project.name, tracker, checks_by_item, tasks_by_item, owner_names)
    from fastapi import Response as FastAPIResponse

    filename = f"{project.name.replace(' ', '-').lower()}-build-tracker.xlsx"
    return FastAPIResponse(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
