"""Test the Forms API — TDD."""


class TestFormsAPI:
    """Tests for form template and instance endpoints."""

    def _create_project(self, client):
        resp = client.post("/api/clients", json={"name": "Form Client"})
        cid = resp.json()["id"]
        resp = client.post("/api/projects", json={"name": "Form Project", "client_id": cid})
        return resp.json()["id"]

    def test_list_templates(self, client):
        """GET /api/forms/templates returns available templates."""
        response = client.get("/api/forms/templates")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_create_form_instance(self, client):
        """POST /api/projects/{id}/forms creates a form instance from a template."""
        pid = self._create_project(client)
        # Get a template
        templates = client.get("/api/forms/templates").json()
        template_id = templates[0]["id"]

        response = client.post(f"/api/projects/{pid}/forms", json={
            "template_id": template_id,
            "project_id": pid,
        })
        assert response.status_code == 201
        assert response.json()["status"] == "Draft"
        assert response.json()["template_id"] == template_id

    def test_list_project_forms(self, client):
        """GET /api/projects/{id}/forms returns form instances for a project."""
        pid = self._create_project(client)
        templates = client.get("/api/forms/templates").json()
        client.post(f"/api/projects/{pid}/forms", json={
            "template_id": templates[0]["id"], "project_id": pid,
        })
        response = client.get(f"/api/projects/{pid}/forms")
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_get_form_instance(self, client):
        """GET /api/forms/{id} returns a form instance with template info."""
        pid = self._create_project(client)
        templates = client.get("/api/forms/templates").json()
        resp = client.post(f"/api/projects/{pid}/forms", json={
            "template_id": templates[0]["id"], "project_id": pid,
        })
        fid = resp.json()["id"]

        response = client.get(f"/api/forms/{fid}")
        assert response.status_code == 200
        assert response.json()["id"] == fid

    def test_update_form_data(self, client):
        """PUT /api/forms/{id} updates form field data."""
        pid = self._create_project(client)
        templates = client.get("/api/forms/templates").json()
        resp = client.post(f"/api/projects/{pid}/forms", json={
            "template_id": templates[0]["id"], "project_id": pid,
        })
        fid = resp.json()["id"]

        response = client.put(f"/api/forms/{fid}", json={
            "data": {"release_version": "1.0.0", "tester_name": "Rana"},
        })
        assert response.status_code == 200
        assert response.json()["data"]["release_version"] == "1.0.0"

    def test_submit_form(self, client):
        """POST /api/forms/{id}/submit changes status to Submitted."""
        pid = self._create_project(client)
        templates = client.get("/api/forms/templates").json()
        resp = client.post(f"/api/projects/{pid}/forms", json={
            "template_id": templates[0]["id"], "project_id": pid,
        })
        fid = resp.json()["id"]

        response = client.post(f"/api/forms/{fid}/submit")
        assert response.status_code == 200
        assert response.json()["status"] == "Submitted"

    def test_approve_form(self, client):
        """POST /api/forms/{id}/approve changes status to Approved."""
        pid = self._create_project(client)
        templates = client.get("/api/forms/templates").json()
        resp = client.post(f"/api/projects/{pid}/forms", json={
            "template_id": templates[0]["id"], "project_id": pid,
        })
        fid = resp.json()["id"]
        client.post(f"/api/forms/{fid}/submit")

        response = client.post(f"/api/forms/{fid}/approve")
        assert response.status_code == 200
        assert response.json()["status"] == "Approved"

    def test_delete_form_instance(self, client):
        """DELETE /api/forms/{id} removes a form instance."""
        pid = self._create_project(client)
        templates = client.get("/api/forms/templates").json()
        resp = client.post(f"/api/projects/{pid}/forms", json={
            "template_id": templates[0]["id"], "project_id": pid,
        })
        fid = resp.json()["id"]

        response = client.delete(f"/api/forms/{fid}")
        assert response.status_code == 204
