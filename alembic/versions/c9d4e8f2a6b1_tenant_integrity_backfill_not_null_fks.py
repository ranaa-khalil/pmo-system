"""tenant integrity: backfill NULL tenant_ids, NOT NULL, self-ref FKs

The tenant-integrity revision (Product Review §4 P0 — 'cheapest now,
impossible-cheap never'). Isolation is enforced by app code across 392
inline filters, but nothing at the data layer refuses a tenant-less row:
`tenant_id` is nullable everywhere, a row written without a tenant is
invisible to every scoped query forever. One revision converts the
discipline into mechanism at the data layer.

Live-apply sequence (the DB must be STAMPED first — it was built by
app/migrate.py and has no alembic_version):

  alembic stamp a7c2e9f41d05   # the 6 existing revisions, no DDL
  alembic upgrade head          # this revision

What it does (idempotent — safe to run more than once):

  1. Backfill — NULL tenant_id business rows get a tenant: derived from the
     row's project_id (multi-tenant safe) where the table has one, then —
     when exactly ONE tenant exists, the cheapest backfill moment there
     will ever be — the remainder is set to it. Rows that stay ambiguous
     are left NULL and the NOT NULL step skips that table (data-driven,
     loud in the migration log instead of failing the revision).
  2. NOT NULL — applied to the tables whose every current writer sets
     tenant_id (writer audit 2026-11-25) and whose backfill left no NULLs.
     Writers that still omit tenant_id keep the column nullable until they
     are fixed: clients-side writers aside, notifications (create_notification),
     form_templates/form_instances (global reference seeds + release gate
     checklists), notification_preferences, beat_runs (worker sweep) and
     task_assignees (raw association inserts) do NOT set tenant_id today —
     a NOT NULL there would 500 the live write paths.
  3. Self-referencing FKs — the 3 model-declared parent links the DB review
     P1 flagged (backlog_items.parent_item_id, risks.escalated_from_id,
     user_tasks.parent_task_id). Already live (hot-path round) and in the
     baseline; re-added idempotently only where missing (Postgres only —
     SQLite builds them from the baseline and doesn't enforce names).

Downgrade restores nullable tenant_id and drops any FKs this revision
added; the backfilled data is not reverted.

Revision ID: c9d4e8f2a6b1
Revises: a7c2e9f41d05
Create Date: 2026-11-25
"""
import sqlalchemy as sa
from sqlalchemy import inspect, text

from alembic import op

# revision identifiers, used by Alembic.
revision = "c9d4e8f2a6b1"
down_revision = "a7c2e9f41d05"
branch_labels = None
depends_on = None

# Tables whose every current writer sets tenant_id (writer audit 2026-11-25):
# model constructors and seed paths all pass tenant_id. NOT NULL is applied
# only when the backfill left 0 NULLs (data-driven).
NOT_NULL_TABLES = [
    "clients", "projects", "backlog_items", "releases", "release_items",
    "kpis", "kpi_history", "roadmaps", "milestones", "stakeholders", "roles",
    "role_assignments", "role_permissions", "permissions",
    "approval_requests", "approval_steps", "user_tasks", "user_personas",
    "project_test_accounts", "project_visions", "github_board_configs",
    "activity_logs", "automation_rules", "lifecycle_templates",
    "artifact_chain", "tags", "approval_guest_links", "approval_guest_decisions",
    "share_links", "item_types", "item_proofs", "project_views",
    "time_entries", "timesheet_locks", "slack_configs", "comments",
    "ai_interactions", "llm_usage", "decision_records",
    "infra_assets", "infra_databases", "infra_environments",
    "infra_secrets", "infra_services", "tenant_settings",
]

# Writers that still omit tenant_id — keep nullable until they are fixed
# (a NOT NULL here would 500 the live write paths). Documented, not applied:
#   notifications            app/services/notifications.py create_notification()
#   notification_preferences app/services/notifications.py set_notification_prefs()
#   form_templates           app/services/form_seeds.py (global reference) +
#                            releases.py _get_or_create_form_template()
#   form_instances           releases.py gate-checklist generation
#   beat_runs                app/worker.py rules_sweep (per-job, not per-tenant)
#   task_assignees           user_tasks.py raw association inserts
UNSAFE_TABLES = [
    "notifications", "notification_preferences", "form_templates",
    "form_instances", "beat_runs", "task_assignees",
]

# Self-referencing parent links the models declare (DB review P1) — re-added
# idempotently where missing, Postgres only (SQLite builds them from the
# baseline and doesn't enforce constraint names).
SELF_REF_FKS = [
    ("backlog_items", "parent_item_id", "CASCADE"),
    ("risks", "escalated_from_id", "SET NULL"),
    ("user_tasks", "parent_task_id", "CASCADE"),
]


def _has_column(conn, table: str, column: str) -> bool:
    return any(c["name"] == column for c in inspect(conn).get_columns(table))


def _backfill(conn) -> list[str]:
    """NULL tenant_id business rows get a tenant. Idempotent (IS NULL only)."""
    tenant_count = conn.execute(text("SELECT count(*) FROM tenants")).scalar()
    for table in NOT_NULL_TABLES + UNSAFE_TABLES:
        if not _has_column(conn, table, "tenant_id"):
            continue
        # 1. Derive from the row's project (multi-tenant safe). Projects with
        #    a NULL tenant leave the row NULL — the subquery returns NULL.
        if _has_column(conn, table, "project_id"):
            conn.execute(text(
                f"UPDATE {table} SET tenant_id = "
                f"(SELECT p.tenant_id FROM projects p WHERE p.id = {table}.project_id) "
                f"WHERE tenant_id IS NULL AND project_id IS NOT NULL"
            ))
        # 2. Single-tenant fallback: the cheapest backfill moment there will
        #    ever be. With more than one tenant the remainder stays NULL
        #    (cross-tenant attribution is a guess this revision refuses).
        if tenant_count == 1:
            conn.execute(text(
                f"UPDATE {table} SET tenant_id = "
                f"(SELECT id FROM tenants ORDER BY id LIMIT 1) "
                f"WHERE tenant_id IS NULL"
            ))
    return []


def _apply_not_null(conn) -> list[str]:
    """NOT NULL where the backfill left no NULLs; skip + log otherwise."""
    applied = []
    for table in NOT_NULL_TABLES:
        if not _has_column(conn, table, "tenant_id"):
            continue
        nulls = conn.execute(
            text(f"SELECT count(*) FROM {table} WHERE tenant_id IS NULL")
        ).scalar()
        if nulls:
            print(f"  tenant integrity: {table} still has {nulls} NULL tenant_id — left nullable")
            continue
        with op.batch_alter_table(table) as batch:
            batch.alter_column("tenant_id", existing_type=sa.Integer(), nullable=False)
        applied.append(table)
    return applied


def _add_self_ref_fks(conn) -> list[str]:
    """The 3 model-declared self-ref FKs, only where missing (Postgres)."""
    if conn.dialect.name != "postgresql":
        return []
    added = []
    for table, column, ondelete in SELF_REF_FKS:
        if not _has_column(conn, table, column):
            continue
        existing = inspect(conn).get_foreign_keys(table)
        already = any(
            column in fk.get("constrained_columns", [])
            and fk.get("referred_table") == table
            for fk in existing
        )
        if already:
            continue
        with op.batch_alter_table(table) as batch:
            batch.create_foreign_key(
                f"{table}_{column}_fkey", table, [column], ["id"], ondelete=ondelete
            )
        added.append(f"{table}.{column}")
    return added


def upgrade() -> None:
    conn = op.get_bind()
    _backfill(conn)
    applied = _apply_not_null(conn)
    fks = _add_self_ref_fks(conn)
    print(f"  tenant integrity: NOT NULL on {len(applied)} tables, +{len(fks)} self-ref FKs")


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        for table, column, _ondelete in SELF_REF_FKS:
            conn.execute(text(
                f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_{column}_fkey"
            ))
    for table in NOT_NULL_TABLES:
        if not _has_column(conn, table, "tenant_id"):
            continue
        with op.batch_alter_table(table) as batch:
            batch.alter_column("tenant_id", existing_type=sa.Integer(), nullable=True)
