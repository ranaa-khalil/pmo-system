"""Test the team workload endpoint — TDD.

Per-member open-item counts (backlog items + personal tasks), sorted by load.
API-only setup: interleaving the db fixture session with TestClient calls on
the shared StaticPool connection deadlocks intermittently.
"""


class TestTeamWorkload:
    """GET /api/workload: per-member open work, sorted by load."""

    def _project(self, client, name):
        cid = client.post("/api/clients", json={"name": name + " Client"}).json()["id"]
        resp = client.post("/api/projects", json={"name": name, "client_id": cid})
        assert resp.status_code in (200, 201), resp.text
        return resp.json()

    def _member(self, client, email, name):
        resp = client.post("/api/admin/tenants/1/users", json={
            "email": email, "name": name, "password": "MemberPass123!",
        })
        assert resp.status_code == 201, resp.text
        return resp.json()

    def _item(self, client, pid, title, status=None, assigned_to=None):
        """BacklogItemCreate has no status/assigned_to — create, then PUT."""
        resp = client.post(f"/api/projects/{pid}/backlog", json={
            "project_id": pid, "title": title,
        })
        assert resp.status_code in (200, 201), resp.text
        item = resp.json()
        payload = {}
        if status is not None:
            payload["status"] = status
        if assigned_to is not None:
            payload["assigned_to"] = assigned_to
        if payload:
            resp = client.put(f"/api/backlog/{item['id']}", json=payload)
            assert resp.status_code == 200, resp.text
        return item

    def test_empty_workload(self, client):
        resp = client.get("/api/workload")
        assert resp.status_code == 200
        rows = resp.json()
        assert isinstance(rows, list)
        assert all("open_items" in r and "open_tasks" in r for r in rows)

    def test_counts_open_items_and_tasks(self, client):
        project = self._project(client, "Workload P")
        owner_id = client.get("/api/auth/me").json()["id"]

        self._item(client, project["id"], "Open item", status="In Progress", assigned_to=owner_id)
        self._item(client, project["id"], "Done item", status="Done", assigned_to=owner_id)
        client.post("/api/tasks", json={
            "title": "Open task", "assigned_to": owner_id,
        })
        client.post("/api/tasks", json={
            "title": "Done task", "assigned_to": owner_id, "status": "Completed",
        })

        rows = client.get("/api/workload").json()
        mine = next(r for r in rows if r["user_id"] == owner_id)
        assert mine["open_items"] == 1  # Done excluded
        assert mine["open_tasks"] == 1  # Completed excluded
        assert mine["total"] == 2

    def test_sorted_by_load_desc(self, client):
        project = self._project(client, "Load P")
        member = self._member(client, "loader@pmotest.io", "Loader")

        self._item(client, project["id"], "A", status="In Progress", assigned_to=member["user_id"])
        self._item(client, project["id"], "B", status="Blocked", assigned_to=member["user_id"])

        rows = client.get("/api/workload").json()
        assert rows[0]["user_id"] == member["user_id"]
        assert rows[0]["total"] == 2
        totals = [r["total"] for r in rows]
        assert totals == sorted(totals, reverse=True)

    def test_untouched_member_zero_load(self, client):
        member = self._member(client, "idle@pmotest.io", "Idle")
        rows = client.get("/api/workload").json()
        row = next(r for r in rows if r["user_id"] == member["user_id"])
        assert row["total"] == 0
