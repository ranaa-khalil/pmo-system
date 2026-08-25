"""FastAPI application entry point."""
import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from app.config import settings
from app.database import Base, engine, SessionLocal
from app.routers import clients, projects, auth, planning, backlog, forms, approvals, dashboard, stakeholders, releases, user_tasks, personas
from app.frontend import router as frontend_router
import app.models  # noqa: F401 — register all models

logger = logging.getLogger("app.main")

# Create tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.app_name,
    description="Project Management Office system for OPEX",
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
