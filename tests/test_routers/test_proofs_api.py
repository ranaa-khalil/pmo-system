"""Test item proofing — TDD.

Versioned proofs on backlog items: upload (file or URL), list, approve /
request changes. File uploads use multipart; decision stored verbatim.
"""
import io


class _Helpers:
    def _project(self, client, name="Proof Project"):
        cid = client.post("/api/clients", json={"name": name + " Client"}).json()["id"]
        return client.post("/api/projects", json={"name": name, "client_id": cid}).json()

    def _item(self, client, pid, title="Proofed item"):
        resp = client.post(f"/api/projects/{pid}/backlog", json={
            "project_id": pid, "title": title,
        })
        assert resp.status_code in (200, 201), resp.text
        return resp.json()

    def _upload(self, client, item_id, title="Mockup v1", url=None, file=None):
        data = {"title": (None, title)}
        if url:
            data["file_url"] = (None, url)
        if file:
            data["file"] = file
        return client.post(f"/api/backlog/{item_id}/proofs", files=data)


class TestProofing(_Helpers):
    """POST/GET /backlog/{id}/proofs + POST /proofs/{id}/decide."""

    def test_upload_url_proof(self, client):
        project = self._project(client)
        item = self._item(client, project["id"])
        resp = self._upload(client, item["id"], title="Design link", url="https://figma.com/file/xyz")
        assert resp.status_code == 201, resp.text
        proof = resp.json()
        assert proof["version"] == 1
        assert proof["status"] == "Pending"
        assert proof["file_url"] == "https://figma.com/file/xyz"

    def test_versions_increment(self, client):
        project = self._project(client)
        item = self._item(client, project["id"])
        self._upload(client, item["id"], title="v1", url="https://a.com/1")
        self._upload(client, item["id"], title="v2", url="https://a.com/2")
        proofs = client.get(f"/api/backlog/{item['id']}/proofs").json()
        assert len(proofs) == 2
        assert proofs[0]["version"] == 2  # newest first
        assert proofs[1]["version"] == 1

    def test_file_upload(self, client):
        project = self._project(client)
        item = self._item(client, project["id"])
        png = io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
        resp = self._upload(client, item["id"], title="Screenshot",
                            file=("shot.png", png, "image/png"))
        assert resp.status_code == 201, resp.text
        proof = resp.json()
        assert proof["file_path"] and proof["file_path"].startswith("/uploads/proofs/")

    def test_upload_requires_file_or_url(self, client):
        project = self._project(client)
        item = self._item(client, project["id"])
        resp = self._upload(client, item["id"], title="Empty")
        assert resp.status_code == 400

    def test_reject_bad_file_type(self, client):
        project = self._project(client)
        item = self._item(client, project["id"])
        exe = io.BytesIO(b"MZ" + b"0" * 64)
        resp = self._upload(client, item["id"], title="Bad",
                            file=("evil.exe", exe, "application/x-msdownload"))
        assert resp.status_code == 400

    def test_approve_proof(self, client):
        project = self._project(client)
        item = self._item(client, project["id"])
        proof = self._upload(client, item["id"], title="v1", url="https://a.com/1").json()
        resp = client.post(f"/api/proofs/{proof['id']}/decide", json={
            "decision": "Approved", "comment": "Looks great",
        })
        assert resp.status_code == 200
        decided = resp.json()
        assert decided["status"] == "Approved"
        assert decided["decision_comment"] == "Looks great"
        assert decided["decider_name"]
        assert decided["decided_at"]

    def test_request_changes(self, client):
        project = self._project(client)
        item = self._item(client, project["id"])
        proof = self._upload(client, item["id"], title="v1", url="https://a.com/1").json()
        resp = client.post(f"/api/proofs/{proof['id']}/decide", json={
            "decision": "Changes Requested", "comment": "Wrong shade of indigo",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "Changes Requested"

    def test_invalid_decision_400(self, client):
        project = self._project(client)
        item = self._item(client, project["id"])
        proof = self._upload(client, item["id"], title="v1", url="https://a.com/1").json()
        resp = client.post(f"/api/proofs/{proof['id']}/decide", json={"decision": "Maybe"})
        assert resp.status_code == 400

    def test_missing_item_404(self, client):
        resp = self._upload(client, 99999, title="X", url="https://a.com/x")
        assert resp.status_code == 404

    def test_proofs_scoped_per_item(self, client):
        project = self._project(client)
        item1 = self._item(client, project["id"], title="One")
        item2 = self._item(client, project["id"], title="Two")
        self._upload(client, item1["id"], title="v1", url="https://a.com/1")
        proofs2 = client.get(f"/api/backlog/{item2['id']}/proofs").json()
        assert proofs2 == []
