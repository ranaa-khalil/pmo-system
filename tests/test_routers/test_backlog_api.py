"""Test the Backlog API — TDD."""
import pytest


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
