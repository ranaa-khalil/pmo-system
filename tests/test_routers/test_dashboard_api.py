"""Test the Dashboard API — TDD."""
import pytest


class TestDashboardAPI:
    """Tests for the dashboard stats endpoint."""

    def test_get_dashboard_stats(self, client):
        """GET /api/dashboard returns aggregated stats."""
        response = client.get("/api/dashboard")
        assert response.status_code == 200
        data = response.json()
        assert "clients" in data
        assert "projects" in data
        assert "backlog_items" in data
        assert "pending_approvals" in data
        assert "forms" in data

    def test_dashboard_stats_with_data(self, client):
        """Dashboard stats reflect actual data."""
        # Create data
        resp = client.post("/api/clients", json={"name": "Dash Client"})
        cid = resp.json()["id"]
        client.post("/api/projects", json={"name": "Dash Project", "client_id": cid})

        response = client.get("/api/dashboard")
        data = response.json()
        assert data["clients"] >= 1
        assert data["projects"] >= 1

    def test_dashboard_phase_distribution(self, client):
        """Dashboard includes backlog phase distribution."""
        response = client.get("/api/dashboard")
        data = response.json()
        assert "phase_distribution" in data
        assert isinstance(data["phase_distribution"], dict)

    def test_dashboard_recent_activity(self, client):
        """Dashboard includes recent activity."""
        response = client.get("/api/dashboard")
        data = response.json()
        assert "recent_projects" in data
        assert isinstance(data["recent_projects"], list)
