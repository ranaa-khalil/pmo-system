"""Tags API router — tenant-wide tag pool with cross-entity links.

One tag, many items; one item, many tags — no duplication (cross-tagging).
Attach/detach is idempotent; every change writes an activity-log row.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.backlog_item import BacklogItem
from app.models.tag import TAG_COLORS, Tag, backlog_item_tags, user_task_tags
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_task import UserTask
from app.schemas.tag import TagAttach, TagCreate
from app.services.notifications import log_activity
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api", tags=["tags"])


def _tag_payload(tag: Tag) -> dict:
    """Tag with usage counts for the picker."""
    return {
        "id": tag.id,
        "name": tag.name,
        "color": tag.color,
        "created_at": tag.created_at,
        "item_count": len(tag.items),
        "task_count": len(tag.tasks),
    }


def _get_tenant_tag(db: Session, tag_id: int, tenant_id: int) -> Tag:
    tag = db.query(Tag).filter(Tag.id == tag_id, Tag.tenant_id == tenant_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found in this workspace")
    return tag


@router.get("/tags")
def list_tags(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """The workspace-wide tag pool, with usage counts."""
    tags = db.query(Tag).filter(Tag.tenant_id == current_tenant.id).order_by(Tag.name).all()
    return [_tag_payload(t) for t in tags]


@router.post("/tags", status_code=201)
def create_tag(
    tag: TagCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Create a tag in the tenant pool. Duplicate names 409."""
    name = (tag.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Tag name cannot be empty")
    if len(name) > 100:
        raise HTTPException(status_code=400, detail="Tag name too long (max 100 characters)")
    if tag.color not in TAG_COLORS:
        raise HTTPException(status_code=400, detail=f"Invalid color. Must be one of: {TAG_COLORS}")
    existing = db.query(Tag).filter(Tag.tenant_id == current_tenant.id, Tag.name == name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Tag '{name}' already exists in this workspace")
    db_tag = Tag(tenant_id=current_tenant.id, name=name, color=tag.color, created_by=current_user.id)
    db.add(db_tag)
    db.commit()
    db.refresh(db_tag)
    return _tag_payload(db_tag)


@router.delete("/tags/{tag_id}")
def delete_tag(
    tag_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Delete a tag; the M2M links cascade."""
    tag = db.query(Tag).filter(Tag.id == tag_id, Tag.tenant_id == current_tenant.id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    db.delete(tag)
    db.commit()
    return {"detail": "Tag deleted"}


@router.post("/backlog/{item_id}/tags", status_code=201)
def attach_item_tag(
    item_id: int,
    body: TagAttach,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Attach a tag to a backlog item. Idempotent: already-attached returns 200."""
    item = db.query(BacklogItem).filter(
        BacklogItem.id == item_id, BacklogItem.tenant_id == current_tenant.id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    tag = _get_tenant_tag(db, body.tag_id, current_tenant.id)
    # Check the association table directly — reliable across sessions
    from sqlalchemy import select

    existing = db.execute(
        select(backlog_item_tags).where(
            backlog_item_tags.c.backlog_item_id == item.id,
            backlog_item_tags.c.tag_id == tag.id,
        )
    ).first()
    if existing:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=200, content={"detail": "Tag already attached"})
    item.tags.append(tag)
    db.commit()
    log_activity(db, current_user.id, current_user.name, item.project_id,
                 "backlog_item", item.id, "updated",
                 f"Tagged '{item.title[:100]}' with #{tag.name}")
    return _tag_payload(tag)


@router.delete("/backlog/{item_id}/tags/{tag_id}")
def detach_item_tag(
    item_id: int,
    tag_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Detach a tag from a backlog item."""
    item = db.query(BacklogItem).filter(
        BacklogItem.id == item_id, BacklogItem.tenant_id == current_tenant.id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    tag = _get_tenant_tag(db, tag_id, current_tenant.id)
    if tag not in item.tags:
        raise HTTPException(status_code=404, detail="Tag not attached to this item")
    item.tags.remove(tag)
    db.commit()
    return {"detail": "Tag removed"}


@router.post("/tasks/{task_id}/tags", status_code=201)
def attach_task_tag(
    task_id: int,
    body: TagAttach,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Attach a tag to a user task. Idempotent: already-attached returns 200."""
    task = db.query(UserTask).filter(
        UserTask.id == task_id, UserTask.tenant_id == current_tenant.id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    tag = _get_tenant_tag(db, body.tag_id, current_tenant.id)
    # Check the association table directly — reliable across sessions
    from sqlalchemy import select

    existing = db.execute(
        select(user_task_tags).where(
            user_task_tags.c.user_task_id == task.id,
            user_task_tags.c.tag_id == tag.id,
        )
    ).first()
    if existing:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=200, content={"detail": "Tag already attached"})
    task.tags.append(tag)
    db.commit()
    log_activity(db, current_user.id, current_user.name, task.project_id,
                 "task", task.id, "updated",
                 f"Tagged '{task.title[:100]}' with #{tag.name}")
    return _tag_payload(tag)


@router.delete("/tasks/{task_id}/tags/{tag_id}")
def detach_task_tag(
    task_id: int,
    tag_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Detach a tag from a user task."""
    task = db.query(UserTask).filter(
        UserTask.id == task_id, UserTask.tenant_id == current_tenant.id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    tag = _get_tenant_tag(db, tag_id, current_tenant.id)
    if tag not in task.tags:
        raise HTTPException(status_code=404, detail="Tag not attached to this task")
    task.tags.remove(tag)
    db.commit()
    return {"detail": "Tag removed"}
