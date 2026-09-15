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
from app.routers import (
    ai,
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

# CORS — allow the frontend and AI agents to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
