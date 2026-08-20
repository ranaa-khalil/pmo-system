"""Test the Auth API endpoints — TDD RED phase."""
import pytest


class TestAuthAPI:
    """Tests for /api/auth endpoints."""

    def test_register_user(self, client):
        """POST /api/auth/register creates a new user."""
        response = client.post("/api/auth/register", json={
            "email": "rana@opex.com.sa",
            "full_name": "Rana Khalil",
            "password": "SecurePass123!",
        })
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "rana@opex.com.sa"
        assert data["full_name"] == "Rana Khalil"
        assert "id" in data
        assert "password" not in data
        assert "hashed_password" not in data

    def test_register_duplicate_email_returns_400(self, client):
        """POST /api/auth/register with existing email returns 400."""
        client.post("/api/auth/register", json={
            "email": "rana@opex.com.sa",
            "full_name": "Rana Khalil",
            "password": "SecurePass123!",
        })
        response = client.post("/api/auth/register", json={
            "email": "rana@opex.com.sa",
            "full_name": "Another User",
            "password": "AnotherPass456!",
        })
        assert response.status_code == 400

    def test_login_with_valid_credentials(self, client):
        """POST /api/auth/login with valid credentials returns JWT token."""
        client.post("/api/auth/register", json={
            "email": "rana@opex.com.sa",
            "full_name": "Rana Khalil",
            "password": "SecurePass123!",
        })
        response = client.post("/api/auth/login", json={
            "email": "rana@opex.com.sa",
            "password": "SecurePass123!",
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert len(data["access_token"]) > 20

    def test_login_with_invalid_password_returns_401(self, client):
        """POST /api/auth/login with wrong password returns 401."""
        client.post("/api/auth/register", json={
            "email": "rana@opex.com.sa",
            "full_name": "Rana Khalil",
            "password": "SecurePass123!",
        })
        response = client.post("/api/auth/login", json={
            "email": "rana@opex.com.sa",
            "password": "WrongPassword!",
        })
        assert response.status_code == 401

    def test_login_with_nonexistent_user_returns_401(self, client):
        """POST /api/auth/login with unknown email returns 401."""
        response = client.post("/api/auth/login", json={
            "email": "nobody@nowhere.com",
            "password": "SomePassword!",
        })
        assert response.status_code == 401

    def test_get_me_with_valid_token(self, client):
        """GET /api/auth/me with valid token returns user info."""
        client.post("/api/auth/register", json={
            "email": "rana@opex.com.sa",
            "full_name": "Rana Khalil",
            "password": "SecurePass123!",
        })
        login_resp = client.post("/api/auth/login", json={
            "email": "rana@opex.com.sa",
            "password": "SecurePass123!",
        })
        token = login_resp.json()["access_token"]

        response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "rana@opex.com.sa"
        assert data["full_name"] == "Rana Khalil"

    def test_get_me_without_token_returns_401(self, db_session):
        """GET /api/auth/me without token returns 401."""
        from fastapi.testclient import TestClient
        from app.main import app as fastapi_app
        raw_client = TestClient(fastapi_app)
        response = raw_client.get("/api/auth/me")
        assert response.status_code == 401

    def test_get_me_with_invalid_token_returns_401(self, db_session):
        """GET /api/auth/me with invalid token returns 401."""
        from fastapi.testclient import TestClient
        from app.main import app as fastapi_app
        raw_client = TestClient(fastapi_app)
        response = raw_client.get("/api/auth/me", headers={"Authorization": "Bearer invalidtoken123"})
        assert response.status_code == 401
