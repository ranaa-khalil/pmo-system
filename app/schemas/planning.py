"""Pydantic schemas for vision, KPI, roadmap, milestone."""
from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel


# ===== Vision =====
class VisionBase(BaseModel):
    statement: str
    strategic_objectives: Optional[str] = None

class VisionCreate(VisionBase):
    project_id: int

class VisionUpdate(BaseModel):
    statement: Optional[str] = None
    strategic_objectives: Optional[str] = None

class VisionResponse(VisionBase):
    id: int
    project_id: int
    model_config = {"from_attributes": True}


# ===== KPI =====
class KPIBase(BaseModel):
    name: str
    target_value: Optional[str] = None
    current_value: Optional[str] = None
    unit: Optional[str] = None
    category: Optional[str] = None
    vision_objective: Optional[str] = None

class KPICreate(KPIBase):
    project_id: int

class KPIUpdate(BaseModel):
    name: Optional[str] = None
    target_value: Optional[str] = None
    current_value: Optional[str] = None
    unit: Optional[str] = None
    category: Optional[str] = None
    vision_objective: Optional[str] = None

class KPIResponse(KPIBase):
    id: int
    project_id: int
    model_config = {"from_attributes": True}


# ===== Roadmap =====
class RoadmapBase(BaseModel):
    title: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None

class RoadmapCreate(RoadmapBase):
    project_id: int

class RoadmapUpdate(BaseModel):
    title: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None

class RoadmapResponse(RoadmapBase):
    id: int
    project_id: int
    model_config = {"from_attributes": True}


# ===== Milestone =====
class MilestoneBase(BaseModel):
    title: str
    target_date: Optional[date] = None
    status: str = "On Track"
    description: Optional[str] = None

class MilestoneCreate(MilestoneBase):
    roadmap_id: int

class MilestoneUpdate(BaseModel):
    title: Optional[str] = None
    target_date: Optional[date] = None
    status: Optional[str] = None
    description: Optional[str] = None

class MilestoneResponse(MilestoneBase):
    id: int
    roadmap_id: int
    model_config = {"from_attributes": True}

class RoadmapWithMilestonesResponse(RoadmapResponse):
    milestones: List[MilestoneResponse] = []
