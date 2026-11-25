"""Backlog API router — business requirements following the 9-phase process."""

from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.backlog_item import BacklogItem
from app.models.kpi import KPI
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
from app.services.release_machine import advance_backlog_item_phase
from app.services.scope import tenant_scoped
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api", tags=["backlog"])

_BULK_MAX_ITEMS = 100  # house batch guard — one request, one machine loop


class BacklogBulkAdvance(BaseModel):
    """Body for PATCH /backlog/bulk — item ids + optional shared step count.

    ``item_ids`` is required (one entry per item to advance); ``steps`` is
    an optional shared advance count (each item walks that many ONE-step
    machine advances; default 1). There is deliberately no per-item target
    phase: the machine advances one step at a time, so a target would just
    be a loop count in disguise.
    """

    item_ids: list[int]
    steps: int = 1


def _auto_export_to_github(db: Session, item: BacklogItem, tenant_id: int):
    """Auto-export a backlog item to GitHub when it reaches the configured trigger phase.

    Uses the project's GitHubBoardConfig if available, otherwise falls back to
    the project's github_repo field with basic issue creation.
    """
    from datetime import datetime

    from app.models.github_board_config import GitHubBoardConfig

    project = tenant_scoped(db, Project, tenant_id).filter(Project.id == item.project_id).first()
    if not project:
        return

    # Check for board config
    config = tenant_scoped(db, GitHubBoardConfig, tenant_id).filter(
        GitHubBoardConfig.project_id == item.project_id,
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
    if not tenant_scoped(db, Project, current_tenant.id).filter(Project.id == project_id).first():
        raise HTTPException(status_code=404, detail="Project not found")
    if item.project_id != project_id:
        raise HTTPException(status_code=400, detail="project_id mismatch")
    if item.parent_item_id:
        parent = tenant_scoped(db, BacklogItem, current_tenant.id).filter(
            BacklogItem.id == item.parent_item_id,
            BacklogItem.project_id == project_id,
        ).first()
        if not parent:
            raise HTTPException(status_code=400, detail="Parent item not found in this project")
        if parent.parent_item_id:
            raise HTTPException(status_code=400, detail="Sub-items cannot nest — one level only")
    # KPI tenancy: the body's kpi_id must be a THIS-tenant KPI — the raw
    # model_dump would otherwise write a cross-tenant link that the coverage
    # and traceability reads silently ignore (data row holds a rogue link).
    if item.kpi_id:
        kpi = tenant_scoped(db, KPI, current_tenant.id).filter(KPI.id == item.kpi_id).first()
        if not kpi:
            raise HTTPException(status_code=400, detail="KPI not found in this tenant")
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
    query = tenant_scoped(db, BacklogItem, current_tenant.id).filter(BacklogItem.project_id == project_id)
    if phase:
        query = query.filter(BacklogItem.current_phase == phase)
    if status:
        query = query.filter(BacklogItem.status == status)
    return query.order_by(BacklogItem.created_at.desc()).all()


@router.get("/projects/{project_id}/backlog/rail")
def get_backlog_rail(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """The phase rail for the frontend — ONE effective lifecycle per project.

    Rethink v2 C1: the phase vocabulary used to live in three places
    (lifecycle_templates rows, the backlog_item.py constants, hardcoded JS)
    and the parts didn't agree. This endpoint serves the single effective
    source — the tenant's TenantLifecycleTemplate row when one exists, the
    built-in phases (the backlog_item.py constants) otherwise — with the
    per-phase gate deliverables/roles from the template when present.

    Response: {project_id, item_types: [...], phases: [{name, order,
    is_release_stage, gate: {deliverables, roles} | null}],
    source: 'template' | 'builtin'}.
    """
    project = tenant_scoped(db, Project, current_tenant.id).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    from app.services.lifecycle import get_effective_lifecycle

    eff = get_effective_lifecycle(db, current_tenant.id, getattr(project, "project_type", None))

    type_rows = (
        db.query(BacklogItem.item_type)
        .filter(BacklogItem.project_id == project_id, BacklogItem.tenant_id == current_tenant.id)
        .distinct()
        .all()
    )
    item_types = sorted({row[0] for row in type_rows if row[0]})

    deliverables = eff["gate_deliverables"]
    roles = eff["gate_roles"]
    phases = []
    for order, name in enumerate(eff["item_phases"]):
        phase_deliverables = deliverables.get(name) or []
        phase_role = roles.get(name)
        gate = None
        if phase_deliverables or phase_role:
            gate = {
                "deliverables": list(phase_deliverables),
                "roles": [phase_role] if phase_role else [],
            }
        phases.append({"name": name, "order": order, "is_release_stage": False, "gate": gate})
    for name in eff["release_stages"]:
        phases.append({"name": name, "order": len(phases), "is_release_stage": True, "gate": None})

    return {
        "project_id": project_id,
        "item_types": item_types,
        "phases": phases,
        "source": eff["source"],
    }


@router.get("/backlog/{item_id}", response_model=BacklogItemResponse)
def get_backlog_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Read one backlog item (tenant-checked).

    The ONE Work drawer's detail fetch and the #N item references both load
    their item here — before this route existed, GET /backlog/{id} hit the
    PUT-only path (405) and every consumer silently fell back to null."""
    item = tenant_scoped(db, BacklogItem, current_tenant.id).filter(BacklogItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Backlog item not found")
    return item


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
    rows = tenant_scoped(db, BacklogItem, current_tenant.id).filter(
        BacklogItem.id.in_(ids)
    ).all()
    by_id = {row.id: row for row in rows}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise HTTPException(status_code=404, detail=f"Backlog items not found: {missing}")
    for entry in order.order:
        by_id[entry.id].board_order = entry.board_order
    db.commit()
    return {"updated": len(order.order)}


@router.patch("/backlog/bulk")
def bulk_advance_backlog(
    bulk: BacklogBulkAdvance,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Advance many backlog items — loops the ONE advance machine (Rethink v2 F3).

    The bulk endpoint ships after the state machines are extracted (Phase
    F1) so it loops release_machine.advance_backlog_item_phase, not a third
    router copy: every id gets the exact single-advance path — same
    effective-lifecycle reads, same GitHub sync on the build phase, same
    log_activity + artifact-chain entries in the same order the router path
    produces.

    Per-item failures NEVER abort the batch: each id is tenant-checked and
    advanced independently, and the response marks every failure inline
    (a foreign tenant's id and an unknown id both read "Backlog item not
    found" — the house 404 string — without advancing anything).

    Body: {"item_ids": [1, 2, 3], "steps": 1} — steps is an optional shared
    advance count (default 1). Response: {"results": [{id, ok,
    previous_phase, phase} | {id, ok: false, error}], "advanced": N,
    "failed": M}.

    NOTE: registered ABOVE the /backlog/{item_id} routes so FastAPI matches
    the literal path first — the same defensive order as board-order.
    """
    if not bulk.item_ids:
        raise HTTPException(status_code=400, detail="item_ids must not be empty")
    if len(bulk.item_ids) > _BULK_MAX_ITEMS:
        raise HTTPException(
            status_code=400,
            detail=f"Too many items: {len(bulk.item_ids)} (max {_BULK_MAX_ITEMS} per batch)",
        )

    results = []
    for item_id in bulk.item_ids:
        item = tenant_scoped(db, BacklogItem, current_tenant.id).filter(
            BacklogItem.id == item_id
        ).first()
        if not item:
            results.append({"id": item_id, "ok": False, "error": "Backlog item not found"})
            continue
        previous_phase = item.current_phase
        try:
            for _ in range(max(1, bulk.steps)):
                item = advance_backlog_item_phase(db, current_tenant, current_user, item)
            results.append({
                "id": item_id,
                "ok": True,
                "previous_phase": previous_phase,
                "phase": item.current_phase,
            })
        except HTTPException as exc:
            results.append({"id": item_id, "ok": False, "error": exc.detail})
    advanced = sum(1 for r in results if r["ok"])
    return {"results": results, "advanced": advanced, "failed": len(results) - advanced}


@router.put("/backlog/{item_id}", response_model=BacklogItemResponse)
def update_backlog_item(
    item_id: int,
    item_update: BacklogItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Update a backlog item. If phase changes to Development, sync to GitHub."""
    item = tenant_scoped(db, BacklogItem, current_tenant.id).filter(BacklogItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Backlog item not found")

    old_phase = item.current_phase
    updates = item_update.model_dump(exclude_unset=True)

    # KPI tenancy on update: None (unlink) is allowed; a non-null kpi_id must
    # be a THIS-tenant KPI — never another tenant's.
    if updates.get("kpi_id") is not None:
        kpi = tenant_scoped(db, KPI, current_tenant.id).filter(KPI.id == updates["kpi_id"]).first()
        if not kpi:
            raise HTTPException(status_code=400, detail="KPI not found in this tenant")

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

    The machine lives once in app/services/release_machine.py (Rethink v2 F1)
    — this router path parses the request (tenant-scoped fetch + 404) and
    delegates; the response shape, status codes and error strings are
    byte-identical to the pre-extraction router.
    """
    item = tenant_scoped(db, BacklogItem, current_tenant.id).filter(BacklogItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Backlog item not found")

    return advance_backlog_item_phase(db, current_tenant, current_user, item)


@router.post("/backlog/{item_id}/send-back", response_model=BacklogItemResponse)
def send_back_to_development(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Send a backlog item back from Testing to Development (rework)."""
    item = tenant_scoped(db, BacklogItem, current_tenant.id).filter(BacklogItem.id == item_id).first()
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

    # The audit writes above are flush-only — commit them or they roll back
    # when the request session closes (live-only failure).
    db.commit()

    return item


@router.delete("/backlog/{item_id}", status_code=204)
def delete_backlog_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Delete a backlog item."""
    item = tenant_scoped(db, BacklogItem, current_tenant.id).filter(BacklogItem.id == item_id).first()
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
    item = tenant_scoped(db, BacklogItem, tid).filter(BacklogItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Backlog item not found")

    target = tenant_scoped(db, BacklogItem, tid).filter(BacklogItem.id == dep.depends_on_id).first()
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
    item = tenant_scoped(db, BacklogItem, tid).filter(BacklogItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Backlog item not found")

    target = tenant_scoped(db, BacklogItem, tid).filter(BacklogItem.id == depends_on_id).first()
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
    item = tenant_scoped(db, BacklogItem, tid).filter(BacklogItem.id == exclude_id).first()
    existing_dep_ids = {d.id for d in item.depends_on} if item else set()
    existing_dep_ids.add(exclude_id)

    items = (
        tenant_scoped(db, BacklogItem, tid)
        .filter(BacklogItem.project_id == project_id)
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
    parent = tenant_scoped(db, BacklogItem, current_tenant.id).filter(BacklogItem.id == item_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Item not found")
    return tenant_scoped(db, BacklogItem, current_tenant.id).filter(
        BacklogItem.parent_item_id == item_id,
    ).order_by(BacklogItem.created_at.asc()).all()


@router.get("/backlog/{item_id}/tree", response_model=SubitemTree)
def subitem_tree(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """An item with its sub-items and a progress rollup (done / total)."""
    parent = tenant_scoped(db, BacklogItem, current_tenant.id).filter(BacklogItem.id == item_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Item not found")
    children = tenant_scoped(db, BacklogItem, current_tenant.id).filter(
        BacklogItem.parent_item_id == item_id,
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
    parent = tenant_scoped(db, BacklogItem, current_tenant.id).filter(BacklogItem.id == item_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Item not found")
    needle = f"#{item_id}"
    rows = tenant_scoped(db, BacklogItem, current_tenant.id).filter(
        BacklogItem.project_id == parent.project_id,
        BacklogItem.id != item_id,
        BacklogItem.description.like(f"%{needle}%"),
    ).order_by(BacklogItem.created_at.desc()).all()
    return rows

