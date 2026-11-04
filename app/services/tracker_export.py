"""Build-tracker xlsx export (Bayan Build Tracker parity).

Produces a workbook like the user's own tracker:
  * Features sheet — one row per Feature item with ID, Epic, Feature, Used by,
    Personas, Depends on, Needed by, Goal, Check 1..4 results, Build tasks
    done, Checks passed, Progress, Status, Owner, Notes
  * Checklist sheet — build tasks (sub-items) keyed by feature with status
Styled per the professional patterns (navy headers, Carlito font).
"""
import io
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

NAVY = "17324D"
SECTION_BLUE = "2F75B5"
LIGHT_BLUE = "D9EAF7"
INPUT_YELLOW = "FFF2CC"
PASS_GREEN = "E2EFDA"
FAIL_RED = "FCE4E4"
FONT = "Carlito"

HEADER_FILL = PatternFill("solid", fgColor=NAVY)
HEADER_FONT = Font(name=FONT, size=11, bold=True, color="FFFFFF")
TITLE_FILL = PatternFill("solid", fgColor=NAVY)
TITLE_FONT = Font(name=FONT, size=14, bold=True, color="FFFFFF")
THIN = Side(style="thin", color="B0B8C0")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

FEATURE_COLS = [
    ("ID", 8), ("Epic", 22), ("Feature", 34), ("Used by", 14), ("Personas", 22),
    ("Depends on", 14), ("Needed by", 14), ("Goal", 40),
    ("Check 1", 14), ("Check 2", 14), ("Check 3", 14), ("Check 4", 14),
    ("Build tasks done", 12), ("Checks passed", 12), ("Progress", 10),
    ("Status", 12), ("Owner", 14), ("Notes", 28),
]


def _style_header(ws, row, cols):
    for i in range(1, cols + 1):
        c = ws.cell(row=row, column=i)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BORDER


def _result_fill(result):
    if result == "Pass":
        return PatternFill("solid", fgColor=PASS_GREEN)
    if result == "Fail":
        return PatternFill("solid", fgColor=FAIL_RED)
    return PatternFill("solid", fgColor=INPUT_YELLOW)


def build_tracker_workbook(project_name: str, features: list[dict], checks_by_item: dict[int, list[dict]], tasks_by_item: dict[int, list[dict]], owner_names: dict[int, str]) -> bytes:
    """Build the tracker workbook and return the bytes."""
    wb = Workbook()

    # ---- Features sheet ----
    ws = wb.active
    ws.title = "Features"
    ws.cell(row=1, column=1, value=f"{project_name} — Features — build tracker")
    ws.cell(row=1, column=1).fill = TITLE_FILL
    ws.cell(row=1, column=1).font = TITLE_FONT
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(FEATURE_COLS))
    ws.row_dimensions[1].height = 30
    ws.cell(row=2, column=1, value=f"{len(features)} features · exported {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    ws.cell(row=2, column=1).font = Font(name=FONT, size=10, italic=True, color="606070")

    header_row = 3
    for i, (name, width) in enumerate(FEATURE_COLS, start=1):
        ws.cell(row=header_row, column=i, value=name)
        ws.column_dimensions[get_column_letter(i)].width = width
    _style_header(ws, header_row, len(FEATURE_COLS))
    ws.freeze_panes = ws.cell(row=header_row + 1, column=4)

    r = header_row + 1
    for f in features:
        checks = checks_by_item.get(f["id"], [])
        check_results = [c["result"] for c in checks[:4]]
        while len(check_results) < 4:
            check_results.append(None)
        owner = owner_names.get(f.get("owner"), "")
        row_vals = [
            f"F{f['id']}", f.get("epic") or "", f.get("title") or "",
            f.get("used_by") or "", f.get("personas") or "",
            ", ".join(f"F{i}" for i in f.get("depends_on", [])) or "—",
            ", ".join(f"F{i}" for i in f.get("needed_by", [])) or "—",
            f.get("goal") or "",
            *check_results,
            f"{f.get('tasks_done', 0)}/{f.get('tasks_total', 0)}",
            f"{f.get('checks_passed', 0)}/{f.get('checks_total', 0)}",
            round((f.get("progress") or 0) * 100, 0) / 100,
            f.get("status") or "", owner, "",
        ]
        for i, val in enumerate(row_vals, start=1):
            c = ws.cell(row=r, column=i, value=val)
            c.font = Font(name=FONT, size=10)
            c.border = BORDER
            c.alignment = Alignment(vertical="center", wrap_text=(i in (3, 8, 18)))
            col_name = FEATURE_COLS[i - 1][0]
            if col_name.startswith("Check") and val:
                c.fill = _result_fill(val)
                c.alignment = Alignment(horizontal="center", vertical="center")
            if col_name == "Progress":
                c.number_format = "0%"
            if col_name == "Status" and val == "Done":
                c.fill = PatternFill("solid", fgColor=PASS_GREEN)
        r += 1

    # ---- Checklist sheet ----
    ws2 = wb.create_sheet("Checklist")
    ws2.cell(row=1, column=1, value=f"{project_name} — Build tasks (Checklist)")
    ws2.cell(row=1, column=1).fill = TITLE_FILL
    ws2.cell(row=1, column=1).font = TITLE_FONT
    ws2.merge_cells(start_row=1, start_column=1, end_row=1, end_column=6)
    ws2.row_dimensions[1].height = 30

    checklist_cols = [("Feature", 22), ("#", 5), ("Build task", 52), ("Status", 12), ("Owner", 14), ("Notes", 24)]
    for i, (name, width) in enumerate(checklist_cols, start=1):
        ws2.cell(row=2, column=i, value=name)
        ws2.column_dimensions[get_column_letter(i)].width = width
    _style_header(ws2, 2, len(checklist_cols))
    ws2.freeze_panes = "A4"

    title_by_id = {f["id"]: f.get("title") or f"F{f['id']}" for f in features}
    r2 = 3
    for f in features:
        tasks = tasks_by_item.get(f["id"], [])
        for t in tasks:
            vals = [
                title_by_id.get(t["parent_item_id"], ""), t["check_order" if "check_order" in t else "order"],
                t.get("title") or "", t.get("status") or "",
                owner_names.get(t.get("assigned_to"), ""), "",
            ]
            for i, val in enumerate(vals, start=1):
                c = ws2.cell(row=r2, column=i, value=val)
                c.font = Font(name=FONT, size=10)
                c.border = BORDER
                if i == 4 and val == "Done":
                    c.fill = PatternFill("solid", fgColor=PASS_GREEN)
            r2 += 1
    if r2 == 3:
        ws2.cell(row=3, column=1, value="No build tasks yet — add sub-items to features.")
        ws2.cell(row=3, column=1).font = Font(name=FONT, size=10, italic=True, color="808080")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
