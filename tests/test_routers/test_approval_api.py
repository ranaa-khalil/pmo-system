"""Test the Approval API — TDD."""


class TestApprovalAPI:
    """Tests for approval workflow endpoints."""

    def _create_project(self, client):
        resp = client.post("/api/clients", json={"name": "Approval Client"})
        cid = resp.json()["id"]
        resp = client.post("/api/projects", json={"name": "Approval Project", "client_id": cid})
        return resp.json()["id"]

    def test_create_approval_request(self, client):
        """POST /api/projects/{id}/approvals creates a request with RACI steps."""
        pid = self._create_project(client)
        response = client.post(f"/api/projects/{pid}/approvals", json={
            "project_id": pid,
            "title": "Release v1.0 Approval",
            "description": "Approve v1.0 to production",
            "request_type": "release",
            "steps": [
                {"role_name": "Product Owner", "step_order": 1},
                {"role_name": "Tech Lead", "step_order": 2},
                {"role_name": "Release Manager", "step_order": 3},
            ],
        })
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "Pending"
        assert data["current_step"] == 1
        assert len(data["steps"]) == 3

    def test_list_project_approvals(self, client):
        """GET /api/projects/{id}/approvals returns approval requests."""
        pid = self._create_project(client)
        client.post(f"/api/projects/{pid}/approvals", json={
            "project_id": pid, "title": "Test", "request_type": "release",
            "steps": [{"role_name": "PM", "step_order": 1}],
        })
        response = client.get(f"/api/projects/{pid}/approvals")
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_get_approval_with_steps(self, client):
        """GET /api/approvals/{id} returns request with steps."""
        pid = self._create_project(client)
        resp = client.post(f"/api/projects/{pid}/approvals", json={
            "project_id": pid, "title": "Test", "request_type": "release",
            "steps": [{"role_name": "PM", "step_order": 1}, {"role_name": "QA Lead", "step_order": 2}],
        })
        aid = resp.json()["id"]
        response = client.get(f"/api/approvals/{aid}")
        assert response.status_code == 200
        assert len(response.json()["steps"]) == 2

    def test_approve_step(self, client):
        """POST /api/approvals/{id}/steps/{step_id}/approve advances the chain."""
        pid = self._create_project(client)
        resp = client.post(f"/api/projects/{pid}/approvals", json={
            "project_id": pid, "title": "Test", "request_type": "release",
            "steps": [
                {"role_name": "PM", "step_order": 1},
                {"role_name": "Tech Lead", "step_order": 2},
            ],
        })
        aid = resp.json()["id"]
        step_id = resp.json()["steps"][0]["id"]

        response = client.post(f"/api/approvals/{aid}/steps/{step_id}/approve", json={"comment": "Looks good"})
        assert response.status_code == 200
        # Step should be approved, request should advance to step 2
        assert response.json()["current_step"] == 2
        assert response.json()["status"] == "Pending"  # Request still pending — step 2 remaining
        # The first step should be approved
        step = next(s for s in response.json()["steps"] if s["id"] == step_id)
        assert step["status"] == "Approved"

    def test_reject_step(self, client):
        """POST /api/approvals/{id}/steps/{step_id}/reject rejects the whole request."""
        pid = self._create_project(client)
        resp = client.post(f"/api/projects/{pid}/approvals", json={
            "project_id": pid, "title": "Test", "request_type": "release",
            "steps": [{"role_name": "PM", "step_order": 1}],
        })
        aid = resp.json()["id"]
        step_id = resp.json()["steps"][0]["id"]

        response = client.post(f"/api/approvals/{aid}/steps/{step_id}/reject", json={"comment": "Not ready"})
        assert response.status_code == 200
        assert response.json()["status"] == "Rejected"

    def test_final_approval_completes_request(self, client):
        """When the last step is approved, the request status becomes Approved."""
        pid = self._create_project(client)
        resp = client.post(f"/api/projects/{pid}/approvals", json={
            "project_id": pid, "title": "Test", "request_type": "release",
            "steps": [{"role_name": "PM", "step_order": 1}],
        })
        aid = resp.json()["id"]
        step_id = resp.json()["steps"][0]["id"]

        response = client.post(f"/api/approvals/{aid}/steps/{step_id}/approve")
        assert response.status_code == 200
        assert response.json()["status"] == "Approved"
        assert response.json()["current_step"] == 1

    def test_delete_approval(self, client):
        """DELETE /api/approvals/{id} removes an approval request."""
        pid = self._create_project(client)
        resp = client.post(f"/api/projects/{pid}/approvals", json={
            "project_id": pid, "title": "Test", "request_type": "release",
            "steps": [{"role_name": "PM", "step_order": 1}],
        })
        aid = resp.json()["id"]
        response = client.delete(f"/api/approvals/{aid}")
        assert response.status_code == 204
