"""add hot-path indexes (Rethink v2 Phase A)

The round-2 panel's architecture review verified that only id + tenant_id are
indexed on the hottest read paths. Postgres does not auto-index FKs, so every
new surface (rail counts, coverage %, gates aging, decisions-by-project,
My Tasks, bundling) would scan at 10k rows/tenant. One revision, no data
movement, no behavior change.

Indexes (Rethink v2 §3 Phase A / System Design & Architecture Review §7 change 1):
  - backlog_items(project_id)          — the #1 list query
  - backlog_items(current_phase)       — the rail counts by phase
  - approval_steps(request_id)         — the gates inbox / aging
  - approval_steps(status)             — pending-gate counts
  - decision_records(project_id, made_at) — decisions-by-project (composite, newest-first)
  - user_tasks(assigned_to)            — My Tasks
  - kpis(project_id)                   — the KPI strip / coverage
  - release_items(release_id)          — release bundling scans
  - projects(status)                   — portfolio triage

Revision ID: a7c2e9f41d05
Revises: 8e1401216cc3
Create Date: 2026-11-22
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "a7c2e9f41d05"
down_revision = "8e1401216cc3"
branch_labels = None
depends_on = None

# (table, index name, columns)
INDEXES = [
    ("backlog_items", "ix_backlog_items_project_id", ["project_id"]),
    ("backlog_items", "ix_backlog_items_current_phase", ["current_phase"]),
    ("approval_steps", "ix_approval_steps_request_id", ["request_id"]),
    ("approval_steps", "ix_approval_steps_status", ["status"]),
    ("decision_records", "ix_decision_records_project_created", ["project_id", "made_at"]),
    ("user_tasks", "ix_user_tasks_assigned_to", ["assigned_to"]),
    ("kpis", "ix_kpis_project_id", ["project_id"]),
    ("release_items", "ix_release_items_release_id", ["release_id"]),
    ("projects", "ix_projects_status", ["status"]),
]


def upgrade() -> None:
    for table, name, columns in INDEXES:
        op.create_index(name, table, columns)


def downgrade() -> None:
    for table, name, _columns in reversed(INDEXES):
        op.drop_index(name, table_name=table)
