"""Guest approval link API — tokenized links for external approvers.

Authenticated: create/list/revoke links on one approval request.
Public: view the request summary + record a decision (no login).

A link bound to a RACI step drives the chain exactly like an in-app decision
(step status, chain advance, auto-advance release, artifact chain entry,
notification). An unbound link records an advisory decision. Every guest
decision is stored verbatim in approval_guest_decisions.
"""
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.database import get_db
from app.dependencies import get_current_user
from app.models.approval import ApprovalRequest, ApprovalStep
from app.models.guest_link import ApprovalGuestDecision, ApprovalGuestLink
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.guest_link import GuestDecisionCreate, GuestLinkCreate
from app.services.auth import hash_password, verify_password
from app.services.notifications import log_activity, notify_approval_result
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api", tags=["guest-links"])
public_router = APIRouter(prefix="/api/guest", tags=["guest-links"])

GUEST_DECISIONS = ["Approved", "Rejected"]


def _link_url(token: str) -> str:
    return f"/guest/approval/{token}"


def _link_payload(link: ApprovalGuestLink) -> dict:
    return {
        "id": link.id,
        "request_id": link.request_id,
        "step_id": link.step_id,
        "token": link.token,
        "label": link.label,
        "has_password": bool(link.password_hash),
        "expires_at": link.expires_at,
        "revoked": link.revoked,
        "url": _link_url(link.token),
    }


@router.post("/approvals/{approval_id}/guest-links", status_code=201)
def create_guest_link(
    approval_id: int,
    body: GuestLinkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Create a tokenized guest link for one approval request."""
    tid = current_tenant.id
    request = db.query(ApprovalRequest).filter(
        ApprovalRequest.id == approval_id, ApprovalRequest.tenant_id == tid
    ).first()
    if not request:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if body.step_id:
        step = db.query(ApprovalStep).filter(
            ApprovalStep.id == body.step_id,
            ApprovalStep.request_id == approval_id,
            ApprovalStep.tenant_id == tid,
        ).first()
        if not step:
            raise HTTPException(status_code=404, detail="Approval step not found")
    if not 1 <= body.expires_in_days <= 90:
        raise HTTPException(status_code=400, detail="expires_in_days must be between 1 and 90")

    link = ApprovalGuestLink(
        tenant_id=tid,
        request_id=approval_id,
        step_id=body.step_id,
        token=secrets.token_urlsafe(32),
        label=(body.label or "").strip()[:200] or None,
        password_hash=hash_password(body.password) if body.password else None,
        expires_at=(datetime.utcnow() + timedelta(days=body.expires_in_days)).isoformat(),
        created_by=current_user.id,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    log_activity(db, current_user.id, current_user.name, request.project_id,
                 "approval", approval_id, "updated",
                 f"Created guest link for: {request.title[:80]}")
    return _link_payload(link)


@router.get("/approvals/{approval_id}/guest-links")
def list_guest_links(
    approval_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """List the guest links on one approval request."""
    links = db.query(ApprovalGuestLink).filter(
        ApprovalGuestLink.request_id == approval_id,
        ApprovalGuestLink.tenant_id == current_tenant.id,
    ).order_by(ApprovalGuestLink.created_at.desc()).all()
    return [_link_payload(l) for l in links]


@router.delete("/guest-links/{link_id}")
def revoke_guest_link(
    link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Revoke a guest link (decisions through it then 410)."""
    link = db.query(ApprovalGuestLink).filter(
        ApprovalGuestLink.id == link_id, ApprovalGuestLink.tenant_id == current_tenant.id
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    link.revoked = True
    db.commit()
    return {"detail": "Link revoked"}


# ---- Public (no auth) ----

def _load_valid_link(db: Session, token: str) -> ApprovalGuestLink:
    link = db.query(ApprovalGuestLink).filter(ApprovalGuestLink.token == token).first()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    if link.revoked:
        raise HTTPException(status_code=410, detail="This link has been revoked")
    if link.expires_at:
        try:
            expires = datetime.fromisoformat(link.expires_at)
        except ValueError:
            raise HTTPException(status_code=410, detail="This link is not valid")
        if datetime.utcnow() > expires:
            raise HTTPException(status_code=410, detail="This link has expired")
    return link


@public_router.get("/approvals/{token}")
def view_guest_approval(token: str, db: Session = Depends(get_db)):
    """Public read-only view of the shared approval request."""
    link = _load_valid_link(db, token)
    request = db.query(ApprovalRequest).filter(ApprovalRequest.id == link.request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Approval request not found")
    project = db.query(Project).filter(Project.id == request.project_id).first()
    steps = db.query(ApprovalStep).filter(
        ApprovalStep.request_id == request.id
    ).order_by(ApprovalStep.step_order).all()
    decisions = db.query(ApprovalGuestDecision).filter(
        ApprovalGuestDecision.request_id == request.id
    ).order_by(ApprovalGuestDecision.decided_at).all()
    bound_step = next((s for s in steps if s.id == link.step_id), None)
    if bound_step:
        can_decide = request.status == "Pending" and bound_step.status == "Pending" and bound_step.step_order == request.current_step
    else:
        can_decide = request.status == "Pending"
    return {
        "label": link.label,
        "expires_at": link.expires_at,
        "has_password": bool(link.password_hash),
        "request": {
            "title": request.title,
            "description": request.description,
            "request_type": request.request_type,
            "status": request.status,
            "project_name": project.name if project else None,
        },
        "steps": [
            {"step_order": s.step_order, "role_name": s.role_name, "status": s.status}
            for s in steps
        ],
        "bound_step": (
            {"step_order": bound_step.step_order, "role_name": bound_step.role_name, "status": bound_step.status}
            if bound_step else None
        ),
        "guest_decisions": [
            {"decision": d.decision, "comment": d.comment, "guest_name": d.guest_name, "decided_at": d.decided_at}
            for d in decisions
        ],
        "can_decide": can_decide,
    }


@public_router.post("/approvals/{token}/decide")
def guest_decide(token: str, body: GuestDecisionCreate, db: Session = Depends(get_db)):
    """Record a guest decision through the tokenized link (no login)."""
    link = _load_valid_link(db, token)
    if link.password_hash and not verify_password(body.password or "", link.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect link password")
    if body.decision not in GUEST_DECISIONS:
        raise HTTPException(status_code=400, detail=f"decision must be one of: {GUEST_DECISIONS}")
    request = db.query(ApprovalRequest).filter(ApprovalRequest.id == link.request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if request.status != "Pending":
        raise HTTPException(status_code=400, detail=f"Cannot decide: request is '{request.status}'")
    guest_name = ((body.guest_name or "").strip() or link.label or "Guest")[:200]

    step = None
    if link.step_id:
        step = db.query(ApprovalStep).filter(
            ApprovalStep.id == link.step_id, ApprovalStep.request_id == request.id
        ).first()
        if not step:
            raise HTTPException(status_code=404, detail="Bound step not found")
        if step.status != "Pending":
            raise HTTPException(status_code=400, detail=f"Step is already '{step.status}'")
        if step.step_order != request.current_step:
            raise HTTPException(
                status_code=400,
                detail=f"This step is not the current step (current: step {request.current_step})",
            )

    # Verbatim audit row for every guest decision
    db.add(ApprovalGuestDecision(
        tenant_id=link.tenant_id,
        link_id=link.id,
        request_id=request.id,
        decision=body.decision,
        comment=body.comment,
        guest_name=guest_name,
    ))

    if step:
        step.status = body.decision
        step.comment = f"{guest_name} (guest): {(body.comment or '').strip()}".strip()
        step.decided_at = func.now()

        # Artifact Chain: the guest gate decision is an immutable, hash-linked entry
        from app.services.artifact_chain import append_artifact

        append_artifact(
            db, link.tenant_id, "approval_request", request.id,
            "approved" if body.decision == "Approved" else "rejected",
            actor_name=guest_name,
            payload={
                "step_id": step.id, "step_order": step.step_order, "role": step.role_name,
                "via": "guest_link", "guest_name": guest_name, "comment": body.comment,
                "title": request.title, "target_phase": request.target_phase,
            },
            artifact_type="gate_event",
        )

        all_steps = db.query(ApprovalStep).filter(
            ApprovalStep.request_id == request.id
        ).order_by(ApprovalStep.step_order).all()
        if body.decision == "Approved":
            if step.step_order >= all_steps[-1].step_order:
                # Last step approved — request fully approved (mirror in-app flow)
                request.status = "Approved"
                if request.request_type == "release" and request.release_id and request.target_phase:
                    from datetime import date as _date

                    from app.models.release import Release
                    from app.routers.releases import _create_phase_approval

                    release = db.query(Release).filter(
                        Release.id == request.release_id, Release.tenant_id == link.tenant_id
                    ).first()
                    if release and release.status != request.target_phase:
                        release.status = request.target_phase
                        if request.target_phase == "Released":
                            release.release_date = _date.today().isoformat()
                        db.commit()
                        db.refresh(release)
                        # _create_phase_approval dereferences current_user — pass the requester
                        requester = db.query(User).filter(User.id == request.requested_by).first() if request.requested_by else None
                        if requester:
                            _create_phase_approval(db, release, requester, link.tenant_id)
                if request.requested_by:
                    release_name = ""
                    if request.release_id:
                        from app.models.release import Release

                        rel = db.query(Release).filter(Release.id == request.release_id).first()
                        release_name = f"{rel.version} — {rel.name}" if rel else ""
                    notify_approval_result(
                        db, True, guest_name, release_name,
                        step.role_name, request.requested_by, request.project_id,
                    )
                log_activity(db, None, guest_name, request.project_id,
                             "approval", request.id, "approved",
                             f"Guest approved: {request.title[:80]} ({step.role_name})")
            else:
                request.current_step = step.step_order + 1
                log_activity(db, None, guest_name, request.project_id,
                             "approval", request.id, "approved",
                             f"Guest approved step {step.step_order}: {request.title[:80]}")
        else:
            request.status = "Rejected"
            if request.requested_by:
                notify_approval_result(
                    db, False, guest_name, "", step.role_name,
                    request.requested_by, request.project_id,
                )
            log_activity(db, None, guest_name, request.project_id,
                         "approval", request.id, "rejected",
                         f"Guest rejected: {request.title[:80]} ({step.role_name})")
    else:
        log_activity(db, None, guest_name, request.project_id,
                     "approval", request.id, "updated",
                     f"Guest decision ({body.decision.lower()}): {request.title[:80]}")

    db.commit()
    db.refresh(request)
    return {
        "detail": f"Decision recorded: {body.decision}",
        "guest_name": guest_name,
        "request_status": request.status,
    }
