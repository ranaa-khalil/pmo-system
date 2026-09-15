"""
PMO System — Frontend UI
A clean, modern single-page app served by FastAPI.
Uses Tailwind CSS + Alpine.js for reactivity.
"""
import json as _json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["ui"])

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page — SPA entry point."""
    # Get tenant branding from subdomain middleware (if any)
    branding = getattr(request.state, "tenant_branding", None) or {}
    tenant_slug = getattr(request.state, "tenant_slug", None) or ""

    response = templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "tenant_branding": branding,
            "tenant_slug": tenant_slug,
        },
    )
    # Prevent browser caching — always serve the latest version
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["X-PMO-Version"] = datetime.now().strftime("%Y%m%d%H%M%S")
    return response


@router.get("/api/branding")
async def get_branding(request: Request):
    """Public endpoint returning tenant branding for the current subdomain."""
    branding = getattr(request.state, "tenant_branding", None)
    if branding:
        return branding
    return {"slug": "", "name": "", "logo_url": "", "primary_color": "", "app_name": "", "hide_powered_by": False}
