"""Gate evidence generation — AI-drafted evidence packs at every gate.

draft_evidence builds the starting-point evidence pack an approver needs:
release notes, open items, test evidence, and the lifecycle template's gate
deliverables for the target phase. The prompt is grounded in the release's
real backlog state. Drafts persist as AiInteraction kind=evidence; the human
edits and signs — the draft is never the final record.
"""
import json

from sqlalchemy.orm import Session

from app.models.ai_interaction import AiInteraction
from app.models.approval import ApprovalRequest
from app.models.backlog_item import BacklogItem
from app.models.tenant import Tenant
from app.services.lifecycle import gate_deliverables, gate_roles, template_for

EVIDENCE_SYSTEM_PROMPT = (
    "You draft gate evidence packs for a project approval. Answer only from "
    "the provided release data — never invent records. Be factual and concise: "
    "the approver needs facts to sign off. Reply ONLY with JSON."
)


def _call_llm(system_prompt: str, user_prompt: str, tenant_config: dict | None = None, max_tokens: int = 900) -> str:
    """Thin wrapper so tests can monkeypatch evidence._call_llm."""
    from app.services.ai import _call_llm as _ai_call
    return _ai_call(system_prompt, user_prompt, max_tokens=max_tokens, json_mode=True, tenant_config=tenant_config)


def draft_evidence(
    db: Session,
    tenant: Tenant,
    project,
    approval: ApprovalRequest,
    tenant_config: dict | None = None,
) -> dict:
    """Draft the evidence pack for one gate approval. Writes only the draft
    (AiInteraction); the approval record itself is untouched."""
    target_phase = approval.target_phase or ""
    template = template_for(project.project_type)
    deliverables = gate_deliverables(project.project_type).get(target_phase, [])
    role = gate_roles(project.project_type).get(target_phase, "approver")

    # ── Ground in the release's real backlog state ──────────────────────
    items = db.query(BacklogItem).filter(
        BacklogItem.project_id == project.id,
    ).order_by(BacklogItem.id).all()

    item_lines = []
    for it in items:
        item_lines.append(f"- {it.title} [{it.item_type or 'Feature'}] — {it.current_phase}, {it.status}")

    open_count = len([it for it in items if it.status in ("In Progress", "Blocked")])

    user_prompt = (
        f"PROJECT: {project.name} ({template['name']})\n"
        f"GATE: {target_phase} — awaiting sign-off from {role}\n"
        f"APPROVAL: {approval.title}\n\n"
        f"REQUIRED DELIVERABLES FOR THIS GATE:\n"
        + ("\n".join(f"- {d}" for d in deliverables) or "(none specified)") + "\n\n"
        f"RELEASE BACKLOG STATE ({len(items)} items, {open_count} open):\n"
        + ("\n".join(item_lines) or "(empty backlog)") + "\n\n"
        "Draft the evidence pack: release_notes (what this gate delivers, from "
        "the backlog state), open_items (items still open at this gate), "
        "test_evidence (what has been verified). Reply ONLY with JSON: "
        '{"release_notes": str, "open_items": [str], "test_evidence": str}'
    )

    raw = _call_llm(EVIDENCE_SYSTEM_PROMPT, user_prompt, tenant_config)
    from app.services.ai import _extract_json
    parsed = _extract_json(raw) or {}

    result = {
        "release_notes": parsed.get("release_notes", ""),
        "open_items": parsed.get("open_items", []),
        "test_evidence": parsed.get("test_evidence", ""),
        "deliverables": deliverables,
        "gate_role": role,
    }

    interaction = AiInteraction(
        tenant_id=tenant.id,
        user_id=None,
        project_id=project.id,
        kind="evidence",
        question=f"Evidence pack for approval #{approval.id} — {target_phase}",
        answer=json.dumps(result),
        sources=json.dumps({"approval_id": approval.id, "items": [it.id for it in items[:50]]}),
        status="generated",
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)

    result["evidence_id"] = interaction.id
    return result
