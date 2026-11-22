"""Cross-tenant isolation smoke test — the per-phase probe (R0, ADR-01).

The first probe in the per-phase isolation discipline: seed two tenants with
real data, then assert tenant A cannot read tenant B's data across the key
routers (projects, clients, backlog items). This test verifies the EXISTING
scoping discipline — every router query filters tenant_id == current_tenant.id
— and must pass against the current build. Expected behavior per the API as
built: cross-tenant single-resource GETs 404, list endpoints omit the other
tenant's rows, tenant-scoped backlog reads come back empty.
"""
import app.models  # noqa: F401 — register all models with Base
from app.models.backlog_item import BacklogItem
from app.models.client import Client
from app.models.project import Project
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.services.auth import hash_password


def _seed_two_tenants(db):
    """Seed tenant A (the conftest auth user's tenant) and tenant B, each with
    a client, a project and a backlog item, BEFORE any API call runs."""
    tenant_a = db.query(Tenant).filter(Tenant.slug == "test-tenant").first()
    client_a = Client(name="Tenant A Client", tenant_id=tenant_a.id)
    db.add(client_a)
    db.commit()
    db.refresh(client_a)
    project_a = Project(name="Tenant A Project", client_id=client_a.id, tenant_id=tenant_a.id)
    db.add(project_a)
    db.commit()
    db.refresh(project_a)
    item_a = BacklogItem(title="Tenant A Item", project_id=project_a.id, tenant_id=tenant_a.id)
    db.add(item_a)

    tenant_b = Tenant(name="Isolation Tenant B", slug="isolation-tenant-b", plan="enterprise", status="active")
    db.add(tenant_b)
    db.commit()
    db.refresh(tenant_b)
    user_b = User(
        email="iso-b@pmo.test",
        name="Tenant B Owner",
        hashed_password=hash_password("TestPass123!"),
        system_role="user",
        active_tenant_id=tenant_b.id,
    )
    db.add(user_b)
    db.commit()
    db.refresh(user_b)
    db.add(TenantMembership(user_id=user_b.id, tenant_id=tenant_b.id, role="owner"))
    client_b = Client(name="Tenant B Client", tenant_id=tenant_b.id)
    db.add(client_b)
    db.commit()
    db.refresh(client_b)
    project_b = Project(name="Tenant B Project", client_id=client_b.id, tenant_id=tenant_b.id)
    db.add(project_b)
    db.commit()
    db.refresh(project_b)
    item_b = BacklogItem(title="Tenant B Item", project_id=project_b.id, tenant_id=tenant_b.id)
    db.add(item_b)
    db.commit()
    return {
        "a": {"client": client_a, "project": project_a, "item": item_a},
        "b": {"tenant": tenant_b, "user": user_b, "client": client_b, "project": project_b, "item": item_b},
    }


class TestTenantIsolation:
    """Tenant A cannot read tenant B's data across the key routers."""

    def test_projects_list_omits_other_tenant_and_get_404s(self, client, db):
        """GET /api/projects never returns tenant B's project; a direct GET of
        tenant B's project id 404s (project lookup is tenant-scoped)."""
        seeded = _seed_two_tenants(db)
        project_b = seeded["b"]["project"]

        resp = client.get("/api/projects")
        assert resp.status_code == 200
        names = [p["name"] for p in resp.json()]
        assert "Tenant A Project" in names  # positive control: own tenant visible
        assert "Tenant B Project" not in names

        resp = client.get(f"/api/projects/{project_b.id}")
        assert resp.status_code == 404

    def test_clients_list_omits_other_tenant_and_get_404s(self, client, db):
        """GET /api/clients never returns tenant B's client; a direct GET of
        tenant B's client id 404s (client lookup is tenant-scoped)."""
        seeded = _seed_two_tenants(db)
        client_b = seeded["b"]["client"]

        resp = client.get("/api/clients")
        assert resp.status_code == 200
        names = [c["name"] for c in resp.json()]
        assert "Tenant A Client" in names  # positive control
        assert "Tenant B Client" not in names

        resp = client.get(f"/api/clients/{client_b.id}")
        assert resp.status_code == 404

    def test_backlog_reads_are_tenant_scoped(self, client, db):
        """Tenant A reading tenant B's project's backlog gets an empty list
        (the query filters tenant_id), and acting on tenant B's backlog item
        404s — the item lookup never matches across tenants."""
        seeded = _seed_two_tenants(db)
        project_a = seeded["a"]["project"]
        project_b = seeded["b"]["project"]
        item_b = seeded["b"]["item"]

        # Tenant A's own backlog is visible (positive control)
        resp = client.get(f"/api/projects/{project_a.id}/backlog")
        assert resp.status_code == 200
        assert [i["title"] for i in resp.json()] == ["Tenant A Item"]

        # Tenant B's project's backlog: no rows match tenant A → empty
        resp = client.get(f"/api/projects/{project_b.id}/backlog")
        assert resp.status_code == 200
        assert resp.json() == []

        # Item-level access to tenant B's item 404s (update path is tenant-scoped)
        resp = client.put(f"/api/backlog/{item_b.id}", json={"title": "hijacked"})
        assert resp.status_code == 404
