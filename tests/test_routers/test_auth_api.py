"""Test the Auth API endpoints — login, me, tenant switching, password reset.

Registration was replaced by super-admin tenant creation: the owner user is
created via POST /api/admin/tenants (CreateTenantRequest), so the auth tests
exercise that flow instead of the old self-registration.
"""
from app.models.user import User
from app.services.auth import hash_password


class TestAuthAPI:
    """Tests for /api/auth endpoints."""

    def _create_owner(self, db):
        """Helper: create a tenant owner via the admin tenant endpoint."""
        resp = client_post_tenant(db)
        return resp

    def test_login_with_valid_credentials(self, client, db):
        """POST /api/auth/login with valid credentials returns JWT token."""
        from app.models.tenant import Tenant, TenantMembership

        tenant = Tenant(name="Auth Co", slug="auth-co", plan="team")
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        user = User(
            email="owner@authco.example.com",
            name="Owner",
            hashed_password=hash_password("SecurePass123!"),
            system_role="member",
            active_tenant_id=tenant.id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.add(TenantMembership(user_id=user.id, tenant_id=tenant.id, role="owner"))
        db.commit()

        response = client.post("/api/auth/login", json={
            "email": "owner@authco.example.com",
            "password": "SecurePass123!",
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert len(data["access_token"]) > 20

    def test_login_with_invalid_password_returns_401(self, client, db):
        """POST /api/auth/login with wrong password returns 401."""
        from app.models.tenant import Tenant, TenantMembership

        tenant = Tenant(name="Auth Co 2", slug="auth-co-2", plan="team")
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        user = User(
            email="owner2@authco.example.com",
            name="Owner 2",
            hashed_password=hash_password("SecurePass123!"),
            system_role="member",
            active_tenant_id=tenant.id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.add(TenantMembership(user_id=user.id, tenant_id=tenant.id, role="owner"))
        db.commit()

        response = client.post("/api/auth/login", json={
            "email": "owner2@authco.example.com",
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

    def test_get_me_with_valid_token(self, client, db):
        """GET /api/auth/me with valid token returns user info."""
        from app.models.tenant import Tenant, TenantMembership

        tenant = Tenant(name="Auth Co 3", slug="auth-co-3", plan="team")
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        user = User(
            email="owner3@authco.example.com",
            name="Rana Khalil",
            hashed_password=hash_password("SecurePass123!"),
            system_role="member",
            active_tenant_id=tenant.id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.add(TenantMembership(user_id=user.id, tenant_id=tenant.id, role="owner"))
        db.commit()

        login_resp = client.post("/api/auth/login", json={
            "email": "owner3@authco.example.com",
            "password": "SecurePass123!",
        })
        token = login_resp.json()["access_token"]

        response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "owner3@authco.example.com"
        assert data["full_name"] == "Rana Khalil"

    def test_get_me_without_token_returns_401(self, anon_client):
        """GET /api/auth/me without token returns 401."""
        response = anon_client.get("/api/auth/me")
        assert response.status_code == 401

    def test_get_me_with_invalid_token_returns_401(self, anon_client):
        """GET /api/auth/me with invalid token returns 401."""
        response = anon_client.get("/api/auth/me", headers={"Authorization": "Bearer invalidtoken123"})
        assert response.status_code == 401

    def test_admin_create_tenant_and_login(self, client, anon_client):
        """POST /api/admin/tenants (super_admin) creates a tenant + owner who can log in."""
        resp = client.post("/api/admin/tenants", json={
            "tenant_name": "NITC Cloud",
            "owner_name": "NITC Owner",
            "owner_email": "owner@nitc.example.com",
            "owner_password": "OwnerPass123!",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["tenant_slug"] == "nitc-cloud"
        assert data["owner_email"] == "owner@nitc.example.com"

        login = anon_client.post("/api/auth/login", json={
            "email": "owner@nitc.example.com",
            "password": "OwnerPass123!",
        })
        assert login.status_code == 200
        assert login.json()["access_token"]

    def test_admin_create_tenant_requires_super_admin(self, anon_client, db):
        """Non-super-admin gets 403 from POST /api/admin/tenants."""
        from app.models.tenant import Tenant, TenantMembership

        tenant = Tenant(name="Member Co", slug="member-co", plan="free")
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        member = User(
            email="member@co.example.com",
            name="Member",
            hashed_password=hash_password("MemberPass123!"),
            system_role="member",
            active_tenant_id=tenant.id,
        )
        db.add(member)
        db.commit()
        db.refresh(member)
        db.add(TenantMembership(user_id=member.id, tenant_id=tenant.id, role="member"))
        db.commit()

        token_resp = anon_client.post("/api/auth/login", json={
            "email": "member@co.example.com", "password": "MemberPass123!",
        })
        headers = {"Authorization": f"Bearer {token_resp.json()['access_token']}"}
        resp = anon_client.post("/api/admin/tenants", json={
            "tenant_name": "Sneaky Co",
            "owner_name": "Sneaky",
            "owner_email": "sneaky@co.example.com",
            "owner_password": "SneakyPass123!",
        }, headers=headers)
        assert resp.status_code == 403

    def test_admin_create_tenant_duplicate_email_400(self, client, db):
        """Creating a tenant with an existing owner email returns 400."""
        from app.models.tenant import Tenant, TenantMembership

        # An existing user (not created via the admin endpoint)
        tenant = Tenant(name="Existing Co", slug="existing-co", plan="free")
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        existing = User(
            email="taken@example.com",
            name="Taken",
            hashed_password=hash_password("Exists123!"),
            system_role="member",
            active_tenant_id=tenant.id,
        )
        db.add(existing)
        db.commit()
        db.refresh(existing)
        db.add(TenantMembership(user_id=existing.id, tenant_id=tenant.id, role="owner"))
        db.commit()

        resp = client.post("/api/admin/tenants", json={
            "tenant_name": "Second Co",
            "owner_name": "Dup",
            "owner_email": "taken@example.com",
            "owner_password": "OwnerPass123!",
        })
        assert resp.status_code == 400
