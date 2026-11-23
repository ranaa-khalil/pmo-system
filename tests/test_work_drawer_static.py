"""Static analysis of the Slice 3b drawer write layer + capture box (R2 flagship).

The Work drawer (templates/components/item_drawer.html) is the ONE detail
surface: its JS lives in static/js/app/domains/planning.js and must call the
SAME endpoints as the 14-tab modal footer (advance/send-back, PUT, tags,
comments) — one verb vocabulary everywhere. The capture box
(templates/components/capture_box.html) rides the collapsed one-call intake.

Static analysis pairs with the endpoint tests (test_routers/test_ai_intake.py,
test_backlog_api.py): these prove the JS calls the right endpoints, those
prove the endpoints behave.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLANNING = REPO / "app/static/js/app/domains/planning.js"
CAPTURE_BOX = REPO / "app/static/js/app/capture_box.js"
PMO_APP = REPO / "app/static/js/app/pmo-app.js"
WORK = REPO / "app/templates/pmo/views/work.html"
TODAY = REPO / "app/templates/pmo/views/today.html"
DRAWER = REPO / "app/templates/components/item_drawer.html"
CAPTURE_PARTIAL = REPO / "app/templates/components/capture_box.html"
FAB = REPO / "app/templates/pmo/modals/fab.html"


def _read(path: Path) -> str:
    assert path.exists(), f"{path.name} missing"
    return path.read_text(encoding="utf-8")


def test_drawer_calls_the_modal_footer_endpoints():
    """Phase verbs share the modal footer's endpoints — advance + send-back."""
    js = _read(PLANNING)
    assert "api('POST', `/backlog/${id}/advance`)" in js, "drawer advance verb missing"
    assert "api('POST', `/backlog/${id}/send-back`)" in js, "drawer send-back verb missing"
    # The move menu routes a Requirements move through the same send-back verb
    move = re.search(r"async moveWorkItemTo\(phase\) \{.*?\n\},", js, re.S)
    assert move, "moveWorkItemTo missing from planning.js"
    assert "send-back" in move.group(0)
    assert "'advance'" in move.group(0)


def test_drawer_edit_save_calls_the_update_endpoint():
    """Inline edit (§8 rule 4) → PUT /backlog/{id}, the 1-step update."""
    js = _read(PLANNING)
    edit = re.search(r"async saveWorkItemEdit\(\) \{.*?\n\},", js, re.S)
    assert edit, "saveWorkItemEdit missing"
    assert "api('PUT', `/backlog/${id}`" in edit.group(0)
    # Markdown hint on the description field (#N autolinks render via renderMarkdown)
    assert "renderMarkdown(workItemDescription()" in _read(DRAWER)


def test_drawer_tags_call_the_existing_tag_endpoints():
    """The re-hosted tag picker calls the same endpoints as modals/task.html."""
    js = _read(PLANNING)
    attach = re.search(r"async attachWorkItemTag\(tag\) \{.*?\n\},", js, re.S)
    detach = re.search(r"async detachWorkItemTag\(tag\) \{.*?\n\},", js, re.S)
    create = re.search(r"async createWorkTagInline\(\) \{.*?\n\},", js, re.S)
    assert attach and detach and create, "drawer tag methods missing"
    assert "api('POST', `/backlog/${id}/tags`, { tag_id: tag.id })" in attach.group(0)
    assert "api('DELETE', `/backlog/${id}/tags/${tag.id}`)" in detach.group(0)
    assert "api('POST', '/tags'" in create.group(0)


def test_drawer_assignee_calls_the_update_endpoint():
    """The toggle picker assigns through PUT /backlog/{id} (single assignee)."""
    js = _read(PLANNING)
    assign = re.search(r"async setWorkItemAssignee\(userId\) \{.*?\n\},", js, re.S)
    assert assign, "setWorkItemAssignee missing"
    assert "api('PUT', `/backlog/${id}`, { assigned_to: userId })" in assign.group(0)
    assert "assigned_to: null" not in assign.group(0)  # unassign passes userId=null


def test_drawer_comment_thread_calls_the_comment_endpoint():
    """Append-only thread → POST /backlog/{id}/comments; Enter posts."""
    js = _read(PLANNING)
    post = re.search(r"async postWorkItemComment\(\) \{.*?\n\},", js, re.S)
    assert post, "postWorkItemComment missing"
    assert "api('POST', `/backlog/${id}/comments`, { body })" in post.group(0)
    partial = _read(DRAWER)
    assert "@keydown.enter.prevent=\"postWorkItemComment()\"" in partial


def test_drawer_is_a_slide_over_not_a_modal():
    """§8 rule 6: 520px right slide-over, Esc + click-out close, no center modal."""
    partial = _read(DRAWER)
    assert "max-w-[520px]" in partial, "drawer is not the 520px slide-over"
    assert "@keydown.escape.window=\"closeWorkItem()\"" in partial
    assert "@click=\"closeWorkItem()\"" in partial  # click-out backdrop
    assert 'x-show="selectedWorkItem"' in partial
    # The new-item mode carries the capture box + form fallback
    assert "x-if=\"workItemNew\"" in partial
    assert "components/capture_box.html" in partial


def test_capture_box_calls_the_one_call_intake():
    """The collapsed intake: one call → amber Confirm → confirm/dismiss."""
    js = _read(CAPTURE_BOX)
    assert "api('POST', '/ai/intake'" in js, "capture box must call the ONE intake endpoint"
    assert "api('POST', '/ai/intake/confirm'" in js
    assert "api('POST', '/ai/intake/dismiss'" in js
    assert "source: 'capture box'" in js
    # Confirm lands the checked items; nothing writes before the tap
    submit = re.search(r"async submit\(\) \{.*?\n        \},", js, re.S)
    assert submit and "/ai/intake/confirm" not in submit.group(0)


def test_capture_box_partial_is_included_everywhere():
    """Work header, Today, the drawer's + New item, and the FAB launcher."""
    assert "components/capture_box.html" in _read(WORK)
    assert "components/capture_box.html" in _read(TODAY)
    assert "components/capture_box.html" in _read(DRAWER)
    assert "components/capture_box.html" in _read(FAB)


def test_capture_box_has_the_visible_form_fallback():
    """§2 Stage 3: the manual path is always visible beside the AI path."""
    partial = _read(CAPTURE_PARTIAL)
    assert "Skip AI — add with the form" in partial
    js = _read(CAPTURE_BOX)
    assert "openWorkItemNew" in js  # opens the drawer's + New item in edit mode


def test_work_view_hosts_the_drawer():
    """The ONE item drawer is included at INDEX level (outside the route-scoped
    views) so it opens from every route: Work, Today rows, project backlog rows,
    dashboard, capture-box Skip AI. Work renders the + New item button."""
    index = _read(REPO / "app/templates/index.html")
    assert "components/item_drawer.html" in index, "the drawer include lives at index level"
    work = _read(WORK)
    assert "components/item_drawer.html" not in work, "the drawer must not be route-scoped inside work.html"
    # The + New item button opens the drawer's new-item mode
    assert "@click=\"newWorkItem()\"" in work


def test_capture_box_component_is_registered():
    """captureBox is an Alpine.data component (per-instance scopes per include)."""
    pmo = _read(PMO_APP)
    assert "Alpine.data('captureBox'" in pmo
    assert "from './capture_box.js?v=" in pmo
    fab_js = _read(REPO / "app/static/js/app/fab.js")
    # FAB drag + persisted position logic stays untouched
    assert "localStorage.getItem('fab_pos')" in fab_js
    assert "localStorage.setItem('fab_pos'" in fab_js
