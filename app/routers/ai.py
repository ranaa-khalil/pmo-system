"""AI router — LLM-powered suggestions for vision, features, and field filling."""
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.project_vision import ProjectVision
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_persona import UserPersona
from app.services.ai import (
    fill_field,
    is_ai_configured,
    suggest_features,
    suggest_vision_improvements,
)
from app.services.settings_service import (
    SETTING_AI_API_KEY,
    SETTING_AI_BASE_URL,
    SETTING_AI_MODEL,
    SETTING_GITHUB_TOKEN,
    get_ai_config,
    is_ai_configured_for_tenant,
    set_setting,
)
from app.services.tenant import get_current_tenant, require_tenant_role

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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Check if AI is configured for this tenant."""
    config = get_ai_config(db, current_tenant.id)
    return {
        "configured": bool(config["api_key"]),
        "base_url": config["base_url"],
        "model": config["model"],
    }


@router.put("/config")
def update_ai_config(
    req: AIConfigRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
    _user: User = Depends(require_tenant_role("owner", "admin")),
):
    """Update AI configuration for this tenant (owner/admin only)."""
    if req.api_key:
        set_setting(db, current_tenant.id, SETTING_AI_API_KEY, req.api_key)
    if req.base_url:
        set_setting(db, current_tenant.id, SETTING_AI_BASE_URL, req.base_url)
    if req.model:
        set_setting(db, current_tenant.id, SETTING_AI_MODEL, req.model)
    db.commit()

    config = get_ai_config(db, current_tenant.id)
    return {
        "configured": bool(config["api_key"]),
        "base_url": config["base_url"],
        "model": config["model"],
        "message": "AI configuration updated.",
    }


@router.post("/suggest-vision")
def ai_suggest_vision(
    req: VisionSuggestionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Suggest improvements to a project's vision statement."""
    tenant_config = get_ai_config(db, current_tenant.id)
    if not tenant_config["api_key"]:
        raise HTTPException(400, "AI is not configured. Set the API key in Settings.")

    project = db.query(Project).filter(Project.id == req.project_id, Project.tenant_id == current_tenant.id).first()
    if not project:
        raise HTTPException(404, "Project not found")

    vision = db.query(ProjectVision).filter(ProjectVision.project_id == req.project_id, ProjectVision.tenant_id == current_tenant.id).first()

    try:
        return suggest_vision_improvements(
            project_name=project.name,
            project_description=project.description or "",
            current_vision=vision.statement if vision else "",
            objectives=vision.strategic_objectives if vision else "",
            tenant_config=tenant_config,
        )
    except Exception as e:
        raise HTTPException(502, f"AI request failed: {str(e)}")


@router.post("/suggest-features")
def ai_suggest_features(
    req: FeatureSuggestionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Suggest epics and features for a project."""
    tenant_config = get_ai_config(db, current_tenant.id)
    if not tenant_config["api_key"]:
        raise HTTPException(400, "AI is not configured. Set the API key in Settings.")

    project = db.query(Project).filter(Project.id == req.project_id, Project.tenant_id == current_tenant.id).first()
    if not project:
        raise HTTPException(404, "Project not found")

    vision = db.query(ProjectVision).filter(ProjectVision.project_id == req.project_id, ProjectVision.tenant_id == current_tenant.id).first()
    items = db.query(BacklogItem).filter(BacklogItem.project_id == req.project_id, BacklogItem.tenant_id == current_tenant.id).all()

    existing_epics = list(set(i.epic for i in items if i.epic))
    existing_features = [i.title for i in items if i.item_type != "Epic"]

    personas = db.query(UserPersona).filter(UserPersona.project_id == req.project_id, UserPersona.tenant_id == current_tenant.id).all()
    persona_list = [{"name": p.name, "role": p.role or ""} for p in personas]

    try:
        return suggest_features(
            project_name=project.name,
            project_description=project.description or "",
            vision=vision.statement if vision else "",
            existing_epics=existing_epics,
            existing_features=existing_features,
            personas=persona_list,
            tenant_config=tenant_config,
        )
    except Exception as e:
        raise HTTPException(502, f"AI request failed: {str(e)}")


@router.post("/fill-field")
def ai_fill_field(
    req: FillFieldRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Fill an empty field on a backlog item using AI."""
    tenant_config = get_ai_config(db, current_tenant.id)
    if not tenant_config["api_key"]:
        raise HTTPException(400, "AI is not configured. Set the API key in Settings.")

    item = db.query(BacklogItem).filter(BacklogItem.id == req.item_id, BacklogItem.tenant_id == current_tenant.id).first()
    if not item:
        raise HTTPException(404, "Backlog item not found")

    project = db.query(Project).filter(Project.id == item.project_id, Project.tenant_id == current_tenant.id).first()
    vision = db.query(ProjectVision).filter(ProjectVision.project_id == item.project_id, ProjectVision.tenant_id == current_tenant.id).first()

    try:
        return fill_field(
            item_title=item.title,
            item_type=item.item_type or "",
            field_name=req.field_name,
            field_context=req.field_context,
            project_name=project.name if project else "",
            vision=vision.statement if vision else "",
            existing_description=item.description or "",
            tenant_config=tenant_config,
        )
    except Exception as e:
        raise HTTPException(502, f"AI request failed: {str(e)}")
