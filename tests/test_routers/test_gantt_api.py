"""Test the project item Gantt API — CPM critical path/float (TDD)."""


def _iso(day):
    return f"2026-11-{day:02d}"


class TestGanttAPI:
    """GET /api/projects/{id}/gantt: schedule + CPM over the dependency DAG."""

    def _setup(self, client, items):
        """items: [(title, start_day, end_day, depends_on_titles)] -> (pid, id_map)."""
        resp = client.post("/api/clients", json={"name": "Gantt Client"})
        cid = resp.json()["id"]
        pid = client.post("/api/projects", json={"name": "Gantt Project", "client_id": cid}).json()["id"]
        id_map = {}
        for title, start, end, _ in items:
            item = client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": title}).json()
            id_map[title] = item["id"]
        for title, start, end, deps in items:
            payload = {"start_date": _iso(start), "end_date": _iso(end)}
            resp = client.put(f"/api/backlog/{id_map[title]}", json=payload)
            assert resp.status_code == 200, resp.text
            for dep in deps:
                client.post(f"/api/backlog/{id_map[title]}/dependencies",
                            json={"depends_on_id": id_map[dep]})
        return pid, id_map

    def test_no_scheduled_items(self, client):
        """With no dated items the Gantt is empty, not guessed."""
        resp = client.post("/api/clients", json={"name": "G2"})
        cid = resp.json()["id"]
        pid = client.post("/api/projects", json={"name": "G2 P", "client_id": cid}).json()["id"]
        client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": "Undated"})
        resp = client.get(f"/api/projects/{pid}/gantt")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["unscheduled_count"] == 1

    def test_chain_critical_path(self, client):
        """A -> B -> C chain: every item critical, floats 0."""
        pid, _ = self._setup(client, [
            ("A", 1, 3, []),
            ("B", 4, 6, ["A"]),
            ("C", 7, 9, ["B"]),
        ])
        resp = client.get(f"/api/projects/{pid}/gantt")
        assert resp.status_code == 200
        data = resp.json()
        assert data["start"] == _iso(1)
        assert data["end"] == _iso(9)
        by_title = {it["title"]: it for it in data["items"]}
        assert by_title["A"]["is_critical"] is True
        assert by_title["B"]["is_critical"] is True
        assert by_title["C"]["is_critical"] is True
        assert by_title["A"]["float"] == 0
        # ES/EF chain: A 0-2 (3 days), B 3-5, C 6-8
        assert by_title["A"]["early_start"] == 0
        assert by_title["B"]["early_start"] == 3
        assert by_title["C"]["early_start"] == 6
        assert data["critical_count"] == 3

    def test_parallel_path_float(self, client):
        """A parallel item that finishes early has positive float."""
        pid, _ = self._setup(client, [
            ("A", 1, 3, []),        # critical root
            ("B", 4, 6, ["A"]),     # critical: A -> B -> C
            ("C", 7, 9, ["B"]),
            ("X", 4, 6, ["A"]),     # parallel to B, doesn't gate C
        ])
        resp = client.get(f"/api/projects/{pid}/gantt")
        by_title = {it["title"]: it for it in resp.json()["items"]}
        assert by_title["X"]["is_critical"] is False
        assert by_title["X"]["float"] > 0
        assert by_title["B"]["is_critical"] is True

    def test_circular_dependencies_rejected(self, client):
        """The API rejects circular dependencies before they reach the Gantt."""
        resp = client.post("/api/clients", json={"name": "G4"})
        cid = resp.json()["id"]
        pid = client.post("/api/projects", json={"name": "G4 P", "client_id": cid}).json()["id"]
        i1 = client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": "One"}).json()
        i2 = client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": "Two"}).json()
        client.put(f"/api/backlog/{i1['id']}", json={"start_date": _iso(1), "end_date": _iso(3)})
        client.put(f"/api/backlog/{i2['id']}", json={"start_date": _iso(1), "end_date": _iso(3)})
        client.post(f"/api/backlog/{i1['id']}/dependencies", json={"depends_on_id": i2["id"]})
        resp = client.post(f"/api/backlog/{i2['id']}/dependencies", json={"depends_on_id": i1["id"]})
        assert resp.status_code == 400
        assert "Circular" in resp.json()["detail"]

    def test_dates_persist_via_update(self, client):
        """PUT /api/backlog/{id} persists start/end dates."""
        resp = client.post("/api/clients", json={"name": "G3"})
        cid = resp.json()["id"]
        pid = client.post("/api/projects", json={"name": "G3 P", "client_id": cid}).json()["id"]
        item = client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": "Dated"}).json()
        client.put(f"/api/backlog/{item['id']}", json={"start_date": _iso(2), "end_date": _iso(5)})
        resp = client.get(f"/api/projects/{pid}/gantt")
        by_title = {it["title"]: it for it in resp.json()["items"]}
        assert by_title["Dated"]["start_date"] == _iso(2)
        assert by_title["Dated"]["duration"] == 4  # inclusive days: Nov 2-5

    def test_unknown_project_404(self, client):
        """A foreign project 404s."""
        resp = client.get("/api/projects/99999/gantt")
        assert resp.status_code == 404
