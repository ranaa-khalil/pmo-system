"""Test the Tags API — cross-tagging pool (TDD)."""


class TestTagsAPI:
    """Tests for tag endpoints: pool CRUD, attach/detach on items and tasks."""

    def _create_project(self, client):
        resp = client.post("/api/clients", json={"name": "Tag Client"})
        cid = resp.json()["id"]
        resp = client.post("/api/projects", json={"name": "Tag Project", "client_id": cid})
        return resp.json()["id"]

    def _create_tag(self, client, name="Urgent", color="rose"):
        resp = client.post("/api/tags", json={"name": name, "color": color})
        assert resp.status_code == 201, resp.text
        return resp.json()

    # ---- Pool CRUD ----

    def test_create_tag(self, client):
        """POST /api/tags creates a tag in the tenant pool."""
        data = self._create_tag(client)
        assert data["name"] == "Urgent"
        assert data["color"] == "rose"
        assert data["item_count"] == 0

    def test_duplicate_tag_409(self, client):
        """POST /api/tags with a duplicate name 409s."""
        self._create_tag(client, "Launch")
        resp = client.post("/api/tags", json={"name": "Launch"})
        assert resp.status_code == 409

    def test_empty_name_400(self, client):
        """POST /api/tags with an empty name 400s."""
        resp = client.post("/api/tags", json={"name": "   "})
        assert resp.status_code == 400

    def test_invalid_color_400(self, client):
        """POST /api/tags with a color outside the palette 400s."""
        resp = client.post("/api/tags", json={"name": "X", "color": "chartreuse"})
        assert resp.status_code == 400

    def test_list_tags(self, client):
        """GET /api/tags returns the tenant pool."""
        self._create_tag(client, "Alpha")
        self._create_tag(client, "Beta")
        resp = client.get("/api/tags")
        assert resp.status_code == 200
        names = [t["name"] for t in resp.json()]
        assert names == ["Alpha", "Beta"]  # ordered by name

    def test_delete_tag(self, client):
        """DELETE /api/tags/{id} removes the tag."""
        data = self._create_tag(client, "Temp")
        resp = client.delete(f"/api/tags/{data['id']}")
        assert resp.status_code == 200
        resp = client.get("/api/tags")
        assert resp.json() == []

    # ---- Attach/detach: backlog items ----

    def test_attach_tag_to_item(self, client):
        """POST /api/backlog/{id}/tags attaches a tag."""
        pid = self._create_project(client)
        resp = client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": "Item A"})
        bid = resp.json()["id"]
        tag = self._create_tag(client, "Infra")
        resp = client.post(f"/api/backlog/{bid}/tags", json={"tag_id": tag["id"]})
        assert resp.status_code == 201, resp.text
        pool = client.get("/api/tags").json()
        assert pool[0]["item_count"] == 1

    def test_attach_tag_idempotent(self, client):
        """Attaching the same tag twice returns 200 the second time."""
        pid = self._create_project(client)
        resp = client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": "Item B"})
        bid = resp.json()["id"]
        tag = self._create_tag(client, "Once")
        client.post(f"/api/backlog/{bid}/tags", json={"tag_id": tag["id"]})
        resp = client.post(f"/api/backlog/{bid}/tags", json={"tag_id": tag["id"]})
        assert resp.status_code == 200
        assert resp.json()["detail"] == "Tag already attached"

    def test_detach_tag_from_item(self, client):
        """DELETE /api/backlog/{id}/tags/{tag_id} detaches."""
        pid = self._create_project(client)
        resp = client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": "Item C"})
        bid = resp.json()["id"]
        tag = self._create_tag(client, "Detach")
        client.post(f"/api/backlog/{bid}/tags", json={"tag_id": tag["id"]})
        resp = client.delete(f"/api/backlog/{bid}/tags/{tag['id']}")
        assert resp.status_code == 200
        pool = client.get("/api/tags").json()
        assert pool[0]["item_count"] == 0

    def test_detach_unattached_tag_404(self, client):
        """Detaching a tag that is not attached 404s."""
        pid = self._create_project(client)
        resp = client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": "Item D"})
        bid = resp.json()["id"]
        tag = self._create_tag(client, "Never")
        resp = client.delete(f"/api/backlog/{bid}/tags/{tag['id']}")
        assert resp.status_code == 404

    def test_attach_unknown_tag_404(self, client):
        """Attaching a tag id from another workspace 404s."""
        pid = self._create_project(client)
        resp = client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": "Item E"})
        bid = resp.json()["id"]
        resp = client.post(f"/api/backlog/{bid}/tags", json={"tag_id": 99999})
        assert resp.status_code == 404

    # ---- Attach/detach: user tasks ----

    def test_attach_tag_to_task(self, client):
        """POST /api/tasks/{id}/tags attaches a tag to a personal task."""
        resp = client.post("/api/tasks", json={"title": "Follow up"})
        tid = resp.json()["id"]
        tag = self._create_tag(client, "Admin")
        resp = client.post(f"/api/tasks/{tid}/tags", json={"tag_id": tag["id"]})
        assert resp.status_code == 201
        pool = client.get("/api/tags").json()
        assert pool[0]["task_count"] == 1

    def test_detach_tag_from_task(self, client):
        """DELETE /api/tasks/{id}/tags/{tag_id} detaches from a task."""
        resp = client.post("/api/tasks", json={"title": "Follow up 2"})
        tid = resp.json()["id"]
        tag = self._create_tag(client, "Remove")
        client.post(f"/api/tasks/{tid}/tags", json={"tag_id": tag["id"]})
        resp = client.delete(f"/api/tasks/{tid}/tags/{tag['id']}")
        assert resp.status_code == 200
        pool = client.get("/api/tags").json()
        assert pool[0]["task_count"] == 0

    # ---- Cross-tagging: one tag, many items (no duplication) ----

    def test_one_tag_many_items(self, client):
        """A single tag can attach to multiple items without duplication."""
        pid = self._create_project(client)
        tag = self._create_tag(client, "Shared")
        for n in range(3):
            resp = client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": f"Item {n}"})
            client.post(f"/api/backlog/{resp.json()['id']}/tags", json={"tag_id": tag["id"]})
        pool = client.get("/api/tags").json()
        assert pool[0]["item_count"] == 3
        assert len(pool) == 1  # one tag, many links — no duplicates

    # ---- Work filter ----

    def test_work_filter_by_tag(self, client):
        """GET /api/work?tag_id= returns only items carrying that tag."""
        pid = self._create_project(client)
        tag = self._create_tag(client, "Filtered")
        r1 = client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": "Tagged"})
        client.post(f"/api/projects/{pid}/backlog", json={"project_id": pid, "title": "Untagged"})
        client.post(f"/api/backlog/{r1.json()['id']}/tags", json={"tag_id": tag["id"]})
        resp = client.get(f"/api/work?tag_id={tag['id']}")
        assert resp.status_code == 200
        titles = [it["title"] for it in resp.json()["items"]]
        assert titles == ["Tagged"]

    def test_work_filter_unknown_tag_404(self, client):
        """GET /api/work?tag_id= with a foreign tag id 404s."""
        resp = client.get("/api/work?tag_id=99999")
        assert resp.status_code == 404
