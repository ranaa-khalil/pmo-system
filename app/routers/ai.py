"""AI router — LLM-powered suggestions for vision, features, and field filling."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.ai_interaction import AiInteraction
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.project_vision import ProjectVision
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_persona import UserPersona
from app.services.ai import (
    fill_field,
    suggest_features,
    suggest_vision_improvements,
)
from app.services.settings_service import (
    SETTING_AI_API_KEY,
    SETTING_AI_BASE_URL,
    SETTING_AI_MODEL,
    get_ai_config,
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
    from app.services.plan_enforcement import require_feature
    require_feature(current_tenant.plan, "ai_assistant")

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


# ── PMO Copilot: grounded chat + action proposals ────────────────────────

class CopilotChatRequest(BaseModel):
    question: str
    project_id: int | None = None


class CopilotProposeRequest(BaseModel):
    intent: str
    project_id: int | None = None
    operations: list[dict] | None = None


@router.post("/copilot/chat")
def copilot_chat_endpoint(
    req: CopilotChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Grounded, read-only Q&A over the user's data. Sources returned with every answer."""
    from app.services.plan_enforcement import require_feature
    require_feature(current_tenant.plan, "ai_assistant")

    tenant_config = get_ai_config(db, current_tenant.id)
    if not tenant_config["api_key"]:
        raise HTTPException(400, "AI is not configured. Set the API key in Settings.")

    from app.services import copilot as copilot_service
    try:
        return copilot_service.copilot_chat(
            db, current_user, current_tenant, req.question, tenant_config,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"AI request failed: {str(e)}")


@router.post("/copilot/propose")
def copilot_propose_endpoint(
    req: CopilotProposeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Draft a write proposal. Executes nothing until confirmed."""
    from app.services.plan_enforcement import require_feature
    require_feature(current_tenant.plan, "ai_assistant")

    tenant_config = get_ai_config(db, current_tenant.id)
    if not tenant_config["api_key"] and not req.operations:
        raise HTTPException(400, "AI is not configured. Set the API key in Settings.")

    from app.services import copilot as copilot_service
    try:
        return copilot_service.copilot_propose(
            db, current_user, current_tenant, req.intent,
            operations=req.operations, tenant_config=tenant_config,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"AI request failed: {str(e)}")


@router.post("/copilot/proposals/{proposal_id}/confirm")
def copilot_confirm_endpoint(
    proposal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Execute a pending proposal as the user. Every op re-checks the user's rights."""
    from app.services import copilot as copilot_service
    result = copilot_service.confirm_proposal(db, current_user, current_tenant, proposal_id)
    if "error" in result:
        raise HTTPException(result["status"], result["error"])
    return result


@router.post("/copilot/proposals/{proposal_id}/reject")
def copilot_reject_endpoint(
    proposal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Reject a pending proposal without executing anything."""
    from app.services import copilot as copilot_service
    result = copilot_service.reject_proposal(db, current_user, current_tenant, proposal_id)
    if "error" in result:
        raise HTTPException(result["status"], result["error"])
    return result


# ── Conversational project intake ────────────────────────────────────────

class IntakeStructureRequest(BaseModel):
    kickoff: str
    project_id: int | None = None
    project_name: str | None = None


class IntakeVerdictRequest(BaseModel):
    title: str
    description: str = ""
    project_id: int | None = None


class IntakeApplyRequest(BaseModel):
    draft: dict | None = None
    draft_id: int | None = None
    project_id: int | None = None


class IntakeCaptureRequest(BaseModel):
    notes: str
    source: str = "meeting"
    project_id: int | None = None


def _intake_project(db: Session, current_tenant: Tenant, project_id: int | None) -> Project | None:
    """Resolve the intake target project inside the current tenant."""
    if project_id is None:
        return None
    return db.query(Project).filter(
        Project.id == project_id, Project.tenant_id == current_tenant.id,
    ).first()


@router.post("/intake/structure")
def intake_structure_endpoint(
    req: IntakeStructureRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Kickoff text → structured draft (epics, features, personas, KPIs). No writes."""
    from app.services.plan_enforcement import require_feature
    require_feature(current_tenant.plan, "ai_assistant")

    if not req.kickoff or not req.kickoff.strip():
        raise HTTPException(400, "Kickoff text is required.")

    project = _intake_project(db, current_tenant, req.project_id)
    tenant_config = get_ai_config(db, current_tenant.id)
    if not tenant_config["api_key"]:
        raise HTTPException(400, "AI is not configured. Set the API key in Settings.")

    from app.services import intake as intake_service
    try:
        return intake_service.structure_intake(
            db, current_user, current_tenant, req.kickoff,
            project_name=req.project_name or (project.name if project else ""),
            tenant_config=tenant_config,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"AI request failed: {str(e)}")


@router.post("/intake/verdict")
def intake_verdict_endpoint(
    req: IntakeVerdictRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Feature verdict: exists / fits an epic / new — with sibling duplicate check."""
    from app.services.plan_enforcement import require_feature
    require_feature(current_tenant.plan, "ai_assistant")

    project = _intake_project(db, current_tenant, req.project_id)
    if not project:
        raise HTTPException(400, "A valid project_id is required for a feature verdict.")
    if not req.title or not req.title.strip():
        raise HTTPException(400, "Feature title is required.")

    tenant_config = get_ai_config(db, current_tenant.id)
    if not tenant_config["api_key"]:
        raise HTTPException(400, "AI is not configured. Set the API key in Settings.")

    from app.services import intake as intake_service
    try:
        return intake_service.feature_verdict(
            db, current_tenant, project, req.title.strip(), req.description,
            tenant_config=tenant_config,
        )
    except Exception as e:
        raise HTTPException(502, f"AI request failed: {str(e)}")


@router.post("/intake/apply")
def intake_apply_endpoint(
    req: IntakeApplyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """THE ONLY intake write path. Applies a reviewed draft to the project."""
    project = _intake_project(db, current_tenant, req.project_id)
    if not project:
        raise HTTPException(400, "A valid project_id is required to apply intake.")

    draft = req.draft
    if draft is None and req.draft_id is not None:
        row = db.query(AiInteraction).filter(
            AiInteraction.id == req.draft_id,
            AiInteraction.tenant_id == current_tenant.id,
            AiInteraction.user_id == current_user.id,
            AiInteraction.kind == "intake_draft",
        ).first()
        if not row:
            raise HTTPException(409, "Draft not found in this tenant — it may belong to another tenant or user.")
        try:
            draft = json.loads(row.answer or "{}")
        except ValueError:
            raise HTTPException(409, "Draft content is invalid.")
        draft["draft_id"] = row.id

    if not draft or not isinstance(draft, dict):
        raise HTTPException(400, "A draft (inline or by draft_id) is required.")

    from app.services import intake as intake_service
    try:
        result = intake_service.apply_intake(db, current_user, current_tenant, project, draft)
    except Exception as e:
        raise HTTPException(502, f"Intake apply failed: {str(e)}")
    return result


@router.post("/intake/capture")
def intake_capture_endpoint(
    req: IntakeCaptureRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Capture ongoing notes (meetings, chats) as source-anchored records."""
    if not req.notes or not req.notes.strip():
        raise HTTPException(400, "Notes are required.")
    project = _intake_project(db, current_tenant, req.project_id)

    from app.services import intake as intake_service
    interaction = intake_service.capture_ongoing(
        db, current_user, current_tenant,
        project or _fallback_project(db, current_tenant),
        req.notes.strip(), source=req.source,
    )
    return {"capture_id": interaction.id, "status": "captured"}


def _fallback_project(db: Session, tenant: Tenant) -> Project | None:
    """First project in the tenant, used when no project_id is given for capture."""
    return db.query(Project).filter(Project.tenant_id == tenant.id).order_by(Project.id).first()
