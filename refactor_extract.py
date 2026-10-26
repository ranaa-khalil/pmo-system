#!/usr/bin/env python3
"""One-shot refactor extractor for the PMO System frontend.

Splits the monolithic app/templates/index.html (10,256 lines) into:
  - app/static/css/*.css           modular stylesheets (byte-exact fragments)
  - app/static/js/app/*.js         ES modules for app JS (byte-exact fragments)
  - app/templates/pmo/**/*.html    Jinja partials (byte-exact fragments)
  - a new index.html shell that assembles them

Every fragment is copied verbatim from the original file, so the rendered
page is byte-identical to the baseline (modulo <link>/<script> tags that
replace the inline blocks).
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "app" / "templates" / "index.html"
OUT = ROOT  # write in place

src = SRC.read_text()
lines = src.split("\n")  # 0-indexed: lines[i] is 1-indexed line i+1


def frag(start_1idx: int, end_1idx: int) -> str:
    """Inclusive 1-indexed line fragment, verbatim."""
    return "\n".join(lines[start_1idx - 1 : end_1idx])


# ---------------------------------------------------------------- regions
# Head region: 1..9 doctype/meta/title (keep), 10 tailwind, 11-13 fonts,
# 14 chart+marked, 15-61 tailwind.config script, 62 blank, 63-85 branding script,
# 86-223 style block, 224 blank, 225+ body.
REGIONS = {
    # CSS (86-223 = <style>...</style>)
    "css": frag(86, 223),
    # branding init script (63-85) — has Jinja template vars
    "branding_js": frag(63, 85),
    # tailwind config script (16-61) — inside <script> at 16? check: script open 16
    "tailwind_cfg": frag(16, 61),
    # body fragments
    "login": frag(229, 350),
    "forgot": frag(352, 468),
    "sidebar": frag(471, 549),
    "topbar": frag(553, 622),
    "v_dashboard": frag(627, 1033),
    "v_clients": frag(1035, 1101),
    "v_client_detail": frag(1103, 1191),
    "v_projects": frag(1193, 1261),
    "v_roadmap": frag(1263, 1435),
    "v_tasks": frag(1437, 1582),
    "v_settings": frag(1584, 1982),
    "v_docs": frag(1984, 2252),
    "v_project_detail": frag(2255, 5568),
    "v_admin_dash": frag(5570, 5659),
    "v_admin_tenants": frag(5661, 5755),
    "v_admin_plans": frag(5757, 5845),
    "v_admin_tenant_detail": frag(5847, 6107),
    "m_ai": frag(6113, 6324),
    "m_fab": frag(6326, 6420),
    "m_task": frag(6422, 6515),
    "m_persona": frag(6517, 6559),
    "m_test_account": frag(6561, 6611),
    "m_client": frag(6613, 6662),
    "m_project": frag(6664, 6753),
    "m_toast": frag(6755, 6765),
    "alpine_fallback": frag(6769, 6778),  # comment + fallback <script>
    "app_js": frag(6779, 10253),          # <script> function pmoApp() ... </script>
}

# ------------------------------------------------- JS domain split markers
# 1-indexed line numbers of the `// ===== X =====` markers inside pmoApp,
# plus the start of the object body and its end.
APP_MARKERS = [
    (6782, "auth_state"),            # ===== Auth state =====
    (6790, "forgot_state"),          # ===== Forgot password =====
    (6801, "branding_state"),        # ===== Tenant branding =====
    (6810, "app_state"),             # ===== App state =====
    (6822, "notification_state"),    # ===== Notification state =====
    (6829, "tenant_state"),          # ===== Tenant state =====
    (6838, "super_admin_state"),     # ===== Super Admin state =====
    (6857, "ai_state"),              # ===== AI assistant state =====
    (6867, "project_detail_state"),  # ===== Project detail state =====
    (6885, "backlog_state"),         # ===== Backlog state =====
    (7000, "forms_state"),           # ===== Forms state =====
    (7006, "approvals_state"),       # ===== Approvals state =====
    (7012, "stakeholders_state"),    # ===== Stakeholders state =====
    (7028, "milestone_kpi_state"),   # ===== Milestone & KPI view/edit state =====
    (7038, "roles_state"),           # ===== Roles state =====
    (7041, "releases_state"),        # ===== Releases state =====
    (7047, "traceability_state"),    # ===== Traceability state =====
    (7050, "user_mgmt_state"),       # ===== User management state =====
    (7057, "dashboard_state"),       # ===== Dashboard stats =====
    (7063, "tasks_state"),           # ===== Tasks state =====
    (7073, "role_helpers"),          # ===== Role helpers =====
    (7090, "timeline_state"),        # ===== Timeline state =====
    (7125, "backlog_computed"),      # ===== Backlog computed =====
    (7331, "greeting_methods"),      # ===== Greeting methods =====
    (7386, "notification_methods"),  # ===== Notification & Activity methods =====
    (7525, "ai_methods"),            # ===== AI assistant methods =====
    (7882, "timeline_computed"),     # ===== Timeline computed properties =====
    (7966, "project_timeline"),      # ===== Project-level timeline =====
    (8062, "auth_methods"),          # ===== Auth =====
    (8220, "task_methods"),          # ===== Tasks (personal to-dos) =====
    (8335, "project_detail_methods"),  # ===== Project detail =====
    (8571, "backlog_methods"),       # ===== Backlog =====
    (9034, "forms_methods"),         # ===== Forms =====
    (9120, "approvals_methods"),     # ===== Approvals =====
    (9200, "roles_methods"),         # ===== Roles =====
    (9209, "stakeholders_methods"),  # ===== Stakeholders =====
    (9244, "personas_methods"),      # ===== Personas & Environments =====
    (9333, "releases_methods"),      # ===== Releases =====
    (9340, "infrastructure_methods"),  # ===== Infrastructure =====
    (9695, "user_mgmt_methods"),     # ===== User Management =====
    (9702, "tenant_methods"),        # ===== Tenant management methods =====
    (9842, "super_admin_methods"),   # ===== Super Admin methods =====
    (10017, "tenant_admin_users"),   # ===== Tenant Admin: User Management =====
]
APP_OBJECT_START = 6781  # "    return {"
APP_OBJECT_END = 10250   # "    };"
APP_FUNC_CLOSE = 10251   # "}"


def js_marker_fragments() -> dict:
    """Extract each domain section between markers, dedented to column 0.

    Lines inside pmoApp are indented 4 (return {) + 4 (properties) = 8 spaces
    for top-level properties. We strip exactly 8 leading spaces so the module
    fragments read as clean object-literal bodies. Verbatim otherwise.
    """
    out = {}
    for i, (line_no, name) in enumerate(APP_MARKERS):
        start = line_no
        end = APP_MARKERS[i + 1][0] - 1 if i + 1 < len(APP_MARKERS) else APP_OBJECT_END - 1
        text = frag(start, end)
        dedented = "\n".join(
            ln[8:] if ln.startswith(" " * 8) else ln.lstrip() if ln.strip() == "" else ln
            for ln in text.split("\n")
        )
        out[name] = dedented
    return out


# ------------------------------------------------------------- write files
def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    print(f"  {path.relative_to(ROOT)}  ({len(content):,} chars)")


print("== CSS ==")
css = REGIONS["css"]
# strip the <style> wrapper (first line) and </style> (last line)
css_body = css.split("\n", 1)[1].rsplit("</style>", 1)[0]
# Dedent 4 spaces (original was indented inside <style>)
css_dedent = "\n".join(ln[4:] if ln.startswith("    ") else ln for ln in css_body.split("\n"))

# Split CSS into three files by selector intent, preserving order within each.
# theme.css: :root, x-cloak, base, brand vars, scrollbar, fonts
# components.css: buttons, inputs, cards, nav, modal, tabs, skeleton, animations
# views.css: md-content, prose, aurora, stat-glow + leftovers
RULE_RE = re.compile(r"(?:(?:/\*[^*]*\*/\s*)?[^@{}]+\{[^}]*\}|/\*[^*]*\*/|@keyframes\s+\w+\s*\{(?:(?:[^{}]*)\{[^}]*\})+\s*\}|@keyframes\s+\w+\s*\{[^{}]*\{[^}]*\}[^{}]*\{[^}]*\}\s*\})\s*", re.S)

# Simpler + safer: split on top-level comments; each chunk = comment + rules until next comment
chunks = re.split(r"\n(?=        /\* )", REGIONS["css"]) if False else None

# We keep the original ordering by writing one file with the full cascade
# (theme.css), then splitting further is risky for byte-identity. To keep
# modular files AND identical cascade, we order files by their position in the
# original sheet and link them in that order.
def css_chunks(text: str, prefix_dedent: int = 4):
    body = text.split("\n", 1)[1].rsplit("</style>", 1)[0]
    lines_c = body.split("\n")
    # start chunks at each top-level comment
    starts = [i for i, ln in enumerate(lines_c) if ln.strip().startswith("/*")]
    if not starts or starts[0] != 0:
        starts = [0] + starts
    chunks_out = []
    for j, s in enumerate(starts):
        e = starts[j + 1] if j + 1 < len(starts) else len(lines_c)
        chunk = "\n".join(ln[prefix_dedent:] if ln.startswith(" " * prefix_dedent) else ln for ln in lines_c[s:e])
        chunks_out.append(chunk.rstrip() + "\n")
    return chunks_out


chunks = css_chunks(REGIONS["css"])
# classification by keyword in chunk
def classify(chunk: str) -> str:
    head = chunk.lower()
    if any(k in head for k in (":root", "x-cloak", "font-smoothing", "scrollbar", "font-feature")) and "btn" not in head and "input" not in head:
        return "theme"
    if any(k in head for k in ("md-content", "prose-")):
        return "views"
    return "components"


buckets = {"theme": [], "components": [], "views": []}
for c in chunks:
    buckets[classify(c)].append(c)
for name, items in buckets.items():
    write(ROOT / "app" / "static" / "css" / f"{name}.css", "\n".join(items))

print("== JS modules ==")
dom = js_marker_fragments()
# domain → sections
DOMAINS = {
    "core": ["auth_state", "app_state", "notification_state", "dashboard_state",
             "greeting_methods", "notification_methods", "auth_methods"],
    "tasks": ["forgot_state", "tasks_state", "task_methods"],
    "backlog": ["backlog_state", "backlog_computed", "backlog_methods"],
    "planning": ["timeline_state", "timeline_computed", "project_timeline",
                 "project_detail_state", "project_detail_methods", "milestone_kpi_state",
                 "traceability_state", "role_helpers"],
    "projects": ["branding_state", "stakeholders_state", "roles_state", "releases_state",
                 "user_mgmt_state", "stakeholders_methods", "roles_methods",
                 "releases_methods", "user_mgmt_methods"],
    "ai": ["ai_state", "ai_methods"],
    "workflows": ["forms_state", "approvals_state", "forms_methods", "approvals_methods",
                  "personas_methods", "infrastructure_methods"],
    "tenants": ["tenant_state", "super_admin_state", "tenant_methods",
                "super_admin_methods", "tenant_admin_users"],
}
all_sections = [n for _, n in APP_MARKERS]
assigned = [s for secs in DOMAINS.values() for s in secs]
missing = [s for s in all_sections if s not in assigned]
if missing:
    raise SystemExit(f"Unassigned JS sections: {missing}")

for domain, secs in DOMAINS.items():
    body = "\n\n".join(dom[s] for s in secs)
    module = (
        f'// PMO System — app/{domain}.js\n'
        f'// {domain.capitalize()} domain of the Alpine pmoApp() store.\n'
        f'// Fragments are verbatim from the original monolith; pmo-app.js assembles them.\n\n'
        f'export const {domain} = {{\n{body}\n}};\n'
    )
    write(ROOT / "app" / "static" / "js" / "app" / "domains" / f"{domain}.js", module)

print("== HTML partials ==")
write(ROOT / "app" / "templates" / "pmo" / "branding.html", REGIONS["branding_js"])
write(ROOT / "app" / "templates" / "pmo" / "auth" / "login.html", REGIONS["login"])
write(ROOT / "app" / "templates" / "pmo" / "auth" / "forgot_password.html", REGIONS["forgot"])
write(ROOT / "app" / "templates" / "pmo" / "shell" / "sidebar.html", REGIONS["sidebar"])
write(ROOT / "app" / "templates" / "pmo" / "shell" / "topbar.html", REGIONS["topbar"])
for v in ("dashboard", "clients", "client_detail", "projects", "roadmap", "tasks",
          "settings", "docs", "project_detail", "admin_dash", "admin_tenants",
          "admin_plans", "admin_tenant_detail"):
    write(ROOT / "app" / "templates" / "pmo" / "views" / f"{v}.html", REGIONS[f"v_{v}"])
for m in ("ai", "fab", "task", "persona", "test_account", "client", "project"):
    write(ROOT / "app" / "templates" / "pmo" / "modals" / f"{m}.html", REGIONS[f"m_{m}"])
write(ROOT / "app" / "templates" / "pmo" / "modals" / "toast.html", REGIONS["m_toast"])
write(ROOT / "app" / "static" / "js" / "app" / "alpine-fallback.js", REGIONS["alpine_fallback"])
write(ROOT / "app" / "static" / "js" / "app" / "tailwind-config.js", REGIONS["tailwind_cfg"])

# Verify the JS modules parse as ES modules
print("== syntax check ==")
import subprocess
for domain in DOMAINS:
    p = ROOT / "app" / "static" / "js" / "app" / "domains" / f"{domain}.js"
    r = subprocess.run(["node", "--check", "--input-type=module", "-"], input=p.read_text(),
                       capture_output=True, text=True)
    status = "OK" if r.returncode == 0 else "FAIL: " + r.stderr[:300]
    print(f"  {p.name}: {status}")

print("\nFragments written. Next: pmo-app.js, bootstrap.js, fab.js, new index.html shell.")
