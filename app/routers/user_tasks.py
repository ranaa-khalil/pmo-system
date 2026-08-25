"""User tasks API router — personal to-dos with project/milestone links and due dates."""
from typing import List, Optional
from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.user_task import UserTask, TASK_STATUSES, TASK_PRIORITIES
from app.models.project import Project
from app.models.milestone import Milestone
from app.schemas.user_task import UserTaskCreate, UserTaskUpdate, UserTaskResponse

router = APIRouter(prefix="/api", tags=["user-tasks"])


def _enrich(task: UserTask, db: Session) -> dict:
    """Add joined display fields to a task response."""
    data = {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "assigned_to": task.assigned_to,
        "created_by": task.created_by,
        "project_id": task.project_id,
        "milestone_id": task.milestone_id,
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
        proj = db.query(Project).filter(Project.id == task.project_id).first()
        if proj:
            data["project_name"] = proj.name
    if task.milestone_id:
        ms = db.query(Milestone).filter(Milestone.id == task.milestone_id).first()
        if ms:
            data["milestone_title"] = ms.title
    assignee = db.query(User).filter(User.id == task.assigned_to).first()
    if assignee:
        data["assignee_name"] = assignee.name
    return data


@router.get("/tasks")
def list_tasks(
    status: Optional[str] = Query(None, description="Filter by status"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    project_id: Optional[int] = Query(None, description="Filter by project"),
    overdue: bool = Query(False, description="Only overdue tasks"),
    upcoming: bool = Query(False, description="Only tasks due within reminder window"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List tasks for the current user, with optional filters."""
    query = db.query(UserTask).filter(UserTask.assigned_to == current_user.id)
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
    return [_enrich(t, db) for t in tasks]


@router.post("/tasks")
def create_task(
    task: UserTaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new task. Defaults to current user if assigned_to is not set."""
    assigned_to = task.assigned_to or current_user.id
    # Validate project if set
    if task.project_id:
        if not db.query(Project).filter(Project.id == task.project_id).first():
            raise HTTPException(status_code=404, detail="Project not found")
    # Validate milestone if set
    if task.milestone_id:
        if not db.query(Milestone).filter(Milestone.id == task.milestone_id).first():
            raise HTTPException(status_code=404, detail="Milestone not found")
    # Validate status
    if task.status not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {TASK_STATUSES}")
    if task.priority not in TASK_PRIORITIES:
        raise HTTPException(status_code=400, detail=f"Invalid priority. Must be one of: {TASK_PRIORITIES}")

    db_task = UserTask(
        title=task.title,
        description=task.description,
        assigned_to=assigned_to,
        created_by=current_user.id,
        project_id=task.project_id,
        milestone_id=task.milestone_id,
        due_date=task.due_date,
        reminder_days=task.reminder_days,
        status=task.status,
        priority=task.priority,
    )
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    return _enrich(db_task, db)


@router.put("/tasks/{task_id}")
def update_task(
    task_id: int,
    task_update: UserTaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a task. Only the assigned user or a super_admin can update."""
    task = db.query(UserTask).filter(UserTask.id == task_id).first()
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

    for field, val in updates.items():
        setattr(task, field, val)

    # Set completed_at when status changes to Completed
    if updates.get("status") == "Completed" and not task.completed_at:
        task.completed_at = date.today().isoformat()
    elif updates.get("status") and updates["status"] != "Completed":
        task.completed_at = None

    db.commit()
    db.refresh(task)
    return _enrich(task, db)


@router.delete("/tasks/{task_id}")
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a task. Only the assigned user or a super_admin can delete."""
    task = db.query(UserTask).filter(UserTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.assigned_to != current_user.id and current_user.system_role != "super_admin":
        raise HTTPException(status_code=403, detail="You can only delete your own tasks")
    db.delete(task)
    db.commit()
    return {"detail": "Task deleted"}


@router.get("/tasks/summary")
def tasks_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a summary of the current user's tasks — for dashboard widget and nav badge."""
    base = db.query(UserTask).filter(UserTask.assigned_to == current_user.id)
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
