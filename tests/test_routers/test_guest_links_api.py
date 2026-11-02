"""Test the guest approval link API — TDD."""


class TestGuestLinksAPI:
    """Tokenized links: create/list/revoke + public view/decide."""

    def _create_approval(self, client):
        resp = client.post("/api/clients", json={"name": "Guest Client"})
        cid = resp.json()["id"]
        pid = client.post("/api/projects", json={"name": "Guest Project", "client_id": cid}).json()["id"]
        approval = client.post(f"/api/projects/{pid}/approvals", json={
            "project_id": pid,
            "title": "Guest Gate",
            "request_type": "release",
            "steps": [
                {"role_name": "Product Owner", "step_order": 1},
                {"role_name": "Tech Lead", "step_order": 2},
            ],
        }).json()
        return pid, approval

    # ---- Authenticated: create/list/revoke ----

    def test_create_guest_link(self, client):
        """POST guest-links returns a tokenized URL."""
        pid, approval = self._create_approval(client)
        resp = client.post(f"/api/approvals/{approval['id']}/guest-links", json={
            "label": "Client Stakeholder",
            "expires_in_days": 7,
        })
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["url"].startswith("/guest/approval/")
        assert data["has_password"] is False
        assert len(data["token"]) >= 20

    def test_create_link_bound_to_step(self, client):
        """A link can bind to a specific RACI step."""
        pid, approval = self._create_approval(client)
        step_id = approval["steps"][0]["id"]
        resp = client.post(f"/api/approvals/{approval['id']}/guest-links", json={
            "step_id": step_id, "expires_in_days": 3,
        })
        assert resp.status_code == 201
        assert resp.json()["step_id"] == step_id

    def test_create_link_with_password(self, client):
        """A link can carry a password (stored hashed)."""
        pid, approval = self._create_approval(client)
        resp = client.post(f"/api/approvals/{approval['id']}/guest-links", json={
            "password": "Secret123!", "expires_in_days": 7,
        })
        assert resp.status_code == 201
        assert resp.json()["has_password"] is True
        assert "password" not in resp.json()["token"]

    def test_create_link_unknown_step_404(self, client):
        """Binding to a step from another request 404s."""
        pid, approval = self._create_approval(client)
        _, other = self._create_approval(client)
        resp = client.post(f"/api/approvals/{approval['id']}/guest-links", json={
            "step_id": other["steps"][0]["id"],
        })
        assert resp.status_code == 404

    def test_create_link_bad_expiry_400(self, client):
        """expires_in_days outside 1-90 400s."""
        pid, approval = self._create_approval(client)
        resp = client.post(f"/api/approvals/{approval['id']}/guest-links", json={"expires_in_days": 0})
        assert resp.status_code == 400

    def test_list_and_revoke(self, client):
        """List returns links; revoke marks them (decisions then 410)."""
        pid, approval = self._create_approval(client)
        link = client.post(f"/api/approvals/{approval['id']}/guest-links", json={}).json()
        links = client.get(f"/api/approvals/{approval['id']}/guest-links").json()
        assert len(links) == 1
        resp = client.delete(f"/api/guest-links/{link['id']}")
        assert resp.status_code == 200
        links = client.get(f"/api/approvals/{approval['id']}/guest-links").json()
        assert links[0]["revoked"] is True
        # Revoked link: public view 410
        resp = client.get(f"/api/guest/approvals/{link['token']}")
        assert resp.status_code == 410

    # ---- Public: view ----

    def test_public_view(self, client):
        """GET /api/guest/approvals/{token} returns the read-only summary."""
        pid, approval = self._create_approval(client)
        link = client.post(f"/api/approvals/{approval['id']}/guest-links", json={
            "label": "ACME Corp",
        }).json()
        resp = client.get(f"/api/guest/approvals/{link['token']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["request"]["title"] == "Guest Gate"
        assert data["request"]["project_name"] == "Guest Project"
        assert len(data["steps"]) == 2
        assert data["label"] == "ACME Corp"
        assert data["can_decide"] is True

    def test_public_view_unknown_token_404(self, client):
        """An unknown token 404s."""
        resp = client.get("/api/guest/approvals/not-a-real-token")
        assert resp.status_code == 404

    def test_public_view_password_link_no_leak(self, client):
        """A password link requires the password before deciding."""
        pid, approval = self._create_approval(client)
        link = client.post(f"/api/approvals/{approval['id']}/guest-links", json={
            "password": "Secret123!",
        }).json()
        resp = client.get(f"/api/guest/approvals/{link['token']}")
        assert resp.status_code == 200
        assert resp.json()["has_password"] is True

    # ---- Public: decide ----

    def test_guest_decide_bound_step_advances_chain(self, client):
        """A guest decision on a bound step advances the chain like in-app."""
        pid, approval = self._create_approval(client)
        step_id = approval["steps"][0]["id"]
        link = client.post(f"/api/approvals/{approval['id']}/guest-links", json={
            "step_id": step_id,
        }).json()
        resp = client.post(f"/api/guest/approvals/{link['token']}/decide", json={
            "decision": "Approved", "comment": "Looks good", "guest_name": "Dana",
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["request_status"] == "Pending"
        # Chain advanced to step 2
        detail = client.get(f"/api/approvals/{approval['id']}").json()
        assert detail["current_step"] == 2
        assert detail["steps"][0]["status"] == "Approved"
        assert "Dana (guest)" in detail["steps"][0]["comment"]

    def test_guest_decide_last_step_completes(self, client):
        """Approving the last step via a guest link completes the request."""
        pid, approval = self._create_approval(client)
        approval["steps"][0]
        # Approve step 1 in-app first
        client.post(f"/api/approvals/{approval['id']}/steps/{approval['steps'][0]['id']}/approve")
        step2 = approval["steps"][1]["id"]
        link = client.post(f"/api/approvals/{approval['id']}/guest-links", json={
            "step_id": step2,
        }).json()
        resp = client.post(f"/api/guest/approvals/{link['token']}/decide", json={
            "decision": "Approved",
        })
        assert resp.status_code == 200
        assert resp.json()["request_status"] == "Approved"
        detail = client.get(f"/api/approvals/{approval['id']}").json()
        assert detail["status"] == "Approved"

    def test_guest_decide_wrong_current_step_400(self, client):
        """A guest cannot decide a non-current step."""
        pid, approval = self._create_approval(client)
        step2 = approval["steps"][1]["id"]
        link = client.post(f"/api/approvals/{approval['id']}/guest-links", json={
            "step_id": step2,
        }).json()
        resp = client.post(f"/api/guest/approvals/{link['token']}/decide", json={"decision": "Approved"})
        assert resp.status_code == 400
        assert "current step" in resp.json()["detail"]

    def test_guest_decide_rejects(self, client):
        """A guest rejection marks the request Rejected."""
        pid, approval = self._create_approval(client)
        step_id = approval["steps"][0]["id"]
        link = client.post(f"/api/approvals/{approval['id']}/guest-links", json={"step_id": step_id}).json()
        resp = client.post(f"/api/guest/approvals/{link['token']}/decide", json={
            "decision": "Rejected", "comment": "Scope unclear",
        })
        assert resp.status_code == 200
        assert resp.json()["request_status"] == "Rejected"

    def test_guest_decide_advisory(self, client):
        """An unbound link records an advisory decision without touching the chain."""
        pid, approval = self._create_approval(client)
        link = client.post(f"/api/approvals/{approval['id']}/guest-links", json={}).json()
        resp = client.post(f"/api/guest/approvals/{link['token']}/decide", json={
            "decision": "Approved", "guest_name": "Advisor",
        })
        assert resp.status_code == 200
        detail = client.get(f"/api/approvals/{approval['id']}").json()
        assert detail["status"] == "Pending"  # chain untouched
        assert detail["current_step"] == 1
        # Decision recorded on the public view
        view = client.get(f"/api/guest/approvals/{link['token']}").json()
        assert len(view["guest_decisions"]) == 1
        assert view["guest_decisions"][0]["guest_name"] == "Advisor"

    def test_guest_decide_wrong_password_401(self, client):
        """A password link rejects a wrong password."""
        pid, approval = self._create_approval(client)
        link = client.post(f"/api/approvals/{approval['id']}/guest-links", json={
            "step_id": approval["steps"][0]["id"], "password": "Secret123!",
        }).json()
        resp = client.post(f"/api/guest/approvals/{link['token']}/decide", json={
            "decision": "Approved", "password": "wrong",
        })
        assert resp.status_code == 401

    def test_guest_decide_right_password(self, client):
        """The correct password lets the guest decide."""
        pid, approval = self._create_approval(client)
        link = client.post(f"/api/approvals/{approval['id']}/guest-links", json={
            "step_id": approval["steps"][0]["id"], "password": "Secret123!",
        }).json()
        resp = client.post(f"/api/guest/approvals/{link['token']}/decide", json={
            "decision": "Approved", "password": "Secret123!",
        })
        assert resp.status_code == 200

    def test_guest_decide_bad_decision_400(self, client):
        """decision outside Approved/Rejected 400s."""
        pid, approval = self._create_approval(client)
        link = client.post(f"/api/approvals/{approval['id']}/guest-links", json={}).json()
        resp = client.post(f"/api/guest/approvals/{link['token']}/decide", json={
            "decision": "Maybe",
        })
        assert resp.status_code == 400

    def test_guest_decide_needs_no_auth(self, anon_client):
        """The decide endpoint is public (token IS the credential)."""
        resp = anon_client.post("/api/guest/approvals/no-token/decide", json={"decision": "Approved"})
        assert resp.status_code == 404
