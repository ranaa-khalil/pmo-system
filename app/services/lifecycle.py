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


def get_effective_lifecycle(db, tenant_id: int | None, item_type: str | None) -> dict:
    """The ONE effective lifecycle for a tenant + project type (Rethink v2 C1).

    The phase vocabulary used to live in three places (lifecycle_templates
    rows, the backlog_item.py ITEM_PHASES/RELEASE_PHASES constants, hardcoded
    frontend literals) and the advance guards read the constants — so a
    tenant's custom template was decorative. This is the single source:

    - built-in fallback: the built-in template vocabulary (for "software"
      byte-identical to backlog_item.py ITEM_PHASES / RELEASE_PHASES) for
      tenants WITHOUT a template row — byte-identical behavior for them;
    - tenant override: the TenantLifecycleTemplate row (phases + gate
      deliverables + gate roles) when one exists for the type — the template
      now DRIVES the advance chain and the rail.

    Returns item_phases, release_stages, gate_deliverables, gate_roles,
    fields, name, description and "source" ("template" | "builtin").
    Copies are defensive: the built-in dicts are module constants and must
    never be mutated through a caller.
    """
    tpl = template_for(item_type, tenant_id=tenant_id, db=db)
    return {
        "name": tpl.get("name"),
        "description": tpl.get("description"),
        "item_phases": list(tpl.get("item_phases") or []),
        "release_stages": list(tpl.get("release_stages") or []),
        "gate_deliverables": {
            k: list(v) for k, v in (tpl.get("gate_deliverables") or {}).items()
        },
        "gate_roles": dict(tpl.get("gate_roles") or {}),
        "fields": list(tpl.get("fields") or []),
        "source": "template" if tpl.get("custom") else "builtin",
    }


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


# ── The dynamic release lifecycle (Release Lifecycle Dynamic Design §3) ───
#
# The key fact that shapes this section: for the software family the
# template's `release_stages` column is a 5-stage TAIL, not the ladder — the
# release ladder is the 7-phase V-cycle below, whose first three stages
# appear in no template column. Extending `release_stages` to the full
# ladder would break the backlog rail (advance_backlog_item_phase checks
# `item.current_phase in release_stages` and would refuse to advance any
# item parked in Testing/Ready for UAT). So the ladder and the item-level
# release marker are resolved separately — one resolver, two outputs,
# per template (release_lifecycle below).

# The software-family release ladder — the 7-phase V-cycle, moved VERBATIM
# from routers/releases.py (V_CYCLE). Byte-identical for the live releases.
RELEASE_LIFECYCLE_SOFTWARE = [
    ("Planning", "Requirements gathered, items selected", "brand"),
    ("In Progress", "Design + Development underway", "blue"),
    ("Testing", "System Integration Testing (SIT)", "amber"),
    ("UAT", "User Acceptance Testing", "violet"),
    ("Pre-Release", "Release notes, deployment prep", "orange"),
    ("Released", "Deployed to production", "emerald"),
    ("Post-Release", "Monitoring, hotfixes if needed", "teal"),
]

# Software-family project types (unknown/None → software).
SOFTWARE_FAMILY_TYPES = ("", "software", "sdlc", "hybrid")

# The stage at which a release is considered shipped — drives release_date
# stamping and done-detection. Authored per built-in.
_RELEASE_LIVE_STAGES = {
    "software": "Released",
    "sdlc": "Released",
    "hybrid": "Released",
    "ai": "Model Deployment",
    "marketing": "Launch",
    "operations": "Verification",
    "adlc": "Agent Deployment",
}

# Software release gates — VERBATIM from routers/releases.py
# (PHASE_GATE_ROLES), keyed by the 6 non-terminal V-cycle stages. The
# "Released" entry — dead code under the old hardcoded guards — is live
# again as the Released → Post-Release gate (the gate mechanism is
# inviolable; every stage transition creates its RACI approval).
SOFTWARE_RELEASE_GATES = {
    "Planning":     ("Product Owner",   "Approve requirements are complete and ready for development",
                     ["Requirements reviewed and signed off",
                      "Backlog items selected for this release",
                      "Scope and priority agreed with stakeholders"]),
    "In Progress":  ("Tech Lead",       "Approve code completion and readiness for testing",
                     ["All features developed and code-reviewed",
                      "Unit tests passing",
                      "Technical debt logged and accepted",
                      "Branch merged to release branch"]),
    "Testing":      ("QA Lead",         "Approve SIT results and readiness for UAT",
                     ["System Integration Testing complete",
                      "All critical defects resolved",
                      "Regression tests passing",
                      "Test report generated"]),
    "UAT":          ("Product Manager", "Approve UAT passed and readiness for release",
                     ["UAT scenarios executed by business users",
                      "All must-fix defects resolved",
                      "Business sign-off obtained",
                      "No critical/severe open defects"]),
    "Pre-Release":  ("DevOps Lead",     "Approve deployment checklist and go-live",
                     ["Release notes generated and reviewed",
                      "Deployment runbook ready",
                      "Rollback plan prepared",
                      "DB migrations tested in staging",
                      "Monitoring and alerts configured"]),
    "Released":     ("DevOps Lead",     "Confirm deployment success and begin monitoring",
                     ["Deployment to production successful",
                      "Smoke tests passed in production",
                      "Stakeholders notified",
                      "Post-release monitoring active"]),
}

# Authored release gates for the non-software built-ins: their release_stages
# are already complete end-to-end ladders, so the gate tables key the same
# stage names. Every non-final stage MUST carry a role — the terminal stage
# (the ladder's last) carries no gate.
AI_RELEASE_GATES = {
    "Business Understanding":       ("Product Manager", "Approve Business Understanding completion",
                                     ["Business KPIs agreed", "Data success criteria"]),
    "Data Readiness & Processing":  ("Data/ML Lead", "Approve Data Readiness & Processing completion",
                                     ["Dataset readiness report", "Provenance & consent record"]),
    "Model Development & Training": ("Tech Lead", "Approve Model Development & Training completion",
                                     ["Training run log", "Model card draft"]),
    "Evaluation":                   ("Product Manager", "Approve Evaluation completion",
                                     ["Model performance report", "Bias & fairness assessment"]),
    "Model Deployment":             ("DevOps Lead", "Approve Model Deployment completion",
                                     ["Inference cost estimate", "Drift-monitoring plan", "Rollback plan"]),
}

MARKETING_RELEASE_GATES = {
    "Briefing":             ("Product Manager", "Approve Briefing completion",
                             ["Budget approval", "Campaign brief sign-off"]),
    "Creative Development": ("Product Manager", "Approve Creative Development completion",
                             ["Creative direction approval"]),
    "Content Production":   ("Content Lead", "Approve Content Production completion",
                             ["Content calendar", "Asset checklist"]),
    "Review":               ("Product Manager", "Approve Review completion",
                             ["Legal/compliance review", "Final QA checklist"]),
    "Launch":               ("Product Manager", "Approve Launch completion",
                             ["Launch plan", "Channel schedule"]),
}

OPERATIONS_RELEASE_GATES = {
    "Intake":       ("Product Manager", "Approve Intake completion",
                     ["Request intake form", "Cost center confirmation"]),
    "Planning":     ("Product Manager", "Approve Planning completion",
                     ["Plan of record", "Vendor quote (if any)"]),
    "Execution":    ("Operations Lead", "Approve Execution completion",
                     ["Execution checklist"]),
    "Verification": ("Product Manager", "Approve Verification completion",
                     ["Verification report", "Lessons learned"]),
}

ADLC_RELEASE_GATES = {
    "Intent Review":       ("Product Manager", "Approve Intent Review completion",
                            ["Intent spec", "Success criteria & eval set"]),
    "Scenario Validation": ("Tech Lead", "Approve Scenario Validation completion",
                            ["Sandbox trace evidence", "Guardrail policy check"]),
    "Agent Deployment":    ("DevOps Lead", "Approve Agent Deployment completion",
                            ["Agent run log", "Rollback & monitoring plan"]),
    "Live Monitoring":     ("Tech Lead", "Approve Live Monitoring completion",
                            ["Drift/cost/loop monitoring review"]),
}

# Built-in template name → its release-gate table (the software family shares
# the V-cycle gates verbatim; SDLC/Hybrid differ only in item phases).
_BUILTIN_RELEASE_GATES = {
    "Software": SOFTWARE_RELEASE_GATES,
    "SDLC": SOFTWARE_RELEASE_GATES,
    "Hybrid (SDLC + ADLC)": SOFTWARE_RELEASE_GATES,
    "AI Project (CPMAI)": AI_RELEASE_GATES,
    "Marketing Campaign": MARKETING_RELEASE_GATES,
    "Operations": OPERATIONS_RELEASE_GATES,
    "ADLC (Agentic)": ADLC_RELEASE_GATES,
}

# The display/notes/DOCX/stats done set for the software family — VERBATIM
# (including its Pre-Release quirk), byte-identical to the old hardcoded
# lists at releases.py:399/741/985/1061 and stats.py DONE_PHASES.
_SOFTWARE_DONE_PHASES = ["Pre-Release", "Release", "Post-Release", "Retrospective"]

# The item-sync done tuple for the software family — VERBATIM from
# _sync_release_items_to_phase (items' status flips Done no earlier than
# the display rule).
_SOFTWARE_SYNC_DONE_PHASES = ("Release", "Post-Release", "Retrospective")


def _release_ladder_key(project_type: str | None) -> str:
    """The template key for a project type; unknown/None → software."""
    key = (project_type or "").lower()
    return key if key in LIFECYCLE_TEMPLATES else DEFAULT_TYPE


def release_lifecycle(db, tenant_id: int | None, project_type: str | None) -> dict:
    """The ONE release-stage ladder for a tenant + project type.

    The release twin of get_effective_lifecycle. Returns
    {"stages": [...], "source": "template"|"builtin", "name": str,
     "live_stage": str}.

    - Software-family built-ins (software, sdlc, hybrid, unknown/None →
      software): the ladder is the 7-phase V-cycle (RELEASE_LIFECYCLE_SOFTWARE,
      byte-identical for the live releases). `release_stages` stays the
      item-level "release-managed phases" marker exactly as the backlog rail
      reads it.
    - All other built-ins (ai, marketing, operations, adlc) and tenant
      template rows: their release_stages are already complete end-to-end
      ladders — the ladder is that list.
    """
    eff = get_effective_lifecycle(db, tenant_id, project_type)
    key = _release_ladder_key(project_type)
    if eff["source"] == "builtin" and key in SOFTWARE_FAMILY_TYPES:
        stages = [p for p, _, _ in RELEASE_LIFECYCLE_SOFTWARE]
    else:
        stages = eff["release_stages"]
    return {
        "stages": list(stages),
        "source": eff["source"],
        "name": eff["name"],
        "live_stage": _live_stage(stages, eff, key),
    }


def _live_stage(stages: list[str], eff: dict, key: str) -> str | None:
    """The stage at which a release is considered shipped.

    Tenant rows: "Released" if present in their stages, else the final
    stage. Built-ins: the authored live stage, falling back to the final
    stage if the authored name is somehow absent.
    """
    if eff["source"] == "template":
        if "Released" in stages:
            return "Released"
        return stages[-1] if stages else None
    live = _RELEASE_LIVE_STAGES.get(key or DEFAULT_TYPE, "Released")
    if live not in stages:
        return stages[-1] if stages else None
    return live


def release_gate(stage: str, eff: dict) -> tuple[str, str, list[str]]:
    """(role, description, checklist) for leaving `stage`. ALWAYS non-None
    for non-terminal stages — a gate-free transition cannot exist.

    Resolution order:
    1. built-in ai/marketing/operations/adlc: the authored per-stage tables;
    2. built-in software family: SOFTWARE_RELEASE_GATES (verbatim);
    3. tenant rows: gate_roles[stage] — required by save-time validation —
       with description/checklist derived from gate_deliverables[stage] or
       the defaults ("Approve {stage} completion" / "{stage} reviewed");
    4. default when nothing is authored: ("Product Manager",
       "Approve {stage} completion", deliverables or generic). Never None —
       never gate-free.
    """
    if eff["source"] == "template":
        role = (eff.get("gate_roles") or {}).get(stage)
        if role:
            checklist = list(
                (eff.get("gate_deliverables") or {}).get(stage) or [f"{stage} reviewed"]
            )
            return (role, f"Approve {stage} completion", checklist)
    else:
        table = _BUILTIN_RELEASE_GATES.get(eff.get("name") or "")
        if table:
            info = table.get(stage)
            if info:
                return (info[0], info[1], list(info[2]))
    return (
        "Product Manager",
        f"Approve {stage} completion",
        list((eff.get("gate_deliverables") or {}).get(stage) or [f"{stage} reviewed"]),
    )


def missing_release_gate_roles(
    release_stages: list[str] | None, gate_roles: dict | None
) -> list[str]:
    """Non-final release stages with no gate role — the save-time validator.

    A template that bypasses governance cannot be saved (BA FR-R2): every
    non-final release stage must declare its gate role.
    """
    stages = list(release_stages or [])
    return [s for s in stages[:-1] if not (gate_roles or {}).get(s)]


def release_done_phases(db, tenant_id: int | None, project_type: str | None) -> list[str]:
    """The done set for display/notes/DOCX/stats (release_lifecycle's twin).

    Software family built-in: today's verbatim list (including its
    Pre-Release quirk). Other templates: the ladder stages from live_stage
    onward.
    """
    key = _release_ladder_key(project_type)
    ladder = release_lifecycle(db, tenant_id, project_type)
    if ladder["source"] == "builtin" and key in SOFTWARE_FAMILY_TYPES:
        return list(_SOFTWARE_DONE_PHASES)
    stages = ladder["stages"]
    live = ladder["live_stage"]
    if live in stages:
        return list(stages[stages.index(live):])
    return list(stages)


def release_sync_done_phases(db, tenant_id: int | None, project_type: str | None) -> tuple[str, ...]:
    """The item-sync done tuple (release_done_phases' twin).

    Software family built-in: today's verbatim tuple. Other templates: the
    same set as the display rule (the display/sync difference is a preserved
    software quirk, not a new one).
    """
    key = _release_ladder_key(project_type)
    ladder = release_lifecycle(db, tenant_id, project_type)
    if ladder["source"] == "builtin" and key in SOFTWARE_FAMILY_TYPES:
        return _SOFTWARE_SYNC_DONE_PHASES
    return tuple(release_done_phases(db, tenant_id, project_type))
