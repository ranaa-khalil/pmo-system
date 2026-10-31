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


@router.get("/predictive-flags")
def get_predictive_flags(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Predictive KPI flags (P3): off-target + deteriorating-trend warnings.

    Derived on read from KPI values + KpiHistory — template-aware kind
    (drift for AI, spend for marketing, capacity for operations). Scoped to
    the user's assigned projects (or one project with ?project_id=).
    """
    from app.services import predictive
    from app.services.copilot import _assigned_project_ids

    if project_id is not None:
        from app.models.project import Project
        project = db.query(Project).filter(
            Project.id == project_id, Project.tenant_id == current_tenant.id,
        ).first()
        if not project:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Project not found")
        proj_ids = [project.id]
    else:
        proj_ids = _assigned_project_ids(db, current_user, current_tenant)

    flags = predictive.predictive_flags(db, current_tenant, proj_ids)
    return {"flags": flags, "count": len(flags)}


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
    history: list[dict] | None = None


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
            project_id=req.project_id,
            history=req.history,
        )
    except HTTPException:
        raise
    except Exception as e:
        import logging
        import traceback
        logging.getLogger("pmo.ai").error(
            "copilot_chat failed: %s: %s\n%s", type(e).__name__, e, traceback.format_exc()
        )
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
            project_id=req.project_id,
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


# ── Interview engine (guided Q&A for create flows) ───────────────────────

class InterviewStartRequest(BaseModel):
    flow: str = "project"
    project_id: int | None = None


class InterviewAnswerRequest(BaseModel):
    question_id: str
    answer: str = ""


class InterviewSkipRequest(BaseModel):
    question_id: str


class InterviewApplyRequest(BaseModel):
    edits: dict | None = None


def _interview_error(result: dict):
    if "error" in result:
        raise HTTPException(result.get("status", 400), result["error"])
    return result


@router.post("/interview/{flow}/start")
def interview_start_endpoint(
    flow: str,
    req: InterviewStartRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Open a guided interview: first question with its smart default."""
    from app.services.plan_enforcement import require_feature
    require_feature(current_tenant.plan, "ai_assistant")
    from app.services import interview as interview_service
    try:
        return interview_service.start_interview(
            db, current_user, current_tenant, flow=flow,
            project_id=(req.project_id if req else None),
        )
    except ValueError:
        raise HTTPException(400, f"Unknown interview flow: {flow}")
    except Exception as e:
        raise HTTPException(502, f"Interview start failed: {str(e)}")


@router.post("/interview/{session_id}/answer")
def interview_answer_endpoint(
    session_id: int,
    req: InterviewAnswerRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Answer the current question; advances or returns a capped follow-up."""
    from app.services import interview as interview_service
    try:
        return _interview_error(interview_service.submit_answer(
            db, current_user, current_tenant, session_id, req.question_id, req.answer,
        ))
    except PermissionError:
        raise HTTPException(404, "Interview session not found in this tenant.")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/interview/{session_id}/skip")
def interview_skip_endpoint(
    session_id: int,
    req: InterviewSkipRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Skip = accept the smart default and advance."""
    from app.services import interview as interview_service
    try:
        return _interview_error(interview_service.skip_question(
            db, current_user, current_tenant, session_id, req.question_id,
        ))
    except PermissionError:
        raise HTTPException(404, "Interview session not found in this tenant.")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/interview/{session_id}/back")
def interview_back_endpoint(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Back = undo the last answered/skipped question and re-ask it."""
    from app.services import interview as interview_service
    try:
        return _interview_error(interview_service.back_question(
            db, current_user, current_tenant, session_id,
        ))
    except PermissionError:
        raise HTTPException(404, "Interview session not found in this tenant.")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/interview/{session_id}/state")
def interview_state_endpoint(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Resume: returns the persisted interview state (question, progress, answers)."""
    from app.services import interview as interview_service
    try:
        return interview_service.current_state(db, current_user, current_tenant, session_id)
    except PermissionError:
        raise HTTPException(404, "Interview session not found in this tenant.")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/interview/{session_id}/finish")
def interview_finish_endpoint(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Assemble the final draft. Apply (the only write) happens separately."""
    from app.services import interview as interview_service
    try:
        return interview_service.finish_interview(db, current_user, current_tenant, session_id)
    except PermissionError:
        raise HTTPException(404, "Interview session not found in this tenant.")
    except ValueError as e:
        msg = str(e)
        if msg == "interview_incomplete":
            raise HTTPException(409, "Interview is not finished — answer or skip the remaining questions first.")
        raise HTTPException(400, msg)


@router.post("/interview/{session_id}/apply")
def interview_apply_endpoint(
    session_id: int,
    req: InterviewApplyRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Apply a reviewed risk/escalation/release interview draft. The ONLY write
    path for those flows — project drafts keep using /intake/apply."""
    from app.services.plan_enforcement import require_feature
    require_feature(current_tenant.plan, "ai_assistant")
    from app.services import interview as interview_service
    try:
        return interview_service.apply_interview_draft(
            db, current_user, current_tenant, session_id,
            edits=(req.edits if req else None),
        )
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        msg = str(e)
        mapping = {
            "already_applied": (409, "This interview draft was already applied."),
            "project_not_found": (404, "Project not found in this tenant."),
            "approval_not_found": (404, "Approval not found in this tenant — pick one in the review panel."),
            "version_required": (400, "A version number is required to apply the release draft."),
            "flow_not_applyable": (400, "This interview flow is not applyable here."),
        }
        code, detail = mapping.get(msg, (400, msg))
        raise HTTPException(code, detail)


def _fallback_project(db: Session, tenant: Tenant) -> Project | None:
    """First project in the tenant, used when no project_id is given for capture."""
    return db.query(Project).filter(Project.tenant_id == tenant.id).order_by(Project.id).first()


# ── Self-proposing automation (P4.2) ─────────────────────────────────────

@router.get("/automation/rules")
def list_automation_rules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """All automation rules for the tenant (mined + template + manual)."""
    from app.services.plan_enforcement import require_feature
    require_feature(current_tenant.plan, "ai_assistant")
    from app.models.automation_rule import AutomationRule
    rules = (
        db.query(AutomationRule)
        .filter(AutomationRule.tenant_id == current_tenant.id)
        .order_by(AutomationRule.id.desc())
        .all()
    )
    return {
        "rules": [
            {
                "id": r.id, "name": r.name, "description": r.description,
                "trigger": r.trigger, "conditions": r.conditions,
                "actions": r.actions, "source": r.source,
                "evidence": r.evidence, "enabled": r.enabled,
                "fire_count": r.fire_count, "last_fired_at": r.last_fired_at,
            }
            for r in rules
        ]
    }


@router.post("/automation/scan")
def automation_scan(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Mine ActivityLog/approval/task patterns → propose rules + coverage scan."""
    from app.services.plan_enforcement import require_feature
    require_feature(current_tenant.plan, "ai_assistant")
    from app.services.automation_mining import coverage_scan, mine_rules
    proposed = mine_rules(db, current_tenant)
    coverage = coverage_scan(db, current_tenant)
    return {
        "proposed": [
            {
                "id": r.id, "name": r.name, "trigger": r.trigger,
                "conditions": r.conditions, "actions": r.actions,
                "evidence": r.evidence, "enabled": r.enabled,
            }
            for r in proposed
        ],
        "coverage": coverage,
    }


@router.post("/automation/rules/{rule_id}/enable")
def enable_automation_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Human one-click enable — the only way a rule goes live."""
    from app.services.plan_enforcement import require_feature
    require_feature(current_tenant.plan, "ai_assistant")
    from app.models.automation_rule import AutomationRule
    rule = (
        db.query(AutomationRule)
        .filter(AutomationRule.id == rule_id, AutomationRule.tenant_id == current_tenant.id)
        .first()
    )
    if not rule:
        raise HTTPException(404, "Rule not found in this tenant.")
    rule.enabled = True
    from app.models.activity_log import ActivityLog
    db.add(ActivityLog(
        tenant_id=current_tenant.id, user_id=current_user.id,
        entity_type="automation_rule", entity_id=rule.id, action="updated",
        summary=f"Automation rule '{rule.name}' enabled by {current_user.name}",
    ))
    db.commit()
    db.refresh(rule)
    return {"id": rule.id, "enabled": rule.enabled}


@router.post("/automation/rules/{rule_id}/disable")
def disable_automation_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Turn a rule off without deleting it (proposals/evidence survive)."""
    from app.services.plan_enforcement import require_feature
    require_feature(current_tenant.plan, "ai_assistant")
    from app.models.automation_rule import AutomationRule
    rule = (
        db.query(AutomationRule)
        .filter(AutomationRule.id == rule_id, AutomationRule.tenant_id == current_tenant.id)
        .first()
    )
    if not rule:
        raise HTTPException(404, "Rule not found in this tenant.")
    rule.enabled = False
    from app.models.activity_log import ActivityLog
    db.add(ActivityLog(
        tenant_id=current_tenant.id, user_id=current_user.id,
        entity_type="automation_rule", entity_id=rule.id, action="updated",
        summary=f"Automation rule '{rule.name}' disabled by {current_user.name}",
    ))
    db.commit()
    db.refresh(rule)
    return {"id": rule.id, "enabled": rule.enabled}


@router.delete("/automation/rules/{rule_id}")
def delete_automation_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """Remove an automation rule."""
    from app.services.plan_enforcement import require_feature
    require_feature(current_tenant.plan, "ai_assistant")
    from app.models.automation_rule import AutomationRule
    rule = (
        db.query(AutomationRule)
        .filter(AutomationRule.id == rule_id, AutomationRule.tenant_id == current_tenant.id)
        .first()
    )
    if not rule:
        raise HTTPException(404, "Rule not found in this tenant.")
    name = rule.name
    db.delete(rule)
    db.commit()
    return {"deleted": name}
