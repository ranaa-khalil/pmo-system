"""Comments API — threaded comments on tasks and backlog items.

GET  /api/tasks/{task_id}/comments   list (oldest first)
POST /api/tasks/{task_id}/comments   add (any project member)
GET  /api/backlog/{item_id}/comments list
POST /api/backlog/{item_id}/comments add
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.backlog_item import BacklogItem
from app.models.comment import Comment
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_task import UserTask
from app.schemas.comment import CommentCreate, CommentResponse
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api", tags=["comments"])


def _row(c: Comment) -> dict:
    return {
        "id": c.id, "task_id": c.task_id, "item_id": c.item_id,
        "user_id": c.user_id, "user_name": c.author.name if c.author else None,
        "body": c.body, "created_at": c.created_at,
    }


def _list_for(db: Session, tenant_id: int, **filters) -> list[dict]:
    rows = (
        db.query(Comment)
        .filter(Comment.tenant_id == tenant_id, *filters.values())
        .order_by(Comment.id.asc())
        .all()
    )
    return [_row(c) for c in rows]


def _create(db: Session, tenant_id: int, user: User, req: CommentCreate, **filters) -> dict:
    body = (req.body or "").strip()
    if not body:
        raise HTTPException(422, "Comment body is required")
    comment = Comment(tenant_id=tenant_id, user_id=user.id, body=body[:5000], **filters)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return _row(comment)


@router.get("/tasks/{task_id}/comments", response_model=list[CommentResponse])
def list_task_comments(task_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    task = db.query(UserTask).filter(UserTask.id == task_id, UserTask.tenant_id == current_tenant.id).first()
    if not task:
        raise HTTPException(404, "Task not found")
    return _list_for(db, current_tenant.id, task_id=Comment.task_id == task_id)


@router.post("/tasks/{task_id}/comments", response_model=CommentResponse, status_code=201)
def create_task_comment(task_id: int, req: CommentCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    task = db.query(UserTask).filter(UserTask.id == task_id, UserTask.tenant_id == current_tenant.id).first()
    if not task:
        raise HTTPException(404, "Task not found")
    return _create(db, current_tenant.id, current_user, req, task_id=task_id)


@router.get("/backlog/{item_id}/comments", response_model=list[CommentResponse])
def list_item_comments(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    item = db.query(BacklogItem).filter(BacklogItem.id == item_id, BacklogItem.tenant_id == current_tenant.id).first()
    if not item:
        raise HTTPException(404, "Item not found")
    return _list_for(db, current_tenant.id, item_id=Comment.item_id == item_id)


@router.post("/backlog/{item_id}/comments", response_model=CommentResponse, status_code=201)
def create_item_comment(item_id: int, req: CommentCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    item = db.query(BacklogItem).filter(BacklogItem.id == item_id, BacklogItem.tenant_id == current_tenant.id).first()
    if not item:
        raise HTTPException(404, "Item not found")
    return _create(db, current_tenant.id, current_user, req, item_id=item_id)
