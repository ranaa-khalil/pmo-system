"""Planning API router — vision, KPIs, roadmaps, milestones."""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.project_vision import ProjectVision
from app.models.kpi import KPI
from app.models.roadmap import Roadmap
from app.models.milestone import Milestone
from app.schemas.planning import (
    VisionCreate, VisionUpdate, VisionResponse,
    KPICreate, KPIUpdate, KPIResponse,
    RoadmapCreate, RoadmapUpdate, RoadmapResponse, RoadmapWithMilestonesResponse,
    MilestoneCreate, MilestoneUpdate, MilestoneResponse,
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

@router.get("/projects/{project_id}/kpis", response_model=List[KPIResponse])
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

@router.get("/projects/{project_id}/roadmaps", response_model=List[RoadmapWithMilestonesResponse])
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
