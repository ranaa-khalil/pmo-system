"""GitHub service — two-way sync between PMO and GitHub.

PMO → GitHub: When a backlog item is approved/exported, create a GitHub issue
              and optionally add it to a GitHub Project V2 board.
GitHub → PMO: Read issue/PR status to auto-update phases.

Requires a GitHub personal access token configured in settings.
For GitHub Projects V2 (board integration), the token needs the 'project' scope
in addition to 'repo'.
"""

import httpx


class GitHubService:
    """GitHub API client for issue sync and project board integration."""

    API_BASE = "https://api.github.com"
    GRAPHQL_URL = "https://api.github.com/graphql"

    def __init__(self, token: str | None = None):
        self.token = token
        self._client = None

    @property
    def client(self):
        if self._client is None:
            headers = {
                "Accept": "application/vnd.github.v3+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            if self.token:
                headers["Authorization"] = f"token {self.token}"
            self._client = httpx.Client(
                base_url=self.API_BASE,
                headers=headers,
                timeout=30,
            )
        return self._client

    # ─── REST API: Issues ──────────────────────────────────────────

    def create_issue(
        self,
        repo: str,
        title: str,
        body: str = "",
        labels: list = None,
        assignees: list = None,
    ) -> dict | None:
        """Create an issue in a GitHub repo. Returns the issue dict or None.

        If label creation fails (no admin rights), retries without labels.
        """
        if not self.token:
            return None
        try:
            payload = {"title": title, "body": body}
            if labels:
                payload["labels"] = labels
            if assignees:
                payload["assignees"] = assignees
            resp = self.client.post(f"/repos/{repo}/issues", json=payload)
            if resp.status_code == 201:
                return resp.json()
            # If label permission error (403/422), retry without labels
            if resp.status_code in (403, 422) and labels:
                payload.pop("labels", None)
                resp = self.client.post(f"/repos/{repo}/issues", json=payload)
                if resp.status_code == 201:
                    return resp.json()
        except Exception:
            pass
        return None

    def get_issue(self, repo: str, issue_number: int) -> dict | None:
        """Get an issue's status from GitHub."""
        if not self.token:
            return None
        try:
            resp = self.client.get(f"/repos/{repo}/issues/{issue_number}")
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "number": data["number"],
                    "state": data["state"],
                    "title": data["title"],
                    "labels": [l["name"] for l in data.get("labels", [])],
                    "html_url": data.get("html_url", ""),
                    "assignees": [a["login"] for a in data.get("assignees", [])],
                }
        except Exception:
            pass
        return None

    def sync_issue_status(self, repo: str, issue_number: int) -> str | None:
        """Check if a GitHub issue is open or closed. Returns 'open', 'closed', or None."""
        issue = self.get_issue(repo, issue_number)
        if issue:
            return issue["state"]
        return None

    def update_issue(
        self,
        repo: str,
        issue_number: int,
        title: str = None,
        body: str = None,
        labels: list = None,
        state: str = None,
    ) -> dict | None:
        """Update an existing GitHub issue."""
        if not self.token:
            return None
        try:
            payload = {}
            if title is not None:
                payload["title"] = title
            if body is not None:
                payload["body"] = body
            if labels is not None:
                payload["labels"] = labels
            if state is not None:
                payload["state"] = state
            resp = self.client.patch(f"/repos/{repo}/issues/{issue_number}", json=payload)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return None

    def add_labels(self, repo: str, issue_number: int, labels: list) -> bool:
        """Add labels to an existing issue."""
        if not self.token:
            return False
        try:
            resp = self.client.post(
                f"/repos/{repo}/issues/{issue_number}/labels",
                json={"labels": labels},
            )
            return resp.status_code == 200
        except Exception:
            return False

    # ─── REST API: Labels ──────────────────────────────────────────

    def list_labels(self, repo: str) -> list[dict]:
        """List all labels in a repo."""
        if not self.token:
            return []
        try:
            resp = self.client.get(f"/repos/{repo}/labels?per_page=100")
            if resp.status_code == 200:
                return [
                    {"name": l["name"], "color": l.get("color", ""), "description": l.get("description", "")}
                    for l in resp.json()
                ]
        except Exception:
            pass
        return []

    def ensure_label(self, repo: str, name: str, color: str = "5B6EE1", description: str = "") -> bool:
        """Create a label if it doesn't exist."""
        if not self.token:
            return False
        try:
            resp = self.client.post(
                f"/repos/{repo}/labels",
                json={"name": name, "color": color, "description": description},
            )
            return resp.status_code == 201
        except Exception:
            return False

    # ─── GraphQL API: Projects V2 ──────────────────────────────────

    def _graphql(self, query: str, variables: dict = None) -> dict | None:
        """Execute a GraphQL query against the GitHub API."""
        if not self.token:
            return None
        try:
            # GraphQL uses a separate client (no base_url)
            resp = httpx.post(
                self.GRAPHQL_URL,
                headers={
                    "Authorization": f"token {self.token}",
                    "Content-Type": "application/json",
                },
                json={"query": query, "variables": variables or {}},
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                if "errors" in data:
                    return None
                return data.get("data")
        except Exception:
            pass
        return None

    def list_projects(self, repo: str) -> list[dict]:
        """List GitHub Projects V2 linked to a repo.

        Returns list of {id, title, url, number} dicts.
        Requires 'project' scope on the token.
        """
        owner, repo_name = repo.split("/") if "/" in repo else (repo, "")
        if not repo_name:
            return []

        query = """
        query($owner: String!, $repo: String!) {
          repository(owner: $owner, name: $repo) {
            projectsV2(first: 20, orderBy: {field: TITLE, direction: ASC}) {
              nodes {
                id
                title
                number
                url
                shortDescription
                closed
              }
            }
          }
        }
        """
        data = self._graphql(query, {"owner": owner, "repo": repo_name})
        if not data or not data.get("repository"):
            return []

        nodes = data["repository"].get("projectsV2", {}).get("nodes", [])
        return [
            {
                "id": n["id"],
                "title": n["title"],
                "number": n.get("number"),
                "url": n.get("url", ""),
                "description": n.get("shortDescription", ""),
                "closed": n.get("closed", False),
            }
            for n in nodes
            if not n.get("closed", False)
        ]

    def list_org_projects(self, org: str) -> list[dict]:
        """List GitHub Projects V2 for an organization."""
        query = """
        query($org: String!) {
          organization(login: $org) {
            projectsV2(first: 20, orderBy: {field: TITLE, direction: ASC}) {
              nodes {
                id
                title
                number
                url
                shortDescription
                closed
              }
            }
          }
        }
        """
        data = self._graphql(query, {"org": org})
        if not data or not data.get("organization"):
            return []

        nodes = data["organization"].get("projectsV2", {}).get("nodes", [])
        return [
            {
                "id": n["id"],
                "title": n["title"],
                "number": n.get("number"),
                "url": n.get("url", ""),
                "description": n.get("shortDescription", ""),
                "closed": n.get("closed", False),
            }
            for n in nodes
            if not n.get("closed", False)
        ]

    def list_user_projects(self) -> list[dict]:
        """List GitHub Projects V2 for the authenticated user."""
        query = """
        query {
          viewer {
            projectsV2(first: 20, orderBy: {field: TITLE, direction: ASC}) {
              nodes {
                id
                title
                number
                url
                shortDescription
                closed
              }
            }
          }
        }
        """
        data = self._graphql(query)
        if not data or not data.get("viewer"):
            return []

        nodes = data["viewer"].get("projectsV2", {}).get("nodes", [])
        return [
            {
                "id": n["id"],
                "title": n["title"],
                "number": n.get("number"),
                "url": n.get("url", ""),
                "description": n.get("shortDescription", ""),
                "closed": n.get("closed", False),
            }
            for n in nodes
            if not n.get("closed", False)
        ]

    def resolve_project_url(self, url: str) -> dict | None:
        """Resolve a GitHub Project V2 URL to its node ID and metadata.

        Accepts URLs like:
          https://github.com/users/{login}/projects/{number}/views/{view}
          https://github.com/users/{login}/projects/{number}
          https://github.com/orgs/{login}/projects/{number}
          https://github.com/{owner}/{repo}/projects/{number}

        Returns dict with: id, title, url, number, description, closed
        or None if the URL can't be parsed or the project can't be found.
        """
        import re

        url = url.strip().rstrip("/")
        # Strip /views/N suffix
        url = re.sub(r"/views/\d+$", "", url)

        # Try user-level: /users/{login}/projects/{number}
        m = re.match(r"https?://github\.com/users/([^/]+)/projects/(\d+)$", url)
        if m:
            login, number = m.group(1), int(m.group(2))
            query = """
            query($login: String!, $number: Int!) {
              user(login: $login) {
                projectV2(number: $number) {
                  id title number url shortDescription closed
                }
              }
            }
            """
            data = self._graphql(query, {"login": login, "number": number})
            if data and data.get("user", {}).get("projectV2"):
                p = data["user"]["projectV2"]
                return {
                    "id": p["id"], "title": p["title"],
                    "number": p.get("number"), "url": p.get("url", ""),
                    "description": p.get("shortDescription", ""),
                    "closed": p.get("closed", False),
                }
            return None

        # Try org-level: /orgs/{login}/projects/{number}
        m = re.match(r"https?://github\.com/orgs/([^/]+)/projects/(\d+)$", url)
        if m:
            login, number = m.group(1), int(m.group(2))
            query = """
            query($login: String!, $number: Int!) {
              organization(login: $login) {
                projectV2(number: $number) {
                  id title number url shortDescription closed
                }
              }
            }
            """
            data = self._graphql(query, {"login": login, "number": number})
            if data and data.get("organization", {}).get("projectV2"):
                p = data["organization"]["projectV2"]
                return {
                    "id": p["id"], "title": p["title"],
                    "number": p.get("number"), "url": p.get("url", ""),
                    "description": p.get("shortDescription", ""),
                    "closed": p.get("closed", False),
                }
            return None

        # Try repo-level: /{owner}/{repo}/projects/{number}
        m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/projects/(\d+)$", url)
        if m:
            owner, repo_name, number = m.group(1), m.group(2), int(m.group(3))
            query = """
            query($owner: String!, $repo: String!, $number: Int!) {
              repository(owner: $owner, name: $repo) {
                projectV2(number: $number) {
                  id title number url shortDescription closed
                }
              }
            }
            """
            data = self._graphql(query, {"owner": owner, "repo": repo_name, "number": number})
            if data and data.get("repository", {}).get("projectV2"):
                p = data["repository"]["projectV2"]
                return {
                    "id": p["id"], "title": p["title"],
                    "number": p.get("number"), "url": p.get("url", ""),
                    "description": p.get("shortDescription", ""),
                    "closed": p.get("closed", False),
                }
            return None

        return None

    def add_issue_to_project(self, project_node_id: str, issue_node_id: str) -> bool:
        """Add an issue to a GitHub Project V2 board.

        Requires 'project' scope on the token.
        Returns True if successful.
        """
        mutation = """
        mutation($projectId: ID!, $contentId: ID!) {
          addProjectV2ItemById(input: {projectId: $projectId, contentId: $contentId}) {
            item {
              id
            }
          }
        }
        """
        data = self._graphql(mutation, {"projectId": project_node_id, "contentId": issue_node_id})
        return data is not None and "addProjectV2ItemById" in (data or {})

    def get_issue_node_id(self, repo: str, issue_number: int) -> str | None:
        """Get the GraphQL node ID of an issue (needed for adding to project boards)."""
        owner, repo_name = repo.split("/") if "/" in repo else (repo, "")
        if not repo_name:
            return None

        query = """
        query($owner: String!, $repo: String!, $number: Int!) {
          repository(owner: $owner, name: $repo) {
            issue(number: $number) {
              id
            }
          }
        }
        """
        data = self._graphql(query, {"owner": owner, "repo": repo_name, "number": issue_number})
        if data and data.get("repository", {}).get("issue"):
            return data["repository"]["issue"]["id"]
        return None

    # ─── GraphQL API: Project V2 items with status ─────────────────

    def get_project_items_with_status(self, project_node_id: str) -> list[dict]:
        """Fetch all items in a GitHub Project V2 board with their field values.

        Returns a list of dicts with keys:
          - issue_number: int or None
          - state: 'open' or 'closed'
          - title: str
          - url: str
          - labels: list of str
          - assignees: list of str
          - project_status: str or None (the "Status" single-select field value)
          - all_fields: dict of field_name → value for all single-select fields

        Requires 'project' scope on the token.
        """
        query = """
        query($projectId: ID!, $first: Int!) {
          node(id: $projectId) {
            ... on ProjectV2 {
              title
              items(first: $first) {
                nodes {
                  id
                  content {
                    __typename
                    ... on Issue {
                      number
                      state
                      title
                      url
                      labels(first: 20) { nodes { name } }
                      assignees(first: 10) { nodes { login } }
                    }
                  }
                  fieldValues(first: 20) {
                    nodes {
                      ... on ProjectV2ItemFieldSingleSelectValue {
                        name
                        field {
                          ... on ProjectV2SingleSelectField {
                            name
                          }
                        }
                      }
                      ... on ProjectV2ItemFieldTextValue {
                        text
                        field {
                          ... on ProjectV2FieldCommon {
                            name
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """
        data = self._graphql(query, {"projectId": project_node_id, "first": 100})
        if not data or not data.get("node"):
            return []

        items = data["node"].get("items", {}).get("nodes", [])
        results = []
        for item in items:
            content = item.get("content")
            if not content or content.get("__typename") != "Issue":
                continue

            # Parse field values
            all_fields = {}
            project_status = None
            for fv in item.get("fieldValues", {}).get("nodes", []):
                if "name" in fv and "field" in fv:
                    field_name = fv["field"].get("name", "")
                    field_value = fv["name"]
                    all_fields[field_name] = field_value
                    if field_name.lower() == "status":
                        project_status = field_value

            labels = [l["name"] for l in content.get("labels", {}).get("nodes", [])]
            assignees = [a["login"] for a in content.get("assignees", {}).get("nodes", [])]

            results.append({
                "issue_number": content.get("number"),
                "state": content.get("state", ""),
                "title": content.get("title", ""),
                "url": content.get("url", ""),
                "labels": labels,
                "assignees": assignees,
                "project_status": project_status,
                "all_fields": all_fields,
            })
        return results

    # ─── High-level: Export backlog items ──────────────────────────

    def export_backlog_item(
        self,
        repo: str,
        title: str,
        description: str = "",
        priority: str = "Medium",
        item_type: str = None,
        epic: str = None,
        primary_actor: str = None,
        story_points: int = None,
        acceptance_criteria: str = None,
        dependencies_text: str = None,
        pmo_item_id: int = None,
        labels: list = None,
        title_prefix: str = None,
        project_node_id: str = None,
        include_acceptance_criteria: bool = True,
        include_dependencies: bool = True,
    ) -> dict | None:
        """Export a single backlog item to GitHub.

        Creates an issue with rich body, applies labels, and optionally
        adds the issue to a GitHub Project V2 board.

        Returns dict with issue info, or None on failure.
        """
        if not self.token:
            return None

        # Build issue title
        full_title = title
        if title_prefix:
            full_title = f"{title_prefix} {title}"

        # Build issue body
        body_parts = []
        body_parts.append(f"## {title}\n")
        if description:
            body_parts.append(f"{description}\n")

        # Metadata table
        meta_rows = []
        if pmo_item_id:
            meta_rows.append(f"| PMO Item ID | {pmo_item_id} |")
        if item_type:
            meta_rows.append(f"| Type | {item_type} |")
        if epic:
            meta_rows.append(f"| Epic | {epic} |")
        if primary_actor:
            meta_rows.append(f"| Primary Actor | {primary_actor} |")
        if priority:
            meta_rows.append(f"| Priority | {priority} |")
        if story_points:
            meta_rows.append(f"| Story Points | {story_points} |")

        if meta_rows:
            body_parts.append("---\n")
            body_parts.append("| Field | Value |\n")
            body_parts.append("|-------|-------|\n")
            body_parts.append("\n".join(meta_rows) + "\n")

        # Acceptance criteria
        if include_acceptance_criteria and acceptance_criteria:
            body_parts.append("\n## Acceptance Criteria\n")
            body_parts.append(f"{acceptance_criteria}\n")

        # Dependencies
        if include_dependencies and dependencies_text:
            body_parts.append("\n## Dependencies\n")
            body_parts.append(f"{dependencies_text}\n")

        body = "\n".join(body_parts)

        # Build labels list
        issue_labels = list(labels or [])
        # Add priority label
        if priority and priority not in issue_labels:
            issue_labels.append(f"priority:{priority.lower()}")
        # Add type label
        if item_type:
            type_label = item_type.lower().replace(" ", "-")
            if type_label not in issue_labels:
                issue_labels.append(type_label)

        # Create the issue
        issue = self.create_issue(
            repo=repo,
            title=full_title,
            body=body,
            labels=issue_labels,
        )

        if not issue:
            return None

        result = {
            "number": issue["number"],
            "html_url": issue.get("html_url", ""),
            "title": issue["title"],
        }

        # Add to project board if configured
        if project_node_id:
            issue_node_id = self.get_issue_node_id(repo, issue["number"])
            if issue_node_id:
                added = self.add_issue_to_project(project_node_id, issue_node_id)
                result["added_to_project"] = added
            else:
                result["added_to_project"] = False
        else:
            result["added_to_project"] = False

        return result

    def close(self):
        if self._client:
            self._client.close()
            self._client = None
