"""Timeline P1/P2 functional tests — release targets, drift, actuals (TDD).

P1 (release target lines + drift chip on the item Gantt):
- GET /api/projects/{id}/gantt carries the project's releases (target_date,
  the DYNAMIC ladder's live_stage), a drift chip object (window end vs the
  release target — the PNU contradiction: plan ends past the target,
  unflagged), and per-item past_release flags for bundled items.

P2 (actuals + baseline-vs-actual bars):
- The advance machine stamps actual_start_date on the first advance and
  actual_end_date when the item reaches Done; the gantt payload carries
  both so the frontend renders baseline-vs-actual bars.
- Actuals are machine-owned: PUT /api/backlog/{id} never writes them.
"""
from datetime import date


def _iso(day):
    return f"2026-11-{day:02d}"


def _make_project(client, name, project_type=None):
    resp = client.post("/api/clients", json={"name": name + " Client"})
    cid = resp.json()["id"]
    payload = {"name": name, "client_id": cid}
    if project_type:
        payload["project_type"] = project_type
    pid = client.post("/api/projects", json=payload).json()["id"]
    return pid


def _make_item(client, pid, title, start=None, end=None):
    item = client.post(f"/api/projects/{pid}/backlog",
                       json={"project_id": pid, "title": title}).json()
    if start and end:
        resp = client.put(f"/api/backlog/{item['id']}",
                          json={"start_date": start, "end_date": end})
        assert resp.status_code == 200, resp.text
    return item["id"]


def _make_release(client, pid, target=None, version="1.0.0"):
    body = {"version": version, "name": "Launch"}
    if target:
        body["target_date"] = target
    resp = client.post(f"/api/projects/{pid}/releases", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


class TestGanttReleasesP1:
    """P1: the commitment is visible — releases, drift chip, item flags."""

    def test_window_drift_chip_fires_past_target(self, client):
        """A plan ending past a release target is flagged (the PNU shape):
        window-level drift even when no item is bundled to the release."""
        pid = _make_project(client, "Drift P")
        _make_item(client, pid, "Late item", start=_iso(1), end=_iso(20))
        _make_release(client, pid, target="2026-09-30")  # before the window end
        resp = client.get(f"/api/projects/{pid}/gantt")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["releases"]) == 1
        row = data["releases"][0]
        assert row["target_date"] == "2026-09-30"
        assert row["version"] == "1.0.0"
        assert row["drift_days"] == 51  # 2026-09-30 -> 2026-11-20
        # The drift chip object: the most-drifted release.
        assert data["drift"]["release_id"] == row["id"]
        assert data["drift"]["drift_days"] == 51
        # No bundle — the item itself is not flagged, the window is.
        assert data["items"][0]["past_release"] is False

    def test_no_drift_when_plan_within_target(self, client):
        """A plan that finishes before the target carries no drift."""
        pid = _make_project(client, "On Time P")
        _make_item(client, pid, "Early item", start=_iso(1), end=_iso(10))
        _make_release(client, pid, target="2026-12-31")
        data = client.get(f"/api/projects/{pid}/gantt").json()
        assert data["releases"][0]["target_date"] == "2026-12-31"
        assert data["releases"][0]["drift_days"] is None
        assert data["drift"] is None

    def test_unparseable_target_never_drifts(self, client):
        """A free-text target ("2026-08") lists but never places a line."""
        pid = _make_project(client, "Fuzzy P")
        _make_item(client, pid, "Item", start=_iso(1), end=_iso(10))
        _make_release(client, pid, target="2026-08")
        data = client.get(f"/api/projects/{pid}/gantt").json()
        assert len(data["releases"]) == 1
        assert data["releases"][0]["drift_days"] is None
        assert data["drift"] is None

    def test_item_past_release_flag_for_bundled_items(self, client):
        """A bundled item whose planned end is past its release target is
        flagged with the drift; an un-bundled item in the same window is not."""
        pid = _make_project(client, "Bundle P")
        late = _make_item(client, pid, "Late item", start=_iso(1), end=_iso(20))
        _make_item(client, pid, "Other item", start=_iso(1), end=_iso(20))
        rid = _make_release(client, pid, target="2026-10-31")
        resp = client.post(f"/api/releases/{rid}/items/{late}")
        assert resp.status_code == 201, resp.text
        data = client.get(f"/api/projects/{pid}/gantt").json()
        by_title = {it["title"]: it for it in data["items"]}
        assert by_title["Late item"]["past_release"] is True
        assert by_title["Late item"]["release_drift"]["release_id"] == rid
        assert by_title["Late item"]["release_drift"]["drift_days"] == 20  # Oct 31 -> Nov 20
        assert by_title["Other item"]["past_release"] is False
        assert by_title["Other item"]["release_drift"] is None

    def test_releases_carry_the_dynamic_ladder_live_stage(self, client):
        """The ladder is DYNAMIC — release rows carry its live_stage."""
        pid = _make_project(client, "Ladder P")
        _make_item(client, pid, "Item", start=_iso(1), end=_iso(10))
        _make_release(client, pid, target="2026-10-31")
        data = client.get(f"/api/projects/{pid}/gantt").json()
        # Software family: the 7-phase V-cycle ladder, live at "Released".
        assert data["releases"][0]["live_stage"] == "Released"

    def test_empty_project_keeps_the_contract(self, client):
        """No scheduled items: releases/drift keys exist, never KeyError."""
        pid = _make_project(client, "Empty P")
        _make_item(client, pid, "Undated")
        data = client.get(f"/api/projects/{pid}/gantt").json()
        assert data["items"] == []
        assert data["releases"] == []
        assert data["drift"] is None


class TestGanttActualsP2:
    """P2: actuals in the advance machine + baseline-vs-actual in the payload."""

    def test_advance_stamps_actual_start(self, client):
        """First advance stamps the actual start; the actual end stays open."""
        pid = _make_project(client, "Actual P")
        iid = _make_item(client, pid, "Flowing item")
        resp = client.post(f"/api/backlog/{iid}/advance")
        assert resp.status_code == 200, resp.text
        row = client.get(f"/api/backlog/{iid}").json()
        assert row["actual_start_date"] == date.today().isoformat()
        assert row["actual_end_date"] is None
        # A second advance never rewrites the stamp.
        client.post(f"/api/backlog/{iid}/advance")
        row = client.get(f"/api/backlog/{iid}").json()
        assert row["actual_start_date"] == date.today().isoformat()

    def test_advance_to_done_stamps_actual_end(self, client):
        """Reaching Done (operations ladder's terminal item phase) stamps
        the actual end."""
        pid = _make_project(client, "Ops P", project_type="operations")
        iid = _make_item(client, pid, "Ops item")  # starts at Intake
        # Template quirk (pre-existing): "Intake" sits in BOTH the operations
        # item_phases and release_stages, so the machine's release-level guard
        # blocks the first advance — park the item at Verify via PUT.
        resp = client.put(f"/api/backlog/{iid}", json={"current_phase": "Verify"})
        assert resp.status_code == 200, resp.text
        row = client.get(f"/api/backlog/{iid}").json()
        assert row["current_phase"] == "Verify"
        assert row["actual_end_date"] is None  # not done yet
        resp = client.post(f"/api/backlog/{iid}/advance")  # Verify -> Done
        assert resp.status_code == 200, resp.text
        row = client.get(f"/api/backlog/{iid}").json()
        assert row["current_phase"] == "Done"
        assert row["actual_end_date"] == date.today().isoformat()

    def test_gantt_payload_carries_actuals(self, client):
        """The gantt items carry actual dates (baseline-vs-actual data);
        items the machine never touched read None."""
        pid = _make_project(client, "Baseline P")
        moved = _make_item(client, pid, "Moved item", start=_iso(1), end=_iso(10))
        _make_item(client, pid, "Untouched item", start=_iso(2), end=_iso(12))
        client.post(f"/api/backlog/{moved}/advance")
        data = client.get(f"/api/projects/{pid}/gantt").json()
        by_title = {it["title"]: it for it in data["items"]}
        assert by_title["Moved item"]["actual_start_date"] == date.today().isoformat()
        assert by_title["Moved item"]["actual_end_date"] is None
        assert by_title["Untouched item"]["actual_start_date"] is None
        assert by_title["Untouched item"]["actual_end_date"] is None

    def test_update_never_writes_actuals(self, client):
        """Actuals are machine-owned — PUT with actual dates is dropped."""
        pid = _make_project(client, "Machine P")
        iid = _make_item(client, pid, "Guarded item")
        resp = client.put(f"/api/backlog/{iid}",
                          json={"actual_start_date": "2026-01-01",
                                "actual_end_date": "2026-01-02"})
        assert resp.status_code == 200, resp.text
        row = client.get(f"/api/backlog/{iid}").json()
        assert row["actual_start_date"] is None
        assert row["actual_end_date"] is None

    def test_send_back_preserves_actuals(self, client):
        """Rework (send-back) never clears a stamped actual start."""
        pid = _make_project(client, "Rework P")
        iid = _make_item(client, pid, "Reworked item")
        for _ in range(3):  # Requirements -> Design -> Development -> Testing
            client.post(f"/api/backlog/{iid}/advance")
        resp = client.post(f"/api/backlog/{iid}/send-back")
        assert resp.status_code == 200, resp.text
        row = client.get(f"/api/backlog/{iid}").json()
        assert row["current_phase"] == "Development"  # send-back: Testing -> Development
        assert row["actual_start_date"] == date.today().isoformat()
