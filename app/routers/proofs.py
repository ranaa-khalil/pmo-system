"""Item proofing API — versioned deliverable proofs on backlog items.

Upload a deliverable (image/PDF) or link one externally; reviewers approve
or request changes. One proof row per version; the latest version's status
is the item's proof status.
"""
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.backlog_item import BacklogItem
from app.models.proof import ItemProof
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.item_type import ProofDecide
from app.services.notifications import log_activity
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api", tags=["proofs"])

_PROOFS_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "proofs"
_PROOFS_URL_PREFIX = "/uploads/proofs"
_PROOF_MAX_SIZE = 10 * 1024 * 1024  # 10 MB
_ALLOWED_PROOF_TYPES = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
    "image/gif": ".gif", "application/pdf": ".pdf",
}


def _get_item(db: Session, item_id: int, tenant_id: int) -> BacklogItem:
    item = db.query(BacklogItem).filter(
        BacklogItem.id == item_id, BacklogItem.tenant_id == tenant_id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Backlog item not found")
    return item


def _payload(p: ItemProof) -> dict:
    return {
        "id": p.id,
        "item_id": p.item_id,
        "version": p.version,
        "title": p.title,
        "file_path": p.file_path,
        "file_url": p.file_url,
        "status": p.status,
        "uploader_name": p.uploader_name,
        "decider_name": p.decider_name,
        "decision_comment": p.decision_comment,
        "decided_at": p.decided_at,
        "created_at": p.created_at,
    }


@router.post("/backlog/{item_id}/proofs", status_code=201)
def upload_proof(
    item_id: int,
    title: str = Form(...),
    file: UploadFile | None = File(None),
    file_url: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Upload a new proof version for an item (file upload or external URL)."""
    item = _get_item(db, item_id, current_tenant.id)
    if not title.strip():
        raise HTTPException(status_code=400, detail="A proof title is required")
    if file is None and not (file_url or "").strip():
        raise HTTPException(status_code=400, detail="Attach a file or provide a URL")

    saved_path = None
    if file is not None:
        ct = file.content_type or ""
        if ct not in _ALLOWED_PROOF_TYPES:
            raise HTTPException(status_code=400, detail="Unsupported file type. Use PNG, JPEG, WebP, GIF, or PDF.")
        data = file.file.read()
        if len(data) > _PROOF_MAX_SIZE:
            raise HTTPException(status_code=400, detail="Proof file too large (max 10 MB).")
        ext = _ALLOWED_PROOF_TYPES[ct]
        _PROOFS_DIR.mkdir(parents=True, exist_ok=True)
        import uuid
        filename = f"item-{item_id}-v{uuid.uuid4().hex[:8]}{ext}"
        (_PROOFS_DIR / filename).write_bytes(data)
        saved_path = f"{_PROOFS_URL_PREFIX}/{filename}"

    next_version = (db.query(ItemProof).filter(
        ItemProof.item_id == item_id, ItemProof.tenant_id == current_tenant.id
    ).count()) + 1

    proof = ItemProof(
        tenant_id=current_tenant.id,
        item_id=item_id,
        version=next_version,
        title=title.strip(),
        file_path=saved_path,
        file_url=(file_url or "").strip() or None,
        status="Pending",
        uploaded_by=current_user.id,
        uploader_name=current_user.name,
    )
    db.add(proof)
    db.commit()
    db.refresh(proof)
    log_activity(db, current_user.id, current_user.name, item.project_id,
                 "backlog_item", item_id, "updated",
                 f"Uploaded proof v{proof.version} on '{item.title[:60]}'")
    return _payload(proof)


@router.get("/backlog/{item_id}/proofs")
def list_proofs(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """All proof versions for an item, newest first."""
    _get_item(db, item_id, current_tenant.id)
    rows = db.query(ItemProof).filter(
        ItemProof.item_id == item_id, ItemProof.tenant_id == current_tenant.id
    ).order_by(ItemProof.version.desc()).all()
    return [_payload(p) for p in rows]


@router.post("/proofs/{proof_id}/decide")
def decide_proof(
    proof_id: int,
    body: ProofDecide,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Approve a proof or request changes (human decision, stored verbatim)."""
    proof = db.query(ItemProof).filter(
        ItemProof.id == proof_id, ItemProof.tenant_id == current_tenant.id
    ).first()
    if not proof:
        raise HTTPException(status_code=404, detail="Proof not found")
    if body.decision not in ("Approved", "Changes Requested"):
        raise HTTPException(status_code=400, detail="decision must be 'Approved' or 'Changes Requested'")
    proof.status = body.decision
    proof.decided_by = current_user.id
    proof.decider_name = current_user.name
    proof.decision_comment = body.comment
    proof.decided_at = datetime.utcnow().isoformat()
    db.commit()
    db.refresh(proof)
    return _payload(proof)
