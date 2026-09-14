"""Planning API router — vision, KPIs, roadmaps, milestones."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.backlog_item import BacklogItem
from app.models.kpi import KPI
from app.models.milestone import Milestone
from app.models.project import Project
from app.models.project_vision import ProjectVision
from app.models.release import Release
from app.models.roadmap import Roadmap
from app.models.user import User
from app.models.user_task import UserTask
from app.schemas.planning import (
    KPICreate,
    KPIResponse,
    KPIUpdate,
    MilestoneCreate,
    MilestoneResponse,
    MilestoneUpdate,
    RoadmapCreate,
    RoadmapResponse,
    RoadmapUpdate,
    RoadmapWithMilestonesResponse,
    VisionCreate,
    VisionResponse,
    VisionUpdate,
)

router = APIRouter(prefix="/api", tags=["planning"])


# ===== Vision =====
@router.post("/projects/{project_id}/vision", response_model=VisionResponse, status_code=201)
def create_vision(project_id: int, vision: VisionCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Create a vision for a project."""
    if not db.query(Project).filter(Project.id == project_id).first():
        raise HTTPException(status_code=404, detail="Project not found")
    if vision.project_id != project_id:
        raise HTTPException(status_code=400, detail="project_id mismatch")
    if db.query(ProjectVision).filter(ProjectVision.project_id == project_id).first():
        raise HTTPException(status_code=409, detail="Vision already exists for this project")
    db_vision = ProjectVision(**vision.model_dump())
    db.add(db_vision)
    db.commit()
    db.refresh(db_vision)
    return db_vision

@router.get("/projects/{project_id}/vision", response_model=VisionResponse)
def get_vision(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get the vision for a project."""
    vision = db.query(ProjectVision).filter(ProjectVision.project_id == project_id).first()
    if not vision:
        raise HTTPException(status_code=404, detail="No vision found for this project")
    return vision

@router.put("/projects/{project_id}/vision", response_model=VisionResponse)
def update_vision(project_id: int, vision_update: VisionUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Update a project's vision."""
    vision = db.query(ProjectVision).filter(ProjectVision.project_id == project_id).first()
    if not vision:
        raise HTTPException(status_code=404, detail="No vision found for this project")
    for field, val in vision_update.model_dump(exclude_unset=True).items():
        setattr(vision, field, val)
    db.commit()
    db.refresh(vision)
    return vision


# ===== KPIs =====
@router.post("/projects/{project_id}/kpis", response_model=KPIResponse, status_code=201)
def create_kpi(project_id: int, kpi: KPICreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not db.query(Project).filter(Project.id == project_id).first():
        raise HTTPException(status_code=404, detail="Project not found")
    kpi.project_id = project_id
    db_kpi = KPI(**kpi.model_dump())
    db.add(db_kpi)
    db.commit()
    db.refresh(db_kpi)
    return db_kpi

@router.get("/projects/{project_id}/kpis", response_model=list[KPIResponse])
def list_kpis(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(KPI).filter(KPI.project_id == project_id).all()

@router.put("/kpis/{kpi_id}", response_model=KPIResponse)
def update_kpi(kpi_id: int, kpi_update: KPIUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    kpi = db.query(KPI).filter(KPI.id == kpi_id).first()
    if not kpi:
        raise HTTPException(status_code=404, detail="KPI not found")
    for field, val in kpi_update.model_dump(exclude_unset=True).items():
        setattr(kpi, field, val)
    db.commit()
    db.refresh(kpi)
    return kpi

@router.delete("/kpis/{kpi_id}", status_code=204)
def delete_kpi(kpi_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    kpi = db.query(KPI).filter(KPI.id == kpi_id).first()
    if not kpi:
        raise HTTPException(status_code=404, detail="KPI not found")
    db.delete(kpi)
    db.commit()


@router.get("/kpis/{kpi_id}/detail")
def get_kpi_detail(kpi_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get a KPI with related items: linked vision objective, releases, backlog items."""
    kpi = db.query(KPI).filter(KPI.id == kpi_id).first()
    if not kpi:
        raise HTTPException(status_code=404, detail="KPI not found")

    project_id = kpi.project_id

    # Linked vision objective
    vision = db.query(ProjectVision).filter(ProjectVision.project_id == project_id).first()

    # Releases for this project (the KPI measures the project's output)
    releases = db.query(Release).filter(Release.project_id == project_id).all()

    # Backlog items for this project
    backlog_items = db.query(BacklogItem).filter(BacklogItem.project_id == project_id).all()

    return {
        "id": kpi.id,
        "name": kpi.name,
        "target_value": kpi.target_value,
        "current_value": kpi.current_value,
        "unit": kpi.unit,
        "category": kpi.category,
        "vision_objective": kpi.vision_objective,
        "project_id": kpi.project_id,
        "vision_statement": vision.statement if vision else None,
        "strategic_objectives": vision.strategic_objectives if vision else None,
        "releases": [{"id": r.id, "version": r.version, "status": r.status, "target_date": r.target_date} for r in releases],
        "backlog_items_count": len(backlog_items),
        "backlog_items_done": len([b for b in backlog_items if b.status == "Done"]),
        "backlog_items_in_progress": len([b for b in backlog_items if b.status not in ("Done",)]),
    }


# ===== Roadmaps =====
@router.post("/projects/{project_id}/roadmaps", response_model=RoadmapResponse, status_code=201)
def create_roadmap(project_id: int, roadmap: RoadmapCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not db.query(Project).filter(Project.id == project_id).first():
        raise HTTPException(status_code=404, detail="Project not found")
    roadmap.project_id = project_id
    db_roadmap = Roadmap(**roadmap.model_dump())
    db.add(db_roadmap)
    db.commit()
    db.refresh(db_roadmap)
    return db_roadmap

@router.get("/projects/{project_id}/roadmaps", response_model=list[RoadmapWithMilestonesResponse])
def list_roadmaps(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    roadmaps = db.query(Roadmap).filter(Roadmap.project_id == project_id).all()
    for rm in roadmaps:
        rm.milestones = db.query(Milestone).filter(Milestone.roadmap_id == rm.id).all()
    return roadmaps

@router.put("/roadmaps/{roadmap_id}", response_model=RoadmapResponse)
def update_roadmap(roadmap_id: int, rm_update: RoadmapUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rm = db.query(Roadmap).filter(Roadmap.id == roadmap_id).first()
    if not rm:
        raise HTTPException(status_code=404, detail="Roadmap not found")
    for field, val in rm_update.model_dump(exclude_unset=True).items():
        setattr(rm, field, val)
    db.commit()
    db.refresh(rm)
    return rm

@router.delete("/roadmaps/{roadmap_id}", status_code=204)
def delete_roadmap(roadmap_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rm = db.query(Roadmap).filter(Roadmap.id == roadmap_id).first()
    if not rm:
        raise HTTPException(status_code=404, detail="Roadmap not found")
    db.delete(rm)
    db.commit()


# ===== Milestones =====
@router.post("/roadmaps/{roadmap_id}/milestones", response_model=MilestoneResponse, status_code=201)
def create_milestone(roadmap_id: int, milestone: MilestoneCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not db.query(Roadmap).filter(Roadmap.id == roadmap_id).first():
        raise HTTPException(status_code=404, detail="Roadmap not found")
    milestone.roadmap_id = roadmap_id
    db_ms = Milestone(**milestone.model_dump())
    db.add(db_ms)
    db.commit()
    db.refresh(db_ms)
    return db_ms

@router.get("/milestones/{milestone_id}/detail")
def get_milestone_detail(milestone_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get a milestone with all related items: tasks, releases, backlog items."""
    ms = db.query(Milestone).filter(Milestone.id == milestone_id).first()
    if not ms:
        raise HTTPException(status_code=404, detail="Milestone not found")

    # Related user tasks
    tasks = db.query(UserTask).filter(UserTask.milestone_id == milestone_id).all()

    # Related releases
    releases = db.query(Release).filter(Release.milestone_id == milestone_id).all()

    # Backlog items for this project (via roadmap → project)
    roadmap = db.query(Roadmap).filter(Roadmap.id == ms.roadmap_id).first()
    backlog_items = []
    if roadmap:
        backlog_items = db.query(BacklogItem).filter(BacklogItem.project_id == roadmap.project_id).all()

    return {
        "id": ms.id,
        "title": ms.title,
        "description": ms.description,
        "target_date": ms.target_date,
        "status": ms.status,
        "roadmap_id": ms.roadmap_id,
        "created_at": ms.created_at,
        "tasks": [{"id": t.id, "title": t.title, "status": t.status, "priority": t.priority, "assignee_name": t.assignee.name if t.assignee else None} for t in tasks],
        "releases": [{"id": r.id, "version": r.version, "status": r.status, "target_date": r.target_date} for r in releases],
        "backlog_items": [{"id": b.id, "title": b.title, "type": b.item_type, "current_phase": b.current_phase, "status": b.status} for b in backlog_items],
    }


@router.put("/milestones/{milestone_id}", response_model=MilestoneResponse)
def update_milestone(milestone_id: int, ms_update: MilestoneUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ms = db.query(Milestone).filter(Milestone.id == milestone_id).first()
    if not ms:
        raise HTTPException(status_code=404, detail="Milestone not found")
    for field, val in ms_update.model_dump(exclude_unset=True).items():
        setattr(ms, field, val)
    db.commit()
    db.refresh(ms)
    return ms

@router.delete("/milestones/{milestone_id}", status_code=204)
def delete_milestone(milestone_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ms = db.query(Milestone).filter(Milestone.id == milestone_id).first()
    if not ms:
        raise HTTPException(status_code=404, detail="Milestone not found")
    db.delete(ms)
    db.commit()
