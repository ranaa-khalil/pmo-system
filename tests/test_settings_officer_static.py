"""Static analysis of the Slice 6 officer settings screen (route 10).

The settings view (templates/pmo/views/settings.html, route === 'settings')
carries the Officer section: the rules master switch (one click →
PUT /api/officer/rules), the Scan now button (POST /api/officer/scan), the
display-only digest schedule, and last-run info from GET /api/officer/status.
Its JS lives in static/js/app/domains/tenants.js and must call the SAME
endpoints the API tests prove behave (test_officer_rules_toggle.py).
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SETTINGS = REPO / "app/templates/pmo/views/settings.html"
TENANTS_JS = REPO / "app/static/js/app/domains/tenants.js"
CORE_JS = REPO / "app/static/js/app/domains/core.js"
INDEX = REPO / "app/templates/index.html"


def _read(path: Path) -> str:
    assert path.exists(), f"{path.name} missing"
    return path.read_text(encoding="utf-8")


def test_settings_screen_has_the_officer_section():
    """The route-10 chip lives inside the settings view's tenant tab."""
    src = _read(SETTINGS)
    officer = re.search(
        r'<!-- Officer card \(Unified System v2 §2 route 10.*?</div>\s*<!-- Tenant General card -->',
        src, re.S,
    )
    assert officer, "Officer section missing from settings.html"


def test_officer_toggle_calls_the_rules_endpoint():
    """One click off/on → PUT /api/officer/rules."""
    src = _read(SETTINGS)
    assert '@click="toggleOfficerRules()"' in src
    js = _read(TENANTS_JS)
    toggle = re.search(r"async toggleOfficerRules\(\) \{.*?\n\},", js, re.S)
    assert toggle, "toggleOfficerRules missing from tenants.js"
    assert "api('PUT', '/officer/rules', { enabled: target })" in toggle.group(0)


def test_officer_scan_now_calls_the_scan_endpoint():
    """Scan now → POST /api/officer/scan; the UI surfaces evaluated/fired."""
    src = _read(SETTINGS)
    assert '@click="runOfficerScan()"' in src
    assert "officerScanResult.evaluated" in src and "officerScanResult.fired" in src
    js = _read(TENANTS_JS)
    scan = re.search(r"async runOfficerScan\(\) \{.*?\n\},", js, re.S)
    assert scan, "runOfficerScan missing from tenants.js"
    assert "api('POST', '/officer/scan', {})" in scan.group(0)


def test_officer_status_loads_last_runs():
    """Last-run info comes from GET /api/officer/status, loaded on navigate."""
    js = _read(TENANTS_JS)
    load = re.search(r"async loadOfficerStatus\(\) \{.*?\n\},", js, re.S)
    assert load, "loadOfficerStatus missing from tenants.js"
    assert "api('GET', '/officer/status')" in load.group(0)
    assert "officerStatus.rules_enabled" in load.group(0)
    core = _read(CORE_JS)
    assert re.search(
        r"if \(route === 'settings'\) \{.*loadOfficerStatus\(\); \}", core, re.S
    ), "settings navigation must load the officer status"


def test_officer_digest_schedule_is_display_only():
    """The nightly 23:00 / weekly Friday / hourly sweep line has no buttons."""
    src = _read(SETTINGS)
    schedule = re.search(
        r'<!-- Digest schedule \(display-only\) -->(.*?)</div>\s*</div>', src, re.S
    )
    assert schedule, "digest schedule row missing"
    row = schedule.group(1)
    assert "Nightly 23:00" in row and "Weekly Friday 23:05" in row and "hourly" in row
    assert "@click" not in row, "the digest schedule is display-only — no buttons"


def test_officer_section_is_inside_the_settings_route():
    """settings.html rides the route === 'settings' view, included by index."""
    index = _read(INDEX)
    assert "pmo/views/settings.html" in index
    src = _read(SETTINGS)
    assert 'x-show="route === \'settings\'"' in src
    assert 'x-show="settingsTab === \'tenant\' && canManageUsers"' in src


def test_officer_state_defaults_rules_on():
    """Rules ON by default (route 10) — the store's initial state says so."""
    js = _read(TENANTS_JS)
    assert re.search(r"officerRulesOn: true,", js)
    assert re.search(r"officerStatus: null,", js)
    assert re.search(r"officerLastRuns: \[\],", js)
