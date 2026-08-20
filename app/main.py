"""FastAPI application entry point."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import Base, engine
from app.routers import clients, projects, auth, planning
from app.frontend import router as frontend_router
import app.models  # noqa: F401 — register all models

# Create tables on startup (for dev; use Alembic migrations in prod)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.app_name,
    description="Project Management Office system for OPEX",
    version="0.1.0",
)

# CORS — allow the frontend and AI agents to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routers
app.include_router(auth.router)
app.include_router(clients.router)
app.include_router(projects.router)
app.include_router(planning.router)

# Register frontend UI
app.include_router(frontend_router)


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "app": settings.app_name}
