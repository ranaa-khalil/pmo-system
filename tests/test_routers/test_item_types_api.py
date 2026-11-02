"""Test the ItemType vocabulary API — TDD.

Tenant-scoped vocabulary, seeded from the standardized defaults on first
read; custom types CRUD; duplicate/color validation.
"""


class TestItemTypes:
    """GET/POST/PUT/DELETE /api/item-types."""

    def test_seeded_defaults_on_first_read(self, client):
        resp = client.get("/api/item-types")
        assert resp.status_code == 200
        types = resp.json()
        keys = [t["key"] for t in types]
        assert "Feature" in keys and "Bug" in keys and "Enhancement" in keys
        assert all(t["is_active"] for t in types)

    def test_seeding_is_idempotent(self, client):
        first = client.get("/api/item-types").json()
        second = client.get("/api/item-types").json()
        assert len(first) == len(second)

    def test_create_custom_type(self, client):
        resp = client.post("/api/item-types", json={
            "key": "Research", "label": "Research", "color": "indigo",
        })
        assert resp.status_code == 201
        created = resp.json()
        assert created["key"] == "Research"
        assert created["color"] == "indigo"
        keys = [t["key"] for t in client.get("/api/item-types").json()]
        assert "Research" in keys

    def test_duplicate_key_400(self, client):
        client.post("/api/item-types", json={"key": "Spike", "label": "Spike"})
        resp = client.post("/api/item-types", json={"key": "Spike", "label": "Spike 2"})
        assert resp.status_code == 400

    def test_invalid_color_400(self, client):
        resp = client.post("/api/item-types", json={
            "key": "Neon", "label": "Neon", "color": "hotpink",
        })
        assert resp.status_code == 400

    def test_update_type(self, client):
        created = client.post("/api/item-types", json={
            "key": "Spike", "label": "Spike", "color": "ink",
        }).json()
        resp = client.put(f"/api/item-types/{created['id']}", json={
            "label": "Tech Spike", "color": "violet",
        })
        assert resp.status_code == 200
        assert resp.json()["label"] == "Tech Spike"

    def test_deactivate_hides_from_default_list(self, client):
        created = client.post("/api/item-types", json={
            "key": "Temp", "label": "Temp",
        }).json()
        client.put(f"/api/item-types/{created['id']}", json={"is_active": False})
        keys = [t["key"] for t in client.get("/api/item-types").json()]
        assert "Temp" not in keys
        keys_all = [t["key"] for t in client.get("/api/item-types?include_inactive=true").json()]
        assert "Temp" in keys_all

    def test_delete_type(self, client):
        created = client.post("/api/item-types", json={
            "key": "Gone", "label": "Gone",
        }).json()
        resp = client.delete(f"/api/item-types/{created['id']}")
        assert resp.status_code == 200
        keys = [t["key"] for t in client.get("/api/item-types").json()]
        assert "Gone" not in keys

    def test_update_missing_404(self, client):
        assert client.put("/api/item-types/99999", json={"label": "X"}).status_code == 404
