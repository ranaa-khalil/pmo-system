"""Test the public share link API — TDD."""


class TestShareLinksAPI:
    """Share links: create/list/revoke + public view with optional password."""

    def _create_project(self, client, name="Share Project"):
        resp = client.post("/api/clients", json={"name": "Share Client"})
        cid = resp.json()["id"]
        return client.post("/api/projects", json={"name": name, "client_id": cid}).json()["id"]

    # ---- Authenticated: create/list/revoke ----

    def test_create_dashboard_link(self, client):
        """POST /api/share-links with dashboard scope returns a tokenized URL."""
        resp = client.post("/api/share-links", json={"scope": "dashboard", "expires_in_days": 30})
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["url"].startswith("/share/")
        assert data["scope"] == "dashboard"
        assert data["has_password"] is False

    def test_create_project_link(self, client):
        """A project-scoped link needs a valid project_id."""
        pid = self._create_project(client)
        resp = client.post("/api/share-links", json={"scope": "project", "project_id": pid})
        assert resp.status_code == 201
        assert resp.json()["project_id"] == pid

    def test_create_project_link_missing_project_400(self, client):
        """Project scope without project_id 400s."""
        resp = client.post("/api/share-links", json={"scope": "project"})
        assert resp.status_code == 400

    def test_create_project_link_unknown_project_404(self, client):
        """Project scope with a foreign project 404s."""
        resp = client.post("/api/share-links", json={"scope": "project", "project_id": 99999})
        assert resp.status_code == 404

    def test_create_link_bad_scope_400(self, client):
        """scope outside the vocabulary 400s."""
        resp = client.post("/api/share-links", json={"scope": "hax"})
        assert resp.status_code == 400

    def test_create_link_bad_expiry_400(self, client):
        """expires_in_days outside 1-90 400s."""
        resp = client.post("/api/share-links", json={"scope": "dashboard", "expires_in_days": 120})
        assert resp.status_code == 400

    def test_list_and_revoke(self, client):
        """List returns links with target names; revoke marks them."""
        pid = self._create_project(client)
        link = client.post("/api/share-links", json={"scope": "project", "project_id": pid}).json()
        links = client.get("/api/share-links").json()
        assert len(links) == 1
        assert links[0]["target_name"] == "Share Project"
        resp = client.delete(f"/api/share-links/{link['id']}")
        assert resp.status_code == 200
        links = client.get("/api/share-links").json()
        assert links[0]["revoked"] is True
        # Revoked link: public view 410
        resp = client.get(f"/api/share/{link['token']}")
        assert resp.status_code == 410

    # ---- Public: view ----

    def test_public_dashboard_view(self, client):
        """GET /api/share/{token} returns the dashboard aggregate."""
        pid = self._create_project(client)
        client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": "Item A"})
        item_b = client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": "Item B"}).json()
        client.put(f"/api/backlog/{item_b['id']}", json={"status": "Done"})
        link = client.post("/api/share-links", json={"scope": "dashboard"}).json()
        resp = client.get(f"/api/share/{link['token']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["scope"] == "dashboard"
        assert data["tenant_name"] == "Test Tenant"
        project = [p for p in data["projects"] if p["name"] == "Share Project"][0]
        assert project["total_items"] == 2
        assert project["done_items"] == 1
        assert project["progress"] == 50

    def test_public_project_view(self, client):
        """GET /api/share/{token} returns the project summary."""
        pid = self._create_project(client)
        client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": "Item C"})
        link = client.post("/api/share-links", json={"scope": "project", "project_id": pid}).json()
        resp = client.get(f"/api/share/{link['token']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["scope"] == "project"
        assert data["project"]["name"] == "Share Project"
        assert data["backlog"]["total"] == 1
        assert data["backlog"]["progress"] == 0

    def test_view_count_increments(self, client):
        """Each public view increments the view counter."""
        link = client.post("/api/share-links", json={"scope": "dashboard"}).json()
        client.get(f"/api/share/{link['token']}")
        client.get(f"/api/share/{link['token']}")
        links = client.get("/api/share-links").json()
        assert links[0]["view_count"] == 2

    def test_public_view_unknown_token_404(self, client):
        """An unknown token 404s."""
        resp = client.get("/api/share/not-a-real-token")
        assert resp.status_code == 404

    # ---- Public: password-protected ----

    def test_password_link_requires_password(self, client):
        """A password link returns requires_password on GET."""
        link = client.post("/api/share-links", json={
            "scope": "dashboard", "password": "ViewPass1!",
        }).json()
        resp = client.get(f"/api/share/{link['token']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["requires_password"] is True
        assert "projects" not in data  # payload not leaked

    def test_password_link_wrong_password_401(self, client):
        """Wrong password 401s."""
        link = client.post("/api/share-links", json={
            "scope": "dashboard", "password": "ViewPass1!",
        }).json()
        resp = client.post(f"/api/share/{link['token']}", json={"password": "nope"})
        assert resp.status_code == 401

    def test_password_link_unlock(self, client):
        """The right password unlocks the payload."""
        link = client.post("/api/share-links", json={
            "scope": "dashboard", "password": "ViewPass1!",
        }).json()
        resp = client.post(f"/api/share/{link['token']}", json={"password": "ViewPass1!"})
        assert resp.status_code == 200
        assert resp.json()["scope"] == "dashboard"

    def test_no_auth_needed_for_public_view(self, anon_client):
        """The public view endpoint needs no auth."""
        resp = anon_client.get("/api/share/not-a-real-token")
        assert resp.status_code == 404  # not 401 — public surface
