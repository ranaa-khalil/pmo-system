"""Test project status reports — TDD.

Locked-on-delivery: each send appends one hash-linked artifact_chain entry
(artifact_type="report"); delivered reports list newest first.
"""


class TestStatusReports:
    """POST /projects/{id}/reports/send + GET /projects/{id}/reports."""

    def _make_project(self, client, name="Report Project"):
        cid = client.post("/api/clients", json={"name": name + " Client"}).json()["id"]
        resp = client.post("/api/projects", json={"name": name, "client_id": cid})
        assert resp.status_code in (200, 201), resp.text
        return resp.json()

    def test_send_creates_chain_entry(self, client):
        project = self._make_project(client)
        resp = client.post(f"/api/projects/{project['id']}/reports/send")
        assert resp.status_code == 201
        body = resp.json()
        assert body["entry"]["hash"]
        assert body["entry"]["seq"] == 1
        assert body["entry"]["artifact_type"] == "report"
        assert body["report"]["project"]["id"] == project["id"]
        assert body["report"]["generated_by"]

    def test_report_counts(self, client):
        project = self._make_project(client, "Counted")
        client.post(f"/api/projects/{project['id']}/backlog", json={
            "project_id": project["id"], "title": "Item A",
        })
        client.post(f"/api/projects/{project['id']}/backlog", json={
            "project_id": project["id"], "title": "Item B",
        })
        body = client.post(f"/api/projects/{project['id']}/reports/send").json()
        report = body["report"]
        assert report["backlog"]["total"] == 2
        assert report["backlog"]["done"] == 0
        assert report["backlog"]["progress"] == 0

    def test_seq_increments_per_send(self, client):
        project = self._make_project(client, "Chained")
        first = client.post(f"/api/projects/{project['id']}/reports/send").json()
        second = client.post(f"/api/projects/{project['id']}/reports/send").json()
        assert second["entry"]["seq"] == first["entry"]["seq"] + 1

    def test_list_newest_first(self, client):
        project = self._make_project(client, "Listed")
        client.post(f"/api/projects/{project['id']}/reports/send")
        client.post(f"/api/projects/{project['id']}/reports/send")
        resp = client.get(f"/api/projects/{project['id']}/reports")
        assert resp.status_code == 200
        reports = resp.json()
        assert len(reports) == 2
        assert reports[0]["seq"] > reports[1]["seq"]
        assert reports[0]["report"]["project"]["id"] == project["id"]

    def test_missing_project_404(self, client):
        assert client.post("/api/projects/99999/reports/send").status_code == 404
        assert client.get("/api/projects/99999/reports").status_code == 404

    def test_reports_scoped_per_project(self, client):
        p1 = self._make_project(client, "One")
        p2 = self._make_project(client, "Two")
        client.post(f"/api/projects/{p1['id']}/reports/send")
        reports_p2 = client.get(f"/api/projects/{p2['id']}/reports").json()
        assert reports_p2 == []
