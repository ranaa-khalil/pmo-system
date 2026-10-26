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
]

COLUMNS = [
    ("github_board_configs", "project_url VARCHAR(500)"),
    ("users", "active_tenant_id INTEGER"),
    ("users", "token_version INTEGER NOT NULL DEFAULT 0"),
    ("projects", "project_type VARCHAR(50) NOT NULL DEFAULT 'software'"),
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
]

# FK constraints that must allow project deletion: nullable audit columns get
# ON DELETE SET NULL on the live DB (create_all doesn't ALTER existing FKs).
# (table, constraint_name, column)
FK_SET_NULL = [
    ("activity_logs", "activity_logs_project_id_fkey", "project_id"),
    ("notifications", "notifications_project_id_fkey", "project_id"),
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
        existing = fks.get(constraint)
        if existing and (existing.get("ondelete") or "").upper() == "SET NULL":
            continue
        with engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}"))
            connection.execute(text(
                f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
                f"FOREIGN KEY ({column}) REFERENCES projects(id) ON DELETE SET NULL"
            ))
        logger.info("Recreated %s with ON DELETE SET NULL", constraint)


def run_migrations() -> None:
    """Apply every known migration; safe to run more than once."""
    Base.metadata.create_all(bind=engine)
    _add_missing_columns()
    _add_missing_indexes()
    _fix_project_delete_fks()
    _ensure_reference_data()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logger.info("Starting PMO database migrations")
    run_migrations()
    logger.info("PMO database migrations completed successfully")
