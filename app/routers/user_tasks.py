"""User tasks API router — personal to-dos with project/milestone links and due dates."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.milestone import Milestone
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_task import TASK_PRIORITIES, TASK_STATUSES, UserTask
from app.schemas.user_task import UserTaskCreate, UserTaskUpdate
from app.services.notifications import log_activity
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api", tags=["user-tasks"])


def _enrich(task: UserTask, db: Session, tenant_id: int) -> dict:
    """Add joined display fields to a task response."""
    data = {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "assigned_to": task.assigned_to,
        "created_by": task.created_by,
        "project_id": task.project_id,
        "milestone_id": task.milestone_id,
        "parent_task_id": task.parent_task_id,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "reminder_days": task.reminder_days,
        "status": task.status,
        "priority": task.priority,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "completed_at": task.completed_at,
        "project_name": None,
        "milestone_title": None,
        "assignee_name": None,
    }
    if task.project_id:
        proj = db.query(Project).filter(Project.id == task.project_id, Project.tenant_id == tenant_id).first()
        if proj:
            data["project_name"] = proj.name
    if task.milestone_id:
        ms = db.query(Milestone).filter(Milestone.id == task.milestone_id, Milestone.tenant_id == tenant_id).first()
        if ms:
            data["milestone_title"] = ms.title
    assignee = db.query(User).filter(User.id == task.assigned_to).first()
    if assignee:
        data["assignee_name"] = assignee.name
    # Secondary assignees (M2M, joined for display)
    from app.models.user_task import task_assignees

    rows = (
        db.query(User.id, User.name)
        .join(task_assignees, task_assignees.c.user_id == User.id)
        .filter(task_assignees.c.task_id == task.id)
        .all()
    )
    data["assignees"] = [{"id": uid, "name": name} for uid, name in rows]
    return data




def _member_of(db: Session, user_id: int, tenant_id: int) -> bool:
    from app.models.tenant import TenantMembership

    return db.query(TenantMembership).filter(
        TenantMembership.user_id == user_id, TenantMembership.tenant_id == tenant_id,
    ).first() is not None

@router.get("/tasks")
def list_tasks(
    status: str | None = Query(None, description="Filter by status"),
    priority: str | None = Query(None, description="Filter by priority"),
    project_id: int | None = Query(None, description="Filter by project"),
    overdue: bool = Query(False, description="Only overdue tasks"),
    upcoming: bool = Query(False, description="Only tasks due within reminder window"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """List tasks for the current user, with optional filters."""
    query = db.query(UserTask).filter(UserTask.assigned_to == current_user.id, UserTask.tenant_id == current_tenant.id)
    if status:
        query = query.filter(UserTask.status == status)
    if priority:
        query = query.filter(UserTask.priority == priority)
    if project_id:
        query = query.filter(UserTask.project_id == project_id)
    if overdue:
        query = query.filter(
            UserTask.due_date < date.today(),
            UserTask.status.notin_(["Completed", "Cancelled"]),
        )
    if upcoming:
        query = query.filter(
            UserTask.due_date.isnot(None),
            UserTask.due_date >= date.today(),
            UserTask.due_date <= date.today() + timedelta(days=7),
            UserTask.status.notin_(["Completed", "Cancelled"]),
        )
    tasks = query.order_by(
        UserTask.status != "Completed",
        UserTask.due_date.is_(None),
        UserTask.due_date,
        UserTask.priority.desc(),
    ).all()
    # Bulk-load tags for all listed tasks (2 queries total, no N+1)
    tag_map = {}
    task_ids = [t.id for t in tasks]
    if task_ids:
        from app.models.tag import Tag, user_task_tags

        rows = (
            db.query(user_task_tags.c.user_task_id, Tag.id, Tag.name, Tag.color)
            .join(Tag, Tag.id == user_task_tags.c.tag_id)
            .filter(user_task_tags.c.user_task_id.in_(task_ids))
            .all()
        )
        for utid, tag_id, tag_name, tag_color in rows:
            tag_map.setdefault(utid, []).append({"id": tag_id, "name": tag_name, "color": tag_color})
    result = [_enrich(t, db, current_tenant.id) for t in tasks]
    for data in result:
        data["tags"] = tag_map.get(data["id"], [])
    return result


@router.post("/tasks")
def create_task(
    task: UserTaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Create a new task. Defaults to current user if assigned_to is not set."""
    tid = current_tenant.id
    assigned_to = task.assigned_to or current_user.id
    # Validate project if set
    if task.project_id:
        if not db.query(Project).filter(Project.id == task.project_id, Project.tenant_id == tid).first():
            raise HTTPException(status_code=404, detail="Project not found")
    # Validate milestone if set
    if task.milestone_id:
        if not db.query(Milestone).filter(Milestone.id == task.milestone_id, Milestone.tenant_id == tid).first():
            raise HTTPException(status_code=404, detail="Milestone not found")
    # Validate status
    if task.status not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {TASK_STATUSES}")
    if task.priority not in TASK_PRIORITIES:
        raise HTTPException(status_code=400, detail=f"Invalid priority. Must be one of: {TASK_PRIORITIES}")
    # Validate subtask parent: must exist in tenant, and one level only
    parent = None
    if task.parent_task_id:
        parent = db.query(UserTask).filter(
            UserTask.id == task.parent_task_id, UserTask.tenant_id == tid
        ).first()
        if not parent:
            raise HTTPException(status_code=404, detail="Parent task not found")
        if parent.parent_task_id is not None:
            raise HTTPException(status_code=400, detail="Subtasks can only be one level deep")

    db_task = UserTask(
        title=task.title,
        description=task.description,
        assigned_to=assigned_to,
        created_by=current_user.id,
        project_id=task.project_id,
        milestone_id=task.milestone_id,
        parent_task_id=task.parent_task_id,
        due_date=task.due_date,
        reminder_days=task.reminder_days,
        status=task.status,
        priority=task.priority,
        tenant_id=tid,
    )
    db.add(db_task)
    db.commit()
    db.refresh(db_task)

    # Secondary assignees
    if task.assignee_ids:
        from app.models.user_task import task_assignees

        valid_users = [
            u.id for u in db.query(User).filter(User.id.in_(task.assignee_ids)).all()
            if _member_of(db, u.id, tid)
        ]
        for uid in dict.fromkeys(valid_users):
            db.execute(task_assignees.insert().values(task_id=db_task.id, user_id=uid))
        db.commit()

    log_activity(db, current_user.id, current_user.name, task.project_id,
                 "task", db_task.id, "created",
                 f"Created task: {db_task.title}")

    return _enrich(db_task, db, tid)


@router.put("/tasks/{task_id}")
def update_task(
    task_id: int,
    task_update: UserTaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Update a task. Only the assigned user or a super_admin can update."""
    task = db.query(UserTask).filter(UserTask.id == task_id, UserTask.tenant_id == current_tenant.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.assigned_to != current_user.id and current_user.system_role != "super_admin":
        raise HTTPException(status_code=403, detail="You can only update your own tasks")

    updates = task_update.model_dump(exclude_unset=True)
    # Validate status
    if "status" in updates and updates["status"] not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {TASK_STATUSES}")
    if "priority" in updates and updates["priority"] not in TASK_PRIORITIES:
        raise HTTPException(status_code=400, detail=f"Invalid priority. Must be one of: {TASK_PRIORITIES}")

    assignee_ids = updates.pop("assignee_ids", None)
    for field, val in updates.items():
        setattr(task, field, val)

    # Replace the secondary assignee set when provided
    if assignee_ids is not None:
        from app.models.user_task import task_assignees

        db.execute(task_assignees.delete().where(task_assignees.c.task_id == task.id))
        valid_users = [
            u.id for u in db.query(User).filter(User.id.in_(assignee_ids)).all()
            if _member_of(db, u.id, current_tenant.id)
        ]
        for uid in dict.fromkeys(valid_users):
            db.execute(task_assignees.insert().values(task_id=task.id, user_id=uid))

    # Set completed_at when status changes to Completed
    if updates.get("status") == "Completed" and not task.completed_at:
        task.completed_at = date.today().isoformat()
    elif updates.get("status") and updates["status"] != "Completed":
        task.completed_at = None

    db.commit()
    db.refresh(task)
    return _enrich(task, db, current_tenant.id)


@router.delete("/tasks/{task_id}")
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Delete a task. Only the assigned user or a super_admin can delete."""
    task = db.query(UserTask).filter(UserTask.id == task_id, UserTask.tenant_id == current_tenant.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.assigned_to != current_user.id and current_user.system_role != "super_admin":
        raise HTTPException(status_code=403, detail="You can only delete your own tasks")
    # Application-level cascade: remove subtasks first (SQLite doesn't fire
    # DB-level ON DELETE CASCADE without the pragma; ORM delete also cleans
    # the tag association rows).
    subtasks = db.query(UserTask).filter(UserTask.parent_task_id == task.id).all()
    for sub in subtasks:
        db.delete(sub)
    db.delete(task)
    db.commit()
    return {"detail": "Task deleted"}


@router.get("/tasks/{task_id}/subtasks")
def list_subtasks(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """List a task's subtasks (checklist). Only the assignee, creator, or super_admin."""
    task = db.query(UserTask).filter(UserTask.id == task_id, UserTask.tenant_id == current_tenant.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.assigned_to != current_user.id and task.created_by != current_user.id and current_user.system_role != "super_admin":
        raise HTTPException(status_code=403, detail="You can only view subtasks of your own tasks")
    subtasks = (
        db.query(UserTask)
        .filter(UserTask.parent_task_id == task_id, UserTask.tenant_id == current_tenant.id)
        .order_by(UserTask.status != "Completed", UserTask.created_at)
        .all()
    )
    done = len([s for s in subtasks if s.status == "Completed"])
    return {
        "parent_id": task.id,
        "total": len(subtasks),
        "done": done,
        "subtasks": [_enrich(s, db, current_tenant.id) for s in subtasks],
    }


@router.get("/tasks/summary")
def tasks_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Get a summary of the current user's tasks — for dashboard widget and nav badge."""
    base = db.query(UserTask).filter(UserTask.assigned_to == current_user.id, UserTask.tenant_id == current_tenant.id)
    total = base.count()
    pending = base.filter(UserTask.status == "Pending").count()
    in_progress = base.filter(UserTask.status == "In Progress").count()
    completed = base.filter(UserTask.status == "Completed").count()
    overdue = base.filter(
        UserTask.due_date < date.today(),
        UserTask.status.notin_(["Completed", "Cancelled"]),
    ).count()
    due_soon = base.filter(
        UserTask.due_date.isnot(None),
        UserTask.due_date >= date.today(),
        UserTask.due_date <= date.today() + timedelta(days=7),
        UserTask.status.notin_(["Completed", "Cancelled"]),
    ).count()
    return {
        "total": total,
        "pending": pending,
        "in_progress": in_progress,
        "completed": completed,
        "overdue": overdue,
        "due_soon": due_soon,
        "active": pending + in_progress,
    }
