"""GitHub service — two-way sync between PMO and GitHub.

PMO → GitHub: When a backlog item enters Development phase, create a GitHub issue.
GitHub → PMO: Read issue/PR status to auto-update phases.

Requires a GitHub personal access token configured in settings.
"""
import httpx
from typing import Optional


class GitHubService:
    """Minimal GitHub API client for issue sync."""

    API_BASE = "https://api.github.com"

    def __init__(self, token: Optional[str] = None):
        self.token = token
        self._client = None

    @property
    def client(self):
        if self._client is None:
            headers = {"Accept": "application/vnd.github.v3+json"}
            if self.token:
                headers["Authorization"] = f"token {self.token}"
            self._client = httpx.Client(
                base_url=self.API_BASE,
                headers=headers,
                timeout=15,
            )
        return self._client

    def create_issue(self, repo: str, title: str, body: str = "", labels: list = None) -> Optional[dict]:
        """Create an issue in a GitHub repo. Returns the issue dict or None."""
        if not self.token:
            return None
        try:
            resp = self.client.post(
                f"/repos/{repo}/issues",
                json={
                    "title": title,
                    "body": body,
                    "labels": labels or [],
                },
            )
            if resp.status_code == 201:
                return resp.json()
        except Exception:
            pass
        return None

    def get_issue(self, repo: str, issue_number: int) -> Optional[dict]:
        """Get an issue's status from GitHub."""
        if not self.token:
            return None
        try:
            resp = self.client.get(f"/repos/{repo}/issues/{issue_number}")
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "number": data["number"],
                    "state": data["state"],  # "open" or "closed"
                    "title": data["title"],
                    "labels": [l["name"] for l in data.get("labels", [])],
                }
        except Exception:
            pass
        return None

    def sync_issue_status(self, repo: str, issue_number: int) -> Optional[str]:
        """Check if a GitHub issue is open or closed. Returns 'open', 'closed', or None."""
        issue = self.get_issue(repo, issue_number)
        if issue:
            return issue["state"]
        return None

    def close(self):
        if self._client:
            self._client.close()
            self._client = None
