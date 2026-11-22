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
from app.models.user_task import UserTask

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
    tenant_config: dict | None = None,
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
    raw = llm_fn(INTAKE_SYSTEM_PROMPT, prompt, tenant_config, 500)
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

    created["project_id"] = project.id
    created["project_name"] = project.name
    return created


def capture_ongoing(
    db: Session,
    user: User,
    tenant: Tenant,
    project: Project | None,
    notes: str,
    source: str = "meeting",
) -> AiInteraction:
    """Record raw ongoing-capture notes (meetings, chats) as a source-anchored
    AiInteraction kind=capture. The copilot can later turn these into proposals.
    project=None is the tenant parking lot (the row keeps project_id null)."""
    interaction = AiInteraction(
        tenant_id=tenant.id,
        user_id=user.id,
        project_id=project.id if project else None,
        kind="capture",
        question=notes[:2000],
        answer=json.dumps({"source": source, "status": "captured"}),
        status="pending",
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)
    return interaction


# ── One-call intake (Slice 3b — the capture box) ─────────────────────────

CAPTURE_SOURCE_TAG = "capture box"
MAX_INTAKE_ITEMS = 30


def _dedupe_first_match(db: Session, tenant: Tenant, title: str) -> dict | None:
    """First tenant item whose title matches — the title-similarity dedupe.

    Returns {item_id, title, project_id, phase} for the "Already captured as
    #12 — merge?" inline, or None when nothing matches."""
    if not (title or "").strip():
        return None
    rows = (
        db.query(BacklogItem)
        .filter(BacklogItem.tenant_id == tenant.id)
        .order_by(BacklogItem.id)
        .all()
    )
    for row in rows:
        if _titles_match(title, row.title):
            return {
                "item_id": row.id,
                "title": row.title,
                "project_id": row.project_id,
                "phase": row.current_phase,
            }
    return None


def _iter_features(draft: dict):
    """Flat iteration over a draft's features, skipping empty titles.

    One caller = one position; the same iteration in one_call_intake and
    confirm_intake keeps the payload's item keys stable."""
    for epic in draft.get("epics", []):
        epic_name = (epic.get("name") or "").strip() or None
        for feat in (epic.get("features") or []):
            title = (feat.get("title") or "").strip()
            if not title:
                continue
            yield epic_name, feat, title


def _verbatim_draft(db: Session, user: User, tenant: Tenant, notes: str, source: str) -> dict:
    """LLM unavailable/slow/erroring → the line is saved VERBATIM as a single
    Requirements-phase draft item, flagged needs structuring. Never raises.

    The raw sentence is never lost: the capture row (step 1) already holds it,
    and this draft makes it confirmable while the LLM is down."""
    draft = {
        "summary": "",
        "epics": [{"name": "", "features": [{
            "title": notes.strip()[:500],
            "description": notes.strip(),
            "verbatim": True,
        }]}],
        "personas": [],
        "kpis": [],
        "assumptions": [],
        "verbatim": True,
        "needs_structuring": True,
    }
    interaction = AiInteraction(
        tenant_id=tenant.id,
        user_id=user.id,
        project_id=None,
        kind="intake_draft",
        question=notes[:2000],
        answer=json.dumps(draft),
        status="pending",
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)
    draft["draft_id"] = interaction.id
    return draft


def one_call_intake(
    db: Session,
    user: User,
    tenant: Tenant,
    notes: str,
    source: str = CAPTURE_SOURCE_TAG,
    project: Project | None = None,
    destination: str = "work_item",
    tenant_config: dict | None = None,
) -> dict:
    """THE capture box behind one call: capture → structure → verdict → apply-prep.

    Internally runs the 4-call chain and returns ONE Confirm payload (draft
    items + dedupe warnings + source tag). The LLM never blocks the capture:
    unavailable/slow/erroring falls back to the line saved VERBATIM as a
    Requirements-phase draft flagged needs structuring. A line with no project
    lands in the tenant parking lot (project_id null). Never 500s on AI
    failure — nothing executes before the human Confirm tap."""
    text = (notes or "").strip()
    if not text:
        raise ValueError("Capture text is required.")

    # 1. CAPTURE — the raw line is saved before anything else can fail
    capture = AiInteraction(
        tenant_id=tenant.id,
        user_id=user.id,
        project_id=project.id if project else None,
        kind="capture",
        question=text[:2000],
        answer=json.dumps({"source": source, "destination": destination, "status": "captured"}),
        status="pending",
    )
    db.add(capture)
    db.commit()
    db.refresh(capture)

    # 2. STRUCTURE — the LLM step; failures fall back to the verbatim line
    structured = True
    try:
        draft = structure_intake(
            db, user, tenant, text,
            project_name=project.name if project else "",
            tenant_config=tenant_config,
        )
    except Exception:
        db.rollback()
        structured = False
        draft = _verbatim_draft(db, user, tenant, text, source)

    # Stamp the draft's target project — the confirm inherits it (sentence →
    # Confirm stays 2 steps); a null project_id IS the parking lot.
    if project is not None and draft.get("draft_id"):
        row = db.query(AiInteraction).filter(AiInteraction.id == draft["draft_id"]).first()
        if row and row.project_id != project.id:
            row.project_id = project.id
            db.commit()

    # 3. VERDICT — title-similarity dedupe against the tenant's existing items
    # 4. APPLY-PREP — the would-be records; nothing written until Confirm
    items = []
    for epic_name, feat, title in _iter_features(draft):
        if len(items) >= MAX_INTAKE_ITEMS:
            break
        items.append({
            "key": f"item-{len(items)}",
            "title": title[:500],
            "description": (feat.get("description") or "").strip(),
            "item_type": feat.get("item_type") or "Feature",
            "epic": epic_name,
            "phase": "Requirements",
            "needs_structuring": bool(feat.get("verbatim") or draft.get("verbatim")),
            "dedupe": _dedupe_first_match(db, tenant, title),
        })

    if not items:
        # The LLM answered but proposed nothing usable — same verbatim path
        structured = False
        draft = _verbatim_draft(db, user, tenant, text, source)
        for epic_name, feat, title in _iter_features(draft):
            items.append({
                "key": f"item-{len(items)}",
                "title": title[:500],
                "description": (feat.get("description") or "").strip(),
                "item_type": feat.get("item_type") or "Feature",
                "epic": epic_name,
                "phase": "Requirements",
                "needs_structuring": True,
                "dedupe": _dedupe_first_match(db, tenant, title),
            })

    return {
        "capture_id": capture.id,
        "draft_id": draft.get("draft_id"),
        "source": source,
        "destination": destination,
        "project_id": project.id if project else None,
        "parking_lot": project is None,
        "structured": structured,
        "items": items,
        "message": (
            f"{len(items)} draft item(s) — confirm to land them in Requirements"
            if structured
            else "AI structuring unavailable — captured verbatim; confirm to land it in Requirements and structure it later"
        ),
    }


def confirm_intake(
    db: Session,
    user: User,
    tenant: Tenant,
    draft_id: int,
    keys: list[str] | None = None,
    project: Project | None = None,
    destination: str = "work_item",
) -> dict:
    """THE confirm write path for capture-box drafts: creates the checked
    items in Requirements (the human tap). Parking-lot drafts need a filed
    project first; My Task destination creates a personal task instead."""
    row = db.query(AiInteraction).filter(
        AiInteraction.id == draft_id,
        AiInteraction.tenant_id == tenant.id,
        AiInteraction.user_id == user.id,
        AiInteraction.kind == "intake_draft",
    ).first()
    if not row:
        raise LookupError("draft_not_found")
    try:
        draft = json.loads(row.answer or "{}")
    except ValueError:
        raise LookupError("draft_invalid")
    if row.status == "applied":
        raise ValueError("draft_already_applied")

    # The confirm inherits the intake's target project unless overridden —
    # sentence → Confirm stays 2 steps (parking-lot rows keep project_id null).
    if project is None and row.project_id:
        project = db.query(Project).filter(
            Project.id == row.project_id, Project.tenant_id == tenant.id,
        ).first()

    if destination != "my_task" and project is None:
        # BacklogItem.project_id is NOT NULL — a parking-lot item needs a PM
        # to file it before it can land in Requirements.
        raise ValueError("project_required")

    wanted = set(keys) if keys is not None else None
    verbatim = bool(draft.get("verbatim"))
    existing_titles = {
        _norm_title(t) for (t,) in db.query(BacklogItem.title).filter(
            BacklogItem.project_id == project.id if project else False,
        ).all() if t
    } if project else set()

    created_items = []
    skipped = 0
    for pos, (epic_name, feat, title) in enumerate(_iter_features(draft)):
        key = f"item-{pos}"
        if wanted is not None and key not in wanted:
            continue
        trimmed = title[:500]
        if destination == "my_task":
            task = UserTask(
                tenant_id=tenant.id,
                title=trimmed,
                description=(feat.get("description") or "").strip() or None,
                assigned_to=user.id,
                created_by=user.id,
                project_id=project.id if project else None,
            )
            db.add(task)
            db.flush()
            created_items.append({"id": task.id, "title": task.title, "kind": "task"})
            continue
        if _norm_title(trimmed) in existing_titles:
            skipped += 1
            continue
        description = (feat.get("description") or "").strip()
        if verbatim:
            source_note = "[Needs structuring — captured verbatim from the capture box]"
        else:
            source_note = f"[Source: Capture box draft #{row.id} — AI-structured, applied by {user.name}]"
        description = (f"{description}\n\n{source_note}").strip()
        item = BacklogItem(
            tenant_id=tenant.id,
            project_id=project.id,
            title=trimmed,
            epic=epic_name,
            current_phase="Requirements",
            status="Draft",
            item_type=feat.get("item_type") or "Feature",
            description=description or None,
        )
        db.add(item)
        db.flush()
        existing_titles.add(_norm_title(trimmed))
        created_items.append({
            "id": item.id, "title": item.title, "kind": "work_item",
            "phase": item.current_phase,
        })

    db.add(ActivityLog(
        tenant_id=tenant.id, user_id=user.id,
        project_id=project.id if project else None,
        entity_type="intake", entity_id=row.id, action="applied",
        summary=f"Capture confirmed: {len(created_items)} item(s) from the capture box",
    ))
    row.status = "applied"
    row.outcome = json.dumps({"created": len(created_items), "skipped": skipped})
    db.commit()
    return {
        "confirmed": len(created_items),
        "skipped": skipped,
        "items": created_items,
        "draft_id": row.id,
    }


def dismiss_intake(db: Session, user: User, tenant: Tenant, draft_id: int) -> dict:
    """Dismiss a capture-box draft — marks it rejected, nothing executes."""
    row = db.query(AiInteraction).filter(
        AiInteraction.id == draft_id,
        AiInteraction.tenant_id == tenant.id,
        AiInteraction.user_id == user.id,
        AiInteraction.kind == "intake_draft",
    ).first()
    if not row:
        raise LookupError("draft_not_found")
    row.status = "rejected"
    db.commit()
    return {"dismissed": True, "draft_id": row.id}
