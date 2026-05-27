"""Jira REST API v3 client."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import httpx

logger = logging.getLogger(__name__)


class JiraAPIError(Exception):
    """Raised when the Jira API returns an error response."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"Jira API error {status_code}: {message}")


class JiraClient:
    """Async Jira REST API v3 client.

    Handles authentication, pagination, and field extraction for the
    ticket types we care about (Stories, Tasks, Bugs, Subtasks, Epics).
    """

    def __init__(self, base_url: str, username: str, api_token: str) -> None:
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=f"{self._base}/rest/api/3",
            auth=(username, api_token),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=30.0,
        )

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "JiraClient":
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    # ── Issue search ───────────────────────────────────────────────────────

    async def search_issues(
        self,
        jql: str,
        max_results: int = 50,
        fields: list[str] | None = None,
        start_at: int = 0,
    ) -> list[dict[str, Any]]:
        """Run a JQL search and return a list of raw issue dicts.

        Automatically paginates to collect up to ``max_results`` issues.
        """
        default_fields = [
            "summary", "description", "status", "issuetype", "priority",
            "assignee", "parent", "labels", "created", "updated",
            "customfield_10014",  # Epic link (common field name)
            "customfield_10016",  # Story points
        ]
        all_issues: list[dict[str, Any]] = []
        page_size = min(max_results, 100)
        offset = start_at

        while len(all_issues) < max_results:
            resp = await self._client.post(
                "/search",
                json={
                    "jql": jql,
                    "maxResults": page_size,
                    "startAt": offset,
                    "fields": fields or default_fields,
                },
            )
            self._raise_for_status(resp)
            data = resp.json()
            issues = data.get("issues", [])
            all_issues.extend(issues)

            total = data.get("total", 0)
            if len(issues) < page_size or len(all_issues) >= total:
                break
            offset += len(issues)

        return all_issues[:max_results]

    async def get_issue(self, key: str) -> dict[str, Any]:
        """Fetch a single issue by key."""
        resp = await self._client.get(f"/issue/{key}")
        self._raise_for_status(resp)
        return resp.json()

    # ── Convenience extractors ─────────────────────────────────────────────

    def extract_ticket_data(self, issue: dict[str, Any]) -> dict[str, Any]:
        """Flatten raw Jira issue into a clean dict matching our JiraTicket schema."""
        fields = issue.get("fields", {})

        # Status
        status = fields.get("status", {}).get("name", "Unknown")

        # Issue type
        issue_type = fields.get("issuetype", {}).get("name", "Task")

        # Priority
        priority = (fields.get("priority") or {}).get("name")

        # Assignee
        assignee_obj = fields.get("assignee") or {}
        assignee = assignee_obj.get("displayName") or assignee_obj.get("emailAddress")

        # Parent (for subtasks and stories under epics)
        parent_obj = fields.get("parent") or {}
        parent_key = parent_obj.get("key")

        # Labels
        labels: list[str] = fields.get("labels") or []

        # Timestamps
        jira_created_at = self._parse_jira_dt(fields.get("created"))
        jira_updated_at = self._parse_jira_dt(fields.get("updated")) or datetime.utcnow()

        # Description (Atlassian Document Format → plain text)
        description = self._adf_to_text(fields.get("description"))

        # Summary
        summary = fields.get("summary", "(no summary)")

        return {
            "key": issue["key"],
            "summary": summary,
            "description": description,
            "status": status,
            "issue_type": issue_type,
            "priority": priority,
            "assignee": assignee,
            "parent_key": parent_key,
            "labels": labels,
            "repos": [],  # Populated separately via dev-info API if needed
            "jira_created_at": jira_created_at,
            "jira_updated_at": jira_updated_at,
        }

    async def get_development_info(self, issue_key: str) -> list[str]:
        """Fetch linked repository names from Jira dev panel (requires Jira Software).

        Returns empty list if dev-info is not available.
        """
        try:
            resp = await self._client.get(
                f"/issue/{issue_key}/remotelink",
            )
            if resp.status_code != 200:
                return []
            links = resp.json()
            repos: set[str] = set()
            for link in links:
                obj = link.get("object", {})
                url = obj.get("url", "")
                if "github.com" in url or "bitbucket" in url or "gitlab" in url:
                    # Extract repo name from URL
                    parts = url.rstrip("/").split("/")
                    if len(parts) >= 2:
                        repos.add(f"{parts[-2]}/{parts[-1]}")
            return sorted(repos)
        except Exception:
            return []

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_jira_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            # Jira returns ISO 8601: "2024-01-15T09:30:00.000+0000"
            return datetime.fromisoformat(value.replace("Z", "+00:00").replace("+0000", "+00:00"))
        except Exception:
            return None

    @staticmethod
    def _adf_to_text(adf: Any) -> str | None:
        """Convert Atlassian Document Format (ADF) to plain text recursively."""
        if not adf:
            return None
        if isinstance(adf, str):
            return adf

        parts: list[str] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                if node.get("type") == "text":
                    parts.append(node.get("text", ""))
                elif node.get("type") in ("hardBreak", "rule"):
                    parts.append("\n")
                for child in node.get("content", []):
                    walk(child)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(adf)
        text = "".join(parts).strip()
        return text or None

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            try:
                body = resp.json()
                msgs = body.get("errorMessages", []) + list(
                    body.get("errors", {}).values()
                )
                message = "; ".join(msgs) if msgs else resp.text
            except Exception:
                message = resp.text
            raise JiraAPIError(resp.status_code, message)
