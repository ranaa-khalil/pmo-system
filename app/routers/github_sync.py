"""GitHub sync API router — board configuration and feature export.

Endpoints:
  GET  /api/projects/{project_id}/github-config         — get board config
  PUT  /api/projects/{project_id}/github-config         — create/update board config
  GET  /api/projects/{project_id}/github/projects       — list available GitHub Project V2 boards
  GET  /api/projects/{project_id}/github/labels         — list labels in the repo
  POST /api/projects/{project_id}/github/export         — export approved features to GitHub
  GET  /api/projects/{project_id}/github/sync-status    — check sync status of backlog items
"""
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.backlog_item import ITEM_PHASES, BacklogItem
from app.models.github_board_config import GitHubBoardConfig
from app.models.project import Project
from app.models.user import User
from app.schemas.github_sync import (
    GitHubBoardConfigResponse,
    GitHubBoardConfigUpdate,
    GitHubExportRequest,
    GitHubExportResult,
    GitHubImportResult,
    GitHubProjectInfo,
    GitHubResolveBoardRequest,
    GitHubSyncStatus,
)
from app.services.github import GitHubService
from app.services.notifications import log_activity

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

@router.get("/projects/{project_id}/github/projects", response_model=list[GitHubProjectInfo])
def list_github_projects(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List available GitHub Project V2 boards.

    Always lists user-level projects (the authenticated user's boards).
    Also lists repo-level and org-level projects if a repo is configured.
    Requires 'project' scope on the GitHub token.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not settings.github_token:
        raise HTTPException(status_code=400, detail="GitHub token not configured. Set PMO_GITHUB_TOKEN environment variable.")

    config = _get_or_create_config(db, project_id)
    repo = _resolve_repo(config, project)

    gh = _get_gh_service()
    try:
        projects = []

        # Always list user-level projects (works without a repo)
        user_projects = gh.list_user_projects()
        projects.extend(user_projects)

        # Also list repo-level and org-level projects if a repo is configured
        if repo:
            repo_projects = gh.list_projects(repo)
            existing_ids = {p["id"] for p in projects}
            for p in repo_projects:
                if p["id"] not in existing_ids:
                    projects.append(p)

            # Also try org-level projects
            owner = repo.split("/")[0] if "/" in repo else ""
            if owner:
                org_projects = gh.list_org_projects(owner)
                existing_ids = {p["id"] for p in projects}
                for p in org_projects:
                    if p["id"] not in existing_ids:
                        projects.append(p)

        return projects
    finally:
        gh.close()


@router.post("/projects/{project_id}/github/resolve-board", response_model=GitHubProjectInfo)
def resolve_board_url(
    project_id: int,
    req: GitHubResolveBoardRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Resolve a GitHub Project V2 board URL to its node ID and metadata.

    Accepts URLs like:
      https://github.com/users/ranaa-khalil/projects/1
      https://github.com/users/ranaa-khalil/projects/1/views/1
      https://github.com/orgs/myorg/projects/3
      https://github.com/owner/repo/projects/2

    Returns the project's node ID, title, URL, etc.
    Requires 'project' scope on the GitHub token.
    """
    if not db.query(Project).filter(Project.id == project_id).first():
        raise HTTPException(status_code=404, detail="Project not found")

    if not settings.github_token:
        raise HTTPException(status_code=400, detail="GitHub token not configured. Set PMO_GITHUB_TOKEN environment variable.")

    gh = _get_gh_service()
    try:
        result = gh.resolve_project_url(req.url)
        if not result:
            raise HTTPException(status_code=404, detail="Could not resolve the board URL. Make sure the URL is correct and the token has 'project' scope.")
        return result
    finally:
        gh.close()


@router.get("/projects/{project_id}/github/labels", response_model=list[dict])
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
        if config.project_node_id:
            raise HTTPException(
                status_code=400,
                detail="A project board is connected but no GitHub repo is configured. "
                       "Issues must be created in a repo before they can be added to a board. "
                       "Please set the GitHub Repository field above."
            )
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
                item.github_synced_at = datetime.now(UTC).isoformat()
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


# ─────────────────────────────────────────────────────────────
# Import / reverse-sync: GitHub → PMO
# ─────────────────────────────────────────────────────────────

@router.post("/projects/{project_id}/github/import", response_model=GitHubImportResult)
def import_from_github(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Pull issue status from GitHub and update backlog items.

    For each backlog item that has been exported to GitHub (has a github_issue_number):
    1. Fetch the issue's current state (open/closed), labels, assignees
    2. Store them on the backlog item (github_state, github_labels, github_assignees)
    3. If the issue is closed, advance the item to "Ready for UAT" + status "Done"
    4. If a project board is configured, also fetch the board's Status field

    Two strategies:
    - If project_node_id is set: single GraphQL call for all board items (fast)
    - Otherwise: individual REST calls per issue (works without project board)
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

    # Get all items that have been exported to GitHub
    synced_items = db.query(BacklogItem).filter(
        BacklogItem.project_id == project_id,
        BacklogItem.github_issue_number.isnot(None),
        BacklogItem.status != "Cancelled",
    ).all()

    if not synced_items:
        return GitHubImportResult(total=0)

    gh = _get_gh_service()
    result = GitHubImportResult(total=len(synced_items))
    now_iso = datetime.now(UTC).isoformat()

    try:
        # Strategy 1: If we have a project board, use GraphQL for a single batch call
        if config.project_node_id:
            board_items = gh.get_project_items_with_status(config.project_node_id)
            # Build a lookup: issue_number → board_item
            board_lookup = {bi["issue_number"]: bi for bi in board_items if bi.get("issue_number")}

            for item in synced_items:
                board_item = board_lookup.get(item.github_issue_number)
                if board_item:
                    old_state = item.github_state
                    new_state = (board_item.get("state", "") or "").lower()

                    item.github_state = new_state
                    item.github_labels = ", ".join(board_item.get("labels", []))
                    item.github_assignees = ", ".join(board_item.get("assignees", []))
                    item.github_last_sync_at = now_iso

                    # Track project board status if available
                    project_status = board_item.get("project_status")
                    phase_changed = False
                    if project_status:
                        # Map common GitHub Project status names to PMO phases
                        ps_lower = project_status.lower()
                        if ps_lower in ("done", "completed", "finished"):
                            if item.current_phase != "Ready for UAT":
                                item.current_phase = "Ready for UAT"
                                phase_changed = True
                            if item.status != "Done":
                                item.status = "Done"
                                phase_changed = True
                        elif ps_lower in ("in review", "review", "reviewing"):
                            if item.current_phase not in ("Testing", "Ready for UAT"):
                                item.current_phase = "Testing"
                                phase_changed = True
                        elif ps_lower in ("in progress", "working", "started"):
                            if item.current_phase not in ("Development", "Testing", "Ready for UAT"):
                                item.current_phase = "Development"
                                phase_changed = True

                    # Also check issue state — closed = done
                    # Normalize old_state for comparison (might be uppercase from older syncs)
                    old_state_norm = (old_state or "").lower()
                    status_changed = (old_state_norm != new_state)
                    if new_state == "closed":
                        if item.status != "Done":
                            item.status = "Done"
                            if item.current_phase not in ("Ready for UAT",):
                                item.current_phase = "Ready for UAT"
                            status_changed = True
                        result.closed_count += 1
                    elif new_state == "open":
                        result.open_count += 1

                    if status_changed or phase_changed:
                        result.updated += 1
                    else:
                        result.unchanged += 1

                    result.details.append({
                        "item_id": item.id,
                        "title": item.title,
                        "issue_number": item.github_issue_number,
                        "state": new_state,
                        "project_status": project_status,
                        "labels": board_item.get("labels", []),
                        "assignees": board_item.get("assignees", []),
                        "changed": status_changed or phase_changed,
                    })
                else:
                    # Issue not found on board — try REST as fallback
                    issue = gh.get_issue(repo, item.github_issue_number)
                    if issue:
                        old_state = item.github_state
                        new_state = (issue["state"] or "").lower()
                        item.github_state = new_state
                        item.github_labels = ", ".join(issue.get("labels", []))
                        item.github_assignees = ", ".join(issue.get("assignees", []))
                        item.github_last_sync_at = now_iso

                        status_changed = (old_state != new_state)
                        if new_state == "closed" and item.status != "Done":
                            item.status = "Done"
                            if item.current_phase != "Ready for UAT":
                                item.current_phase = "Ready for UAT"
                            status_changed = True
                            result.closed_count += 1
                        elif new_state == "open":
                            result.open_count += 1

                        if status_changed:
                            result.updated += 1
                        else:
                            result.unchanged += 1

                        result.details.append({
                            "item_id": item.id,
                            "title": item.title,
                            "issue_number": item.github_issue_number,
                            "state": new_state,
                            "labels": issue.get("labels", []),
                            "assignees": issue.get("assignees", []),
                            "changed": status_changed,
                        })
                    else:
                        result.failed += 1
                        result.details.append({
                            "item_id": item.id,
                            "title": item.title,
                            "issue_number": item.github_issue_number,
                            "error": "Could not fetch issue",
                        })

        # Strategy 2: No project board — fetch each issue via REST
        else:
            for item in synced_items:
                issue = gh.get_issue(repo, item.github_issue_number)
                if issue:
                    old_state = item.github_state
                    new_state = (issue["state"] or "").lower()
                    item.github_state = new_state
                    item.github_labels = ", ".join(issue.get("labels", []))
                    item.github_assignees = ", ".join(issue.get("assignees", []))
                    item.github_last_sync_at = now_iso

                    status_changed = (old_state != new_state)
                    if new_state == "closed" and item.status != "Done":
                        item.status = "Done"
                        if item.current_phase != "Ready for UAT":
                            item.current_phase = "Ready for UAT"
                        status_changed = True
                        result.closed_count += 1
                    elif new_state == "open":
                        result.open_count += 1

                    if status_changed:
                        result.updated += 1
                    else:
                        result.unchanged += 1

                    result.details.append({
                        "item_id": item.id,
                        "title": item.title,
                        "issue_number": item.github_issue_number,
                        "state": new_state,
                        "labels": issue.get("labels", []),
                        "assignees": issue.get("assignees", []),
                        "changed": status_changed,
                    })
                else:
                    result.failed += 1
                    result.details.append({
                        "item_id": item.id,
                        "title": item.title,
                        "issue_number": item.github_issue_number,
                        "error": "Could not fetch issue",
                    })

        db.commit()

        log_activity(db, current_user.id, current_user.name, project_id,
                     "github_import", 0, "synced",
                     f"Imported status from GitHub ({repo}). "
                     f"Updated: {result.updated}, Unchanged: {result.unchanged}, "
                     f"Failed: {result.failed}, Closed: {result.closed_count}")

    finally:
        gh.close()

    return result
