"""Test the Clients API endpoints — TDD RED phase."""
import pytest


class TestClientsAPI:
    """Tests for the /api/clients endpoints."""

    def test_create_client(self, client):
        """POST /api/clients creates a client and returns 201."""
        response = client.post("/api/clients", json={
            "name": "NITC / PNU",
            "contact_name": "Aldaana Almuqrin",
            "contact_email": "AEalmuqrin@nitc.sa",
            "description": "Princess Nourah bint Abdulrahman University",
        })
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "NITC / PNU"
        assert data["contact_email"] == "AEalmuqrin@nitc.sa"
        assert "id" in data

    def test_list_clients(self, client):
        """GET /api/clients returns a list of clients."""
        # Create a client first
        client.post("/api/clients", json={"name": "GO Telecom", "contact_email": "info@go.com.sa"})
        
        response = client.get("/api/clients")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert any(c["name"] == "GO Telecom" for c in data)

    def test_get_client_by_id(self, client):
        """GET /api/clients/{id} returns a specific client."""
        create_resp = client.post("/api/clients", json={
            "name": "Test Client",
            "contact_email": "test@test.com",
        })
        client_id = create_resp.json()["id"]

        response = client.get(f"/api/clients/{client_id}")
        assert response.status_code == 200
        assert response.json()["name"] == "Test Client"

    def test_get_nonexistent_client_returns_404(self, client):
        """GET /api/clients/999 returns 404."""
        response = client.get("/api/clients/999")
        assert response.status_code == 404

    def test_update_client(self, client):
        """PUT /api/clients/{id} updates a client."""
        create_resp = client.post("/api/clients", json={
            "name": "Old Name",
            "contact_email": "old@test.com",
        })
        client_id = create_resp.json()["id"]

        response = client.put(f"/api/clients/{client_id}", json={"name": "New Name"})
        assert response.status_code == 200
        assert response.json()["name"] == "New Name"

    def test_delete_client(self, client):
        """DELETE /api/clients/{id} removes a client."""
        create_resp = client.post("/api/clients", json={
            "name": "To Delete",
            "contact_email": "delete@test.com",
        })
        client_id = create_resp.json()["id"]

        response = client.delete(f"/api/clients/{client_id}")
        assert response.status_code == 204

        # Verify it's gone
        get_resp = client.get(f"/api/clients/{client_id}")
        assert get_resp.status_code == 404

    def test_create_client_without_name_returns_422(self, client):
        """POST /api/clients without name returns 422 validation error."""
        response = client.post("/api/clients", json={"contact_email": "noname@test.com"})
        assert response.status_code == 422
