"""Pydantic schemas for vision, KPI, roadmap, milestone."""
from datetime import date

from pydantic import BaseModel


# ===== Vision =====
class VisionBase(BaseModel):
    statement: str
    strategic_objectives: str | None = None

class VisionCreate(VisionBase):
    project_id: int

class VisionUpdate(BaseModel):
    statement: str | None = None
    strategic_objectives: str | None = None

class VisionResponse(VisionBase):
    id: int
    project_id: int
    model_config = {"from_attributes": True}


# ===== KPI =====
class KPIBase(BaseModel):
    name: str
    target_value: str | None = None
    current_value: str | None = None
    unit: str | None = None
    category: str | None = None
    vision_objective: str | None = None

class KPICreate(KPIBase):
    project_id: int

class KPIUpdate(BaseModel):
    name: str | None = None
    target_value: str | None = None
    current_value: str | None = None
    unit: str | None = None
    category: str | None = None
    vision_objective: str | None = None

class KPIResponse(KPIBase):
    id: int
    project_id: int
    model_config = {"from_attributes": True}


# ===== Roadmap =====
class RoadmapBase(BaseModel):
    title: str
    start_date: date | None = None
    end_date: date | None = None

class RoadmapCreate(RoadmapBase):
    project_id: int

class RoadmapUpdate(BaseModel):
    title: str | None = None
    start_date: date | None = None
    end_date: date | None = None

class RoadmapResponse(RoadmapBase):
    id: int
    project_id: int
    model_config = {"from_attributes": True}


# ===== Milestone =====
class MilestoneBase(BaseModel):
    title: str
    target_date: date | None = None
    status: str = "On Track"
    description: str | None = None

class MilestoneCreate(MilestoneBase):
    roadmap_id: int

class MilestoneUpdate(BaseModel):
    title: str | None = None
    target_date: date | None = None
    status: str | None = None
    description: str | None = None

class MilestoneResponse(MilestoneBase):
    id: int
    roadmap_id: int
    model_config = {"from_attributes": True}

class RoadmapWithMilestonesResponse(RoadmapResponse):
    milestones: list[MilestoneResponse] = []
