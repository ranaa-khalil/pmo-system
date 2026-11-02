"""Test the MCP server — TDD.

JSON-RPC 2.0 over HTTP: initialize → tools/list → tools/call, JWT-protected,
tenant-scoped. Tool errors surface as MCP tool errors, not 500s.
"""
import json


class _Helpers:
    def _rpc(self, client, method, id_=1, params=None):
        body = {"jsonrpc": "2.0", "id": id_, "method": method}
        if params is not None:
            body["params"] = params
        return client.post("/api/mcp", json=body)

    def _project(self, client, name="MCP Project"):
        cid = client.post("/api/clients", json={"name": name + " Client"}).json()["id"]
        return client.post("/api/projects", json={"name": name, "client_id": cid}).json()

    def _item(self, client, pid, title="MCP item"):
        return client.post(f"/api/projects/{pid}/backlog", json={
            "project_id": pid, "title": title,
        }).json()


class TestMCPServer(_Helpers):
    """POST /api/mcp: initialize, tools/list, tools/call."""

    def test_initialize(self, client):
        resp = self._rpc(client, "initialize", params={})
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert result["protocolVersion"] == "2024-11-05"
        assert result["serverInfo"]["name"] == "pmo-system"
        assert "tools" in result["capabilities"]

    def test_tools_list(self, client):
        result = self._rpc(client, "tools/list", params={}).json()["result"]
        names = {t["name"] for t in result["tools"]}
        assert {"list_projects", "get_item", "create_backlog_item",
                "get_status_report", "list_approvals"} <= names
        assert all("inputSchema" in t for t in result["tools"])

    def test_list_projects(self, client):
        project = self._project(client, "Listed")
        result = self._rpc(client, "tools/call", params={
            "name": "list_projects", "arguments": {},
        }).json()["result"]
        assert result["isError"] is False
        payload = json.loads(result["content"][0]["text"])
        assert any(p["id"] == project["id"] for p in payload["projects"])

    def test_create_and_read_item(self, client):
        project = self._project(client, "Crud")
        result = self._rpc(client, "tools/call", params={
            "name": "create_backlog_item",
            "arguments": {"project_id": project["id"], "title": "MCP created",
                          "item_type": "Feature", "priority": "High"},
        }).json()["result"]
        payload = json.loads(result["content"][0]["text"])
        assert payload["created"]["title"] == "MCP created"
        assert payload["created"]["status"] == "Draft"

        item_id = payload["created"]["id"]
        result = self._rpc(client, "tools/call", params={
            "name": "get_item", "arguments": {"item_id": item_id},
        }).json()["result"]
        payload = json.loads(result["content"][0]["text"])
        assert payload["title"] == "MCP created"
        assert payload["type"] == "Feature"
        assert payload["depends_on"] == []

    def test_update_item_status(self, client):
        project = self._project(client, "Status")
        item = self._item(client, project["id"])
        result = self._rpc(client, "tools/call", params={
            "name": "update_item_status",
            "arguments": {"item_id": item["id"], "status": "In Progress"},
        }).json()["result"]
        payload = json.loads(result["content"][0]["text"])
        assert payload["updated"]["status"] == "In Progress"

    def test_invalid_status_rejected(self, client):
        project = self._project(client, "Invalid")
        item = self._item(client, project["id"])
        result = self._rpc(client, "tools/call", params={
            "name": "update_item_status",
            "arguments": {"item_id": item["id"], "status": "Shipped"},
        }).json()["result"]
        payload = json.loads(result["content"][0]["text"])
        assert "error" in payload
        assert result["isError"] is True

    def test_status_report_tool(self, client):
        project = self._project(client, "Reported")
        self._item(client, project["id"])
        result = self._rpc(client, "tools/call", params={
            "name": "get_status_report", "arguments": {"project_id": project["id"]},
        }).json()["result"]
        payload = json.loads(result["content"][0]["text"])
        assert payload["project"]["id"] == project["id"]
        assert payload["backlog"]["total"] == 1

    def test_unknown_tool_rpc_error(self, client):
        resp = self._rpc(client, "tools/call", params={
            "name": "deploy_to_prod", "arguments": {},
        })
        assert resp.json()["error"]["code"] == -32602

    def test_unknown_method_rpc_error(self, client):
        resp = self._rpc(client, "resources/list")
        assert resp.json()["error"]["code"] == -32601

    def test_tool_error_not_500(self, client):
        resp = self._rpc(client, "tools/call", params={
            "name": "get_item", "arguments": {"item_id": 99999},
        })
        assert resp.status_code == 200
        result = resp.json()["result"]
        payload = json.loads(result["content"][0]["text"])
        assert "error" in payload

    def test_requires_auth(self, anon_client):
        resp = anon_client.post("/api/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
        })
        assert resp.status_code in (401, 403)

    def test_tenant_scoped(self, client):
        """Tools only see the caller's tenant — no cross-tenant leakage."""
        result = self._rpc(client, "tools/call", params={
            "name": "get_item", "arguments": {"item_id": 999999},
        }).json()["result"]
        payload = json.loads(result["content"][0]["text"])
        assert "error" in payload
