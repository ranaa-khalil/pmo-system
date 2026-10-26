"""Tests for the AiInteraction model — copilot audit trail + trust metrics.

Uses the shared in-memory SQLite fixture from tests/conftest.py (fast, no
Postgres round-trips, no lock contention with the running server).
"""
import json

import pytest

from app.models.ai_interaction import AiInteraction
from app.models.user import User


@pytest.fixture()
def ai_user(db):
    """A real user row so ai_interactions.user_id FKs resolve."""
    user = User(email="ai-test@pmo.test", name="AI Test", hashed_password="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_create_query_interaction(db, ai_user):
    """A copilot query can be logged with sources and outcome (JSON as text)."""
    interaction = AiInteraction(
        kind="query",
        user_id=ai_user.id,
        question="What's overdue on PNU Cloud?",
        sources=json.dumps([{"entity_type": "backlog_item", "entity_id": 42, "title": "SSO login"}]),
        answer="PMO-42 SSO login is overdue by 3 days.",
    )
    db.add(interaction)
    db.commit()

    stored = db.query(AiInteraction).filter(AiInteraction.kind == "query").first()
    assert stored is not None
    assert stored.question == "What's overdue on PNU Cloud?"
    assert json.loads(stored.sources)[0]["entity_id"] == 42
    assert stored.answer.startswith("PMO-42")
    assert stored.created_at is not None


def test_create_proposal_interaction(db, ai_user):
    """A proposal starts pending and can be confirmed/rejected."""
    interaction = AiInteraction(
        kind="proposal",
        user_id=ai_user.id,
        question="move 3 finished items to Testing",
        proposal=json.dumps({"operations": [{"op": "advance_item", "item_id": 1}]}),
        status="pending",
    )
    db.add(interaction)
    db.commit()

    stored = db.query(AiInteraction).filter(AiInteraction.kind == "proposal").first()
    assert stored.status == "pending"
    stored.status = "approved"
    db.commit()
    assert db.query(AiInteraction).filter(AiInteraction.status == "approved").count() == 1


def test_create_intake_interaction(db, ai_user):
    """An intake draft (kickoff) stores the proposal tree."""
    tree = {"epics": [{"name": "Auth", "features": [{"title": "Login", "source_ref": "para:1"}]}]}
    interaction = AiInteraction(
        kind="intake",
        user_id=ai_user.id,
        question="kickoff from paragraph",
        proposal=json.dumps(tree),
        status="pending",
    )
    db.add(interaction)
    db.commit()
    stored = db.query(AiInteraction).filter(AiInteraction.kind == "intake").first()
    assert json.loads(stored.proposal)["epics"][0]["name"] == "Auth"


def test_create_brief_interaction(db, ai_user):
    """A weekly brief stores narrative + numbers."""
    interaction = AiInteraction(
        kind="brief",
        user_id=ai_user.id,
        proposal=json.dumps({"narrative": "On track.", "numbers": {"velocity": 4}}),
        status="applied",
    )
    db.add(interaction)
    db.commit()
    stored = db.query(AiInteraction).filter(AiInteraction.kind == "brief").first()
    assert json.loads(stored.proposal)["numbers"]["velocity"] == 4


def test_kind_and_status_defaults(db, ai_user):
    """New rows default to kind=query, status=pending."""
    interaction = AiInteraction(user_id=ai_user.id, question="hi")
    db.add(interaction)
    db.commit()
    stored = db.query(AiInteraction).first()
    assert stored.kind == "query"
    assert stored.status == "pending"
