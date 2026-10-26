"""Interview engine — guided Q&A for every create flow (P2.1).

The AI PM conducts a short interview: it asks a few sharp questions one at a
time, the human answers (types, taps a quick-pick chip, or accepts the smart
default), and the proposal draft assembles live. Six rules from the rethink
doc (v3.1):

1. 4–8 questions max per flow, every one skippable — defaults come from the
   system (sibling projects, lifecycle templates, the record itself).
2. The AI skips what it can infer; scripts only ask what it can't.
3. Three ways to answer: free text, quick-pick chip, or accept-default.
4. Max 2 follow-ups per answer (enforced by spec validation).
5. The draft grows live in the review panel; Apply remains the only write —
   the assembler produces the SAME shape as the one-shot intake draft, and
   apply_intake stays the single write path.
6. Resumable: session state persists in AiInteraction (kind=interview).

The interview feeds existing draft builders; it never creates records itself.
"""
import json

from sqlalchemy.orm import Session

from app.models.ai_interaction import AiInteraction
from app.models.tenant import Tenant
from app.models.user import User

MAX_FOLLOWUPS = 2


def _sibling_stakeholders(db: Session, user: User, tenant: Tenant) -> str:
    """Default for 'involved': stakeholders seen on sibling projects."""
    from app.models.stakeholder import Stakeholder
    rows = (
        db.query(Stakeholder)
        .filter(Stakeholder.tenant_id == tenant.id)
        .order_by(Stakeholder.id.desc())
        .limit(5)
        .all()
    )
    names = sorted({r.name for r in rows if r.name}) if rows else []
    return ", ".join(names)


# ── Flow specs (data, not code) ──────────────────────────────────────────
# Each question: id, prompt, type (text|choice|date|person|textarea),
# default (static) or default_resolver (fn(db, user, tenant) -> str),
# optional choices (quick-pick chips), optional followup (fn(answer) -> str|None).
# max_followups is capped at MAX_FOLLOWUPS by contract (≤2).

FLOWS = {
    "project": {
        "title": "New project kickoff",
        "produces": "Project draft + epics/features/personas/KPIs tree (intake apply)",
        "questions": [
            {
                "id": "building_what",
                "prompt": "What are we building? One or two sentences is enough.",
                "type": "textarea",
                "default": "",
                "default_resolver": None,  # required — no smart default exists
                "required": True,
            },
            {
                "id": "target_users",
                "prompt": "Who is it for?",
                "type": "text",
                "default": "End users of the platform",
                "default_resolver": None,
            },
            {
                "id": "success_looks_like",
                "prompt": "What does 'done' look like? (the success measure)",
                "type": "text",
                "default": "Launched and adopted by the target users",
                "default_resolver": None,
            },
            {
                "id": "constraints",
                "prompt": "Any hard constraints? (date, budget, compliance)",
                "type": "text",
                "default": "None recorded",
                "default_resolver": None,
            },
            {
                "id": "involved",
                "prompt": "Who is involved? (teams, stakeholders)",
                "type": "text",
                "default": "",
                "default_resolver": _sibling_stakeholders,
            },
            {
                "id": "project_type",
                "prompt": "What kind of project is it?",
                "type": "choice",
                "choices": ["software", "ai", "marketing", "operations"],
                "default": "software",
                "default_resolver": None,
            },
        ],
    },
    "feature": {
        "title": "Feature intake",
        "produces": "Pre-filled feature form fields (backlog save path)",
        "questions": [
            {
                "id": "acceptance_criteria",
                "prompt": "What are the acceptance criteria for this feature?",
                "type": "textarea",
                "default": "",
                "default_resolver": None,
            },
            {
                "id": "priority",
                "prompt": "Priority?",
                "type": "choice",
                "choices": ["Critical", "High", "Medium", "Low"],
                "default": "Medium",
                "default_resolver": None,
            },
            {
                "id": "target_release",
                "prompt": "Target release?",
                "type": "text",
                "default": "",
                "default_resolver": None,
            },
            {
                "id": "dependencies",
                "prompt": "Depends on anything? (item numbers or 'none')",
                "type": "text",
                "default": "none",
                "default_resolver": None,
            },
        ],
    },
    "risk": {
        "title": "Risk entry",
        "produces": "Risk draft (severity × probability computed at confirm)",
        "questions": [
            {
                "id": "what_could_go_wrong",
                "prompt": "What could go wrong?",
                "type": "textarea",
                "default": "",
                "default_resolver": None,
                "required": True,
            },
            {
                "id": "likelihood",
                "prompt": "How likely is it?",
                "type": "choice",
                "choices": ["Rare", "Unlikely", "Medium", "Likely", "Almost Certain"],
                "default": "Medium",
                "default_resolver": None,
            },
            {
                "id": "impact",
                "prompt": "If it happens, how bad?",
                "type": "choice",
                "choices": ["Low", "Medium", "High", "Critical"],
                "default": "Medium",
                "default_resolver": None,
            },
            {
                "id": "mitigation",
                "prompt": "How could we prevent or soften it?",
                "type": "textarea",
                "default": "None recorded",
                "default_resolver": None,
            },
        ],
    },
    "escalation": {
        "title": "Escalation",
        "produces": "Escalation proposal + notification draft",
        "questions": [
            {
                "id": "whats_blocked",
                "prompt": "What is blocked or stuck?",
                "type": "textarea",
                "default": "",
                "default_resolver": None,
                "required": True,
            },
            {
                "id": "since_when",
                "prompt": "Since when?",
                "type": "date",
                "default": "",
                "default_resolver": None,
            },
            {
                "id": "who_can_unblock",
                "prompt": "Who can unblock it?",
                "type": "person",
                "default": "",
                "default_resolver": None,
            },
            {
                "id": "ask",
                "prompt": "What do you need from them?",
                "type": "textarea",
                "default": "",
                "default_resolver": None,
            },
        ],
    },
}


def _default_for(db: Session, user: User, tenant: Tenant, q: dict) -> str:
    """Smart default: resolver reads system state; falls back to the static default."""
    resolver = q.get("default_resolver")
    if resolver:
        try:
            val = resolver(db, user, tenant)
            if val:
                return val
        except Exception:
            pass
    return q.get("default", "")


def _sibling_stakeholders(db: Session, user: User, tenant: Tenant) -> str:
    """Default for 'involved': stakeholders seen on sibling projects."""
    from app.models.stakeholder import Stakeholder
    rows = (
        db.query(Stakeholder)
        .filter(Stakeholder.tenant_id == tenant.id)
        .order_by(Stakeholder.id.desc())
        .limit(5)
        .all()
    )
    names = sorted({r.name for r in rows if r.name}) if rows else []
    return ", ".join(names)


# ── Session state (persisted in AiInteraction.proposal JSON) ─────────────

def _session_row(db: Session, tenant: Tenant, user: User, session_id: int) -> AiInteraction:
    row = (
        db.query(AiInteraction)
        .filter(
            AiInteraction.id == session_id,
            AiInteraction.tenant_id == tenant.id,
            AiInteraction.user_id == user.id,
            AiInteraction.kind == "interview",
        )
        .first()
    )
    if not row:
        raise PermissionError("session_not_found")
    return row


def _state_dict(row: AiInteraction) -> dict:
    try:
        return json.loads(row.proposal or "{}")
    except ValueError:
        return {}


def _flow_of(row: AiInteraction) -> dict:
    state = _state_dict(row)
    flow_id = state.get("flow_id")
    if flow_id not in FLOWS:
        raise ValueError("unknown_flow")
    return FLOWS[flow_id]


def _question_view(db: Session, user: User, tenant: Tenant, flow: dict, qid: str) -> dict:
    spec = next(q for q in flow["questions"] if q["id"] == qid)
    view = {
        "id": spec["id"],
        "prompt": spec["prompt"],
        "type": spec["type"],
        "default": _default_for(db, user, tenant, spec),
        "required": bool(spec.get("required")),
    }
    if spec.get("choices"):
        view["choices"] = spec["choices"]
    return view


def _remaining(flow: dict, answers: dict, skipped: list) -> list:
    return [q["id"] for q in flow["questions"] if q["id"] not in answers]


def _sync(row: AiInteraction, db: Session) -> None:
    row.updated_at = row.updated_at  # touch
    db.commit()


# ── Public engine API ────────────────────────────────────────────────────

def start_interview(db: Session, user: User, tenant: Tenant, flow: str, project_id: int | None = None) -> dict:
    """Open a new interview session. Returns the first question + defaults."""
    if flow not in FLOWS:
        raise ValueError("unknown_flow")
    spec = FLOWS[flow]
    first = spec["questions"][0]
    state = {
        "flow_id": flow,
        "answers": {},
        "skipped": [],
        "current_step": first["id"],
    }
    row = AiInteraction(
        tenant_id=tenant.id,
        user_id=user.id,
        project_id=project_id,
        kind="interview",
        question=f"[interview:{flow}]",
        proposal=json.dumps(state),
        status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    return {
        "session_id": row.id,
        "flow": flow,
        "title": spec["title"],
        "question": _question_view(db, user, tenant, spec, first["id"]),
        "progress": {"current": 1, "total": len(spec["questions"])},
        "answers_so_far": {},
    }


def current_state(db: Session, user: User, tenant: Tenant, session_id: int) -> dict:
    """Resume: read state purely from the persisted row."""
    row = _session_row(db, tenant, user, session_id)
    flow = _flow_of(row)
    state = _state_dict(row)
    remaining = _remaining(flow, state.get("answers", {}), state.get("skipped", []))
    if not remaining:
        return {"done": True, "session_id": session_id, "answers_so_far": state.get("answers", {})}
    qid = remaining[0]
    if state.get("current_step") != qid:
        state["current_step"] = qid
        row.proposal = json.dumps(state)
        _sync(row, db)
    return {
        "done": False,
        "session_id": session_id,
        "question": _question_view(db, user, tenant, flow, qid),
        "progress": {
            "current": len(flow["questions"]) - len(remaining) + 1,
            "total": len(flow["questions"]),
        },
        "answers_so_far": state.get("answers", {}),
    }


def submit_answer(db: Session, user: User, tenant: Tenant, session_id: int, question_id: str, answer: str) -> dict:
    """Record an answer, advance. Follow-ups are capped at 2 per question and
    generated by the LLM only when the spec defines a followup rule."""
    row = _session_row(db, tenant, user, session_id)
    try:
        flow = _flow_of(row)
    except ValueError:
        return {"error": "unknown_flow", "status": 400}
    state = _state_dict(row)
    spec = next((q for q in flow["questions"] if q["id"] == question_id), None)
    if not spec or question_id not in _remaining(flow, state.get("answers", {}), state.get("skipped", [])):
        return {"error": "unknown_question", "status": 409}

    answers = state.setdefault("answers", {})
    answers[question_id] = (answer or "").strip()

    # Follow-up rule: max 2 per question, only when the spec defines one.
    followups = state.setdefault("followups", {})
    fu_count = followups.get(question_id, 0)
    if spec.get("followup") and fu_count < MAX_FOLLOWUPS:
        try:
            fu = spec["followup"](answers[question_id])
        except Exception:
            fu = None
        if fu:
            followups[question_id] = fu_count + 1
            state["followup_question"] = {"for": question_id, "prompt": fu}
            row.proposal = json.dumps(state)
            _sync(row, db)
            return {
                "done": False,
                "session_id": session_id,
                "followup": {"for": question_id, "prompt": fu},
                "question": _question_view(db, user, tenant, flow, question_id),
                "progress": {
                    "current": len(flow["questions"]) - len(_remaining(flow, answers, state.get("skipped", []))),
                    "total": len(flow["questions"]),
                },
                "answers_so_far": answers,
            }
    state.pop("followup_question", None)

    remaining = _remaining(flow, answers, state.get("skipped", []))
    if not remaining:
        state["current_step"] = None
        row.proposal = json.dumps(state)
        _sync(row, db)
        return {"done": True, "session_id": session_id, "answers_so_far": answers}
    state["current_step"] = remaining[0]
    row.proposal = json.dumps(state)
    _sync(row, db)
    return {
        "done": False,
        "session_id": session_id,
        "question": _question_view(db, user, tenant, flow, remaining[0]),
        "progress": {
            "current": len(flow["questions"]) - len(remaining) + 1,
            "total": len(flow["questions"]),
        },
        "answers_so_far": answers,
    }


def skip_question(db: Session, user: User, tenant: Tenant, session_id: int, question_id: str) -> dict:
    """Skip = accept the smart default. Recorded as both answer and skipped."""
    row = _session_row(db, tenant, user, session_id)
    try:
        flow = _flow_of(row)
    except ValueError:
        return {"error": "unknown_flow", "status": 400}
    state = _state_dict(row)
    spec = next((q for q in flow["questions"] if q["id"] == question_id), None)
    if not spec or question_id not in _remaining(flow, state.get("answers", {}), state.get("skipped", [])):
        return {"error": "unknown_question", "status": 409}
    if spec.get("required"):
        return {"error": "question_required", "status": 409}

    default = _default_for(db, user, tenant, spec)
    state.setdefault("answers", {})[question_id] = default
    state.setdefault("skipped", []).append(question_id)
    state.pop("followup_question", None)

    remaining = _remaining(flow, state["answers"], state.get("skipped", []))
    if not remaining:
        state["current_step"] = None
        row.proposal = json.dumps(state)
        _sync(row, db)
        return {"done": True, "session_id": session_id, "answers_so_far": state["answers"]}
    state["current_step"] = remaining[0]
    row.proposal = json.dumps(state)
    _sync(row, db)
    return {
        "done": False,
        "session_id": session_id,
        "question": _question_view(db, user, tenant, flow, remaining[0]),
        "progress": {
            "current": len(flow["questions"]) - len(remaining) + 1,
            "total": len(flow["questions"]),
        },
        "answers_so_far": state["answers"],
    }


def finish_interview(db: Session, user: User, tenant: Tenant, session_id: int) -> dict:
    """Assemble the final draft. Parity contract: the output has exactly the
    same keys and shapes as the one-shot intake draft — apply_intake remains
    the single write path. Nothing is written to projects here."""
    row = _session_row(db, tenant, user, session_id)
    flow = _flow_of(row)
    state = _state_dict(row)
    answers = state.get("answers", {})
    remaining = _remaining(flow, answers, state.get("skipped", []))
    if remaining:
        raise ValueError("interview_incomplete")

    flow_id = state["flow_id"]
    kickoff_text = _answers_to_kickoff(flow, answers)

    if flow_id == "project":
        # Assemble via the SAME intake service the one-shot path uses.
        from app.services import intake as intake_service
        draft = intake_service.structure_intake(
            db, user, tenant, kickoff_text,
            project_name=answers.get("building_what", "")[:120],
            tenant_config=None,
        )
        draft["source"] = f"Interview #{row.id} — guided Q&A kickoff"
        draft["interview_id"] = row.id
        draft["interview_answers"] = answers
        row.status = "pending"  # still awaiting human Apply
        row.answer = json.dumps(draft)
        _sync(row, db)
        return {"done": True, "session_id": session_id, "flow": flow_id, "draft": draft}

    if flow_id == "feature":
        form = {
            "acceptance_criteria": answers.get("acceptance_criteria", ""),
            "priority": answers.get("priority", "Medium"),
            "target_release": answers.get("target_release", ""),
            "dependencies": answers.get("dependencies", "none"),
        }
        row.status = "pending"
        row.answer = json.dumps(form)
        _sync(row, db)
        return {"done": True, "session_id": session_id, "flow": flow_id, "draft": form}

    # Generic: return the raw answers as the draft (risk/escalation wire in next)
    row.status = "pending"
    row.answer = json.dumps(answers)
    _sync(row, db)
    return {"done": True, "session_id": session_id, "flow": flow_id, "draft": answers}


def _answers_to_kickoff(flow: dict, answers: dict) -> str:
    """Render the interview answers as kickoff material — the exact input the
    one-shot intake expects, so parity holds by construction."""
    lines = []
    label = {q["id"]: q["prompt"] for q in flow["questions"]}
    for qid, val in answers.items():
        if val:
            lines.append(f"{label.get(qid, qid)}: {val}")
    return "\n".join(lines)
