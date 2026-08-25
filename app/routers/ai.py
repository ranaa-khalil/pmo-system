"""AI router — LLM-powered suggestions for vision, features, and field filling."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.project_vision import ProjectVision
from app.models.backlog_item import BacklogItem
from app.models.user_persona import UserPersona
from app.config import settings
from app.services.ai import (
    is_ai_configured, suggest_vision_improvements,
    suggest_features, fill_field,
)
import os

router = APIRouter(prefix="/api/ai", tags=["ai"])


class VisionSuggestionRequest(BaseModel):
    project_id: int


class FeatureSuggestionRequest(BaseModel):
    project_id: int


class FillFieldRequest(BaseModel):
    item_id: int
    field_name: str
    field_context: str = ""


class AIConfigRequest(BaseModel):
    api_key: str = ""
    base_url: str = ""
    model: str = ""


@router.get("/status")
def ai_status(
    current_user: User = Depends(get_current_user),
):
    """Check if AI is configured."""
    return {
        "configured": is_ai_configured(),
        "base_url": settings.ai_base_url,
        "model": settings.ai_model,
    }


@router.put("/config")
def update_ai_config(
    req: AIConfigRequest,
    current_user: User = Depends(get_current_user),
):
    """Update AI configuration (super_admin only)."""
    if current_user.system_role != "super_admin":
        raise HTTPException(403, "Only super admins can configure AI settings.")
    # Update env vars and settings at runtime
    if req.api_key:
        os.environ["PMO_AI_API_KEY"] = req.api_key
        settings.ai_api_key = req.api_key
    if req.base_url:
        os.environ["PMO_AI_BASE_URL"] = req.base_url
        settings.ai_base_url = req.base_url
    if req.model:
        os.environ["PMO_AI_MODEL"] = req.model
        settings.ai_model = req.model
    return {"configured": is_ai_configured(), "message": "AI configuration updated."}


@router.post("/suggest-vision")
def ai_suggest_vision(
    req: VisionSuggestionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Suggest improvements to a project's vision statement."""
    if not is_ai_configured():
        raise HTTPException(400, "AI is not configured. Set the API key in Settings or .env (PMO_AI_API_KEY).")

    project = db.query(Project).filter(Project.id == req.project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")

    vision = db.query(ProjectVision).filter(ProjectVision.project_id == req.project_id).first()

    return suggest_vision_improvements(
        project_name=project.name,
        project_description=project.description or "",
        current_vision=vision.statement if vision else "",
        objectives=vision.strategic_objectives if vision else "",
    )


@router.post("/suggest-features")
def ai_suggest_features(
    req: FeatureSuggestionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Suggest epics and features for a project."""
    if not is_ai_configured():
        raise HTTPException(400, "AI is not configured. Set the API key in Settings or .env (PMO_AI_API_KEY).")

    project = db.query(Project).filter(Project.id == req.project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")

    vision = db.query(ProjectVision).filter(ProjectVision.project_id == req.project_id).first()
    items = db.query(BacklogItem).filter(BacklogItem.project_id == req.project_id).all()

    existing_epics = list(set(i.epic for i in items if i.epic))
    existing_features = [i.title for i in items if i.item_type != "Epic"]

    personas = db.query(UserPersona).filter(UserPersona.project_id == req.project_id).all()
    persona_list = [{"name": p.name, "role": p.role or ""} for p in personas]

    return suggest_features(
        project_name=project.name,
        project_description=project.description or "",
        vision=vision.statement if vision else "",
        existing_epics=existing_epics,
        existing_features=existing_features,
        personas=persona_list,
    )


@router.post("/fill-field")
def ai_fill_field(
    req: FillFieldRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fill an empty field on a backlog item using AI."""
    if not is_ai_configured():
        raise HTTPException(400, "AI is not configured. Set the API key in Settings or .env (PMO_AI_API_KEY).")

    item = db.query(BacklogItem).filter(BacklogItem.id == req.item_id).first()
    if not item:
        raise HTTPException(404, "Backlog item not found")

    project = db.query(Project).filter(Project.id == item.project_id).first()
    vision = db.query(ProjectVision).filter(ProjectVision.project_id == item.project_id).first()

    field_labels = {
        "description": "A detailed description of what this item does and why it's needed",
        "acceptance_criteria": "Clear, testable acceptance criteria (as a bullet list)",
        "primary_actor": "The primary user persona who benefits from this feature",
    }

    return fill_field(
        item_title=item.title,
        item_type=item.item_type or "Feature",
        field_name=req.field_name,
        field_context=field_labels.get(req.field_name, req.field_context),
        project_name=project.name if project else "",
        vision=vision.statement if vision else "",
        existing_description=item.description or "",
    )
