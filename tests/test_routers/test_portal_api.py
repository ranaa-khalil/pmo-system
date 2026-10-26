"""Test the Client Portal (P4) — portal login, scoped tokens, management."""

import pytest


@pytest.fixture
def portal_world(client, db):
    """Super admin + a client with a contact email."""
    from app.models.client import Client
    from app.models.tenant import Tenant, TenantMembership

    tenant = Tenant(name="OPEX", slug="opex", plan="enterprise")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    db.add(TenantMembership(user_id=1, tenant_id=tenant.id, role="owner"))

    c = Client(
        name="NITC / PNU",
        contact_name="Aldaana",
        contact_email="client@pnu.edu.sa",
        tenant_id=tenant.id,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"client": c, "tenant": tenant}


class TestPortalManagement:
    """PM-side: enable / status / disable a client's portal."""

    def test_enable_portal_returns_passcode_once(self, client, auth_headers, portal_world):
        c = portal_world["client"]
        resp = client.post(f"/api/clients/{c.id}/portal", json={}, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["portal_enabled"] is True
        assert len(data["passcode"]) >= 8
        # The passcode must never be retrievable again
        status_resp = client.get(f"/api/clients/{c.id}/portal", headers=auth_headers)
        assert status_resp.status_code == 200
        assert status_resp.json() == {"client_id": c.id, "portal_enabled": True}

    def test_enable_portal_requires_contact_email(self, client, auth_headers, db, portal_world):
        from app.models.client import Client
        c2 = Client(name="No Email Client", tenant_id=portal_world["tenant"].id)
        db.add(c2)
        db.commit()
        db.refresh(c2)
        resp = client.post(f"/api/clients/{c2.id}/portal", json={}, headers=auth_headers)
        assert resp.status_code == 400

    def test_enable_portal_short_passcode_422(self, client, auth_headers, portal_world):
        c = portal_world["client"]
        resp = client.post(f"/api/clients/{c.id}/portal", json={"passcode": "short"}, headers=auth_headers)
        assert resp.status_code == 422

    def test_disable_portal(self, client, auth_headers, portal_world):
        c = portal_world["client"]
        client.post(f"/api/clients/{c.id}/portal", json={"passcode": "TestPass123!"}, headers=auth_headers)
        resp = client.delete(f"/api/clients/{c.id}/portal", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["portal_enabled"] is False

    def test_portal_setup_without_auth_401(self, client, portal_world):
        c = portal_world["client"]
        resp = client.post(f"/api/clients/{c.id}/portal", json={})
        assert resp.status_code in (401, 403)


class TestPortalLogin:
    """Client-side: email + passcode → scoped portal token."""

    def test_login_with_correct_passcode(self, client, auth_headers, portal_world):
        c = portal_world["client"]
        setup = client.post(f"/api/clients/{c.id}/portal", json={}, headers=auth_headers).json()
        resp = client.post("/api/portal/login", json={
            "email": "client@pnu.edu.sa", "passcode": setup["passcode"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"]
        assert data["client"]["name"] == "NITC / PNU"

    def test_login_wrong_passcode_401(self, client, auth_headers, portal_world):
        c = portal_world["client"]
        client.post(f"/api/clients/{c.id}/portal", json={"passcode": "CorrectHorse1!"}, headers=auth_headers)
        resp = client.post("/api/portal/login", json={
            "email": "client@pnu.edu.sa", "passcode": "WrongPass999!",
        })
        assert resp.status_code == 401

    def test_login_unknown_email_401_uniform(self, client, auth_headers, portal_world):
        """Unknown email gets the same 401 as a wrong passcode (no enumeration)."""
        resp = client.post("/api/portal/login", json={
            "email": "nobody@nowhere.com", "passcode": "Whatever123!",
        })
        assert resp.status_code == 401

    def test_login_disabled_portal_401(self, client, auth_headers, portal_world):
        c = portal_world["client"]
        setup = client.post(f"/api/clients/{c.id}/portal", json={}, headers=auth_headers).json()
        client.delete(f"/api/clients/{c.id}/portal", headers=auth_headers)
        resp = client.post("/api/portal/login", json={
            "email": "client@pnu.edu.sa", "passcode": setup["passcode"],
        })
        assert resp.status_code == 401


class TestPortalScope:
    """Portal tokens are mutually exclusive with user tokens."""

    def test_portal_token_rejected_on_user_api(self, client, auth_headers, portal_world):
        """A portal token must never authenticate as a user."""
        c = portal_world["client"]
        setup = client.post(f"/api/clients/{c.id}/portal", json={}, headers=auth_headers).json()
        login = client.post("/api/portal/login", json={
            "email": "client@pnu.edu.sa", "passcode": setup["passcode"],
        }).json()
        portal_token = login["access_token"]

        resp = client.get("/api/clients", headers={"Authorization": f"Bearer {portal_token}"})
        assert resp.status_code == 401

    def test_user_token_rejected_on_portal_api(self, client, auth_headers):
        resp = client.get("/api/portal/overview", headers=auth_headers)
        assert resp.status_code == 401

    def test_portal_overview_scoped_to_own_client(self, client, auth_headers, db, portal_world):
        """The portal overview shows ONLY the logged-in client's projects."""
        from app.models.client import Client
        from app.models.project import Project
        c1 = portal_world["client"]
        c2 = Client(name="Other Client", contact_email="other@x.com", tenant_id=portal_world["tenant"].id)
        db.add(c2)
        db.commit()
        db.refresh(c2)
        db.add(Project(name="Mine", client_id=c1.id, tenant_id=portal_world["tenant"].id))
        db.add(Project(name="Theirs", client_id=c2.id, tenant_id=portal_world["tenant"].id))
        db.commit()

        setup = client.post(f"/api/clients/{c1.id}/portal", json={}, headers=auth_headers).json()
        login = client.post("/api/portal/login", json={
            "email": "client@pnu.edu.sa", "passcode": setup["passcode"],
        }).json()
        headers = {"Authorization": f"Bearer {login['access_token']}"}

        resp = client.get("/api/portal/overview", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        names = [p["name"] for p in data["projects"]]
        assert "Mine" in names
        assert "Theirs" not in names

    def test_portal_overview_includes_progress_and_releases(self, client, auth_headers, db, portal_world):
        from app.models.backlog_item import BacklogItem
        from app.models.project import Project
        from app.models.release import Release
        c = portal_world["client"]
        p = Project(name="PNU Cloud", client_id=c.id, tenant_id=portal_world["tenant"].id)
        db.add(p)
        db.commit()
        db.refresh(p)
        db.add(BacklogItem(project_id=p.id, title="Item A", current_phase="Requirements", status="In Progress"))
        db.add(BacklogItem(project_id=p.id, title="Item B", current_phase="Pre-Release", status="Done"))
        db.add(Release(project_id=p.id, version="1.0.0", name="Launch", status="Released", tenant_id=portal_world["tenant"].id))
        db.commit()

        setup = client.post(f"/api/clients/{c.id}/portal", json={}, headers=auth_headers).json()
        login = client.post("/api/portal/login", json={
            "email": "client@pnu.edu.sa", "passcode": setup["passcode"],
        }).json()
        headers = {"Authorization": f"Bearer {login['access_token']}"}

        resp = client.get("/api/portal/overview", headers=headers)
        data = resp.json()
        proj = data["projects"][0]
        assert proj["backlog_total"] == 2
        assert proj["backlog_done"] == 1
        assert proj["progress_pct"] == 50
        assert data["releases"][0]["version"] == "1.0.0"
        assert data["releases"][0]["status"] == "Released"
