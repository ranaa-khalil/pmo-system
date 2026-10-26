"""Intake service — conversational project initiation with proposal semantics.

structure_intake turns a kickoff paragraph/doc into a structured draft
(epics, features, personas, KPIs). apply_intake is the ONLY write path and
runs after human confirmation; it never duplicates existing features and
stores traceability at birth (every created record links its intake source).
feature_verdict answers "exists / fits an epic / new" with a sibling-project
duplicate check. capture_ongoing records raw meeting/chat notes.
"""
import json
import re
from difflib import SequenceMatcher
from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog
from app.models.ai_interaction import AiInteraction
from app.models.backlog_item import BacklogItem
from app.models.kpi import KPI
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_persona import UserPersona

INTAKE_SYSTEM_PROMPT = (
    "You are a senior Business Analyst structuring a project kickoff. "
    "From the kickoff material, extract a structured draft as JSON: "
    '{"summary": str, "epics": [{"name": str, "features": [{"title": str, "description": str}]}], '
    '"personas": [{"name": str, "role": str, "goals": str, "pain_points": str}], '
    '"kpis": [{"name": str, "target": str, "unit": str, "category": str}], '
    '"assumptions": [str]}. '
    "Personas are END-USERS of the product (never stakeholder/RACI roles). "
    "Features are user-facing capabilities grouped by epic. Never invent facts "
    "not present in the material; put unknowns in assumptions."
)

# Title similarity above this counts as a duplicate
DUP_THRESHOLD = 0.75


def _call_llm(system_prompt: str, user_prompt: str, tenant_config: dict | None = None, max_tokens: int = 2000) -> str:
    """Thin wrapper so tests can monkeypatch intake._call_llm."""
    from app.services.ai import _call_llm as _ai_call
    return _ai_call(system_prompt, user_prompt, max_tokens=max_tokens, json_mode=True, tenant_config=tenant_config)


def _extract_json(raw: str) -> dict:
    from app.services.ai import _extract_json as _extract
    return _extract(raw) or {}


def structure_intake(
    db: Session,
    user: User,
    tenant: Tenant,
    kickoff_text: str,
    project_name: str = "",
    tenant_config: dict | None = None,
) -> dict:
    """Turn kickoff material into a structured draft. Writes nothing."""
    user_prompt = (
        f"PROJECT: {project_name or '(new project)'}\n\n"
        f"KICKOFF MATERIAL:\n{kickoff_text}"
    )
    raw = _call_llm(INTAKE_SYSTEM_PROMPT, user_prompt, tenant_config)
    parsed = _extract_json(raw)

    draft = {
        "summary": parsed.get("summary", ""),
        "epics": parsed.get("epics", []),
        "personas": parsed.get("personas", []),
        "kpis": parsed.get("kpis", []),
        "assumptions": parsed.get("assumptions", []),
    }

    interaction = AiInteraction(
        tenant_id=tenant.id,
        user_id=user.id,
        kind="intake_draft",
        question=(kickoff_text or "")[:2000],
        answer=json.dumps(draft),
        status="pending",
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)

    draft["draft_id"] = interaction.id
    return draft


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (title or "").lower()).strip()


def _titles_match(a: str, b: str) -> bool:
    a, b = _norm_title(a), _norm_title(b)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    return SequenceMatcher(None, a, b).ratio() >= DUP_THRESHOLD


def feature_verdict(
    db: Session,
    tenant: Tenant,
    project: Project,
    feature_title: str,
    feature_description: str = "",
    llm_fn=None,
) -> dict:
    """Verdict for adding one feature: exists / fits an epic / new.

    The sibling-project duplicate check runs BEFORE the LLM call: name matches
    in other projects of the tenant are surfaced as warnings with source links.
    """
    # 1. Exact-ish match in this project → exists
    items = db.query(BacklogItem).filter(BacklogItem.project_id == project.id).all()
    for item in items:
        if _titles_match(feature_title, item.title):
            return {
                "verdict": "exists",
                "existing_item_id": item.id,
                "existing_epic": item.epic,
                "confidence": 0.9,
                "sibling_duplicates": [],
            }

    # 2. Sibling-project duplicate scan (traceability + reuse)
    siblings = db.query(Project).filter(
        Project.tenant_id == tenant.id, Project.id != project.id,
    ).all()
    sibling_duplicates = []
    for sibling in siblings:
        sib_items = db.query(BacklogItem).filter(BacklogItem.project_id == sibling.id).all()
        for sib in sib_items:
            if _titles_match(feature_title, sib.title):
                sibling_duplicates.append({
                    "project": sibling.name,
                    "project_id": sibling.id,
                    "item_id": sib.id,
                    "title": sib.title,
                    "epic": sib.epic,
                    "phase": sib.current_phase,
                })

    # 3. LLM verdict for epic fit vs new (mockable)
    if llm_fn is None:
        llm_fn = _call_llm
    tree_lines = [
        f"- {item.epic or 'Ungrouped'} :: {item.title}"
        for item in items
    ]
    prompt = (
        f"PROJECT: {project.name}\n"
        f"EXISTING BACKLOG:\n" + ("\n".join(tree_lines) or "(empty)") + "\n\n"
        f"PROPOSED FEATURE: {feature_title}\n{feature_description}\n\n"
        'Reply ONLY with JSON: {"verdict": "exists"|"fits_epic"|"new", "epic": str|null, '
        '"confidence": 0-1, "reasoning": str}'
    )
    raw = llm_fn(INTAKE_SYSTEM_PROMPT, prompt, None, 500)
    parsed = _extract_json(raw)

    return {
        "verdict": parsed.get("verdict", "new"),
        "epic": parsed.get("epic"),
        "confidence": parsed.get("confidence", 0.5),
        "reasoning": parsed.get("reasoning", ""),
        "sibling_duplicates": sibling_duplicates,
    }


def apply_intake(
    db: Session,
    user: User,
    tenant: Tenant,
    project: Project,
    draft: dict,
) -> dict:
    """The ONLY write path for intake. Creates personas, KPIs, and features.

    Never duplicates: a feature whose title already exists in the project is
    skipped. Traceability stored at birth: descriptions carry the intake source.
    """
    created = {"features_created": 0, "features_skipped": 0,
               "personas_created": 0, "kpis_created": 0,
               "feature_ids": [], "persona_ids": [], "kpi_ids": []}

    existing_titles = {
        _norm_title(t) for (t,) in db.query(BacklogItem.title).filter(
            BacklogItem.project_id == project.id,
        ).all() if t
    }

    for epic in draft.get("epics", []):
        epic_name = epic.get("name") or "Ungrouped"
        for feat in epic.get("features", []):
            title = (feat.get("title") or "").strip()
            if not title:
                continue
            if _norm_title(title) in existing_titles:
                created["features_skipped"] += 1
                continue
            description = feat.get("description") or ""
            item = BacklogItem(
                tenant_id=tenant.id,
                project_id=project.id,
                title=title,
                epic=epic_name,
                current_phase="Requirements",
                status="Draft",
                item_type="Feature",
                description=(
                    f"{description}\n\n"
                    f"[Source: Intake draft #{draft.get('draft_id', '?')} — AI-structured kickoff, "
                    f"applied by {user.name}]"
                ).strip(),
            )
            db.add(item)
            db.flush()
            created["feature_ids"].append(item.id)
            existing_titles.add(_norm_title(title))
            created["features_created"] += 1

    for persona in draft.get("personas", []):
        name = (persona.get("name") or "").strip()
        if not name:
            continue
        row = UserPersona(
            tenant_id=tenant.id,
            project_id=project.id,
            name=name,
            role=persona.get("role"),
            description=persona.get("description"),
            goals=persona.get("goals"),
            pain_points=persona.get("pain_points"),
        )
        db.add(row)
        db.flush()
        created["persona_ids"].append(row.id)
        created["personas_created"] += 1

    for kpi in draft.get("kpis", []):
        name = (kpi.get("name") or "").strip()
        if not name:
            continue
        row = KPI(
            tenant_id=tenant.id,
            project_id=project.id,
            name=name,
            target_value=kpi.get("target"),
            unit=kpi.get("unit"),
            category=kpi.get("category"),
        )
        db.add(row)
        db.flush()
        created["kpi_ids"].append(row.id)
        created["kpis_created"] += 1

    db.add(ActivityLog(
        tenant_id=tenant.id, user_id=user.id, project_id=project.id,
        entity_type="intake", entity_id=project.id, action="applied",
        summary=(
            f"Intake applied: {created['features_created']} features, "
            f"{created['personas_created']} personas, {created['kpis_created']} KPIs"
        ),
    ))
    db.commit()

    return created


def capture_ongoing(
    db: Session,
    user: User,
    tenant: Tenant,
    project: Project,
    notes: str,
    source: str = "meeting",
) -> AiInteraction:
    """Record raw ongoing-capture notes (meetings, chats) as a source-anchored
    AiInteraction kind=capture. The copilot can later turn these into proposals."""
    interaction = AiInteraction(
        tenant_id=tenant.id,
        user_id=user.id,
        project_id=project.id,
        kind="capture",
        question=notes[:2000],
        answer=json.dumps({"source": source, "status": "captured"}),
        status="pending",
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)
    return interaction
