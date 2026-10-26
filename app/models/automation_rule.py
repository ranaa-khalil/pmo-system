"""AutomationRule model — tenant-scoped automation proposed by mining or templates.

P4.1 of the AI-First plan: rules are never auto-enabled; a human flips
enabled=True (one-click). The rules engine worker evaluates triggers and
executes the action list.
"""
from sqlalchemy import JSON, Boolean, Column, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base

# Trigger vocabulary — the engine and UI share these strings
RULE_TRIGGERS = [
    "approval_aging",    # an approval has sat in a gate past N hours
    "task_overdue",      # a user task passed its due date
    "item_sent_back",    # a backlog item was sent back a phase
    "item_blocked",      # a backlog item entered Blocked
    "kpi_off_target",    # a KPI drifted past its target (predictive flag)
    "release_advanced",  # a release moved phase (informational)
]

# Action vocabulary — what the engine may execute
RULE_ACTIONS = [
    "notify",        # in-app notification to a role/user
    "create_task",   # create a user task (escalation follow-up)
    "flag",          # surface in the daily briefing / copilot context
]

# Where the rule came from
RULE_SOURCES = ["mined", "template", "manual"]


class AutomationRule(Base):
    """A proposable automation rule (trigger + conditions + actions)."""

    __tablename__ = "automation_rules"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    trigger = Column(String(50), nullable=False, index=True)  # one of RULE_TRIGGERS
    conditions = Column(JSON, nullable=True)   # e.g. {"hours_in_gate": 48}
    actions = Column(JSON, nullable=False)     # e.g. [{"type": "notify", "role": "gate_owner"}]
    source = Column(String(20), default="manual", nullable=False)  # mined | template | manual
    evidence = Column(JSON, nullable=True)     # mining evidence: {"matches_last_30d": 3, "sample": [...]}
    enabled = Column(Boolean, default=False, nullable=False, index=True)  # human-gated
    last_fired_at = Column(String, nullable=True)  # ISO timestamp of last execution
    fire_count = Column(Integer, default=0, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(String, server_default=func.now(), nullable=False)
    updated_at = Column(String, server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<AutomationRule(id={self.id}, trigger={self.trigger}, enabled={self.enabled})>"
