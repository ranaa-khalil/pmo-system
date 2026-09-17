"""FastAPI application entry point."""
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import app.models  # noqa: F401 — register all models
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.frontend import router as frontend_router
from app.middleware import QuotaHeaderMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware, SubdomainMiddleware
from app.routers import (
    ai,
    analytics,
    api_keys,
    approvals,
    auth,
    backlog,
    clients,
    dashboard,
    forms,
    github_sync,
    notifications,
    personas,
    planning,
    projects,
    releases,
    stakeholders,
    tenant,
    user_tasks,
)

logger = logging.getLogger("app.main")

# Create tables on startup
Base.metadata.create_all(bind=engine)

# Tables that should have tenant_id added (all tenant-scoped tables)
_TENANT_TABLES = [
    "clients", "projects", "backlog_items", "releases", "release_items",
    "kpis", "roadmaps", "milestones", "stakeholders", "roles",
    "role_assignments", "role_permissions", "permissions",
    "approval_requests", "approval_steps", "user_tasks",
    "form_templates", "form_instances", "user_personas",
    "project_test_accounts", "project_visions", "github_board_configs",
    "notifications", "notification_preferences", "activity_logs",
]


def _auto_migrate():
    """Add new columns to existing tables."""
    from sqlalchemy import inspect, text
    inspector = inspect(engine)

    def _has_column(table: str, column: str) -> bool:
        return column in [c["name"] for c in inspector.get_columns(table)]

    def _add_column(table: str, column_def: str):
        """Add a column using ALTER TABLE (works for both SQLite and PostgreSQL)."""
        if inspector.has_table(table) and not _has_column(table, column_def.split()[0]):
            conn = engine.connect()
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column_def}"))
                conn.commit()
                logger.info(f"Migrated: added {column_def.split()[0]} to {table}")
            except Exception as e:
                logger.warning(f"Migration skipped for {table}.{column_def.split()[0]}: {e}")
            finally:
                conn.close()

    # Add project_url to github_board_configs (from earlier migration)
    _add_column("github_board_configs", "project_url VARCHAR(500)")

    # Add active_tenant_id to users
    _add_column("users", "active_tenant_id INTEGER")

    # Add tenant_id to all tenant-scoped tables
    for table in _TENANT_TABLES:
        _add_column(table, "tenant_id INTEGER")

    # Add branding column to tenants (Phase 3.2 white-labeling)
    _add_column("tenants", "branding TEXT")

    # Add configurable tenant resource limits
    _add_column("tenants", "limits TEXT")

    # Create indexes on tenant_id for all tenant-scoped tables (Phase 3.6)
    def _has_index(table: str, index_name: str) -> bool:
        if not inspector.has_table(table):
            return True
        return index_name in [i["name"] for i in inspector.get_indexes(table)]

    for table in _TENANT_TABLES:
        idx_name = f"idx_{table}_tenant"
        if not _has_index(table, idx_name):
            conn = engine.connect()
            try:
                conn.execute(text(f"CREATE INDEX {idx_name} ON {table} (tenant_id)"))
                conn.commit()
                logger.info(f"Index created: {idx_name}")
            except Exception as e:
                logger.warning(f"Index skipped for {table}: {e}")
            finally:
                conn.close()

    # Composite indexes for common query patterns
    _composite_indexes = [
        ("idx_backlog_tenant_project", "backlog_items", "tenant_id, project_id"),
        ("idx_releases_tenant_project", "releases", "tenant_id, project_id"),
        ("idx_stakeholders_tenant_project", "stakeholders", "tenant_id, project_id"),
        ("idx_kpis_tenant_project", "kpis", "tenant_id, project_id"),
        ("idx_notifications_tenant_user", "notifications", "tenant_id, user_id"),
    ]
    for idx_name, table, columns in _composite_indexes:
        if not _has_index(table, idx_name) and inspector.has_table(table):
            conn = engine.connect()
            try:
                conn.execute(text(f"CREATE INDEX {idx_name} ON {table} ({columns})"))
                conn.commit()
                logger.info(f"Composite index created: {idx_name}")
            except Exception as e:
                logger.warning(f"Composite index skipped for {table}: {e}")
            finally:
                conn.close()


_auto_migrate()

app = FastAPI(
    title=settings.app_name,
    description="Project Management Office system for Obelion",
    version="0.1.0",
)

# Serve static files (JS/CSS) locally — no CDN dependency
static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# Serve uploaded files (tenant logos, etc.)
uploads_path = Path(__file__).parent.parent / "uploads"
uploads_path.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_path)), name="uploads")

# CORS — allow the frontend and AI agents to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add middleware (order matters: subdomain → security → rate limit → quota)
app.add_middleware(SubdomainMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(QuotaHeaderMiddleware)
app.add_middleware(RateLimitMiddleware)

# Register API routers
app.include_router(auth.router)
app.include_router(tenant.router)
app.include_router(clients.router)
app.include_router(projects.router)
app.include_router(planning.router)
app.include_router(backlog.router)
app.include_router(forms.router)
app.include_router(approvals.router)
app.include_router(dashboard.router)
app.include_router(stakeholders.router)
app.include_router(releases.router)
app.include_router(user_tasks.router)
app.include_router(personas.router)
app.include_router(notifications.router)
app.include_router(ai.router)
app.include_router(github_sync.router)
app.include_router(api_keys.router)
app.include_router(analytics.router)

# Register frontend UI
app.include_router(frontend_router)


@app.on_event("startup")
def auto_seed_on_startup():
    """Auto-seed the database on first run / each deploy on ephemeral filesystems."""
    from app.models.user import User
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            logger.info("No users found — running seed...")
            from app.seed import seed
            seed()
            logger.info("Seed complete.")
        else:
            logger.info("Database already has data — skipping seed.")
    except Exception as e:
        logger.error(f"Auto-seed error: {e}")
    finally:
        db.close()


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "app": settings.app_name}
