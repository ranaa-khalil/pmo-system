"""
PMO System — Frontend UI
A clean, modern single-page app served by FastAPI.
Uses Tailwind CSS + Alpine.js for reactivity.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

router = APIRouter(tags=["ui"])

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page — SPA entry point."""
    return templates.TemplateResponse("index.html", {"request": request})
