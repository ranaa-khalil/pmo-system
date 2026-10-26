"""FastAPI application entry point."""
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import app.models  # noqa: F401 — register all models
from app.config import settings
from app.database import SessionLocal
from app.frontend import router as frontend_router
from app.middleware import QuotaHeaderMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware, SubdomainMiddleware
from app.migrate import run_migrations
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
    infrastructure,
    lifecycle,
    notifications,
    personas,
    planning,
    projects,
    releases,
    risks,
    stakeholders,
    tenant,
    user_tasks,
)

logger = logging.getLogger("app.main")

# Keep startup migration for compatibility. Production deployments can run the
# same migration explicitly first with `python -m app.migrate`.
run_migrations()

app = FastAPI(
    title=settings.app_name,
    description="Project Management Office system for Obelion",
    version="0.1.0",
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

# Serve static files (JS/CSS) locally — no CDN dependency
static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# Serve uploaded files (tenant logos, etc.)
uploads_path = Path(__file__).parent.parent / "uploads"
uploads_path.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_path)), name="uploads")

# CORS — restrict in production, allow all in development
if settings.is_production:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.app_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
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
app.include_router(lifecycle.router)
app.include_router(risks.router)
app.include_router(github_sync.router)
app.include_router(api_keys.router)
app.include_router(analytics.router)
app.include_router(infrastructure.router)

# Register frontend UI
app.include_router(frontend_router)


@app.on_event("startup")
def auto_seed_on_startup():
    """Auto-seed the database on first run / each deploy on ephemeral filesystems."""
    # Production safety checks
    if settings.is_production and settings.has_default_secret:
        logger.warning("⚠️  SECRET_KEY is still the default! Change it in .env immediately.")
    if settings.is_production and settings.debug:
        logger.warning("⚠️  DEBUG is True in production! Set PMO_DEBUG=false in .env.")

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


@app.on_event("startup")
async def start_rate_limiter_cleanup():
    """Periodically prune the in-memory rate limiter to prevent memory growth.

    Sliding-window buckets accumulate one key per unique tenant/IP; without a
    sweep they are never freed. Runs every 10 minutes in the background.
    """
    import asyncio

    from app.middleware.rate_limit import rate_limiter

    async def _cleanup_loop():
        while True:
            await asyncio.sleep(600)
            try:
                rate_limiter.cleanup()
            except Exception as e:  # pragma: no cover — never kill the loop
                logger.warning(f"Rate limiter cleanup error: {e}")

    asyncio.create_task(_cleanup_loop())


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "app": settings.app_name}
