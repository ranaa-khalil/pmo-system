"""Idempotent database schema and reference-data migrations.

Run directly with: python -m app.migrate
"""
import json
import logging

from sqlalchemy import inspect, text

import app.models  # noqa: F401 — register all models
from app.database import Base, SessionLocal, engine

logger = logging.getLogger("app.migrate")

TENANT_TABLES = [
    "clients", "projects", "backlog_items", "releases", "release_items",
    "kpis", "kpi_history", "roadmaps", "milestones", "stakeholders", "roles",
    "role_assignments", "role_permissions", "permissions",
    "approval_requests", "approval_steps", "user_tasks",
    "form_templates", "form_instances", "user_personas",
    "project_test_accounts", "project_visions", "github_board_configs",
    "notifications", "notification_preferences", "activity_logs",
    "automation_rules", "lifecycle_templates", "artifact_chain",
    "tags",
    "approval_guest_links", "approval_guest_decisions", "share_links",
    "item_types", "item_proofs",
    "project_views",
    "time_entries", "timesheet_locks",
    "slack_configs", "comments", "task_assignees",
]

COLUMNS = [
    ("github_board_configs", "project_url VARCHAR(500)"),
    ("users", "active_tenant_id INTEGER"),
    ("users", "token_version INTEGER NOT NULL DEFAULT 0"),
    ("projects", "project_type VARCHAR(50) NOT NULL DEFAULT 'software'"),
    ("projects", "health VARCHAR(20)"),
    ("projects", "budget_hours NUMERIC(8,1)"),
    ("projects", "budget_amount NUMERIC(12,2)"),
    ("risks", "tenant_id INTEGER"),
    ("risks", "release_id INTEGER"),
    ("risks", "mitigation TEXT"),
    ("risks", "owner_id INTEGER"),
    ("risks", "source VARCHAR(20) DEFAULT 'manual' NOT NULL"),
    # Client portal (P4): hashed passcode + enable flag
    # NOTE: Postgres requires DEFAULT FALSE for BOOLEAN (DEFAULT 0 fails);
    # SQLite accepts both.
    ("clients", "portal_passcode_hash VARCHAR(255)"),
    ("clients", "portal_enabled BOOLEAN NOT NULL DEFAULT FALSE"),
    *((table, "tenant_id INTEGER") for table in TENANT_TABLES),
    ("tenants", "branding TEXT"),
    ("tenants", "limits TEXT"),
    ("tenants", "plan_id INTEGER"),
    # Kanban board ordering within a phase lane (lower = higher in the lane)
    ("backlog_items", "board_order INTEGER"),
    # Subtasks (checklists): self-referencing parent, one level only
    ("user_tasks", "parent_task_id INTEGER"),
    # Gantt scheduling: planned window per backlog item
    ("backlog_items", "start_date DATE"),
    ("backlog_items", "end_date DATE"),
    # Actuals (Timeline P2): machine-stamped actual dates for the item
    # Gantt's baseline-vs-actual bars (first advance / reaching Done)
    ("backlog_items", "actual_start_date DATE"),
    ("backlog_items", "actual_end_date DATE"),
    # RAID register (R6): one risks table, four kinds + kind fields + lineage
    ("risks", "kind VARCHAR(20) DEFAULT 'Risk' NOT NULL"),
    ("risks", "validation_plan TEXT"),
    ("risks", "resolution TEXT"),
    ("risks", "date_raised TIMESTAMPTZ"),
    ("risks", "needed_by DATE"),
    ("risks", "external_owner VARCHAR(100)"),
    ("risks", "escalated_from_id INTEGER"),
    # Sub-issues on backlog items (R6): self-referencing parent, one level only
    ("backlog_items", "parent_item_id INTEGER"),
]

INDEXES = [
    *((f"idx_{table}_tenant", table, "tenant_id") for table in TENANT_TABLES),
    ("ix_tenants_plan_id", "tenants", "plan_id"),
    ("idx_backlog_tenant_project", "backlog_items", "tenant_id, project_id"),
    ("idx_releases_tenant_project", "releases", "tenant_id, project_id"),
    ("idx_stakeholders_tenant_project", "stakeholders", "tenant_id, project_id"),
    ("idx_kpis_tenant_project", "kpis", "tenant_id, project_id"),
    ("idx_notifications_tenant_user", "notifications", "tenant_id, user_id"),
    # Unique per-tenant setting keys — prevents duplicate rows from
    # concurrent query-then-insert races in set_setting().
    ("uq_tenant_settings_key", "tenant_settings", "tenant_id, key"),
    # Hot-path indexes (Rethink v2 Phase A — a7c2e9f41d05): Postgres does not
    # auto-index FKs, so the hottest read paths (rail counts, coverage %,
    # gates aging, decisions-by-project, My Tasks, bundling, portfolio
    # triage) would scan at 10k rows/tenant without these.
    ("ix_backlog_items_project_id", "backlog_items", "project_id"),
    ("ix_backlog_items_current_phase", "backlog_items", "current_phase"),
    ("ix_approval_steps_request_id", "approval_steps", "request_id"),
    ("ix_approval_steps_status", "approval_steps", "status"),
    ("ix_decision_records_project_created", "decision_records", "project_id, made_at"),
    ("ix_user_tasks_assigned_to", "user_tasks", "assigned_to"),
    ("ix_kpis_project_id", "kpis", "project_id"),
    ("ix_release_items_release_id", "release_items", "release_id"),
    ("ix_projects_status", "projects", "status"),
]

# FK constraints that must allow project deletion: nullable audit columns get
# ON DELETE SET NULL on the live DB (create_all doesn't ALTER existing FKs).
# (table, constraint_name, column)
FK_SET_NULL = [
    ("activity_logs", "activity_logs_project_id_fkey", "project_id"),
    ("notifications", "notifications_project_id_fkey", "project_id"),
]

# Project-owned records deleted WITH the project — project_id is NOT NULL, so
# SET NULL would violate it; these get ON DELETE CASCADE.
FK_CASCADE = [
    ("risks", "risks_project_id_fkey", "project_id"),
]

# Self-referencing parent links the live DB was built without: the columns
# were added by _add_missing_columns() as bare INTEGERs before the models
# declared the FKs, and create_all never ALTERs existing tables to attach
# constraints — so sub-issue / sub-task / escalation links had no referential
# integrity. ondelete matches the model declarations.
# (table, column, ondelete)
SELF_REF_FKS = [
    ("backlog_items", "parent_item_id", "CASCADE"),
    ("risks", "escalated_from_id", "SET NULL"),
    ("user_tasks", "parent_task_id", "CASCADE"),
]


def _add_missing_columns() -> None:
    for table, column_def in COLUMNS:
        inspector = inspect(engine)
        column = column_def.split()[0]
        if not inspector.has_table(table):
            continue
        if column in {item["name"] for item in inspector.get_columns(table)}:
            continue
        with engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column_def}"))
        logger.info("Added column %s.%s", table, column)


def _add_missing_indexes() -> None:
    for index_name, table, columns in INDEXES:
        inspector = inspect(engine)
        if not inspector.has_table(table):
            continue
        if index_name in {item["name"] for item in inspector.get_indexes(table)}:
            continue
        with engine.begin() as connection:
            connection.execute(text(f"CREATE INDEX {index_name} ON {table} ({columns})"))
        logger.info("Created index %s", index_name)


def _ensure_reference_data() -> None:
    from app.models.plan import Plan
    from app.models.tenant import Tenant
    from app.seed import DEFAULT_PLANS

    db = SessionLocal()
    try:
        for plan_data in DEFAULT_PLANS:
            if not db.query(Plan).filter(Plan.name == plan_data["name"]).first():
                db.add(Plan(**plan_data))
        db.flush()

        enterprise_plan = db.query(Plan).filter(Plan.name == "Enterprise").first()
        if enterprise_plan:
            for tenant in db.query(Tenant).filter(Tenant.plan_id.is_(None)).all():
                if (tenant.plan or "").lower() == "enterprise":
                    tenant.plan_id = enterprise_plan.id
                    tenant.limits = json.dumps({
                        "max_users": enterprise_plan.max_users,
                        "max_projects": enterprise_plan.max_projects,
                        "max_clients": enterprise_plan.max_clients,
                        "max_releases": enterprise_plan.max_releases,
                        "max_backlog_items": enterprise_plan.max_backlog_items,
                    })
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _fix_project_delete_fks() -> None:
    """Drop and recreate audit FKs with ON DELETE SET NULL (idempotent).

    Deleting a project 500'd with ForeignKeyViolation when the project had
    ActivityLog or Notification rows — the FKs had no ondelete behavior.
    Only touches Postgres (SQLite doesn't enforce these names).
    """
    if engine.dialect.name != "postgresql":
        return
    inspector = inspect(engine)
    for table, constraint, column in FK_SET_NULL:
        if not inspector.has_table(table):
            continue
        fks = {fk["name"]: fk for fk in inspector.get_foreign_keys(table)}
        # Constraint exists already with ON DELETE SET NULL → nothing to do
        # (get_foreign_keys reports ondelete under options, not at top level)
        existing = fks.get(constraint)
        if existing and (existing.get("options") or {}).get("ondelete", "").upper() == "SET NULL":
            continue
        with engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}"))
            connection.execute(text(
                f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
                f"FOREIGN KEY ({column}) REFERENCES projects(id) ON DELETE SET NULL"
            ))
        logger.info("Recreated %s with ON DELETE SET NULL", constraint)


def _fix_project_cascade_fks() -> None:
    """Drop and recreate the RAID register FK with ON DELETE CASCADE (idempotent).

    Deleting a project 500'd with ForeignKeyViolation when the project had
    risks — risks_project_id_fkey had no ondelete behavior. Only touches
    Postgres (SQLite doesn't enforce these names).
    """
    if engine.dialect.name != "postgresql":
        return
    inspector = inspect(engine)
    for table, constraint, column in FK_CASCADE:
        if not inspector.has_table(table):
            continue
        fks = {fk["name"]: fk for fk in inspector.get_foreign_keys(table)}
        # Constraint exists already with ON DELETE CASCADE → nothing to do
        # (get_foreign_keys reports ondelete under options, not at top level)
        existing = fks.get(constraint)
        if existing and (existing.get("options") or {}).get("ondelete", "").upper() == "CASCADE":
            continue
        with engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}"))
            connection.execute(text(
                f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
                f"FOREIGN KEY ({column}) REFERENCES projects(id) ON DELETE CASCADE"
            ))
        logger.info("Recreated %s with ON DELETE CASCADE", constraint)


def _add_missing_self_ref_fks() -> None:
    """Add the self-referencing parent FKs the live DB is missing (idempotent).

    Only touches Postgres (SQLite doesn't enforce these constraint names).
    Adding the FK validates existing data — orphaned parent links would fail
    the migration loudly instead of staying silent.
    """
    if engine.dialect.name != "postgresql":
        return
    inspector = inspect(engine)
    for table, column, ondelete in SELF_REF_FKS:
        if not inspector.has_table(table):
            continue
        constraint = f"{table}_{column}_fkey"
        matched = False
        for fk in inspector.get_foreign_keys(table):
            if column not in fk.get("constrained_columns", []):
                continue
            if fk.get("referred_table") != table:
                continue
            if (fk.get("options") or {}).get("ondelete", "").upper() == ondelete:
                matched = True
                break
        if matched:
            continue
        with engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}"))
            connection.execute(text(
                f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
                f"FOREIGN KEY ({column}) REFERENCES {table}(id) ON DELETE {ondelete}"
            ))
        logger.info("Recreated %s with ON DELETE %s", constraint, ondelete)


def run_migrations() -> None:
    """Apply every known migration; safe to run more than once."""
    Base.metadata.create_all(bind=engine)
    _add_missing_columns()
    _add_missing_indexes()
    _add_missing_self_ref_fks()
    _fix_project_delete_fks()
    _fix_project_cascade_fks()
    _ensure_reference_data()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logger.info("Starting PMO database migrations")
    run_migrations()
    logger.info("PMO database migrations completed successfully")
