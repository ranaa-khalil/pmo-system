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
                "id": "title",
                "prompt": "What should this feature be called?",
                "type": "text",
                "default": "",
                "default_resolver": None,
                "required": True,
            },
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
    "release": {
        "title": "Release planning",
        "produces": "Release draft (creates the release on Apply — existing create path)",
        "questions": [
            {
                "id": "whats_shipping",
                "prompt": "What is shipping in this release?",
                "type": "textarea",
                "default": "",
                "default_resolver": None,
                "required": True,
            },
            {
                "id": "version",
                "prompt": "Version number? (e.g. 1.4.0)",
                "type": "text",
                "default": "",
                "default_resolver": None,
                "required": True,
            },
            {
                "id": "release_name",
                "prompt": "Release name? (short label)",
                "type": "text",
                "default": "",
                "default_resolver": None,
            },
            {
                "id": "target_date",
                "prompt": "Target date? (YYYY-MM-DD, or skip)",
                "type": "date",
                "default": "",
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


def back_question(db: Session, user: User, tenant: Tenant, session_id: int) -> dict:
    """Undo the last answered/skipped question and re-ask it.

    Back = remove the most recent answer from the resumable state (and its
    skipped mark + follow-up trail), then return that question again so the
    human can re-answer or choose a different path (e.g. abandon release
    planning for a different capability). The first question cannot go back
    further — Back on question 1 offers the exit instead (client-side).
    """
    row = _session_row(db, tenant, user, session_id)
    try:
        flow = _flow_of(row)
    except ValueError:
        return {"error": "unknown_flow", "status": 400}
    state = _state_dict(row)
    answers = state.get("answers", {})
    if not answers:
        return {"error": "nothing_to_undo", "status": 409}

    # Drop follow-up trails first: a pending follow-up belongs to the last
    # answered question, so back returns to the QUESTION, follow-up gone.
    state.pop("followup_question", None)
    followups = state.get("followups", {})

    # The last touched question = the current step if it has no answer yet
    # (a follow-up was pending), otherwise the most recently answered one.
    answered_order = list(answers.keys())  # insertion order = ask order
    last_qid = answered_order[-1]

    answers.pop(last_qid, None)
    followups.pop(last_qid, None)
    if followups:
        state["followups"] = followups
    else:
        state.pop("followups", None)
    skipped = [qid for qid in state.get("skipped", []) if qid != last_qid]
    if skipped:
        state["skipped"] = skipped
    else:
        state.pop("skipped", None)

    state["current_step"] = last_qid
    row.proposal = json.dumps(state)
    _sync(row, db)
    remaining = _remaining(flow, answers, state.get("skipped", []))
    return {
        "done": False,
        "session_id": session_id,
        "question": _question_view(db, user, tenant, flow, last_qid),
        "progress": {
            "current": len(flow["questions"]) - len(remaining),
            "total": len(flow["questions"]),
        },
        "answers_so_far": answers,
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
            "title": (answers.get("title", "") or "").strip(),
            "acceptance_criteria": answers.get("acceptance_criteria", ""),
            "priority": answers.get("priority", "Medium"),
            "target_release": answers.get("target_release", ""),
            "dependencies": answers.get("dependencies", "none"),
        }
        row.status = "pending"
        row.answer = json.dumps(form)
        _sync(row, db)
        return {"done": True, "session_id": session_id, "flow": flow_id, "draft": form}

    if flow_id == "risk":
        # Risk draft: the Apply step (interview_apply_risk) creates the record
        # via the same rules as the risks API (PM-only, score computed on read).
        draft = {
            "title": (answers.get("what_could_go_wrong", "") or "Untitled risk")[:255],
            "description": answers.get("what_could_go_wrong", ""),
            "mitigation": answers.get("mitigation", ""),
            "severity": answers.get("impact", "Medium"),
            "probability": answers.get("likelihood", "Medium"),
            "project_id": row.project_id,
        }
        row.status = "pending"  # awaiting human Apply
        row.answer = json.dumps(draft)
        _sync(row, db)
        return {"done": True, "session_id": session_id, "flow": flow_id, "draft": draft}

    if flow_id == "escalation":
        # Escalation draft: the Apply step (interview_apply_escalation) appends
        # the escalation note to the chosen approval — same rule as the Copilot
        # escalate op (PM-only).
        draft = {
            "whats_blocked": answers.get("whats_blocked", ""),
            "since_when": answers.get("since_when", ""),
            "who_can_unblock": answers.get("who_can_unblock", ""),
            "ask": answers.get("ask", ""),
            "approval_id": None,  # chosen at review time (no smart default)
            "note": _escalation_note(answers),
            "project_id": row.project_id,
        }
        row.status = "pending"  # awaiting human Apply
        row.answer = json.dumps(draft)
        _sync(row, db)
        return {"done": True, "session_id": session_id, "flow": flow_id, "draft": draft}

    # Generic: return the raw answers as the draft (release wires in next)
    row.status = "pending"
    row.answer = json.dumps(answers)
    _sync(row, db)
    return {"done": True, "session_id": session_id, "flow": flow_id, "draft": answers}


def _escalation_note(answers: dict) -> str:
    """Render escalation answers as the note appended to the approval."""
    parts = []
    if answers.get("whats_blocked"):
        parts.append(f"Blocked: {answers['whats_blocked']}")
    if answers.get("since_when"):
        parts.append(f"since {answers['since_when']}")
    if answers.get("who_can_unblock"):
        parts.append(f"Unblock via: {answers['who_can_unblock']}")
    if answers.get("ask"):
        parts.append(f"Ask: {answers['ask']}")
    return "; ".join(parts) or "Escalated via interview"


def apply_interview_draft(db: Session, user: User, tenant: Tenant, session_id: int, edits: dict | None = None) -> dict:
    """The ONLY write path for risk/escalation/release interview drafts.
    Applies the reviewed draft through the same rules as the manual paths:
    - risk → risks create rules (PM or super admin, source=interview)
    - escalation → approval escalate rules (PM or super admin)
    - release → release create rules (existing create path)
    Returns the created record payload. Never duplicates: the session row is
    marked applied, so a second Apply is refused.
    """
    row = _session_row(db, tenant, user, session_id)
    if row.status == "applied":
        raise ValueError("already_applied")
    flow = _flow_of(row)
    flow_id = json.loads(row.proposal or "{}").get("flow_id")
    try:
        draft = json.loads(row.answer or "{}")
    except ValueError:
        draft = {}
    if edits:
        draft.update(edits)

    if flow_id == "risk":
        from app.models.project import Project
        from app.models.risk import Risk
        project = db.query(Project).filter(
            Project.id == draft.get("project_id"), Project.tenant_id == tenant.id,
        ).first()
        if not project:
            raise ValueError("project_not_found")
        if project.project_manager_id != user.id and user.system_role != "super_admin":
            raise PermissionError("Only the project manager can create risks")
        risk = Risk(
            tenant_id=tenant.id, project_id=project.id,
            title=(draft.get("title") or "Untitled risk")[:255],
            description=draft.get("description"),
            mitigation=draft.get("mitigation"),
            severity=draft.get("severity") or "Medium",
            probability=draft.get("probability") or "Medium",
            status="Open", owner_id=user.id, source="copilot",
        )
        db.add(risk)
        db.flush()
        from app.models.activity_log import ActivityLog
        db.add(ActivityLog(
            tenant_id=tenant.id, user_id=user.id, project_id=project.id,
            entity_type="risk", entity_id=risk.id, action="created",
            summary=f"Risk created via interview #{row.id}: {risk.title[:180]}",
        ))
        db.commit()
        row.status = "applied"
        _sync(row, db)
        return {"applied": "risk", "risk_id": risk.id, "score": risk.score, "title": risk.title}

    if flow_id == "escalation":
        from app.models.approval import ApprovalRequest
        from app.models.project import Project
        approval = db.query(ApprovalRequest).filter(
            ApprovalRequest.id == draft.get("approval_id"), ApprovalRequest.tenant_id == tenant.id,
        ).first()
        if not approval:
            raise ValueError("approval_not_found")
        project = db.query(Project).filter(Project.id == approval.project_id).first()
        if not project or (project.project_manager_id != user.id and user.system_role != "super_admin"):
            raise PermissionError("Only the project manager can escalate this approval")
        note = draft.get("note") or "Escalated via interview"
        approval.description = f"{approval.description or ''}\n[ESCALATED] {note}".strip()
        db.commit()
        row.status = "applied"
        _sync(row, db)
        return {"applied": "escalation", "approval_id": approval.id, "escalated": True}

    if flow_id == "release":
        from app.models.project import Project
        from app.models.release import Release
        version = (draft.get("version") or "").strip()
        if not version:
            raise ValueError("version_required")
        project = db.query(Project).filter(
            Project.id == draft.get("project_id"), Project.tenant_id == tenant.id,
        ).first()
        if not project:
            raise ValueError("project_not_found")
        release = Release(
            tenant_id=tenant.id, project_id=project.id,
            created_by=user.id,
            version=version[:50],
            name=(draft.get("release_name") or f"Release {version}")[:255],
            description=draft.get("whats_shipping"),
            status="Planning",
            target_date=draft.get("target_date") or None,
        )
        db.add(release)
        db.flush()
        from app.models.activity_log import ActivityLog
        db.add(ActivityLog(
            tenant_id=tenant.id, user_id=user.id, project_id=project.id,
            entity_type="release", entity_id=release.id, action="created",
            summary=f"Release {release.version} created via interview #{row.id}",
        ))
        db.commit()
        row.status = "applied"
        _sync(row, db)
        return {"applied": "release", "release_id": release.id, "version": release.version, "name": release.name}

    raise ValueError("flow_not_applyable")


def _answers_to_kickoff(flow: dict, answers: dict) -> str:
    """Render the interview answers as kickoff material — the exact input the
    one-shot intake expects, so parity holds by construction."""
    lines = []
    label = {q["id"]: q["prompt"] for q in flow["questions"]}
    for qid, val in answers.items():
        if val:
            lines.append(f"{label.get(qid, qid)}: {val}")
    return "\n".join(lines)
