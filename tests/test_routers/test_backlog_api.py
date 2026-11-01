"""Test the Backlog API — TDD."""


class TestBacklogAPI:
    """Tests for backlog item endpoints."""

    def _create_project(self, client):
        resp = client.post("/api/clients", json={"name": "BL Client"})
        cid = resp.json()["id"]
        resp = client.post("/api/projects", json={"name": "BL Project", "client_id": cid})
        return resp.json()["id"]

    def test_create_backlog_item(self, client):
        """POST /api/projects/{id}/backlog creates a backlog item."""
        pid = self._create_project(client)
        response = client.post(f"/api/projects/{pid}/backlog", json={
            "project_id": pid,
            "title": "User authentication",
            "description": "JWT-based login",
            "priority": "High",
        })
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "User authentication"
        assert data["current_phase"] == "Requirements"
        assert data["status"] == "Draft"
        assert data["priority"] == "High"

    def test_list_backlog_items(self, client):
        """GET /api/projects/{id}/backlog returns all items."""
        pid = self._create_project(client)
        client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": "Feature A"})
        client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": "Feature B"})
        response = client.get(f"/api/projects/{pid}/backlog")
        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_filter_backlog_by_phase(self, client):
        """GET /api/projects/{id}/backlog?phase=Development filters by phase."""
        pid = self._create_project(client)
        r1 = client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": "A"})
        client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": "B"})
        # Advance first item to Development
        client.put(f"/api/backlog/{r1.json()['id']}", json={"current_phase": "Development"})
        response = client.get(f"/api/projects/{pid}/backlog?phase=Development")
        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["title"] == "A"

    def test_update_backlog_item(self, client):
        """PUT /api/backlog/{id} updates an item."""
        pid = self._create_project(client)
        resp = client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": "Original"})
        bid = resp.json()["id"]
        response = client.put(f"/api/backlog/{bid}", json={
            "title": "Updated title",
            "status": "In Progress",
        })
        assert response.status_code == 200
        assert response.json()["title"] == "Updated title"
        assert response.json()["status"] == "In Progress"

    def test_advance_backlog_phase(self, client):
        """POST /api/backlog/{id}/advance moves to the next phase."""
        pid = self._create_project(client)
        resp = client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": "Advance Me"})
        bid = resp.json()["id"]
        assert resp.json()["current_phase"] == "Requirements"

        response = client.post(f"/api/backlog/{bid}/advance")
        assert response.status_code == 200
        assert response.json()["current_phase"] == "Design"

    def test_advance_past_last_phase_stays_at_retrospective(self, client):
        """Advancing past Retrospective stays at Retrospective."""
        pid = self._create_project(client)
        resp = client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": "Last"})
        bid = resp.json()["id"]
        # Move to last phase
        item = client.put(f"/api/backlog/{bid}", json={"current_phase": "Retrospective"})
        # Try to advance
        response = client.post(f"/api/backlog/{bid}/advance")
        assert response.status_code == 200
        assert response.json()["current_phase"] == "Retrospective"

    def test_delete_backlog_item(self, client):
        """DELETE /api/backlog/{id} removes an item."""
        pid = self._create_project(client)
        resp = client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": "Delete Me"})
        bid = resp.json()["id"]
        response = client.delete(f"/api/backlog/{bid}")
        assert response.status_code == 204
        # Verify it's gone
        response = client.get(f"/api/projects/{pid}/backlog")
        assert len(response.json()) == 0

    def test_backlog_item_without_title_returns_422(self, client):
        """POST backlog without title returns 422."""
        pid = self._create_project(client)
        response = client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid})
        assert response.status_code == 422

    def test_board_reorder_persists_order(self, client):
        """PUT /api/backlog/board-order persists per-lane card order."""
        pid = self._create_project(client)
        r1 = client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": "Card A"}).json()
        r2 = client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": "Card B"}).json()
        r3 = client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": "Card C"}).json()
        # Reorder: C first, A second, B third
        response = client.put("/api/backlog/board-order", json={"order": [
            {"id": r3["id"], "board_order": 0},
            {"id": r1["id"], "board_order": 1},
            {"id": r2["id"], "board_order": 2},
        ]})
        assert response.status_code == 200
        assert response.json()["updated"] == 3
        items = client.get(f"/api/projects/{pid}/backlog").json()
        by_title = {i["title"]: i["board_order"] for i in items}
        assert by_title["Card C"] == 0
        assert by_title["Card A"] == 1
        assert by_title["Card B"] == 2

    def test_board_reorder_unknown_item_404(self, client):
        """Reordering an item from another tenant (nonexistent id) returns 404."""
        pid = self._create_project(client)
        response = client.put("/api/backlog/board-order", json={"order": [{"id": 999999, "board_order": 0}]})
        assert response.status_code == 404

    def test_board_reorder_empty_is_noop(self, client):
        """Empty order list is a clean no-op."""
        response = client.put("/api/backlog/board-order", json={"order": []})
        assert response.status_code == 200
        assert response.json()["updated"] == 0

    def test_quick_add_with_board_order_and_phase(self, client):
        """Quick-add: create item with explicit phase + board_order in one POST."""
        pid = self._create_project(client)
        response = client.post(f"/api/projects/{pid}/backlog", json={
            "project_id": pid,
            "title": "Board quick add",
            "item_type": "Feature",
            "current_phase": "Design",
            "priority": "High",
            "story_points": 5,
            "board_order": 0,
        })
        assert response.status_code == 201
        data = response.json()
        assert data["current_phase"] == "Design"
        assert data["priority"] == "High"
        assert data["story_points"] == 5
        assert data["board_order"] == 0
