"""GitHub sync API router — board configuration and feature export.

Endpoints:
  GET  /api/projects/{project_id}/github-config         — get board config
  PUT  /api/projects/{project_id}/github-config         — create/update board config
  GET  /api/projects/{project_id}/github/projects       — list available GitHub Project V2 boards
  GET  /api/projects/{project_id}/github/labels         — list labels in the repo
  POST /api/projects/{project_id}/github/export         — export approved features to GitHub
  GET  /api/projects/{project_id}/github/sync-status    — check sync status of backlog items
"""
from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.backlog_item import BacklogItem, ITEM_PHASES
from app.models.github_board_config import GitHubBoardConfig
from app.services.github import GitHubService
from app.services.notifications import log_activity
from app.config import settings
from app.schemas.github_sync import (
    GitHubBoardConfigCreate,
    GitHubBoardConfigUpdate,
    GitHubBoardConfigResponse,
    GitHubProjectInfo,
    GitHubExportRequest,
    GitHubExportResult,
    GitHubSyncStatus,
)

router = APIRouter(prefix="/api", tags=["github-sync"])


def _get_or_create_config(db: Session, project_id: int) -> GitHubBoardConfig:
    """Get existing config or create a new default one."""
    config = db.query(GitHubBoardConfig).filter(
        GitHubBoardConfig.project_id == project_id
    ).first()
    if not config:
        config = GitHubBoardConfig(project_id=project_id)
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def _resolve_repo(config: GitHubBoardConfig, project: Project) -> str:
    """Determine which repo to use — config.repo falls back to project.github_repo."""
    return config.repo or project.github_repo or ""


def _get_gh_service() -> GitHubService:
    """Create a GitHubService instance with the configured token."""
    return GitHubService(token=settings.github_token or None)


# ─────────────────────────────────────────────────────────────
# Board configuration
# ─────────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/github-config", response_model=GitHubBoardConfigResponse)
def get_github_config(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the GitHub board configuration for a project."""
    if not db.query(Project).filter(Project.id == project_id).first():
        raise HTTPException(status_code=404, detail="Project not found")
    config = _get_or_create_config(db, project_id)
    return config


@router.put("/projects/{project_id}/github-config", response_model=GitHubBoardConfigResponse)
def update_github_config(
    project_id: int,
    config_update: GitHubBoardConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create or update the GitHub board configuration for a project."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    config = _get_or_create_config(db, project_id)
    updates = config_update.model_dump(exclude_unset=True)
    for field, val in updates.items():
        setattr(config, field, val)

    db.commit()
    db.refresh(config)

    log_activity(db, current_user.id, current_user.name, project_id,
                 "github_config", config.id, "updated",
                 f"Updated GitHub board config for '{project.name}'")

    return config


# ─────────────────────────────────────────────────────────────
# GitHub Project V2 boards listing
# ─────────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/github/projects", response_model=List[GitHubProjectInfo])
def list_github_projects(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List available GitHub Project V2 boards for the project's repo.

    Also searches org-level and user-level projects.
    Requires 'project' scope on the GitHub token.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    config = _get_or_create_config(db, project_id)
    repo = _resolve_repo(config, project)
    if not repo:
        raise HTTPException(status_code=400, detail="No GitHub repo configured. Set the repo in the board config or project settings.")

    gh = _get_gh_service()
    try:
        projects = gh.list_projects(repo)

        # Also try org-level projects if the repo is under an org
        owner = repo.split("/")[0] if "/" in repo else ""
        if owner:
            org_projects = gh.list_org_projects(owner)
            # Merge, avoiding duplicates by ID
            existing_ids = {p["id"] for p in projects}
            for p in org_projects:
                if p["id"] not in existing_ids:
                    projects.append(p)

        # Also try user-level projects
        user_projects = gh.list_user_projects()
        existing_ids = {p["id"] for p in projects}
        for p in user_projects:
            if p["id"] not in existing_ids:
                projects.append(p)

        return projects
    finally:
        gh.close()


@router.get("/projects/{project_id}/github/labels", response_model=List[dict])
def list_github_labels(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List available labels in the project's GitHub repo."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    config = _get_or_create_config(db, project_id)
    repo = _resolve_repo(config, project)
    if not repo:
        raise HTTPException(status_code=400, detail="No GitHub repo configured")

    gh = _get_gh_service()
    try:
        return gh.list_labels(repo)
    finally:
        gh.close()


# ─────────────────────────────────────────────────────────────
# Export approved features to GitHub
# ─────────────────────────────────────────────────────────────

@router.post("/projects/{project_id}/github/export", response_model=GitHubExportResult)
def export_to_github(
    project_id: int,
    export_req: GitHubExportRequest = GitHubExportRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export approved backlog items to GitHub.

    If item_ids is provided, exports those specific items.
    Otherwise, exports all items that have passed Requirements phase
    (i.e., items in Design, Development, Testing, or Ready for UAT)
    and haven't been synced yet.

    For each item:
    1. Creates a GitHub issue with rich body (metadata, acceptance criteria, etc.)
    2. Applies configured labels
    3. Optionally adds the issue to a GitHub Project V2 board
    4. Records the issue number, URL, and sync timestamp on the backlog item
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    config = _get_or_create_config(db, project_id)
    repo = _resolve_repo(config, project)
    if not repo:
        raise HTTPException(status_code=400, detail="No GitHub repo configured. Set the repo in the board config or project settings.")

    if not settings.github_token:
        raise HTTPException(status_code=400, detail="GitHub token not configured. Set PMO_GITHUB_TOKEN environment variable.")

    # Determine which items to export
    if export_req.item_ids:
        items = db.query(BacklogItem).filter(
            BacklogItem.project_id == project_id,
            BacklogItem.id.in_(export_req.item_ids),
        ).all()
    else:
        # Export all items past Requirements that aren't synced yet
        exportable_phases = [p for p in ITEM_PHASES if p != "Requirements"]
        items = db.query(BacklogItem).filter(
            BacklogItem.project_id == project_id,
            BacklogItem.current_phase.in_(exportable_phases),
            BacklogItem.github_issue_number.is_(None),
            BacklogItem.status != "Cancelled",
        ).all()

    # Parse labels
    labels = []
    if config.default_labels:
        labels = [l.strip() for l in config.default_labels.split(",") if l.strip()]

    gh = _get_gh_service()
    result = GitHubExportResult(total=len(items))

    try:
        for item in items:
            # Skip already-synced items
            if item.github_issue_number:
                result.skipped += 1
                result.details.append({
                    "item_id": item.id,
                    "title": item.title,
                    "status": "skipped",
                    "reason": "Already synced",
                    "issue_number": item.github_issue_number,
                })
                continue

            # Export the item
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
                title_prefix=config.issue_title_prefix,
                project_node_id=config.project_node_id,
                include_acceptance_criteria=config.include_acceptance_criteria,
                include_dependencies=config.include_dependencies,
            )

            if issue:
                item.github_issue_number = issue["number"]
                item.github_issue_url = issue.get("html_url", "")
                item.github_synced_at = datetime.now(timezone.utc).isoformat()
                result.exported += 1
                result.details.append({
                    "item_id": item.id,
                    "title": item.title,
                    "status": "exported",
                    "issue_number": issue["number"],
                    "issue_url": issue.get("html_url", ""),
                    "added_to_project": issue.get("added_to_project", False),
                })
            else:
                result.failed += 1
                result.details.append({
                    "item_id": item.id,
                    "title": item.title,
                    "status": "failed",
                    "reason": "GitHub API error",
                })

        db.commit()

        log_activity(db, current_user.id, current_user.name, project_id,
                     "github_export", 0, "exported",
                     f"Exported {result.exported} items to GitHub ({repo}). "
                     f"Skipped: {result.skipped}, Failed: {result.failed}")

    finally:
        gh.close()

    return result


# ─────────────────────────────────────────────────────────────
# Sync status
# ─────────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/github/sync-status", response_model=GitHubSyncStatus)
def get_sync_status(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Check the GitHub sync status of a project's backlog items."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    config = _get_or_create_config(db, project_id)

    all_items = db.query(BacklogItem).filter(
        BacklogItem.project_id == project_id,
        BacklogItem.status != "Cancelled",
    ).all()

    synced = [i for i in all_items if i.github_issue_number]
    unsynced = [i for i in all_items if not i.github_issue_number]

    return GitHubSyncStatus(
        total_items=len(all_items),
        synced_items=len(synced),
        unsynced_items=len(unsynced),
        config=config,
    )
