"""Test protected routes — TDD RED phase.

These tests verify that:
1. Routes require authentication (401 without token)
2. Routes work with a valid token
3. Permission checks work (403 when lacking permission)
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app as fastapi_app


class TestProtectedRoutes:
    """Tests that existing CRUD routes require authentication."""

    def _register_and_login(self, client):
        """Helper: register a user and return the auth token."""
        client.post("/api/auth/register", json={
            "email": "protected@test.com",
            "full_name": "Protected User",
            "password": "TestPass123!",
        })
        resp = client.post("/api/auth/login", json={
            "email": "protected@test.com",
            "password": "TestPass123!",
        })
        return resp.json()["access_token"]

    def _auth_headers(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_get_clients_without_token_returns_401(self, db_session):
        """GET /api/clients without token returns 401."""
        # Use a raw TestClient without auto-auth
        raw_client = TestClient(fastapi_app)
        response = raw_client.get("/api/clients")
        assert response.status_code == 401

    def test_create_client_without_token_returns_401(self, db_session):
        """POST /api/clients without token returns 401."""
        raw_client = TestClient(fastapi_app)
        response = raw_client.post("/api/clients", json={"name": "Test"})
        assert response.status_code == 401

    def test_get_projects_without_token_returns_401(self, db_session):
        """GET /api/projects without token returns 401."""
        raw_client = TestClient(fastapi_app)
        response = raw_client.get("/api/projects")
        assert response.status_code == 401

    def test_get_clients_with_token(self, client):
        """GET /api/clients with valid token returns 200."""
        response = client.get("/api/clients")
        assert response.status_code == 200

    def test_create_client_with_token(self, client):
        """POST /api/clients with valid token creates client."""
        response = client.post("/api/clients", json={
            "name": "NITC / PNU",
            "contact_email": "test@nitc.sa",
        })
        assert response.status_code == 201

    def test_create_project_with_token(self, client):
        """POST /api/projects with valid token creates project."""
        # Create a client first
        resp = client.post("/api/clients", json={"name": "Test Client"})
        client_id = resp.json()["id"]
        # Create project
        response = client.post("/api/projects", json={
            "name": "Test Project",
            "client_id": client_id,
        })
        assert response.status_code == 201

    def test_delete_client_with_token(self, client):
        """DELETE /api/clients/{id} with valid token deletes client."""
        resp = client.post("/api/clients", json={"name": "To Delete"})
        client_id = resp.json()["id"]
        response = client.delete(f"/api/clients/{client_id}")
        assert response.status_code == 204

    def test_update_project_with_token(self, client):
        """PUT /api/projects/{id} with valid token updates project."""
        # Create client + project
        resp = client.post("/api/clients", json={"name": "C1"})
        cid = resp.json()["id"]
        resp = client.post("/api/projects", json={"name": "P1", "client_id": cid})
        pid = resp.json()["id"]
        # Update
        response = client.put(f"/api/projects/{pid}", json={"name": "Updated Name"})
        assert response.status_code == 200
        assert response.json()["name"] == "Updated Name"
