"""Static analysis of Slice B4 (Rethink v2 Phase B): notification deep-link + briefing dedupe.

The topbar notification rows (templates/pmo/shell/topbar.html) previously
carried only markNotifRead — the model's link field (app/models/notification.py:20
"route to navigate to when clicked") and the API return ship it, but the UI
never navigated. openNotification (static/js/app/domains/core.js) now
deep-links: known route ids (the sidebar's navItems list) via navigate(),
project-scoped links (/projects/<id>/…) via openProjectById — Today's
openWorkItemFromToday pattern.

The dashboard's "Your daily briefing" card (views/dashboard.html) duplicated
Today's Copilot Briefing — one draft, two renderings. Removed: Today owns the
brief, and the dead 'briefing' dashboard-widget key is cleaned from core.js
(no dead picker row). Copilot drawer state in copilot.js is untouched.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOPBAR = REPO / "app/templates/pmo/shell/topbar.html"
CORE_JS = REPO / "app/static/js/app/domains/core.js"
DASHBOARD = REPO / "app/templates/pmo/views/dashboard.html"
TODAY = REPO / "app/templates/pmo/views/today.html"


def _read(path: Path) -> str:
    assert path.exists(), f"{path.name} missing"
    return path.read_text(encoding="utf-8")


def test_notification_rows_call_the_deep_link_handler():
    """Rows click → openNotification(n); the click affordance stays on the row."""
    src = _read(TOPBAR)
    assert '@click="openNotification(n)"' in src
    assert '@click="markNotifRead(n)"' not in src, "the row handler must be the deep-link one"
    row = re.search(r'<template x-for="n in notifications".*?</template>', src, re.S)
    assert row, "notification row loop missing"
    assert "cursor-pointer" in row.group(0) and "hover:bg-ink-50" in row.group(0)


def test_link_rows_carry_a_visible_affordance():
    """Rows with a link show the chevron affordance; it is hidden otherwise."""
    src = _read(TOPBAR)
    row = re.search(r'<template x-for="n in notifications".*?</template>', src, re.S)
    assert row, "notification row loop missing"
    assert 'x-show="n.link"' in row.group(0), "link rows need the chevron affordance"


def test_open_notification_marks_read_and_deep_links():
    """openNotification marks read via markNotifRead, then navigates by link."""
    js = _read(CORE_JS)
    handler = re.search(r"async openNotification\(notif\) \{.*?\n\},", js, re.S)
    assert handler, "openNotification missing from core.js"
    body = handler.group(0)
    assert "markNotifRead(notif)" in body
    assert "this.navigate(route)" in body
    assert "navItems.some" in body, "known route ids come from the sidebar's navItems"


def test_project_links_fall_back_to_the_project_drawer():
    """Project-scoped links use the payload's project_id, else parse /projects/<id>/…."""
    js = _read(CORE_JS)
    handler = re.search(r"async openNotification\(notif\) \{.*?\n\},", js, re.S)
    assert handler, "openNotification missing from core.js"
    body = handler.group(0)
    assert "notif.project_id" in body
    assert "openProjectById" in body


def test_dashboard_briefing_card_is_gone():
    """The duplicated 'Your daily briefing' card is removed — Today owns the brief."""
    src = _read(DASHBOARD)
    assert "Your daily briefing" not in src
    assert "briefingSummary" not in src and "briefingVerdict" not in src
    assert "predictiveFlags" not in src
    assert "dashWidgetVisible('briefing')" not in src
    today = _read(TODAY)
    assert "Copilot Briefing" in today, "Today's briefing must stay"


def test_briefing_widget_key_cleaned_from_core():
    """No dead 'briefing' widget key/label left in core.js — the picker stays honest."""
    js = _read(CORE_JS)
    assert "briefing" not in js, "core.js must not reference the removed briefing widget"
    assert "generateBriefing" not in js, "the login-time briefing call served only the removed card"
