"""Smoke tests — verify all routers respond and auth works."""


class TestHealth:
    """Basic health checks."""

    def test_health_check(self, client):
        """Health endpoint returns 200."""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"


class TestAuth:
    """Authentication smoke tests."""

    def test_login_page_loads(self, client):
        """Frontend loads."""
        resp = client.get("/")
        assert resp.status_code == 200

    def test_protected_endpoint_without_token(self, client):
        """API requires authentication."""
        resp = client.get("/api/projects")
        assert resp.status_code in (401, 403)

    def test_protected_endpoint_with_token(self, client, auth_headers):
        """API accepts valid token."""
        resp = client.get("/api/projects", headers=auth_headers)
        assert resp.status_code == 200


class TestRouters:
    """Smoke test all API routers — verify they're mounted and respond."""

    def test_projects_router(self, client, auth_headers):
        resp = client.get("/api/projects", headers=auth_headers)
        assert resp.status_code == 200

    def test_clients_router(self, client, auth_headers):
        resp = client.get("/api/clients", headers=auth_headers)
        assert resp.status_code == 200

    def test_backlog_router(self, client, auth_headers):
        resp = client.get("/api/projects/1/backlog", headers=auth_headers)
        assert resp.status_code in (200, 404)  # 404 if no project 1

    def test_releases_router(self, client, auth_headers):
        resp = client.get("/api/projects/1/releases", headers=auth_headers)
        assert resp.status_code in (200, 404)

    def test_stakeholders_router(self, client, auth_headers):
        resp = client.get("/api/projects/1/stakeholders", headers=auth_headers)
        assert resp.status_code in (200, 404)

    def test_dashboard_router(self, client, auth_headers):
        resp = client.get("/api/dashboard", headers=auth_headers)
        assert resp.status_code == 200

    def test_notifications_router(self, client, auth_headers):
        resp = client.get("/api/notifications", headers=auth_headers)
        assert resp.status_code == 200

    def test_user_tasks_router(self, client, auth_headers):
        resp = client.get("/api/tasks", headers=auth_headers)
        assert resp.status_code == 200

    def test_personas_router(self, client, auth_headers):
        resp = client.get("/api/projects/1/personas", headers=auth_headers)
        assert resp.status_code in (200, 404)

    def test_forms_router(self, client, auth_headers):
        resp = client.get("/api/forms/templates", headers=auth_headers)
        assert resp.status_code == 200

    def test_github_sync_router(self, client, auth_headers):
        resp = client.get("/api/projects/1/github/sync-status", headers=auth_headers)
        assert resp.status_code in (200, 404)
