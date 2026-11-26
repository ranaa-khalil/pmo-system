"""Copilot service — grounded context assembly, chat, and action proposals.

Every AI call executes as the logged-in user: context is filtered exactly like
the dashboard (user's assigned clients/projects), so RBAC and tenant isolation
are inherited, not rebuilt. Every entry carries a source tag so answers are
traceable to real records. Writes only ever happen via the proposal pattern:
draft → human confirm → execute.
"""
import json
import re as _re

from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog
from app.models.ai_interaction import AiInteraction
from app.models.approval import ApprovalRequest
from app.models.backlog_item import BacklogItem
from app.models.project import Project
from app.models.risk import Risk
from app.models.tenant import Tenant
from app.models.user import User
from app.services import grounding
from app.services.grounding import (
    _days_since,
)
from app.services.grounding import (  # noqa: F401 — re-exported for routers/ai.py
    assigned_project_ids as _assigned_project_ids,
)
from app.services.scope import tenant_scoped

# Proposals expire after this many days pending
PROPOSAL_EXPIRY_DAYS = 7

# v1 operation vocabulary — each maps to an existing service call
PROPOSAL_OPS = ["advance_item", "assign_user", "create_risk", "escalate_approval"]

# Per-capability metering (Rethink slice 2): the llm_usage.feature labels the
# copilot's burns. The fast path (lookups) makes NO call and writes no row.
REASONED_FEATURE = "copilot.reasoned"
BRIEFING_FEATURE = "copilot.briefing"


def build_context(
    db: Session,
    user: User,
    tenant: Tenant,
    project_id: int | None = None,
) -> dict:
    """Assemble the grounded system state the copilot can see.

    Rethink slice 2: a FACADE over the grounding bundles (app/services/
    grounding.py) — the payload is byte-identical to the pre-facade compute
    (the chat tests are the parity gate). Every entry has entity_type/
    entity_id/title so the UI can render source chips and the LLM can cite
    record ids.
    """
    proj_ids = grounding.resolve_project_ids(db, user, tenant, project_id)

    if not proj_ids:
        return {
            "projects": [], "pending_approvals": [], "aging_items": [],
            "overdue_tasks": [], "at_risk_releases": [], "epic_tree": {},
            "open_risks": [], "predictive_flags": [],
            "schedule": None, "schedules": [],
        }

    bundles = grounding.get_bundles(db, list(grounding.BUNDLES), user, tenant, proj_ids, project_id=project_id)
    return grounding.assemble(bundles)


def _render_schedule_block(s: dict, max_items: int = 40) -> str:
    """One project's schedule as prompt lines — the ask's schedule block.

    Computed states are labeled as computed: the critical path is CPM
    (zero float against the planned windows) and drift compares the plan's
    last end date with the release target — never a manual flag. Every
    entry keeps its record type so the model cites "Item 3"/"Release 1".
    """
    lines = []
    if s.get("planned_finish"):
        window = f"{s.get('window_start')} → {s.get('window_end')}"
        lines.append(
            f"- planned window {window}, planned finish {s['planned_finish']}"
        )
    critical = s.get("critical_items") or []
    if critical:
        members = "; ".join(
            f"Item {c['entity_id']}: {c['title']} ({c.get('phase')}, {c.get('status')})"
            for c in critical[:max_items]
        )
        lines.append(
            f"- critical path ({s.get('critical_count', len(critical))} items, zero float): {members}"
        )
    lines.append(f"- unscheduled items: {s.get('unscheduled_count', 0)}")
    for r in (s.get("releases") or [])[:6]:
        rel = f"- Release {r['entity_id']}: {r['title']} ({r.get('status')}, live stage {r.get('live_stage')}"
        if r.get("target_date"):
            rel += f", target {r['target_date']}"
        rel += ")"
        if r.get("drift_days"):
            rel += f" — the plan runs {r['drift_days']} days past the release target"
        lines.append(rel)
    return (
        "PROJECT SCHEDULE (computed from the item Gantt — CPM + release windows, not manual flags):\n"
        + "\n".join(lines)
    )


def summarize_context(ctx: dict, max_items: int = 40) -> str:
    """Compact text rendering of the context for the LLM prompt.

    Every entry is prefixed with its record type — "Task 2", "Approval 2",
    "Item 5", "Release 1" — never a bare id. Same-numbered records of different
    types can't be blurred, and ages are only ever attached to their own record.
    """
    lines: list[str] = []
    identity = ctx.get("project_identity")
    portfolio = ctx.get("portfolio_identity") or []
    if identity:
        parts = [f"Project {identity['entity_id']}: {identity['title']} ({identity['status']})"]
        if identity.get("description"):
            parts.append(f"description: {identity['description']}")
        if identity.get("client"):
            parts.append(f"client: {identity['client']}")
        if identity.get("manager"):
            parts.append(f"PM: {identity['manager']}")
        lines.append("THIS PROJECT: " + "; ".join(parts))
        if identity.get("vision"):
            lines.append("PROJECT VISION: " + identity["vision"])
        if identity.get("milestones"):
            ms = "; ".join(
                f"{m['title']}" + (f" (target {m['target_date']}, {m['status']})" if m.get("target_date") else "")
                for m in identity["milestones"][:8]
            )
            lines.append("ROADMAP MILESTONES: " + ms)
        if identity.get("recent_activity"):
            acts = "; ".join(f"{a['summary']}" for a in identity["recent_activity"][:8])
            lines.append("RECENT ACTIVITY (newest first): " + acts)
    elif portfolio:
        # Portfolio mode: a story block per project — name, client, vision,
        # description — so answers are relevant to the project the question
        # is actually about, not just the first-assigned one.
        for p in portfolio[:5]:
            parts = [f"Project {p['entity_id']}: {p['title']} ({p['status']})"]
            if p.get("client"):
                parts.append(f"client: {p['client']}")
            if p.get("description"):
                parts.append(f"what it is: {p['description']}")
            if p.get("vision"):
                parts.append(f"vision: {p['vision']}")
            lines.append("PORTFOLIO PROJECT: " + "; ".join(parts))
    elif ctx["projects"]:
        lines.append("PROJECTS: " + "; ".join(
            f"Project {p['entity_id']}: {p['title']} ({p['status']})" for p in ctx["projects"]))
    if ctx.get("schedule"):
        lines.append(_render_schedule_block(ctx["schedule"], max_items))
    elif ctx.get("schedules"):
        rows = []
        for s in ctx["schedules"][:5]:
            if not s.get("planned_finish"):
                rows.append(f"- Project {s['entity_id']} ({s['title']}): no planned windows yet")
                continue
            parts = [
                f"Project {s['entity_id']} ({s['title']}): planned finish {s['planned_finish']}, "
                f"{s['critical_count']} on critical path, {s['unscheduled_count']} unscheduled"
            ]
            for r in s.get("releases", [])[:3]:
                rel = f"Release {r['entity_id']}: {r['title']} ({r['status']}, target {r['target_date']})"
                if r.get("drift_days"):
                    rel += f" — plan runs {r['drift_days']} days past the target"
                parts.append(rel)
            rows.append("; ".join(parts))
        lines.append(
            "SCHEDULE PER PROJECT (computed from the item Gantt — CPM + release windows, not manual flags):\n"
            + "\n".join(f"- {r}" for r in rows)
        )
    if ctx["pending_approvals"]:
        rows = [f"- Approval {a['entity_id']}: {a['title']} (awaiting {a.get('awaiting_role') or 'next role'}, pending for {a.get('days_pending', 0)} days)" for a in ctx["pending_approvals"][:max_items]]
        lines.append("PENDING GATE APPROVALS:\n" + "\n".join(rows))
    if ctx["overdue_tasks"]:
        rows = [f"- Task {t['entity_id']}: {t['title']} (status {t.get('status')}, due {t['due_date']} — {t['days_overdue']} days overdue)" for t in ctx["overdue_tasks"][:max_items]]
        lines.append("YOUR OVERDUE TASKS:\n" + "\n".join(rows))
    if ctx["aging_items"]:
        rows = [f"- Item {i['entity_id']}: {i['title']} — {i['phase']} for {i['days_in_phase']} days" for i in ctx["aging_items"][:max_items]]
        lines.append("ITEMS AGING IN PHASE:\n" + "\n".join(rows))
    if ctx["at_risk_releases"]:
        rows = [f"- Release {r['entity_id']}: {r['title']} — {'; '.join(r['reasons'])}" for r in ctx["at_risk_releases"][:max_items]]
        lines.append("AT-RISK RELEASES (computed: overdue target or pending gate — no manual flag):\n" + "\n".join(rows))
    if ctx.get("open_risks"):
        rows = [f"- Risk {r['entity_id']}: {r['title']} (severity {r['severity']} × probability {r['probability']}, score {r['score']}, {r['status']})" for r in ctx["open_risks"][:max_items]]
        lines.append("OPEN RISKS:\n" + "\n".join(rows))
    if ctx.get("predictive_flags"):
        rows = [f"- {f['message']} (trend: {f['trend']}, severity {f['severity']})" for f in ctx["predictive_flags"][:max_items]]
        lines.append("PREDICTIVE FLAGS (computed from KPI values + history — not manual flags):\n" + "\n".join(rows))
    tree = ctx.get("epic_tree") or {}
    if tree:
        rows = []
        for epic, node in list(tree.items())[:12]:
            feats = ", ".join(
                f"{f['title']} ({f['status']}/{f['phase']})" for f in node["features"][:8]
            )
            rows.append(f"- Epic '{epic}': {feats}")
        lines.append("BACKLOG (epics → features):\n" + "\n".join(rows))
    return "\n\n".join(lines) if lines else "No signal data found for your assignments."


# ── Chat (grounded, read-only Q&A) ───────────────────────────────────────

CHAT_SYSTEM_PROMPT = (
    "You are the PMO Copilot — the user's AI PMO officer inside the PMO System. "
    "Answer only from the provided project data. Cite sources by record type and id "
    "(e.g. 'Task 2', 'Approval 7', 'Item 5', 'Release 1') and by project NAME "
    "(e.g. 'in PNU Cloud...') — never attach one record's "
    "age or status to a different record; every entry's facts belong to that entry alone. "
    "Ground every answer in the specifics: name the project, the feature, the epic, "
    "or the vision statement the answer is about. When the data includes project "
    "descriptions or visions, use them — discuss what the project is FOR and where "
    "it's heading, not just ids and counts. "
    "Statements of work in the conversation are status updates: when the user says "
    "'finished X' or 'SSO is done', treat it as project fact and reflect what it "
    "means for the plan (phases, releases, approvals) in your answer. "
    "The system computes at-risk releases (overdue target or pending gate); never say a "
    "release was 'flagged' unless the data shows a flag. "
    "The schedule block is computed from the item Gantt (CPM forward/backward pass): "
    "'critical path' means zero-float items against the planned windows, and release drift "
    "compares the plan's last end date with the release target date — a computed comparison, "
    "never a manual flag. Answer schedule questions (what's blocking the release, what to move) "
    "from it. "
    "If the data doesn't contain the answer, say so plainly — never invent records. "
    "Reply ONLY with a JSON object with EXACTLY these keys: "
    '{"answer": "<your answer as concise markdown>", "sources": ["Task 2", "Approval 7", "PNU Cloud"]}. '
    "Never use schema.org JSON-LD (no @type), never add other keys, never wrap the JSON "
    "in prose. Be concise and operational: the user is a PM who needs to act."
)


def _call_llm(
    system_prompt: str, user_prompt: str, tenant_config: dict,
    max_tokens: int = 900, feature: str = REASONED_FEATURE,
) -> str:
    """Thin wrapper so tests can monkeypatch copilot_service._call_llm.

    `feature` labels the llm_usage row (per-capability metering): every
    copilot writer call is `copilot.reasoned` unless the caller names another
    capability. Tests that replace this wrapper keep their exact signatures —
    the call sites below never pass feature through.
    """
    from app.services.ai import _call_llm as _ai_call
    return _ai_call(system_prompt, user_prompt, max_tokens=max_tokens, json_mode=True,
                    tenant_config=tenant_config, feature=feature)


# ── Intent routing (Rethink slice 2): rules-first, keyword/entity ────────
# The old frontend 5-verb regex (^(move|assign|draft|escalate|create)) is
# replaced SERVER-SIDE by a keyword/entity router:
#   - _FAST_RULES: lookup-shaped questions ("how many approvals", "what is
#     overdue", "release status", "what needs me") fire the FAST path — the
#     matching bundle runs and a deterministic digest renders from its
#     records with ZERO LLM tokens. Anchored on the spelled-out lookup
#     phrasings: conversational questions ("what's overdue?") keep the
#     reasoned writer (the chat contract tests pin that path).
#   - _SELECTION_RULES: pick the 1–3 bundles the reasoned writer sees.
_FAST_RULES = [
    ("release_readiness", _re.compile(r"\bhow\s+many\s+approvals?\b")),
    ("release_readiness", _re.compile(r"\brelease\s+(status|readiness|ready)\b")),
    ("release_readiness", _re.compile(r"\bis\s+[^.?!]*\brelease\b[^.?!]*\bready\b")),
    ("release_readiness", _re.compile(r"\bwhat('?s| is)?\s+ready\s+to\s+ship\b")),
    ("project_health", _re.compile(r"\bwhat\s+is\s+overdue\b")),
    ("project_health", _re.compile(r"\bhow\s+many\s+(overdue|tasks?)\b")),
    ("project_health", _re.compile(r"\bwhat\s+needs\s+(me|my\s+attention)\b")),
    ("risk_exposure", _re.compile(r"\bhow\s+many\s+risks?\b")),
    ("risk_exposure", _re.compile(r"\b(open|top|show|list)\s+risks\b")),
    ("risk_exposure", _re.compile(r"\brisk\s+exposure\b")),
    ("stakeholder_map", _re.compile(r"\bwho\s+(are|is)\b[^.?!]*\b(stakeholder|pm|manager|owner|sponsor)s?\b")),
    ("stakeholder_map", _re.compile(r"\bstakeholders?\b")),
    ("backlog_shape", _re.compile(r"\bhow\s+(many|big)\s+(is\s+the\s+)?(backlog|features?|epics?)\b")),
    ("backlog_shape", _re.compile(r"\bbacklog\s+shape\b")),
]

_SELECTION_RULES = [
    ("release_readiness", _re.compile(r"\b(approvals?|gate|release|readiness|deliverables?|sign.?off|uat)\b")),
    ("risk_exposure", _re.compile(r"\b(risks?|exposure|threat|mitigation|blockers?)\b")),
    ("stakeholder_map", _re.compile(r"\b(stakeholders?|sponsor|clients?|raci|team|owners?|who)\b")),
    ("backlog_shape", _re.compile(r"\b(backlog|epics?|features?|requirements|scope|items?)\b")),
]


def _fast_route(question: str) -> list[str] | None:
    """The fast-path bundle(s) for a lookup-shaped question, or None.

    Rules-first: the first matching rule wins; "what needs me" spans two
    bundles (the needs-you aggregate lives in project_health's overdue/aging
    plus release_readiness's pending approvals)."""
    q = (question or "").lower()
    for bundles, pattern in _FAST_RULES:
        if pattern.search(q):
            if bundles == "project_health" and ("needs me" in q or "needs my attention" in q):
                return ["project_health", "release_readiness"]
            return [bundles]
    return None


def _select_bundles(question: str) -> list[str]:
    """Rule-based bundle selection for the reasoned path (1–3 bundles).

    project_health is always the spine (identity + schedule + aging +
    overdue); the keyword rules add the bundles the question names. A
    question that matches NO rule is broad — it gets the full grounding
    (all five), the same context the pre-facade chat assembled, so general
    questions lose nothing."""
    q = (question or "").lower()
    if not any(pattern.search(q) for _, pattern in _SELECTION_RULES):
        return list(grounding.BUNDLES)
    selected = ["project_health"]
    for name, pattern in _SELECTION_RULES:
        if pattern.search(q) and name not in selected:
            selected.append(name)
    return selected[:3]


# ── Deterministic digest renderer (fast path + degraded fallback) ────────


def render_digest(bundles: list[dict], question: str = "", degraded: bool = False) -> str:
    """Deterministic markdown digest over bundle records — the fast path's
    answer and the degraded fallback. Records → prose with ZERO LLM tokens:
    one bold verdict line per bundle, then the records behind it. Every line
    cites its record by type + id so the citation validator can turn it into
    a clickable deep link."""
    sections = [s for s in (_digest_for_bundle(b) for b in bundles) if s]
    if not sections:
        return "No signal data found for your assignments."
    body = "\n\n".join(sections)
    footer = (
        "_Computed without narrative — the AI writer was unavailable; these are the live records._"
        if degraded else
        "_Computed from the live records — no AI call._"
    )
    return body + "\n\n" + footer


def _digest_for_bundle(bundle: dict) -> str:
    """One bundle's digest: a bold verdict line + its top records."""
    name = bundle.get("bundle")
    counts = bundle.get("counts") or {}
    sections = bundle.get("sections") or {}

    if name == "project_health":
        parts = []
        if counts.get("overdue_tasks"):
            parts.append(f"{counts['overdue_tasks']} overdue task{'s' if counts['overdue_tasks'] != 1 else ''}")
        if counts.get("aging_items"):
            parts.append(f"{counts['aging_items']} aging item{'s' if counts['aging_items'] != 1 else ''}")
        if counts.get("predictive_flags"):
            parts.append(f"{counts['predictive_flags']} predictive flag{'s' if counts['predictive_flags'] != 1 else ''}")
        n_projects = counts.get("projects", 0)
        if not parts:
            return f"**Project health: all clear across {n_projects} project{'s' if n_projects != 1 else ''} — nothing overdue or aging.**"
        lines = [f"**Project health: {', '.join(parts)} across {n_projects} project{'s' if n_projects != 1 else ''}.**"]
        for t in (sections.get("overdue_tasks") or [])[:8]:
            lines.append(f"- Task {t['entity_id']}: {t['title']} (status {t.get('status')}, due {t['due_date']} — {t['days_overdue']} days overdue)")
        for i in (sections.get("aging_items") or [])[:8]:
            lines.append(f"- Item {i['entity_id']}: {i['title']} — {i['phase']} for {i['days_in_phase']} days")
        for f in (sections.get("predictive_flags") or [])[:8]:
            lines.append(f"- {f.get('message')} (trend: {f.get('trend')}, severity {f.get('severity')})")
        return "\n".join(lines)

    if name == "release_readiness":
        lines = [
            f"**Release readiness: {counts.get('pending_approvals', 0)} pending approval(s), "
            f"{counts.get('at_risk_releases', 0)} at-risk release(s), "
            f"{counts.get('incomplete_items', 0)} incomplete item(s), "
            f"{counts.get('drifted_releases', 0)} drifted.**"
        ]
        for a in (sections.get("pending_approvals") or [])[:8]:
            lines.append(f"- Approval {a['entity_id']}: {a['title']} (awaiting {a.get('awaiting_role') or 'next role'}, pending for {a.get('days_pending', 0)} days)")
        drift_by_id = {r["entity_id"]: r for r in (sections.get("release_drift") or [])}
        for r in (sections.get("at_risk_releases") or [])[:8]:
            line = f"- Release {r['entity_id']}: {r['title']} — {'; '.join(r['reasons'])}"
            drift = drift_by_id.get(r["entity_id"])
            if drift and drift.get("drift_days"):
                line += f"; the plan runs {drift['drift_days']} days past the target"
            lines.append(line)
        for ri in (sections.get("release_items") or [])[:8]:
            lines.append(f"- Item {ri['backlog_item_id']}: {ri['title']} (bundled to Release {ri['release_id']}, status {ri['status']})")
        for d in (sections.get("release_drift") or [])[:6]:
            if d["entity_id"] not in {r["entity_id"] for r in sections.get("at_risk_releases") or []}:
                lines.append(f"- Release {d['entity_id']}: {d['title']} — the plan runs {d['drift_days']} days past the target")
        return "\n".join(lines)

    if name == "risk_exposure":
        n = counts.get("open_risks", 0)
        lines = [f"**{n} open risk{'s' if n != 1 else ''}**"]
        top = sorted(sections.get("open_risks") or [], key=lambda r: -r.get("score", 0))[:8]
        for r in top:
            lines.append(
                f"- Risk {r['entity_id']}: {r['title']} (severity {r['severity']} × probability "
                f"{r['probability']}, score {r['score']}, {r['status']})"
            )
        return "\n".join(lines)

    if name == "stakeholder_map":
        n = counts.get("stakeholders", 0)
        lines = [f"**{n} stakeholder{'s' if n != 1 else ''} across {len({s.get('project_id') for s in sections.get('stakeholders') or []})} project(s)**"]
        for s in (sections.get("stakeholders") or [])[:10]:
            company = f", {s['company']}" if s.get("company") else ""
            lines.append(f"- Project {s.get('project_id')}: {s['title']} ({s.get('role_name')}, {s.get('raci_type') or 'I'}{company})")
        return "\n".join(lines)

    if name == "backlog_shape":
        by_epic = counts.get("by_epic") or {}
        lines = [
            f"**Backlog: {counts.get('items', 0)} item(s) across {counts.get('epics', 0)} epic(s)**"
        ]
        for epic, shape in list(by_epic.items())[:8]:
            lines.append(f"- Epic '{epic}': {shape['total']} item(s), {shape['done']} done")
        return "\n".join(lines)

    return ""


def _unwrap_chat_answer(raw: str, parsed: dict) -> tuple[str, list]:
    """Extract (answer, sources) from a chat response, whatever shape the model used.

    The model sometimes ignores the exact-keys instruction and returns schema.org
    JSON-LD ({"@type": "Answer", "text": ...}), its own key names, or plain
    markdown. Unwrap every observed shape so the drawer never renders raw JSON:
      1. parsed["answer"] (the contract)
      2. parsed["text"] / parsed["response"] / parsed["message"] (renamed answer)
      3. schema.org JSON-LD: {"@type": "Answer", "text": ...} at any nesting
      4. dict of sections (briefing-style: verdict/summary/risks...) → rendered
      5. plain markdown string (no JSON at all)
    """
    def _find_answer(node, depth: int = 0) -> str:
        if depth > 4 or not isinstance(node, dict):
            return ""
        for key in ("answer", "text", "response", "message", "summary"):
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key in ("mainEntity", "acceptedAnswer", "object", "item"):
            found = _find_answer(node.get(key), depth + 1)
            if found:
                return found
        for value in node.values():
            if isinstance(value, dict):
                found = _find_answer(value, depth + 1)
                if found:
                    return found
        return ""

    # 1/2/3: the contract key, renamed keys, or nested JSON-LD
    if isinstance(parsed, dict) and parsed:
        answer = _find_answer(parsed)
        if answer:
            sources = parsed.get("sources")
            return answer, sources if isinstance(sources, list) else []

        # 4: section-shaped dict with no answer key — render as readable text
        sections = []
        for key, value in parsed.items():
            if key.startswith("@"):
                continue  # JSON-LD metadata (@context, @type...)
            label = key.replace("_", " ").title()
            if isinstance(value, list):
                items = "\n".join(f"- {item}" for item in value)
                sections.append(f"**{label}**\n{items}" if items else "")
            elif value is not None and str(value).strip():
                sections.append(f"**{label}**\n{value}")
        rendered = "\n\n".join(s for s in sections if s)
        if rendered:
            return rendered, []

    # 5: not JSON, or JSON that yielded nothing — the raw text itself
    return raw.strip(), []


def copilot_chat(
    db: Session,
    user: User,
    tenant: Tenant,
    question: str,
    tenant_config: dict,
    project_id: int | None = None,
    history: list[dict] | None = None,
    mode: str = "auto",
) -> dict:
    """Grounded Q&A scoped to the open project when one is selected.

    Rethink slice 2 — intent routes rules-first (the keyword/entity router
    above, replacing the old frontend 5-verb regex):

    - FAST path (mode="lookup", or "auto" + a lookup rule): the matching
      bundle(s) run and a deterministic markdown digest renders from their
      records — ZERO LLM tokens, no llm_usage row, no quota burn.
    - REASONED path (mode="reasoned", or "auto" + no lookup rule): rule-based
      bundle selection → compact prompt (only those bundles' records) →
      strict-JSON writer with ONE repair retry on parse failure → server-side
      citation validation against the bundles fetched this turn.
    - DEGRADED fallback: LLM down/timeout/unparseable → the digest renderer
      over the already-fetched bundles with degraded=True — never a raw 502
      for a read-only question. A quota 403 keeps propagating (the plan gate
      is a deliberate hard stop, not an outage).

    Read-only: never writes records. With a project_id the context covers that
    project only (when the user can see it); without one it covers every
    assigned project, with an identity block (client, description, vision) per
    project so answers are relevant across the whole portfolio. `history` is
    the recent conversation (oldest first, [{role, text}, ...]) so follow-up
    questions keep their context. Returns {answer, sources, references,
    interaction_id, mode, bundles_used, degraded, counts}.
    """
    from app.services.ai import _extract_json
    from app.services.llm import FALLBACK_TEXT

    if mode not in ("auto", "lookup", "reasoned"):
        raise ValueError("mode must be one of: auto, lookup, reasoned")

    proj_ids = grounding.resolve_project_ids(db, user, tenant, project_id)
    scope_label = f"the selected project (id={project_id})" if project_id else "all your assigned projects"

    # ── Fast path: deterministic digest, zero LLM tokens ─────────────────
    fast_bundles = _fast_route(question) if mode in ("auto", "lookup") else None
    if mode == "lookup" and not fast_bundles:
        # Forced lookup with no matching rule: the orientation bundle, still
        # zero LLM tokens.
        fast_bundles = ["project_health"]
    if fast_bundles:
        bundles = grounding.get_bundles(db, fast_bundles, user, tenant, proj_ids, project_id=project_id)
        answer = render_digest(bundles, question)
        # Citations in the digest validate against exactly what the digest
        # was rendered from.
        labels, references = _validate_references(answer, [], grounding.assemble(bundles))
        interaction = _persist_chat(db, user, tenant, question, answer, references)
        return {
            "answer": answer,
            "sources": labels,         # backward compatible: the VALIDATED labels
            "references": references,  # entity_type/entity_id/title/url deep links
            "interaction_id": interaction.id,
            "mode": "lookup",
            "bundles_used": [b["bundle"] for b in bundles],
            "degraded": False,
            "counts": {b["bundle"]: b.get("counts", {}) for b in bundles},
        }

    # ── Reasoned path: rule-based bundles → compact prompt → writer ──────
    selected = _select_bundles(question)
    bundles = grounding.get_bundles(db, selected, user, tenant, proj_ids, project_id=project_id)
    ctx = grounding.assemble(bundles)
    context_text = summarize_context(ctx)

    conversation = ""
    if history:
        turns = []
        for turn in history[-8:]:
            role = "User" if turn.get("role") == "user" else "Copilot"
            text = (turn.get("text") or "").strip()
            if text:
                turns.append(f"{role}: {text[:500]}")
        if turns:
            conversation = "RECENT CONVERSATION (oldest first):\n" + "\n".join(turns) + "\n\n"

    user_prompt = (
        f"SCOPE: {scope_label}\n\n"
        f"PROJECT DATA:\n{context_text}\n\n"
        + conversation
        + f"QUESTION: {question}"
    )

    raw = _call_llm(CHAT_SYSTEM_PROMPT, user_prompt, tenant_config, max_tokens=900)
    answer, model_sources, degraded = _reasoned_answer(
        raw, user_prompt, tenant_config, bundles, _extract_json, FALLBACK_TEXT,
    )

    # Rethink MVP #2 + slice 2: citations are validated SERVER-SIDE against
    # the bundles fetched this turn — an id they don't contain is dropped
    # before render, and every surviving citation becomes a clickable
    # deep-link reference. AiInteraction.sources stores the validated shape.
    if degraded:
        labels, references = _validate_references(answer, [], ctx)
    else:
        labels, references = _validate_references(answer, model_sources, ctx)

    interaction = _persist_chat(db, user, tenant, question, answer, references)

    return {
        "answer": answer,
        "sources": labels,        # backward compatible: now the VALIDATED labels
        "references": references,  # entity_type/entity_id/title/url deep links
        "interaction_id": interaction.id,
        "mode": "reasoned",
        "bundles_used": [b["bundle"] for b in bundles],
        "degraded": degraded,
        "counts": {b["bundle"]: b.get("counts", {}) for b in bundles},
    }


def _persist_chat(db: Session, user: User, tenant: Tenant, question: str,
                  answer: str, references: list) -> AiInteraction:
    """Persist one chat interaction (kind=query) with the validated sources —
    the audit trail for both the fast and reasoned paths."""
    interaction = AiInteraction(
        tenant_id=tenant.id,
        user_id=user.id,
        kind="query",
        question=question,
        answer=answer,
        sources=json.dumps(references),
        status="pending",
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)
    return interaction


def _reasoned_answer(
    raw: str,
    user_prompt: str,
    tenant_config: dict,
    bundles: list[dict],
    extract_json,
    fallback_text: str,
) -> tuple[str, list, bool]:
    """Strict-JSON writer with ONE repair retry; degraded fallback.

    Returns (answer, model_sources, degraded). LLM down/timeout (the door's
    FALLBACK_TEXT) or unparseable after the repair retry → the deterministic
    digest over the already-fetched bundles, degraded=True — a read-only
    question never surfaces a raw error."""
    def _door_failure(text: str) -> bool:
        return not text or text == fallback_text or "AI service unavailable" in text

    if _door_failure(raw):
        return render_digest(bundles, degraded=True), [], True

    parsed = extract_json(raw)
    if parsed is None:
        # ONE repair retry — the writer gets its broken reply back.
        repair_prompt = (
            f"{user_prompt}\n\n"
            "Your previous reply was not valid JSON. Reply ONLY with the JSON object "
            '{"answer": "...", "sources": ["..."]} — no prose, no code fences, no commentary.'
        )
        raw = _call_llm(CHAT_SYSTEM_PROMPT, repair_prompt, tenant_config, max_tokens=900)
        if _door_failure(raw):
            return render_digest(bundles, degraded=True), [], True
        parsed = extract_json(raw)
        if parsed is None:
            return render_digest(bundles, degraded=True), [], True

    answer, model_sources = _unwrap_chat_answer(raw, parsed)
    if not answer:
        return render_digest(bundles, degraded=True), [], True
    return answer, model_sources, False


# ── Clickable deep-link references (Rethink MVP #2) ──────────────────────
# The model's free-text citations ("Task 2", "Approval 7", "Item 5",
# "Release 1", "Risk 3", "Project 1") are VALIDATED server-side against the
# context fetched this turn: an id the context doesn't contain is dropped,
# never rendered. Every surviving citation becomes a reference record
# (entity_type, entity_id, title, url) the drawer renders as a CLICKABLE
# deep link (the openNotification + projectTab navigation pattern).

# Spoken record type → context entity_type
_CITATION_TYPES = {
    "task": "user_task",
    "approval": "approval_request",
    "item": "backlog_item",
    "feature": "backlog_item",
    "release": "release",
    "risk": "risk",
    "project": "project",
    "epic": "epic",
}

# entity_type → the drawer's deep-link target (route or project path)
_REFERENCE_URLS = {
    "project": "/projects/{project_id}",
    "backlog_item": "/projects/{project_id}/backlog",
    "approval_request": "/projects/{project_id}/approvals",
    "release": "/projects/{project_id}/releases",
    "risk": "/projects/{project_id}/risks",
    "user_task": "/tasks",
}


def _reference_url(entity_type: str, entity_id: int, project_id: int | None) -> str | None:
    """The deep-link path for a validated reference (openNotification pattern)."""
    template = _REFERENCE_URLS.get(entity_type)
    if not template:
        return None
    if "{project_id}" in template:
        if not project_id:
            return None
        return template.format(project_id=project_id)
    return template.format(project_id=project_id)


def _context_registry(ctx: dict) -> dict:
    """(entity_type, entity_id) → record for every entry in this turn's context.

    Walks the context lists (pending_approvals, aging_items, overdue_tasks,
    at_risk_releases, open_risks, projects, schedules) and the epic tree —
    the SAME entries the model was shown, so a citation validated here is a
    record the copilot can actually see.
    """
    registry: dict = {}

    def _add(entry: dict) -> None:
        if not isinstance(entry, dict):
            return
        etype, eid = entry.get("entity_type"), entry.get("entity_id")
        if etype is None or eid is None:
            return
        registry.setdefault(
            (etype, eid),
            {
                "entity_type": etype,
                "entity_id": eid,
                "title": entry.get("title") or "",
                "project_id": entry.get("project_id"),
            },
        )

    for key in ("projects", "pending_approvals", "aging_items", "overdue_tasks",
                "at_risk_releases", "open_risks"):
        for entry in ctx.get(key) or []:
            _add(entry)
    for entry in ctx.get("schedules") or []:
        _add(entry)
        for item in entry.get("critical_items") or []:
            _add(item)
        for rel in entry.get("releases") or []:
            _add(rel)
    schedule = ctx.get("schedule")
    if schedule:
        _add(schedule)
        for item in schedule.get("critical_items") or []:
            _add(item)
        for rel in schedule.get("releases") or []:
            _add(rel)
    for node in (ctx.get("epic_tree") or {}).values():
        _add(node)
        for feat in node.get("features") or []:
            _add(feat)
    return registry


def _validate_references(answer: str, sources: list, ctx: dict) -> tuple[list, list]:
    """Validate the model's citations against this turn's context.

    Returns (labels, references): the surviving citation labels (backward
    compatible `sources` strings) and the validated reference records
    (entity_type, entity_id, title, url) for the clickable chips. Citations
    whose (entity_type, entity_id) the context doesn't contain are DROPPED —
    citation without a validated record is never rendered.
    """
    import re as _re

    registry = _context_registry(ctx)
    if not registry:
        return [], []

    # 1. Structured model sources can carry ids directly (defensive: the
    #    contract asks for label strings, but dict sources pass through).
    candidate_ids: set = set()
    for src in sources or []:
        if isinstance(src, dict):
            etype, eid = src.get("entity_type"), src.get("entity_id")
            if etype and eid is not None:
                candidate_ids.add((etype, eid))

    # 2. Free-text citations in the answer + model-authored source labels:
    #    "Task 2", "Approval 7", "Item 5", "Release 1", "Risk 3", "Project 1".
    seen_order: list = []
    matched_labels: set = set()

    def _match_text(text: str) -> None:
        if not text:
            return
        for m in _re.finditer(r"\b(Task|Approval|Item|Feature|Release|Risk|Project|Epic)\s+#?(\d+)\b", text, _re.IGNORECASE):
            etype = _CITATION_TYPES.get(m.group(1).lower())
            if not etype:
                continue
            key = (etype, int(m.group(2)))
            if key in registry:
                candidate_ids.add(key)
                label = f"{m.group(1).title()} {m.group(2)}"
                if label not in matched_labels:
                    matched_labels.add(label)
                    seen_order.append(label)

    _match_text(answer or "")
    for src in sources or []:
        if isinstance(src, str):
            _match_text(src)

    # 3. Structured ids first (ordered as given), then free-text labels.
    labels: list = []
    references: list = []
    for key in candidate_ids:
        record = registry[key]
        label = None
        for src in sources or []:
            if isinstance(src, dict) and (src.get("entity_type"), src.get("entity_id")) == key:
                label = src.get("label") or src.get("title")
                break
        if not label:
            type_label = next(
                (spoken.title() for spoken, et in _CITATION_TYPES.items() if et == record["entity_type"]),
                record["entity_type"].replace("_", " ").title(),
            )
            label = f"{type_label} {record['entity_id']}"
        if label not in labels:
            labels.append(label)
        url = _reference_url(record["entity_type"], record["entity_id"], record.get("project_id"))
        references.append({
            "entity_type": record["entity_type"],
            "entity_id": record["entity_id"],
            "label": label,
            "title": record.get("title") or "",
            "url": url,
            "project_id": record.get("project_id"),
        })
    return labels, references


# ── Action proposals (draft → human confirm → execute) ───────────────────

def copilot_propose(
    db: Session,
    user: User,
    tenant: Tenant,
    intent: str,
    operations: list[dict] | None = None,
    tenant_config: dict | None = None,
    project_id: int | None = None,
) -> dict:
    """Draft a write proposal from an intent. Executes nothing.

    Scoped to the open project when one is selected (project_id); operations
    referencing other projects fail at confirm time (authority re-check).
    If operations aren't given, the LLM compiles them from the intent using the
    v1 vocabulary. Operations are validated against PROPOSAL_OPS; anything else
    is rejected before drafting.
    """
    from app.services.ai import _extract_json

    if not operations:
        ctx = build_context(db, user, tenant, project_id=project_id)
        scope = f"ONLY project id={project_id}" if project_id else "the user's assigned projects"
        system = (
            "You compile PMO write operations. Reply ONLY with JSON: "
            '{"operations": [{"op": "advance_item"|"assign_user"|"create_risk"|"escalate_approval", ...args}]}. '
            f"Use only these four ops. Reference records by id from the data below — scope is {scope}, never reference records outside it. "
            "If the intent is out of scope, reply {\"operations\": []}."
        )
        raw = _call_llm(
            system,
            f"PROJECT DATA:\n{summarize_context(ctx)}\n\nINTENT: {intent}",
            tenant_config, max_tokens=700,
        )
        parsed = _extract_json(raw) or {}
        operations = parsed.get("operations") or []

    # Validate the vocabulary — unknown ops are dropped, never executed
    safe_ops = [op for op in operations if isinstance(op, dict) and op.get("op") in PROPOSAL_OPS]

    interaction = AiInteraction(
        tenant_id=tenant.id,
        user_id=user.id,
        kind="proposal",
        question=intent,
        proposal=json.dumps({"operations": safe_ops}),
        status="pending",
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)

    return {"proposal_id": interaction.id, "operations": safe_ops, "status": "pending"}


def get_proposal(db: Session, user: User, tenant: Tenant, proposal_id: int) -> AiInteraction | None:
    """Load a proposal owned by this user in this tenant; expire stale drafts."""
    row = tenant_scoped(db, AiInteraction, tenant.id).filter(
        AiInteraction.id == proposal_id,
        AiInteraction.user_id == user.id,
        AiInteraction.kind == "proposal",
    ).first()
    if row and row.status == "pending" and _days_since(row.created_at) > PROPOSAL_EXPIRY_DAYS:
        row.status = "expired"
        db.commit()
    return row


def confirm_proposal(db: Session, user: User, tenant: Tenant, proposal_id: int) -> dict:
    """Execute a pending proposal AS the user, enforcing the user's authority.

    Every op re-checks the user's rights over the target record before writing.
    Returns {executed: [...], failed: [...]}.
    """
    row = get_proposal(db, user, tenant, proposal_id)
    if not row:
        return {"error": "Proposal not found", "status": 404}
    if row.status != "pending":
        return {"error": f"Proposal is {row.status}, only pending proposals can be confirmed", "status": 409}

    operations = json.loads(row.proposal or "{}").get("operations", [])
    executed, failed = [], []

    for op in operations:
        try:
            result = _execute_op(db, user, tenant, op)
            executed.append({"op": op, "result": result})
        except Exception as e:  # noqa: BLE001 — one failed op must not block the rest
            failed.append({"op": op, "error": str(e)[:200]})

    row.status = "approved"
    row.outcome = json.dumps({"executed": executed, "failed": failed})
    db.commit()

    return {"executed": executed, "failed": failed, "proposal_id": row.id}


def reject_proposal(db: Session, user: User, tenant: Tenant, proposal_id: int) -> dict:
    """Reject a pending proposal without executing anything."""
    row = get_proposal(db, user, tenant, proposal_id)
    if not row:
        return {"error": "Proposal not found", "status": 404}
    if row.status != "pending":
        return {"error": f"Proposal is {row.status}", "status": 409}
    row.status = "rejected"
    db.commit()
    return {"proposal_id": row.id, "status": "rejected"}


def _execute_op(db: Session, user: User, tenant: Tenant, op: dict) -> dict:
    """Execute one validated op with per-record permission checks.

    Authority ceiling: the proposal executes with the user's rights — an op the
    user couldn't do manually raises and lands in `failed`.
    """

    kind = op.get("op")

    if kind == "advance_item":
        item = tenant_scoped(db, BacklogItem, tenant.id).filter(
            BacklogItem.id == op.get("item_id"),
        ).first()
        if not item:
            raise ValueError(f"Backlog item {op.get('item_id')} not found")
        project = db.query(Project).filter(Project.id == item.project_id).first()
        if not project or (project.project_manager_id != user.id and user.system_role != "super_admin"
                           and not _has_role_assignment(db, user.id, item.project_id)):
            raise PermissionError("You don't have rights over this project's items")
        # The advance goes through the ONE advance machine (the same path the
        # backlog advance route uses) so the effective lifecycle decides the
        # next phase and the artifact-chain entry lands. A no-op advance
        # (target == current phase) was a false success — a real transition or
        # a clear failure only.
        from app.models.backlog_item import RELEASE_PHASES
        from app.services.lifecycle import get_effective_lifecycle
        from app.services.release_machine import advance_backlog_item_phase

        eff = get_effective_lifecycle(db, tenant.id, project.project_type)
        if item.current_phase in RELEASE_PHASES or item.current_phase in eff["release_stages"]:
            raise ValueError(
                f"Item is in the release-level phase '{item.current_phase}' — "
                "advance it through the release workflow, not the Copilot"
            )
        if item.current_phase not in eff["item_phases"]:
            raise ValueError(
                f"Item phase '{item.current_phase}' is not part of this project's "
                "lifecycle — advance it manually"
            )
        phases = eff["item_phases"]
        current_idx = phases.index(item.current_phase)
        if current_idx >= len(phases) - 1:
            raise ValueError(
                f"Item is at its final item phase ({phases[-1]}) — no next phase "
                "exists. Add it to a release to continue through the release stages."
            )
        next_phase = phases[current_idx + 1]
        requested = op.get("target_phase")
        if requested and requested != next_phase:
            raise ValueError(
                f"Proposal targets '{requested}' but the item's next phase is "
                f"'{next_phase}' — Copilot advances resolve to the next phase only"
            )
        old = item.current_phase
        item = advance_backlog_item_phase(db, tenant, user, item)
        if item.current_phase == old:
            raise ValueError(f"Item did not advance from '{old}'")
        return {"item_id": item.id, "phase": item.current_phase}

    if kind == "assign_user":
        item = tenant_scoped(db, BacklogItem, tenant.id).filter(
            BacklogItem.id == op.get("item_id"),
        ).first()
        if not item:
            raise ValueError(f"Backlog item {op.get('item_id')} not found")
        project = db.query(Project).filter(Project.id == item.project_id).first()
        if not project or (project.project_manager_id != user.id and user.system_role != "super_admin"):
            raise PermissionError("Only the project manager can assign items")
        assignee = db.query(User).filter(User.id == op.get("assignee_id")).first()
        if not assignee:
            raise ValueError(f"User {op.get('assignee_id')} not found")
        # The assignee must be a member of the item's tenant — same
        # TenantMembership check every route does. Without it a cross-tenant
        # user id executed as a real assignment.
        from app.models.tenant import TenantMembership
        membership = db.query(TenantMembership).filter(
            TenantMembership.user_id == assignee.id,
            TenantMembership.tenant_id == tenant.id,
        ).first()
        if not membership:
            raise PermissionError(
                f"{assignee.name} is not a member of this tenant — cross-tenant assignment rejected"
            )
        item.assigned_to = assignee.id
        db.commit()
        return {"item_id": item.id, "assigned_to": assignee.id}

    if kind == "create_risk":
        # P3: a confirmed proposal writes a real Risk row (replaces P1 risk drafts)
        project_id = op.get("project_id")
        project = tenant_scoped(db, Project, tenant.id).filter(
            Project.id == project_id,
        ).first() if project_id else None
        if not project:
            raise ValueError(f"Project {project_id} not found")
        if project.project_manager_id != user.id and user.system_role != "super_admin":
            raise PermissionError("Only the project manager can draft risks")
        risk = Risk(
            tenant_id=tenant.id, project_id=project.id,
            release_id=op.get("release_id"),
            title=(op.get("description") or "Risk (Copilot)")[:255],
            description=op.get("detail"),
            severity=op.get("severity") or "Medium",
            probability=op.get("probability") or "Medium",
            status="Open", owner_id=user.id, source="copilot",
        )
        db.add(risk)
        db.flush()
        db.add(ActivityLog(
            tenant_id=tenant.id, user_id=user.id, project_id=project.id,
            entity_type="risk", entity_id=risk.id, action="created",
            summary=f"Risk created via Copilot: {risk.title[:180]}",
        ))
        db.commit()
        return {"risk_id": risk.id, "score": risk.score, "title": risk.title}

    if kind == "escalate_approval":
        approval = tenant_scoped(db, ApprovalRequest, tenant.id).filter(
            ApprovalRequest.id == op.get("approval_id"),
        ).first()
        if not approval:
            raise ValueError(f"Approval {op.get('approval_id')} not found")
        project = db.query(Project).filter(Project.id == approval.project_id).first()
        if not project or (project.project_manager_id != user.id and user.system_role != "super_admin"):
            raise PermissionError("Only the project manager can escalate this approval")
        note = op.get("note") or "Escalated via Copilot proposal"
        approval.description = f"{approval.description or ''}\n[ESCALATED] {note}".strip()
        db.commit()
        return {"approval_id": approval.id, "escalated": True}

    raise ValueError(f"Unknown op: {kind}")


def _has_role_assignment(db: Session, user_id: int, project_id: int) -> bool:
    from app.models.role_assignment import RoleAssignment
    return db.query(RoleAssignment).filter(
        RoleAssignment.user_id == user_id,
        RoleAssignment.project_id == project_id,
    ).first() is not None
