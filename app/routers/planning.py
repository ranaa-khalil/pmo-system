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
from app.models.tenant import Tenant
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
from app.services.tenant import get_current_tenant

router = APIRouter(prefix="/api", tags=["planning"])


# ===== Vision =====
@router.post("/projects/{project_id}/vision", response_model=VisionResponse, status_code=201)
def create_vision(project_id: int, vision: VisionCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    """Create a vision for a project."""
    if not db.query(Project).filter(Project.id == project_id, Project.tenant_id == current_tenant.id).first():
        raise HTTPException(status_code=404, detail="Project not found")
    if vision.project_id != project_id:
        raise HTTPException(status_code=400, detail="project_id mismatch")
    if db.query(ProjectVision).filter(ProjectVision.project_id == project_id, ProjectVision.tenant_id == current_tenant.id).first():
        raise HTTPException(status_code=409, detail="Vision already exists for this project")
    db_vision = ProjectVision(**vision.model_dump(), tenant_id=current_tenant.id)
    db.add(db_vision)
    db.commit()
    db.refresh(db_vision)
    return db_vision

@router.get("/projects/{project_id}/vision", response_model=VisionResponse)
def get_vision(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    """Get the vision for a project."""
    vision = db.query(ProjectVision).filter(ProjectVision.project_id == project_id, ProjectVision.tenant_id == current_tenant.id).first()
    if not vision:
        raise HTTPException(status_code=404, detail="No vision found for this project")
    return vision

@router.put("/projects/{project_id}/vision", response_model=VisionResponse)
def update_vision(project_id: int, vision_update: VisionUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    """Update a project's vision."""
    vision = db.query(ProjectVision).filter(ProjectVision.project_id == project_id, ProjectVision.tenant_id == current_tenant.id).first()
    if not vision:
        raise HTTPException(status_code=404, detail="No vision found for this project")
    for field, val in vision_update.model_dump(exclude_unset=True).items():
        setattr(vision, field, val)
    db.commit()
    db.refresh(vision)
    return vision


# ===== KPIs =====
@router.post("/projects/{project_id}/kpis", response_model=KPIResponse, status_code=201)
def create_kpi(project_id: int, kpi: KPICreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    if not db.query(Project).filter(Project.id == project_id, Project.tenant_id == current_tenant.id).first():
        raise HTTPException(status_code=404, detail="Project not found")
    kpi.project_id = project_id
    db_kpi = KPI(**kpi.model_dump(), tenant_id=current_tenant.id)
    db.add(db_kpi)
    db.commit()
    db.refresh(db_kpi)
    return db_kpi

@router.get("/projects/{project_id}/kpis", response_model=list[KPIResponse])
def list_kpis(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    return db.query(KPI).filter(KPI.project_id == project_id, KPI.tenant_id == current_tenant.id).all()

@router.put("/kpis/{kpi_id}", response_model=KPIResponse)
def update_kpi(kpi_id: int, kpi_update: KPIUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    kpi = db.query(KPI).filter(KPI.id == kpi_id, KPI.tenant_id == current_tenant.id).first()
    if not kpi:
        raise HTTPException(status_code=404, detail="KPI not found")
    for field, val in kpi_update.model_dump(exclude_unset=True).items():
        setattr(kpi, field, val)
    db.commit()
    db.refresh(kpi)
    return kpi

@router.delete("/kpis/{kpi_id}", status_code=204)
def delete_kpi(kpi_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    kpi = db.query(KPI).filter(KPI.id == kpi_id, KPI.tenant_id == current_tenant.id).first()
    if not kpi:
        raise HTTPException(status_code=404, detail="KPI not found")
    db.delete(kpi)
    db.commit()


@router.get("/kpis/{kpi_id}/detail")
def get_kpi_detail(kpi_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    """Get a KPI with related items: linked vision objective, releases, backlog items."""
    tid = current_tenant.id
    kpi = db.query(KPI).filter(KPI.id == kpi_id, KPI.tenant_id == tid).first()
    if not kpi:
        raise HTTPException(status_code=404, detail="KPI not found")

    project_id = kpi.project_id

    # Linked vision objective
    vision = db.query(ProjectVision).filter(ProjectVision.project_id == project_id, ProjectVision.tenant_id == tid).first()

    # Releases for this project (the KPI measures the project's output)
    releases = db.query(Release).filter(Release.project_id == project_id, Release.tenant_id == tid).all()

    # Backlog items for this project
    backlog_items = db.query(BacklogItem).filter(BacklogItem.project_id == project_id, BacklogItem.tenant_id == tid).all()

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
def create_roadmap(project_id: int, roadmap: RoadmapCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    if not db.query(Project).filter(Project.id == project_id, Project.tenant_id == current_tenant.id).first():
        raise HTTPException(status_code=404, detail="Project not found")
    roadmap.project_id = project_id
    db_roadmap = Roadmap(**roadmap.model_dump(), tenant_id=current_tenant.id)
    db.add(db_roadmap)
    db.commit()
    db.refresh(db_roadmap)
    return db_roadmap

@router.get("/projects/{project_id}/roadmaps", response_model=list[RoadmapWithMilestonesResponse])
def list_roadmaps(project_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    roadmaps = db.query(Roadmap).filter(Roadmap.project_id == project_id, Roadmap.tenant_id == current_tenant.id).all()
    for rm in roadmaps:
        rm.milestones = db.query(Milestone).filter(Milestone.roadmap_id == rm.id, Milestone.tenant_id == current_tenant.id).all()
    return roadmaps

@router.put("/roadmaps/{roadmap_id}", response_model=RoadmapResponse)
def update_roadmap(roadmap_id: int, rm_update: RoadmapUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    rm = db.query(Roadmap).filter(Roadmap.id == roadmap_id, Roadmap.tenant_id == current_tenant.id).first()
    if not rm:
        raise HTTPException(status_code=404, detail="Roadmap not found")
    for field, val in rm_update.model_dump(exclude_unset=True).items():
        setattr(rm, field, val)
    db.commit()
    db.refresh(rm)
    return rm

@router.delete("/roadmaps/{roadmap_id}", status_code=204)
def delete_roadmap(roadmap_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    rm = db.query(Roadmap).filter(Roadmap.id == roadmap_id, Roadmap.tenant_id == current_tenant.id).first()
    if not rm:
        raise HTTPException(status_code=404, detail="Roadmap not found")
    db.delete(rm)
    db.commit()


# ===== Milestones =====
@router.post("/roadmaps/{roadmap_id}/milestones", response_model=MilestoneResponse, status_code=201)
def create_milestone(roadmap_id: int, milestone: MilestoneCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    if not db.query(Roadmap).filter(Roadmap.id == roadmap_id, Roadmap.tenant_id == current_tenant.id).first():
        raise HTTPException(status_code=404, detail="Roadmap not found")
    milestone.roadmap_id = roadmap_id
    db_ms = Milestone(**milestone.model_dump(), tenant_id=current_tenant.id)
    db.add(db_ms)
    db.commit()
    db.refresh(db_ms)
    return db_ms

@router.get("/milestones/{milestone_id}/detail")
def get_milestone_detail(milestone_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user), current_tenant: Tenant = Depends(get_current_tenant)):
    """Get a milestone with all related items: tasks, releases, backlog items."""
    tid = current_tenant.id
    ms = db.query(Milestone).filter(Milestone.id == milestone_id, Milestone.tenant_id == tid).first()
    if not ms:
        raise HTTPException(status_code=404, detail="Milestone not found")

    # Related user tasks
    tasks = db.query(UserTask).filter(UserTask.milestone_id == milestone_id, UserTask.tenant_id == tid).all()

    # Related releases
    releases = db.query(Release).filter(Release.milestone_id == milestone_id, Release.tenant_id == tid).all()

    # Backlog items for this milestone's project
    rm = db.query(Roadmap).filter(Roadmap.id == ms.roadmap_id, Roadmap.tenant_id == tid).first()
    backlog_items = []
    if rm:
        backlog_items = db.query(BacklogItem).filter(BacklogItem.project_id == rm.project_id, BacklogItem.tenant_id == tid).all()

    return {
        "id": ms.id,
        "title": ms.title,
        "target_date": str(ms.target_date) if ms.target_date else None,
        "status": ms.status,
        "roadmap_id": ms.roadmap_id,
        "tasks": [{"id": t.id, "title": t.title, "status": t.status, "assignee_id": t.assignee_id} for t in tasks],
        "releases": [{"id": r.id, "version": r.version, "status": r.status, "target_date": r.target_date} for r in releases],
        "backlog_items_count": len(backlog_items),
        "backlog_items_done": len([b for b in backlog_items if b.status == "Done"]),
    }


# ===== Traceability =====
@router.get("/projects/{project_id}/traceability")
def get_traceability(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Return the full traceability chain: Vision → KPIs → Milestones → Releases → Backlog Items."""
    tid = current_tenant.id

    # Vision
    vision = db.query(ProjectVision).filter(ProjectVision.project_id == project_id, ProjectVision.tenant_id == tid).first()
    vision_data = None
    if vision:
        vision_data = {
            "statement": vision.statement,
            "strategic_objectives": vision.strategic_objectives,
        }

    # KPIs (with linked backlog items)
    kpis = db.query(KPI).filter(KPI.project_id == project_id, KPI.tenant_id == tid).all()
    kpi_data = []
    for k in kpis:
        linked_items = db.query(BacklogItem).filter(BacklogItem.kpi_id == k.id, BacklogItem.tenant_id == tid).all()
        kpi_data.append({
            "id": k.id,
            "name": k.name,
            "target_value": k.target_value,
            "current_value": k.current_value,
            "unit": k.unit,
            "category": k.category,
            "vision_objective": k.vision_objective,
            "backlog_items": [{"id": i.id, "title": i.title, "phase": i.current_phase, "status": i.status} for i in linked_items],
        })

    # Roadmaps + Milestones
    roadmaps = db.query(Roadmap).filter(Roadmap.project_id == project_id, Roadmap.tenant_id == tid).all()
    roadmap_data = []
    for rm in roadmaps:
        milestones = db.query(Milestone).filter(Milestone.roadmap_id == rm.id, Milestone.tenant_id == tid).all()
        roadmap_data.append({
            "id": rm.id,
            "title": rm.title,
            "milestones": [{"id": m.id, "title": m.title, "target_date": str(m.target_date) if m.target_date else None, "status": m.status} for m in milestones],
        })

    # Releases (with linked backlog items)
    from app.models.release import ReleaseItem
    releases = db.query(Release).filter(Release.project_id == project_id, Release.tenant_id == tid).all()
    release_data = []
    for rel in releases:
        rel_items = db.query(ReleaseItem).filter(ReleaseItem.release_id == rel.id, ReleaseItem.tenant_id == tid).all()
        item_ids = [ri.backlog_item_id for ri in rel_items]
        linked_items = db.query(BacklogItem).filter(BacklogItem.id.in_(item_ids), BacklogItem.tenant_id == tid).all() if item_ids else []
        release_data.append({
            "id": rel.id,
            "version": rel.version,
            "name": rel.name,
            "status": rel.status,
            "target_date": str(rel.target_date) if rel.target_date else None,
            "items": [{"id": i.id, "title": i.title, "phase": i.current_phase, "status": i.status} for i in linked_items],
        })

    # All backlog items
    backlog_items = db.query(BacklogItem).filter(BacklogItem.project_id == project_id, BacklogItem.tenant_id == tid).all()
    backlog_data = [{"id": i.id, "title": i.title, "phase": i.current_phase, "status": i.status, "priority": i.priority, "item_type": i.item_type} for i in backlog_items]

    return {
        "vision": vision_data,
        "kpis": kpi_data,
        "roadmaps": roadmap_data,
        "releases": release_data,
        "backlog_items": backlog_data,
    }
