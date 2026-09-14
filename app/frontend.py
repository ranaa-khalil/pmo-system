"""
PMO System — Frontend UI
A clean, modern single-page app served by FastAPI.
Uses Tailwind CSS + Alpine.js for reactivity.
"""
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
    response = templates.TemplateResponse(request=request, name="index.html")
    # Prevent browser caching — always serve the latest version
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["X-PMO-Version"] = datetime.now().strftime("%Y%m%d%H%M%S")
    return response
