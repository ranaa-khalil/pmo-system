"""Test task subtasks (checklists) — TDD."""


class TestTaskSubtasks:
    """Subtasks: create with parent, one-level guard, list, permissions."""

    def test_create_subtask(self, client):
        """POST /api/tasks with parent_task_id creates a subtask (route default 200)."""
        parent = client.post("/api/tasks", json={"title": "Prepare launch"}).json()
        resp = client.post("/api/tasks", json={
            "title": "Write changelog",
            "parent_task_id": parent["id"],
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["parent_task_id"] == parent["id"]
        assert data["status"] == "Pending"

    def test_unknown_parent_404(self, client):
        """Subtask with an unknown parent 404s."""
        resp = client.post("/api/tasks", json={"title": "Orphan", "parent_task_id": 99999})
        assert resp.status_code == 404

    def test_no_nested_subtasks(self, client):
        """A subtask cannot itself be a parent (one level only, 400)."""
        parent = client.post("/api/tasks", json={"title": "Parent"}).json()
        sub = client.post("/api/tasks", json={"title": "Sub", "parent_task_id": parent["id"]}).json()
        resp = client.post("/api/tasks", json={"title": "Sub-sub", "parent_task_id": sub["id"]})
        assert resp.status_code == 400
        assert "one level" in resp.json()["detail"]

    def test_list_subtasks(self, client):
        """GET /api/tasks/{id}/subtasks returns the checklist + done counts."""
        parent = client.post("/api/tasks", json={"title": "Checklist"}).json()
        client.post("/api/tasks", json={"title": "Step 1", "parent_task_id": parent["id"]})
        client.post("/api/tasks", json={"title": "Step 2", "parent_task_id": parent["id"]})
        client.post("/api/tasks", json={"title": "Step 3", "parent_task_id": parent["id"]})
        resp = client.get(f"/api/tasks/{parent['id']}/subtasks")
        assert resp.status_code == 200
        data = resp.json()
        assert data["parent_id"] == parent["id"]
        assert data["total"] == 3
        assert data["done"] == 0
        assert len(data["subtasks"]) == 3

    def test_subtask_completion_counts(self, client):
        """Completing a subtask moves the done counter."""
        parent = client.post("/api/tasks", json={"title": "Ship"}).json()
        sub = client.post("/api/tasks", json={"title": "Tag build", "parent_task_id": parent["id"]}).json()
        client.put(f"/api/tasks/{sub['id']}", json={"status": "Completed"})
        resp = client.get(f"/api/tasks/{parent['id']}/subtasks")
        assert resp.json()["done"] == 1
        assert resp.json()["total"] == 1

    def test_subtasks_of_other_user_403(self, client, db):
        """Another user's task subtasks 403 (only assignee/creator/super_admin)."""
        from app.models.tenant import TenantMembership
        from app.models.user import User
        from app.services.auth import create_access_token, hash_password

        resp = client.post("/api/tasks", json={"title": "Private task"})
        tid = resp.json()["id"]

        tenant_id = db.query(TenantMembership).first().tenant_id
        other = User(
            email="other@pmo.test",
            name="Other User",
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
        import os
        original = client.headers.get("Authorization")
        client.headers.update({"Authorization": f"Bearer {token}"})
        try:
            resp = client.get(f"/api/tasks/{tid}/subtasks")
            assert resp.status_code == 403
        finally:
            client.headers.update({"Authorization": original})

    def test_deleting_parent_cascades_subtasks(self, client, db):
        """Deleting a parent task removes its subtasks (CASCADE)."""
        from app.models.user_task import UserTask

        parent = client.post("/api/tasks", json={"title": " doomed"}).json()
        sub = client.post("/api/tasks", json={"title": "child", "parent_task_id": parent["id"]}).json()
        client.delete(f"/api/tasks/{parent['id']}")
        remaining = db.query(UserTask).filter(UserTask.id == sub["id"]).first()
        assert remaining is None
