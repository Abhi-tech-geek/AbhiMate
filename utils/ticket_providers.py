"""Bug-tracker integrations — JIRA Cloud + Linear (Feature #11).

Each provider exposes a tiny ``create_issue(title, body_md, project_or_team=None)``
method. The adapter handles the auth and the body format quirks:

* JIRA Cloud REST v3 wants Atlassian Document Format (ADF) for descriptions
  — we generate a minimal ADF from Markdown by splitting on blank lines.
* Linear uses GraphQL and accepts Markdown directly in ``description``.

Errors surface as ``TicketProviderError`` with the HTTP status + body excerpt
so the route layer can show a clean message to the user.
"""

from __future__ import annotations

import json
from base64 import b64encode
from typing import Any, Dict, Optional

import requests


class TicketProviderError(Exception):
    """Raised when the upstream provider rejects the request."""

    def __init__(self, message: str, status: Optional[int] = None,
                 body: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.body = (body or "")[:500]


# ---------------------------------------------------------------------
# JIRA — Cloud REST v3
# ---------------------------------------------------------------------

class JiraProvider:
    """Atlassian JIRA Cloud adapter."""

    PROVIDER = "jira"

    def __init__(self, base_url: str, auth_email: str, auth_token: str,
                 default_project: Optional[str] = None,
                 session: Optional[requests.Session] = None):
        if not base_url or not auth_email or not auth_token:
            raise TicketProviderError(
                "JIRA needs base_url, auth_email and auth_token configured."
            )
        self.base_url = base_url.rstrip("/")
        self.auth_email = auth_email
        self.auth_token = auth_token
        self.default_project = default_project
        self._sess = session or requests.Session()

    def _headers(self) -> Dict[str, str]:
        creds = f"{self.auth_email}:{self.auth_token}".encode("utf-8")
        return {
            "Authorization": "Basic " + b64encode(creds).decode("ascii"),
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def create_issue(self, title: str, body_md: str,
                     project_or_team: Optional[str] = None,
                     issue_type: str = "Bug") -> Dict[str, str]:
        project_key = project_or_team or self.default_project
        if not project_key:
            raise TicketProviderError(
                "JIRA project key required (either default_project on creds "
                "or 'project_or_team' arg)."
            )
        payload = {
            "fields": {
                "project": {"key": project_key},
                "summary": title[:255],
                "description": _markdown_to_adf(body_md),
                "issuetype": {"name": issue_type},
            }
        }
        url = f"{self.base_url}/rest/api/3/issue"
        try:
            r = self._sess.post(url, headers=self._headers(),
                                data=json.dumps(payload), timeout=15)
        except requests.RequestException as e:
            raise TicketProviderError(f"Network error reaching JIRA: {e}") from e

        if r.status_code >= 400:
            raise TicketProviderError(
                f"JIRA rejected the issue ({r.status_code})", status=r.status_code,
                body=r.text,
            )
        data = r.json() or {}
        key = data.get("key", "")
        return {
            "provider": "jira",
            "key": key,
            "id": data.get("id", ""),
            "url": f"{self.base_url}/browse/{key}" if key else (data.get("self") or ""),
        }


def _markdown_to_adf(md: str) -> dict:
    """Cheap-and-cheerful Markdown→ADF. Splits on blank lines into paragraphs
    and turns ``` fenced blocks into ADF codeBlock nodes. Good enough for
    bug-body content; not a full Markdown parser."""
    md = md or ""
    blocks = []
    i = 0
    paragraphs = md.split("\n\n")
    for p in paragraphs:
        p = p.strip("\n")
        if not p:
            continue
        if p.startswith("```"):
            lines = p.splitlines()
            lang = lines[0][3:].strip() or "plain"
            code = "\n".join(l for l in lines[1:] if l.strip() != "```")
            blocks.append({
                "type": "codeBlock",
                "attrs": {"language": lang},
                "content": [{"type": "text", "text": code}],
            })
        else:
            blocks.append({
                "type": "paragraph",
                "content": [{"type": "text", "text": p}],
            })
        i += 1
    if not blocks:
        blocks = [{"type": "paragraph", "content": [{"type": "text", "text": " "}]}]
    return {"version": 1, "type": "doc", "content": blocks}


# ---------------------------------------------------------------------
# Linear — GraphQL
# ---------------------------------------------------------------------

class LinearProvider:
    """Linear adapter — single GraphQL mutation."""

    PROVIDER = "linear"
    ENDPOINT = "https://api.linear.app/graphql"

    def __init__(self, auth_token: str, default_project: Optional[str] = None,
                 session: Optional[requests.Session] = None,
                 base_url: Optional[str] = None,
                 auth_email: Optional[str] = None):
        # base_url / auth_email accepted for API parity but unused.
        if not auth_token:
            raise TicketProviderError("Linear needs an API token.")
        self.auth_token = auth_token
        self.default_project = default_project  # this is team_id for Linear
        self._sess = session or requests.Session()
        self.base_url = (base_url or "").rstrip("/")

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": self.auth_token,
            "Content-Type": "application/json",
        }

    _MUTATION = """
    mutation IssueCreate($title: String!, $description: String!, $teamId: String!) {
      issueCreate(input: {title: $title, description: $description, teamId: $teamId}) {
        success
        issue { id identifier url title }
      }
    }
    """.strip()

    def create_issue(self, title: str, body_md: str,
                     project_or_team: Optional[str] = None,
                     issue_type: str = "Bug") -> Dict[str, str]:
        team_id = project_or_team or self.default_project
        if not team_id:
            raise TicketProviderError(
                "Linear team_id required (set default_project on creds or "
                "pass 'project_or_team')."
            )
        payload = {
            "query": self._MUTATION,
            "variables": {
                "title": title[:255],
                "description": body_md,
                "teamId": team_id,
            },
        }
        try:
            r = self._sess.post(self.ENDPOINT, headers=self._headers(),
                                data=json.dumps(payload), timeout=15)
        except requests.RequestException as e:
            raise TicketProviderError(f"Network error reaching Linear: {e}") from e

        if r.status_code >= 400:
            raise TicketProviderError(
                f"Linear rejected the request ({r.status_code})",
                status=r.status_code, body=r.text,
            )
        body = r.json() or {}
        if body.get("errors"):
            raise TicketProviderError(
                f"Linear GraphQL error: {body['errors']}", status=200,
                body=json.dumps(body)[:500],
            )
        created = ((body.get("data") or {}).get("issueCreate") or {})
        if not created.get("success"):
            raise TicketProviderError(
                "Linear refused to create the issue (success=false)",
                body=json.dumps(body)[:500],
            )
        issue = created.get("issue") or {}
        return {
            "provider": "linear",
            "key": issue.get("identifier", ""),
            "id": issue.get("id", ""),
            "url": issue.get("url", ""),
        }


# ---------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------

def build_provider(creds: Dict[str, Any],
                   session: Optional[requests.Session] = None):
    """Pick the adapter for a credentials row from ``ticket_credentials``."""
    if not creds:
        raise TicketProviderError("No credentials configured for this provider.")
    provider = (creds.get("provider") or "").lower()
    common = dict(
        auth_token=creds.get("auth_token") or "",
        default_project=creds.get("default_project"),
        session=session,
    )
    if provider == "jira":
        return JiraProvider(
            base_url=creds.get("base_url") or "",
            auth_email=creds.get("auth_email") or "",
            **common,
        )
    if provider == "linear":
        return LinearProvider(
            base_url=creds.get("base_url"),
            auth_email=creds.get("auth_email"),
            **common,
        )
    raise TicketProviderError(f"Unknown provider: {provider}")
