"""API tests for the template builder (P4.4).

GET /api/lifecycle/types — custom + built-in types
POST /api/lifecycle/templates — define/replace a tenant lifecycle
GET /api/lifecycle/{type} — tenant override wins
DELETE /api/lifecycle/templates/{id} — remove (falls back to built-in)
"""
from app.models.lifecycle_template import TenantLifecycleTemplate

_TEMPLATE = {
    "project_type": "Research",
    "name": "Research Study",
    "item_phases": ["Proposal", "Collection", "Analysis", "Writeup"],
    "release_stages": ["Proposal", "Fieldwork", "Analysis", "Publication"],
    "gate_deliverables": {"Proposal": ["Study plan"]},
    "gate_roles": {"Proposal": "Product Manager"},
    "fields": [{"name": "sample_size", "label": "Sample size", "type": "text"}],
}


def test_create_and_resolve_custom_template(client, db, auth_user):
    resp = client.post("/api/lifecycle/templates", json=_TEMPLATE)
    assert resp.status_code == 201
    data = resp.json()
    assert data["project_type"] == "research"  # normalized lowercase

    # The custom type resolves with the tenant's vocabulary
    resp2 = client.get("/api/lifecycle/research")
    assert resp2.status_code == 200
    t = resp2.json()
    assert t["name"] == "Research Study"
    assert t["item_phases"][0] == "Proposal"
    assert t["custom"] is True


def test_types_lists_custom_and_builtin(client, db, auth_user):
    client.post("/api/lifecycle/templates", json=_TEMPLATE)
    resp = client.get("/api/lifecycle/types")
    assert resp.status_code == 200
    types = resp.json()
    keys = {t["key"] for t in types}
    assert "research" in keys and "software" in keys
    assert any(t["custom"] for t in types)


def test_replace_existing_template(client, db, auth_user):
    client.post("/api/lifecycle/templates", json=_TEMPLATE)
    replaced = dict(_TEMPLATE, name="Research v2", item_phases=["X", "Y"])
    resp = client.post("/api/lifecycle/templates", json=replaced)
    assert resp.status_code == 201
    rows = db.query(TenantLifecycleTemplate).all()
    assert len(rows) == 1
    assert rows[0].name == "Research v2"


def test_delete_falls_back_to_builtin(client, db, auth_user):
    created = client.post("/api/lifecycle/templates", json=_TEMPLATE).json()
    resp = client.delete(f"/api/lifecycle/templates/{created['id']}")
    assert resp.status_code == 200
    resp2 = client.get("/api/lifecycle/research")
    assert resp2.json()["custom"] is False
    assert resp2.json()["name"] == "Software"  # unknown key falls back


def test_other_tenant_template_404(client, db, auth_user):
    from app.models.tenant import Tenant

    other = Tenant(name="OT", slug="ot", plan="enterprise", status="active")
    db.add(other)
    db.commit()
    db.refresh(other)
    row = TenantLifecycleTemplate(
        tenant_id=other.id, project_type="theirs", name="Theirs",
        item_phases=["X"], release_stages=["X"],
        gate_deliverables={}, gate_roles={}, fields=[],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    resp = client.delete(f"/api/lifecycle/templates/{row.id}")
    assert resp.status_code == 404


def test_validation_requires_phases(client, db, auth_user):
    bad = dict(_TEMPLATE, item_phases=[])
    resp = client.post("/api/lifecycle/templates", json=bad)
    assert resp.status_code == 400
