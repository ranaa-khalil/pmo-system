"""Release API router — V-cycle release management."""
from typing import List
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.backlog_item import BacklogItem
from app.models.release import Release, ReleaseItem, RELEASE_STATUSES
from app.schemas.release import ReleaseCreate, ReleaseUpdate, ReleaseResponse

router = APIRouter(prefix="/api", tags=["releases"])


@router.post("/projects/{project_id}/releases", response_model=ReleaseResponse, status_code=201)
def create_release(
    project_id: int,
    release: ReleaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new release for a project."""
    if not db.query(Project).filter(Project.id == project_id).first():
        raise HTTPException(status_code=404, detail="Project not found")
    db_release = Release(
        project_id=project_id,
        created_by=current_user.id,
        **release.model_dump(),
    )
    db.add(db_release)
    db.commit()
    db.refresh(db_release)
    return db_release


@router.get("/projects/{project_id}/releases", response_model=List[ReleaseResponse])
def list_releases(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all releases for a project."""
    return db.query(Release).filter(Release.project_id == project_id).order_by(Release.created_at.desc()).all()


@router.get("/releases/{release_id}", response_model=dict)
def get_release(
    release_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get release detail with linked backlog items."""
    release = db.query(Release).filter(Release.id == release_id).first()
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")
    items = []
    for ri in release.items:
        bi = db.query(BacklogItem).filter(BacklogItem.id == ri.backlog_item_id).first()
        if bi:
            items.append({
                "id": bi.id, "title": bi.title, "description": bi.description,
                "current_phase": bi.current_phase, "status": bi.status,
                "priority": bi.priority,
            })
    return {
        "id": release.id,
        "project_id": release.project_id,
        "version": release.version,
        "name": release.name,
        "description": release.description,
        "status": release.status,
        "target_date": release.target_date,
        "release_date": release.release_date,
        "release_notes": release.release_notes,
        "created_by": release.created_by,
        "items": items,
    }


@router.put("/releases/{release_id}", response_model=ReleaseResponse)
def update_release(
    release_id: int,
    update: ReleaseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a release."""
    release = db.query(Release).filter(Release.id == release_id).first()
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")
    for field, val in update.model_dump(exclude_unset=True).items():
        setattr(release, field, val)
    db.commit()
    db.refresh(release)
    return release


@router.delete("/releases/{release_id}", status_code=204)
def delete_release(
    release_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a release."""
    release = db.query(Release).filter(Release.id == release_id).first()
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")
    db.delete(release)
    db.commit()


@router.post("/releases/{release_id}/items/{backlog_item_id}", status_code=201)
def add_item_to_release(
    release_id: int,
    backlog_item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Link a backlog item to a release."""
    release = db.query(Release).filter(Release.id == release_id).first()
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")
    item = db.query(BacklogItem).filter(BacklogItem.id == backlog_item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Backlog item not found")
    existing = db.query(ReleaseItem).filter(
        ReleaseItem.release_id == release_id,
        ReleaseItem.backlog_item_id == backlog_item_id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Item already in this release")
    ri = ReleaseItem(release_id=release_id, backlog_item_id=backlog_item_id)
    db.add(ri)
    db.commit()
    return {"message": "Item added to release"}


@router.delete("/releases/{release_id}/items/{backlog_item_id}", status_code=204)
def remove_item_from_release(
    release_id: int,
    backlog_item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a backlog item from a release."""
    ri = db.query(ReleaseItem).filter(
        ReleaseItem.release_id == release_id,
        ReleaseItem.backlog_item_id == backlog_item_id,
    ).first()
    if not ri:
        raise HTTPException(status_code=404, detail="Item not in this release")
    db.delete(ri)
    db.commit()


@router.post("/releases/{release_id}/generate-notes", response_model=dict)
def generate_release_notes(
    release_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Auto-generate release notes from completed backlog items."""
    release = db.query(Release).filter(Release.id == release_id).first()
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")

    items = []
    for ri in release.items:
        bi = db.query(BacklogItem).filter(BacklogItem.id == ri.backlog_item_id).first()
        if bi:
            items.append(bi)

    # Group by phase
    done_phases = ["Pre-Release", "Release", "Post-Release", "Retrospective"]
    completed = [i for i in items if i.current_phase in done_phases]
    in_progress = [i for i in items if i.current_phase not in done_phases]

    # Build release notes
    today = date.today().isoformat()
    notes_lines = [
        f"# Release {release.version} — {release.name}",
        f"**Date:** {today}",
        f"**Status:** {release.status}",
        "",
    ]
    if release.description:
        notes_lines.append(f"## Overview")
        notes_lines.append(release.description)
        notes_lines.append("")

    if completed:
        notes_lines.append("## ✅ Completed Items")
        for item in completed:
            notes_lines.append(f"- **{item.title}** — {item.current_phase}")
            if item.description:
                notes_lines.append(f"  {item.description}")
        notes_lines.append("")

    if in_progress:
        notes_lines.append("## 🔄 In Progress")
        for item in in_progress:
            notes_lines.append(f"- **{item.title}** — {item.current_phase} ({item.status})")
        notes_lines.append("")

    notes_lines.append("---")
    notes_lines.append(f"**Total items:** {len(items)}")
    notes_lines.append(f"**Completed:** {len(completed)} | **In Progress:** {len(in_progress)}")

    notes = "\n".join(notes_lines)
    release.release_notes = notes
    db.commit()

    return {"release_notes": notes, "total_items": len(items), "completed": len(completed)}
