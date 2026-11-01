"""Test per-user UI preferences — TDD."""


class TestPreferencesAPI:
    """GET/PUT /api/me/preferences: allow-listed keys, JSON round-trip."""

    def test_get_empty(self, client):
        """GET with no stored preferences returns {}."""
        resp = client.get("/api/me/preferences")
        assert resp.status_code == 200
        assert resp.json() == {}

    def test_put_roundtrip(self, client):
        """PUT stores a JSON value; GET returns it decoded."""
        resp = client.put("/api/me/preferences", json={
            "key": "dashboard_widgets",
            "value": ["stats", "briefing", "charts"],
        })
        assert resp.status_code == 200
        resp = client.get("/api/me/preferences")
        assert resp.json()["dashboard_widgets"] == ["stats", "briefing", "charts"]

    def test_put_upserts_existing_key(self, client):
        """PUT on the same key replaces the value (no duplicate rows)."""
        client.put("/api/me/preferences", json={"key": "task_view_mode", "value": "list"})
        client.put("/api/me/preferences", json={"key": "task_view_mode", "value": "board"})
        resp = client.get("/api/me/preferences")
        assert resp.json()["task_view_mode"] == "board"

    def test_unknown_key_400(self, client):
        """PUT with a key outside the allow-list 400s."""
        resp = client.put("/api/me/preferences", json={"key": "theme_hax", "value": "dark"})
        assert resp.status_code == 400
        assert "Allowed" in resp.json()["detail"]

    def test_no_auth_401(self, anon_client):
        """Preferences require authentication."""
        resp = anon_client.get("/api/me/preferences")
        assert resp.status_code == 401

    def test_preferences_are_per_user(self, client, db):
        """Another user does not see this user's preferences."""
        from app.models.tenant import TenantMembership
        from app.models.user import User
        from app.services.auth import create_access_token, hash_password

        client.put("/api/me/preferences", json={"key": "task_view_mode", "value": "board"})

        tenant_id = db.query(TenantMembership).first().tenant_id
        other = User(
            email="pref-other@pmo.test",
            name="Pref Other",
            hashed_password=hash_password("OtherPass123!"),
            system_role="member",
            active_tenant_id=tenant_id,
        )
        db.add(other)
        db.commit()
        db.refresh(other)
        db.add(TenantMembership(user_id=other.id, tenant_id=tenant_id, role="member"))
        db.commit()

        token = create_access_token({"sub": str(other.id)})
        original = client.headers.get("Authorization")
        client.headers.update({"Authorization": f"Bearer {token}"})
        try:
            resp = client.get("/api/me/preferences")
            assert resp.json() == {}
        finally:
            client.headers.update({"Authorization": original})
