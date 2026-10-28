"""Lifecycle templates — phases/stages/gates become DATA per project type.

template_for(project_type) selects the vocabulary; the gate MECHANISM and
RBAC never change (ApprovalRequest/ApprovalStep + RACI roles stay exactly
as they are). Software keeps today's V-cycle verbatim as the default;
AI/CPMAI adds dataset, bias, and drift gates; Marketing Campaign and
Operations get their own phases and gate deliverables.
"""

# ── Software (default) — today's V-cycle, verbatim ───────────────────────

_SOFTWARE = {
    "name": "Software",
    "item_phases": [
        "Requirements", "Design", "Development", "Testing", "Ready for UAT",
    ],
    "release_stages": [
        "UAT", "Pre-Release", "Release", "Post-Release", "Retrospective",
    ],
    "gate_deliverables": {
        "Requirements": ["BRD", "Requirements traceability matrix"],
        "Design": ["Design review sign-off"],
        "Development": ["Code review", "Test evidence pack"],
        "Testing": ["Test summary report"],
        "Ready for UAT": ["Release notes draft", "Rollback plan"],
    },
    "gate_roles": {
        "Requirements": "Product Manager",
        "Design": "Product Owner",
        "Development": "Tech Lead",
        "Testing": "QA Lead",
        "Ready for UAT": "Product Manager",
    },
    "fields": [],  # no extra fields beyond the standard schema
}

# ── AI Project (CPMAI-aligned) ───────────────────────────────────────────

_AI = {
    "name": "AI Project (CPMAI)",
    "item_phases": [
        "Data Readiness", "Model Design", "Development & Training",
        "Evaluation", "Ready for Deployment",
    ],
    "release_stages": [
        "Business Understanding", "Data Readiness & Processing",
        "Model Development & Training", "Evaluation",
        "Model Deployment", "Post-Deployment Monitoring",
    ],
    "gate_deliverables": {
        "Data Readiness": ["Dataset readiness report", "Data provenance & consent record"],
        "Model Design": ["Model design review", "ML experiment plan"],
        "Development & Training": ["Training run log", "Model card draft"],
        "Evaluation": ["Model performance report", "Bias & fairness assessment"],
        "Ready for Deployment": ["Inference cost estimate", "Drift-monitoring plan", "Rollback plan"],
    },
    "gate_roles": {
        "Data Readiness": "Data/ML Lead",
        "Model Design": "Data/ML Lead",
        "Development & Training": "Tech Lead",
        "Evaluation": "Product Manager",
        "Ready for Deployment": "DevOps Lead",
    },
    "fields": [
        {"name": "dataset_refs", "label": "Dataset refs", "type": "text"},
        {"name": "model_version", "label": "Model version", "type": "text"},
        {"name": "eval_metrics", "label": "Eval metrics", "type": "markdown"},
        {"name": "bias_status", "label": "Bias status", "type": "select",
         "options": ["not assessed", "pass", "fail", "mitigating"]},
        {"name": "inference_cost", "label": "Inference cost / 1k calls", "type": "text"},
        {"name": "drift_alerts", "label": "Drift alerts", "type": "toggle"},
    ],
}

# ── Marketing Campaign ───────────────────────────────────────────────────

_MARKETING = {
    "name": "Marketing Campaign",
    "item_phases": ["Brief", "Creative", "Content Production", "Review", "Ready for Launch"],
    "release_stages": ["Briefing", "Creative Development", "Content Production", "Review", "Launch", "Post-Campaign Analysis"],
    "gate_deliverables": {
        "Brief": ["Budget approval", "Campaign brief sign-off"],
        "Creative": ["Creative direction approval"],
        "Content Production": ["Content calendar", "Asset checklist"],
        "Review": ["Legal/compliance review", "Final QA checklist"],
        "Ready for Launch": ["Launch plan", "Channel schedule"],
    },
    "gate_roles": {
        "Brief": "Product Manager",
        "Creative": "Product Manager",
        "Content Production": "Content Lead",
        "Review": "Product Manager",
        "Ready for Launch": "Product Manager",
    },
    "fields": [
        {"name": "budget", "label": "Budget", "type": "text"},
        {"name": "channels", "label": "Channels", "type": "text"},
        {"name": "cac_target", "label": "CAC target", "type": "text"},
        {"name": "ctr_target", "label": "CTR target", "type": "text"},
        {"name": "roas_target", "label": "ROAS target", "type": "text"},
    ],
}

# ── Operations / non-technical ───────────────────────────────────────────

_OPERATIONS = {
    "name": "Operations",
    "item_phases": ["Intake", "Plan", "Execute", "Verify", "Done"],
    "release_stages": ["Intake", "Planning", "Execution", "Verification", "Closure"],
    "gate_deliverables": {
        "Intake": ["Request intake form", "Cost center confirmation"],
        "Plan": ["Plan of record", "Vendor quote (if any)"],
        "Execute": ["Execution checklist"],
        "Verify": ["Verification report", "Lessons learned"],
        "Done": ["Closure sign-off"],
    },
    "gate_roles": {
        "Intake": "Product Manager",
        "Plan": "Product Manager",
        "Execute": "Operations Lead",
        "Verify": "Product Manager",
        "Done": "Product Manager",
    },
    "fields": [
        {"name": "cost_center", "label": "Cost center", "type": "text"},
        {"name": "vendor", "label": "Vendor", "type": "text"},
        {"name": "capacity_impact", "label": "Capacity impact", "type": "text"},
    ],
}

# ── SDLC — classic software delivery, explicit verification stages ───────

_SDLC = {
    "name": "SDLC",
    "item_phases": [
        "Requirements", "Design", "Implementation", "Testing", "Ready for UAT",
    ],
    "release_stages": [
        "UAT", "Pre-Release", "Release", "Post-Release", "Retrospective",
    ],
    "gate_deliverables": {
        "Requirements": ["SRS", "Requirements traceability matrix"],
        "Design": ["Design document sign-off", "Architecture review"],
        "Implementation": ["Code review", "Unit test evidence"],
        "Testing": ["Test summary report", "Defect log"],
        "Ready for UAT": ["UAT plan", "Rollback plan"],
    },
    "gate_roles": {
        "Requirements": "Product Manager",
        "Design": "Product Owner",
        "Implementation": "Tech Lead",
        "Testing": "QA Lead",
        "Ready for UAT": "Product Manager",
    },
    "fields": [],
}

# ── ADLC — Agentic Development Life Cycle (AI agents as first-class work) ─

_ADLC = {
    "name": "ADLC (Agentic)",
    "item_phases": [
        "Agent Intent", "Tooling & Guardrails", "Agent Build", "Evaluation", "Ready for Release",
    ],
    "release_stages": [
        "Intent Review", "Scenario Validation", "Agent Deployment",
        "Live Monitoring", "Drift Retrospective",
    ],
    "gate_deliverables": {
        "Agent Intent": ["Intent spec", "Success criteria & eval set"],
        "Tooling & Guardrails": ["Tool allowlist", "Guardrail policy (injection, loops, spend caps)"],
        "Agent Build": ["Agent run log", "Prompt/version card", "Sandbox trace evidence"],
        "Evaluation": ["Eval report (pass rate, regressions)", "Safety assessment", "Human-handoff criteria"],
        "Ready for Release": ["Rollback plan", "Monitoring plan (drift, cost, loops)"],
    },
    "gate_roles": {
        "Agent Intent": "Product Manager",
        "Tooling & Guardrails": "Tech Lead",
        "Agent Build": "Tech Lead",
        "Evaluation": "Product Manager",
        "Ready for Release": "DevOps Lead",
    },
    "fields": [
        {"name": "agent_version", "label": "Agent version", "type": "text"},
        {"name": "model_refs", "label": "Model refs", "type": "text"},
        {"name": "tool_allowlist", "label": "Tool allowlist", "type": "markdown"},
        {"name": "eval_pass_rate", "label": "Eval pass rate", "type": "text"},
        {"name": "guardrail_status", "label": "Guardrail status", "type": "select",
         "options": ["not assessed", "pass", "fail", "mitigating"]},
        {"name": "spend_cap", "label": "Spend cap / run", "type": "text"},
        {"name": "drift_alerts", "label": "Drift alerts", "type": "toggle"},
    ],
}

# ── Hybrid — SDLC spine + agentic track where the work involves agents ───

_HYBRID = {
    "name": "Hybrid (SDLC + ADLC)",
    "item_phases": [
        "Requirements", "Design", "Development", "Agent Build", "Testing", "Ready for UAT",
    ],
    "release_stages": [
        "UAT", "Pre-Release", "Release", "Post-Release", "Retrospective",
    ],
    "gate_deliverables": {
        "Requirements": ["BRD", "Requirements traceability matrix"],
        "Design": ["Design review sign-off"],
        "Development": ["Code review", "Test evidence pack"],
        "Agent Build": ["Agent run log", "Guardrail policy", "Eval evidence"],
        "Testing": ["Test summary report", "Agent eval regression report"],
        "Ready for UAT": ["Release notes draft", "Rollback plan"],
    },
    "gate_roles": {
        "Requirements": "Product Manager",
        "Design": "Product Owner",
        "Development": "Tech Lead",
        "Agent Build": "Tech Lead",
        "Testing": "QA Lead",
        "Ready for UAT": "Product Manager",
    },
    "fields": [
        {"name": "agent_version", "label": "Agent version", "type": "text"},
        {"name": "eval_metrics", "label": "Eval metrics", "type": "markdown"},
        {"name": "guardrail_status", "label": "Guardrail status", "type": "select",
         "options": ["not assessed", "pass", "fail", "mitigating"]},
    ],
}

LIFECYCLE_TEMPLATES = {
    "software": _SOFTWARE,
    "ai": _AI,
    "marketing": _MARKETING,
    "operations": _OPERATIONS,
    "sdlc": _SDLC,
    "adlc": _ADLC,
    "hybrid": _HYBRID,
}

DEFAULT_TYPE = "software"

# Phases that trigger GitHub issue export on entry, per template. Missing key
# falls back to ["Development"].
GITHUB_SYNC_PHASES = {
    "software": ["Development"],
    "sdlc": ["Implementation"],
    "adlc": ["Agent Build"],
    "hybrid": ["Development", "Agent Build"],
}


def template_for(project_type: str | None, tenant_id: int | None = None, db=None) -> dict:
    """Template for a project type; None/unknown defaults to software.

    P4.4 methodology depth: a tenant-defined template for the project_type
    key overrides the built-in. Built-ins stay verbatim otherwise.
    Pass db= to reuse the caller's session (tests, request handlers);
    otherwise a short-lived SessionLocal is used.
    """
    key = (project_type or "").lower()
    if tenant_id:
        from app.models.lifecycle_template import TenantLifecycleTemplate
        own_session = db is None
        if own_session:
            from app.database import SessionLocal
            db = SessionLocal()
        try:
            row = (
                db.query(TenantLifecycleTemplate)
                .filter(
                    TenantLifecycleTemplate.tenant_id == tenant_id,
                    TenantLifecycleTemplate.project_type == key,
                )
                .first()
            )
            if row:
                return {
                    "name": row.name,
                    "description": row.description,
                    "item_phases": row.item_phases,
                    "release_stages": row.release_stages,
                    "gate_deliverables": row.gate_deliverables,
                    "gate_roles": row.gate_roles,
                    "fields": row.fields or [],
                    "custom": True,
                }
        finally:
            if own_session:
                db.close()
    return LIFECYCLE_TEMPLATES.get(key, LIFECYCLE_TEMPLATES[DEFAULT_TYPE])


def item_phases(project_type: str | None) -> list[str]:
    return template_for(project_type)["item_phases"]


def release_stages(project_type: str | None) -> list[str]:
    return template_for(project_type)["release_stages"]


def gate_deliverables(project_type: str | None) -> dict[str, list[str]]:
    return template_for(project_type)["gate_deliverables"]


def gate_roles(project_type: str | None) -> dict[str, str]:
    return template_for(project_type)["gate_roles"]


def template_fields(project_type: str | None) -> list[dict]:
    return template_for(project_type)["fields"]
