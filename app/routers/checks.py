"""Acceptance checks API — structured checks per backlog item.

GET    /api/backlog/{item_id}/checks   list (ordered)
POST   /api/backlog/{item_id}/checks   add
PUT    /api/checks/{check_id}          update text / result / order
DELETE /api/checks/{check_id}          remove
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.acceptance_check import CHECK_RESULTS, AcceptanceCheck
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.user import User
from app.permissions import can_manage_project
from app.schemas.acceptance_check import (
    AcceptanceCheckCreate,
    AcceptanceCheckResponse,
    AcceptanceCheckUpdate,
)
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api", tags=["checks"])


def _load_item(db: Session, item_id: int, tenant_id: int) -> BacklogItem:
    item = db.query(BacklogItem).filter(
        BacklogItem.id == item_id, BacklogItem.tenant_id == tenant_id,
    ).first()
    if not item:
        raise HTTPException(404, "Item not found")
    return item


@router.get("/backlog/{item_id}/checks", response_model=list[AcceptanceCheckResponse])
def list_checks(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    _load_item(db, item_id, current_tenant.id)
    rows = (
        db.query(AcceptanceCheck)
        .filter(AcceptanceCheck.item_id == item_id)
        .order_by(AcceptanceCheck.check_order.asc(), AcceptanceCheck.id.asc())
        .all()
    )
    return rows


@router.post("/backlog/{item_id}/checks", response_model=AcceptanceCheckResponse, status_code=201)
def create_check(item_id: int, req: AcceptanceCheckCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    item = _load_item(db, item_id, current_tenant.id)
    project = db.query(Project).filter(Project.id == item.project_id).first()
    if not can_manage_project(current_user, project, db):
        raise HTTPException(403, "You don't have permission to manage checks on this item")
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(422, "Check text is required")
    max_order = db.query(AcceptanceCheck).filter(AcceptanceCheck.item_id == item_id).count()
    check = AcceptanceCheck(
        tenant_id=current_tenant.id, item_id=item_id,
        check_order=req.check_order if req.check_order else max_order + 1,
        text=text[:500], result="Not tested",
    )
    db.add(check)
    db.commit()
    db.refresh(check)
    return check


@router.put("/checks/{check_id}", response_model=AcceptanceCheckResponse)
def update_check(check_id: int, req: AcceptanceCheckUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    check = db.query(AcceptanceCheck).filter(
        AcceptanceCheck.id == check_id, AcceptanceCheck.tenant_id == current_tenant.id,
    ).first()
    if not check:
        raise HTTPException(404, "Check not found")
    item = db.query(BacklogItem).filter(BacklogItem.id == check.item_id).first()
    project = db.query(Project).filter(Project.id == item.project_id).first() if item else None
    if not can_manage_project(current_user, project, db):
        raise HTTPException(403, "You don't have permission to update checks on this item")
    if req.result is not None and req.result not in CHECK_RESULTS:
        raise HTTPException(400, f"Invalid result. Must be one of: {CHECK_RESULTS}")
    if req.text is not None:
        text = req.text.strip()
        if not text:
            raise HTTPException(422, "Check text cannot be empty")
        check.text = text[:500]
    if req.result is not None:
        check.result = req.result
    if req.check_order is not None:
        check.check_order = req.check_order
    db.commit()
    db.refresh(check)
    return check


@router.delete("/checks/{check_id}", status_code=204)
def delete_check(check_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    check = db.query(AcceptanceCheck).filter(
        AcceptanceCheck.id == check_id, AcceptanceCheck.tenant_id == current_tenant.id,
    ).first()
    if not check:
        raise HTTPException(404, "Check not found")
    item = db.query(BacklogItem).filter(BacklogItem.id == check.item_id).first()
    project = db.query(Project).filter(Project.id == item.project_id).first() if item else None
    if not can_manage_project(current_user, project, db):
        raise HTTPException(403, "You don't have permission to delete checks on this item")
    db.delete(check)
    db.commit()
