"""FastAPI application entry point."""
from fastapi import FastAPI
from app.config import settings
from app.routers import clients, projects

app = FastAPI(
    title=settings.app_name,
    description="Project Management Office system for OPEX",
    version="0.1.0",
)

# Register routers
app.include_router(clients.router)
app.include_router(projects.router)


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "app": settings.app_name}
