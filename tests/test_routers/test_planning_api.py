"""Test the Planning API (vision, KPIs, roadmaps, milestones) — TDD."""
import pytest
from datetime import date


class TestVisionAPI:
    """Tests for project vision endpoints."""

    def _create_project(self, client):
        """Helper: create a client + project and return project_id."""
        resp = client.post("/api/clients", json={"name": "Test Client"})
        cid = resp.json()["id"]
        resp = client.post("/api/projects", json={"name": "Test Project", "client_id": cid})
        return resp.json()["id"]

    def test_create_vision(self, client):
        """POST /api/projects/{id}/vision creates a vision."""
        pid = self._create_project(client)
        response = client.post(f"/api/projects/{pid}/vision", json={
            "project_id": pid,
            "statement": "Become the leading cloud platform",
            "strategic_objectives": "1. 99.9% uptime\n2. 50K users",
        })
        assert response.status_code == 201
        assert response.json()["statement"] == "Become the leading cloud platform"

    def test_get_vision(self, client):
        """GET /api/projects/{id}/vision returns the vision."""
        pid = self._create_project(client)
        client.post(f"/api/projects/{pid}/vision", json={
            "project_id": pid,
            "statement": "Leading platform",
        })
        response = client.get(f"/api/projects/{pid}/vision")
        assert response.status_code == 200
        assert response.json()["statement"] == "Leading platform"

    def test_get_vision_not_found(self, client):
        """GET /api/projects/{id}/vision returns 404 if no vision."""
        pid = self._create_project(client)
        response = client.get(f"/api/projects/{pid}/vision")
        assert response.status_code == 404

    def test_duplicate_vision_returns_409(self, client):
        """POST vision twice returns 409."""
        pid = self._create_project(client)
        client.post(f"/api/projects/{pid}/vision", json={
            "project_id": pid,
            "statement": "First vision",
        })
        response = client.post(f"/api/projects/{pid}/vision", json={
            "project_id": pid,
            "statement": "Second vision",
        })
        assert response.status_code == 409

    def test_update_vision(self, client):
        """PUT /api/projects/{id}/vision updates the vision."""
        pid = self._create_project(client)
        client.post(f"/api/projects/{pid}/vision", json={
            "project_id": pid,
            "statement": "Original",
        })
        response = client.put(f"/api/projects/{pid}/vision", json={
            "statement": "Updated vision",
        })
        assert response.status_code == 200
        assert response.json()["statement"] == "Updated vision"


class TestKPIAPI:
    """Tests for KPI endpoints."""

    def _create_project(self, client):
        resp = client.post("/api/clients", json={"name": "KPI Client"})
        cid = resp.json()["id"]
        resp = client.post("/api/projects", json={"name": "KPI Project", "client_id": cid})
        return resp.json()["id"]

    def test_create_kpi(self, client):
        pid = self._create_project(client)
        response = client.post(f"/api/projects/{pid}/kpis", json={
            "project_id": pid,
            "name": "Uptime",
            "target_value": "99.9%",
            "current_value": "99.5%",
            "unit": "percentage",
            "category": "SLA",
        })
        assert response.status_code == 201
        assert response.json()["name"] == "Uptime"

    def test_list_kpis(self, client):
        pid = self._create_project(client)
        client.post(f"/api/projects/{pid}/kpis", json={"project_id": pid, "name": "KPI 1"})
        client.post(f"/api/projects/{pid}/kpis", json={"project_id": pid, "name": "KPI 2"})
        response = client.get(f"/api/projects/{pid}/kpis")
        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_update_kpi(self, client):
        pid = self._create_project(client)
        resp = client.post(f"/api/projects/{pid}/kpis", json={"project_id": pid, "name": "K1"})
        kid = resp.json()["id"]
        response = client.put(f"/api/kpis/{kid}", json={"current_value": "98%"})
        assert response.status_code == 200
        assert response.json()["current_value"] == "98%"

    def test_delete_kpi(self, client):
        pid = self._create_project(client)
        resp = client.post(f"/api/projects/{pid}/kpis", json={"project_id": pid, "name": "K1"})
        kid = resp.json()["id"]
        response = client.delete(f"/api/kpis/{kid}")
        assert response.status_code == 204


class TestRoadmapAPI:
    """Tests for roadmap endpoints."""

    def _create_project(self, client):
        resp = client.post("/api/clients", json={"name": "RM Client"})
        cid = resp.json()["id"]
        resp = client.post("/api/projects", json={"name": "RM Project", "client_id": cid})
        return resp.json()["id"]

    def test_create_roadmap(self, client):
        pid = self._create_project(client)
        response = client.post(f"/api/projects/{pid}/roadmaps", json={
            "project_id": pid,
            "title": "2026 Roadmap",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        })
        assert response.status_code == 201
        assert response.json()["title"] == "2026 Roadmap"

    def test_list_roadmaps_with_milestones(self, client):
        pid = self._create_project(client)
        resp = client.post(f"/api/projects/{pid}/roadmaps", json={
            "project_id": pid,
            "title": "2026",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        })
        rid = resp.json()["id"]
        # Add milestones
        client.post(f"/api/roadmaps/{rid}/milestones", json={
            "roadmap_id": rid,
            "title": "Q1 Go-Live",
            "target_date": "2026-03-31",
        })
        client.post(f"/api/roadmaps/{rid}/milestones", json={
            "roadmap_id": rid,
            "title": "Q2 Review",
            "target_date": "2026-06-30",
        })
        response = client.get(f"/api/projects/{pid}/roadmaps")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert len(data[0]["milestones"]) == 2

    def test_update_roadmap(self, client):
        pid = self._create_project(client)
        resp = client.post(f"/api/projects/{pid}/roadmaps", json={
            "project_id": pid, "title": "Original",
        })
        rid = resp.json()["id"]
        response = client.put(f"/api/roadmaps/{rid}", json={"title": "Updated"})
        assert response.status_code == 200
        assert response.json()["title"] == "Updated"

    def test_delete_roadmap(self, client):
        pid = self._create_project(client)
        resp = client.post(f"/api/projects/{pid}/roadmaps", json={
            "project_id": pid, "title": "To Delete",
        })
        rid = resp.json()["id"]
        response = client.delete(f"/api/roadmaps/{rid}")
        assert response.status_code == 204


class TestMilestoneAPI:
    """Tests for milestone endpoints."""

    def _create_roadmap(self, client):
        resp = client.post("/api/clients", json={"name": "MS Client"})
        cid = resp.json()["id"]
        resp = client.post("/api/projects", json={"name": "MS Project", "client_id": cid})
        pid = resp.json()["id"]
        resp = client.post(f"/api/projects/{pid}/roadmaps", json={
            "project_id": pid, "title": "Roadmap",
        })
        return resp.json()["id"]

    def test_create_milestone(self, client):
        rid = self._create_roadmap(client)
        response = client.post(f"/api/roadmaps/{rid}/milestones", json={
            "roadmap_id": rid,
            "title": "Phase 1",
            "target_date": "2026-03-31",
            "status": "On Track",
        })
        assert response.status_code == 201
        assert response.json()["title"] == "Phase 1"

    def test_update_milestone(self, client):
        rid = self._create_roadmap(client)
        resp = client.post(f"/api/roadmaps/{rid}/milestones", json={
            "roadmap_id": rid, "title": "M1",
        })
        mid = resp.json()["id"]
        response = client.put(f"/api/milestones/{mid}", json={"status": "At Risk"})
        assert response.status_code == 200
        assert response.json()["status"] == "At Risk"

    def test_delete_milestone(self, client):
        rid = self._create_roadmap(client)
        resp = client.post(f"/api/roadmaps/{rid}/milestones", json={
            "roadmap_id": rid, "title": "M1",
        })
        mid = resp.json()["id"]
        response = client.delete(f"/api/milestones/{mid}")
        assert response.status_code == 204
