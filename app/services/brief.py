"""Weekly brief service — audience-differentiated automated reporting.

generate_report assembles the SAME grounded data (build_context) for every
audience; the narrative shape varies by profile. The data_hash fingerprint
proves the numbers never differ — only relevance filtering. The send path is
approval-gated: nothing is emailed without the recipient's digest preference,
and every report is persisted as an AiInteraction kind=report.
"""
import hashlib
import json

from sqlalchemy.orm import Session

from app.models.ai_interaction import AiInteraction
from app.models.tenant import Tenant
from app.models.user import User
from app.services.copilot import build_context, summarize_context

# Audience profiles: the report shape per stakeholder role.
# Same data spine, different narrative — numbers never differ.
AUDIENCE_PROFILES = {
    "exec_weekly": {
        "label": "Executive weekly verdict",
        "sections": ["verdict", "what_changed", "risks", "decisions_needed"],
        "style": "one page, verdict up front, money/dates/risk, no phase jargon",
    },
    "pm_weekly": {
        "label": "PM operational weekly",
        "sections": ["gates_pending", "aging_items", "overdue_tasks", "needs_escalation"],
        "style": "operational, gate-aging and items to chase, template vocabulary",
    },
    "approver_gate": {
        "label": "Approver gate digest",
        "sections": ["waiting_on_me", "evidence_summary", "changed_since_last"],
        "style": "gate-only: what's waiting on me + evidence; no status noise",
    },
    "team_daily": {
        "label": "Team daily tasks",
        "sections": ["today_tasks", "sent_back", "blocked"],
        "style": "task-only: today's work, what was sent back, blockers",
    },
}

REPORT_SYSTEM_PROMPT = (
    "You write project reports. Answer only from the provided project data — "
    "never invent records. Match the requested audience shape exactly and keep "
    "the tone {style}. Reply ONLY with JSON using these keys: {sections}."
)


def _call_llm(system_prompt: str, user_prompt: str, tenant_config: dict | None = None, max_tokens: int = 1200) -> str:
    """Thin wrapper so tests can monkeypatch brief._call_llm."""
    from app.services.ai import _call_llm as _ai_call
    return _ai_call(system_prompt, user_prompt, max_tokens=max_tokens, json_mode=True, tenant_config=tenant_config)


def _data_fingerprint(ctx: dict) -> str:
    """Stable hash of the grounded data — identical across audiences."""
    canonical = json.dumps(ctx, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def generate_report(
    db: Session,
    tenant: Tenant,
    project,
    audience: str = "exec_weekly",
    user: User | None = None,
    tenant_config: dict | None = None,
) -> dict:
    """Generate a report for ONE audience from the SAME grounded data.

    Returns {audience, content, markdown, sections, data_hash, report_id}.
    """
    profile = AUDIENCE_PROFILES.get(audience)
    if not profile:
        raise ValueError(f"Unknown audience: {audience}. Known: {sorted(AUDIENCE_PROFILES)}")

    ctx = build_context(db, user, tenant, project_id=project.id)
    data_hash = _data_fingerprint(ctx)

    system = REPORT_SYSTEM_PROMPT.format(style=profile["style"], sections=", ".join(profile["sections"]))
    user_prompt = (
        f"PROJECT: {project.name}\n\n"
        f"PROJECT DATA:\n{summarize_context(ctx)}\n\n"
        f"Write the {profile['label']} using exactly these sections: "
        f"{', '.join(profile['sections'])}."
    )
    raw = _call_llm(system, user_prompt, tenant_config)
    from app.services.ai import _extract_json
    content = _extract_json(raw) or {}

    markdown = render_markdown(project, profile, content)
    sections = list(content.keys())

    interaction = AiInteraction(
        tenant_id=tenant.id,
        user_id=user.id if user else None,
        project_id=project.id,
        kind="report",
        question=f"{audience} report — week ending {__import__('datetime').date.today().isoformat()}",
        answer=json.dumps({"content": content, "audience": audience}),
        sources=json.dumps({"data_hash": data_hash, "sections": profile["sections"]}),
        status="generated",
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)

    return {
        "audience": audience,
        "content": content,
        "markdown": markdown,
        "sections": sections,
        "data_hash": data_hash,
        "report_id": interaction.id,
    }


def render_markdown(project, profile: dict, content: dict) -> str:
    """Markdown rendering of a report — docx generation reuses these sections."""
    lines = [f"# {profile['label']} — {project.name}", ""]
    for section in profile["sections"]:
        value = content.get(section)
        if not value:
            continue
        lines.append(f"## {section.replace('_', ' ').title()}")
        if isinstance(value, list):
            lines.extend(f"- {item}" for item in value)
        else:
            lines.append(str(value))
        lines.append("")
    return "\n".join(lines).strip()


def send_report(
    db: Session,
    tenant: Tenant,
    report: dict,
    recipient: User,
    digest_preference: bool = False,
) -> dict:
    """Approval-gated send: nothing is emailed without the recipient's digest
    preference. The email is queued via email_service (never sent live here)."""
    if not digest_preference:
        return {
            "sent": False,
            "reason": "Recipient has no digest preference — reports are not sent without approval.",
        }

    body = report.get("markdown", "")
    html = f"<pre style=\"font-family:inherit;white-space:pre-wrap\">{body}</pre>"
    result = _queue_email(
        db=db,
        tenant=tenant,
        recipient=recipient,
        subject=f"[PMO] {AUDIENCE_PROFILES[report['audience']]['label']} — {report.get('project_name', '')}".strip(),
        body=body,
        html=html,
    )
    return {"sent": True, "queued": result}


def _queue_email(db=None, tenant=None, recipient=None, subject="", body="", html=""):
    """Thin wrapper so tests can monkeypatch brief._queue_email.

    Production wires this to app/services/email_service.send_email.
    """
    from app.services import email_service
    return email_service.send_email(
        db=db, tenant_id=tenant.id, to_email=recipient.email,
        subject=subject, body=body, html=html,
    )
