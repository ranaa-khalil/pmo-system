"""Test the Projects API endpoints — TDD RED phase."""


class TestProjectsAPI:
    """Tests for the /api/projects endpoints."""

    def _create_client(self, client):
        """Helper: create a client and return its ID."""
        resp = client.post("/api/clients", json={
            "name": "Test Client",
            "contact_email": "test@test.com",
        })
        return resp.json()["id"]

    def test_create_project(self, client):
        """POST /api/projects creates a project linked to a client."""
        client_id = self._create_client(client)
        response = client.post("/api/projects", json={
            "name": "PNU Cloud",
            "client_id": client_id,
            "description": "Cloud infrastructure project",
            "github_repo": "opexsa/pnu-cloud",
        })
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "PNU Cloud"
        assert data["client_id"] == client_id
        assert data["github_repo"] == "opexsa/pnu-cloud"
        assert data["status"] == "Active"

    def test_list_projects(self, client):
        """GET /api/projects returns a list of projects."""
        client_id = self._create_client(client)
        client.post("/api/projects", json={"name": "CloudGate", "client_id": client_id})

        response = client.get("/api/projects")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert any(p["name"] == "CloudGate" for p in data)

    def test_get_project_by_id(self, client):
        """GET /api/projects/{id} returns a specific project."""
        client_id = self._create_client(client)
        create_resp = client.post("/api/projects", json={
            "name": "Test Project",
            "client_id": client_id,
        })
        project_id = create_resp.json()["id"]

        response = client.get(f"/api/projects/{project_id}")
        assert response.status_code == 200
        assert response.json()["name"] == "Test Project"

    def test_get_nonexistent_project_returns_404(self, client):
        """GET /api/projects/999 returns 404."""
        response = client.get("/api/projects/999")
        assert response.status_code == 404

    def test_update_project(self, client):
        """PUT /api/projects/{id} updates a project."""
        client_id = self._create_client(client)
        create_resp = client.post("/api/projects", json={
            "name": "Old Name",
            "client_id": client_id,
        })
        project_id = create_resp.json()["id"]

        response = client.put(f"/api/projects/{project_id}", json={
            "name": "New Name",
            "status": "On Hold",
        })
        assert response.status_code == 200
        assert response.json()["name"] == "New Name"
        assert response.json()["status"] == "On Hold"

    def test_delete_project(self, client):
        """DELETE /api/projects/{id} removes a project."""
        client_id = self._create_client(client)
        create_resp = client.post("/api/projects", json={
            "name": "To Delete",
            "client_id": client_id,
        })
        project_id = create_resp.json()["id"]

        response = client.delete(f"/api/projects/{project_id}")
        assert response.status_code == 204

    def test_filter_projects_by_client(self, client):
        """GET /api/projects?client_id={id} filters by client."""
        client_id = self._create_client(client)
        client.post("/api/projects", json={"name": "Project A", "client_id": client_id})

        response = client.get(f"/api/projects?client_id={client_id}")
        assert response.status_code == 200
        data = response.json()
        assert all(p["client_id"] == client_id for p in data)
