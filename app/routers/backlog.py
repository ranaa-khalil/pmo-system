"""Backlog API router — business requirements following the 9-phase process."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.backlog_item import BacklogItem, PHASES
from app.schemas.backlog import BacklogItemCreate, BacklogItemUpdate, BacklogItemResponse
from app.services.github import GitHubService
from app.config import settings

router = APIRouter(prefix="/api", tags=["backlog"])


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
        project = db.query(Project).filter(Project.id == item.project_id).first()
        if project and project.github_repo:
            gh = GitHubService(token=settings.github_token or None)
            issue = gh.create_issue(
                repo=project.github_repo,
                title=item.title,
                body=f"**PMO Backlog Item**\n\n{item.description or 'No description'}\n\n---\nPriority: {item.priority}\nPhase: {item.current_phase}",
                labels=["from-pmo"],
            )
            if issue:
                item.github_issue_number = issue["number"]
            gh.close()

    db.commit()
    db.refresh(item)
    return item


@router.post("/backlog/{item_id}/advance", response_model=BacklogItemResponse)
def advance_backlog_phase(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Advance a backlog item to the next phase in the 9-phase process."""
    item = db.query(BacklogItem).filter(BacklogItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Backlog item not found")

    current_idx = PHASES.index(item.current_phase) if item.current_phase in PHASES else 0
    if current_idx < len(PHASES) - 1:
        item.current_phase = PHASES[current_idx + 1]
        if item.status == "Draft":
            item.status = "In Progress"

        # GitHub sync on entering Development
        if item.current_phase == "Development" and not item.github_issue_number:
            project = db.query(Project).filter(Project.id == item.project_id).first()
            if project and project.github_repo:
                gh = GitHubService(token=settings.github_token or None)
                issue = gh.create_issue(
                    repo=project.github_repo,
                    title=item.title,
                    body=f"**PMO Backlog Item**\n\n{item.description or ''}\n\n---\nPriority: {item.priority}",
                    labels=["from-pmo"],
                )
                if issue:
                    item.github_issue_number = issue["number"]
                gh.close()

    db.commit()
    db.refresh(item)
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
