"""Regression tests for the copilot's overdue/at-risk grounding bugs (Session 21).

User-reported: the copilot merged UserTask #2 with ApprovalRequest #2 (both
id=2, same project) into one fictitious "38-day-old release approval", missed
an In Progress overdue task, and claimed a release was "flagged as at-risk"
when no flag exists.

Fixes under test:
1. Overdue tasks include In Progress (not just Pending)
2. Every context entry is prefixed with its record type — "Task 2", not "2" —
   so same-numbered records of different types can't be blurred
3. At-risk reasons distinguish a computed overdue state from a real flag;
   nothing is ever phrased as "flagged" unless a flag column is set
4. Tasks carry due_date/days_overdue explicitly so the LLM never borrows a
   task's age for a different record
"""
from datetime import date, datetime, timedelta

import pytest

import app.models  # noqa: F401
from app.models.approval import ApprovalRequest
from app.models.project import Project
from app.models.release import Release
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_task import UserTask
from app.services.copilot import build_context, summarize_context


@pytest.fixture()
def merge_world(db):
    tenant = Tenant(name="Merge Co", slug="merge-co")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    pm = User(email="pm-merge@copilot.test", name="PM", hashed_password="x")
    db.add(pm)
    db.commit()
    db.refresh(pm)

    project = Project(name="PNU Cloud", client_id=1, tenant_id=tenant.id, project_manager_id=pm.id)
    db.add(project)
    db.commit()
    db.refresh(project)

    # Both records share id-space collisions: the task and the approval will
    # both get low ids (1, 2, ...) — exactly the blur the user saw.
    task = UserTask(
        tenant_id=tenant.id, title="Approve release v1.0.0", assigned_to=pm.id,
        project_id=project.id, due_date=date.today() - timedelta(days=38),
        status="Pending", description="Review and approve the phase gate",
    )
    db.add(task)
    approval = ApprovalRequest(
        tenant_id=tenant.id, project_id=project.id,
        title="Release v1.0.0: In Progress → Testing",
        request_type="release", target_phase="Testing", status="Pending",
    )
    db.add(approval)
    db.commit()
    db.refresh(task)
    db.refresh(approval)

    release = Release(
        tenant_id=tenant.id, project_id=project.id, version="1.0.0",
        name="Core Platform Launch", status="In Progress",
        target_date=date.today() - timedelta(days=26),
    )
    db.add(release)
    db.commit()
    return {"tenant": tenant, "pm": pm, "project": project, "task": task, "approval": approval, "release": release}


def test_overdue_tasks_include_in_progress(db):
    """In Progress tasks past due are overdue too — not just Pending."""
    tenant = Tenant(name="Prog Co", slug="prog-co")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    pm = User(email="pm-prog@copilot.test", name="PM", hashed_password="x")
    db.add(pm)
    db.commit()
    db.refresh(pm)
    project = Project(name="P1", client_id=1, tenant_id=tenant.id, project_manager_id=pm.id)
    db.add(project)
    db.commit()
    db.refresh(project)

    db.add(UserTask(
        tenant_id=tenant.id, title="Plan CloudGate v2.0.0", assigned_to=pm.id,
        project_id=project.id, due_date=date.today() - timedelta(days=31),
        status="In Progress",
    ))
    db.commit()

    ctx = build_context(db, pm, tenant)
    titles = [t["title"] for t in ctx["overdue_tasks"]]
    assert "Plan CloudGate v2.0.0" in titles


def test_context_labels_record_types_in_summary(db, merge_world):
    """summarize_context prefixes every entry with its record type.

    "Task 2" / "Approval 2" — never a bare id, so the LLM can't borrow one
    record's age for a same-numbered record of another type.
    """
    text = summarize_context(build_context(db, merge_world["pm"], merge_world["tenant"]))
    assert f"Task {merge_world['task'].id}" in text
    assert f"Approval {merge_world['approval'].id}" in text
    # No bare "(id=2)" style references remain
    assert "(id=" not in text


def test_overdue_task_carries_due_date_and_status(db, merge_world):
    """The task entry carries due_date + days_overdue + status explicitly."""
    ctx = build_context(db, merge_world["pm"], merge_world["tenant"])
    entry = next(t for t in ctx["overdue_tasks"] if t["entity_id"] == merge_world["task"].id)
    assert entry["due_date"] == str(date.today() - timedelta(days=38))
    assert entry["days_overdue"] == 38
    assert entry["status"] == "Pending"
    assert entry["entity_type"] == "user_task"


def test_at_risk_reason_never_claims_a_flag(db, merge_world):
    """Reasons are computed facts, phrased as overdue — never 'flagged at-risk'."""
    ctx = build_context(db, merge_world["pm"], merge_world["tenant"])
    rel = next(r for r in ctx["at_risk_releases"] if r["entity_id"] == merge_world["release"].id)
    joined = "; ".join(rel["reasons"])
    assert "passed" in joined
    assert "flagged" not in joined.lower()


def test_approval_entry_never_borrows_task_age(db, merge_world):
    """The approval line carries its own age (days pending), not the task's."""
    text = summarize_context(build_context(db, merge_world["pm"], merge_world["tenant"]))
    approval_line = next(
        line for line in text.splitlines() if f"Approval {merge_world['approval'].id}" in line
    )
    assert "days overdue" not in approval_line
    assert "pending for" in approval_line  # its own age, labeled

def test_unwrap_chat_answer_shapes():
    """The drawer never renders raw JSON — every observed LLM shape unwraps."""
    from app.services.copilot import _unwrap_chat_answer

    # 1. The contract shape
    answer, sources = _unwrap_chat_answer(
        '{"answer": "Overdue: Task 2", "sources": ["Task 2"]}',
        {"answer": "Overdue: Task 2", "sources": ["Task 2"]},
    )
    assert answer == "Overdue: Task 2" and sources == ["Task 2"]

    # 2. Schema.org JSON-LD (the user-reported bug)
    raw = '{"@type": "Answer", "text": "You have 3 overdue tasks:\\n1. Task 2"}'
    answer, _ = _unwrap_chat_answer(raw, {"@type": "Answer", "text": "You have 3 overdue tasks:\n1. Task 2"})
    assert answer == "You have 3 overdue tasks:\n1. Task 2"
    assert "@type" not in answer

    # 3. Renamed keys (response/message)
    answer, _ = _unwrap_chat_answer('{"response": "hi"}', {"response": "hi"})
    assert answer == "hi"

    # 4. Section-shaped dict (briefing style) renders readable text
    answer, _ = _unwrap_chat_answer(
        '{"verdict": "needs_attention", "risks": ["gate stalled"]}',
        {"verdict": "needs_attention", "risks": ["gate stalled"]},
    )
    assert "Verdict" in answer and "needs_attention" in answer
    assert "- gate stalled" in answer
    assert "{" not in answer

    # 5. Plain markdown (no JSON) passes through
    answer, _ = _unwrap_chat_answer("Plain markdown answer", {})
    assert answer == "Plain markdown answer"
