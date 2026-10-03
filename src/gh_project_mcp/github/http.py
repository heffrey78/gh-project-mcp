"""GitHub over HTTPS (ADR-0004): GraphQL for the one read that needs links, REST for everything else.

This package is the only place that opens a connection or runs `gh`. Failures become GitHubError carrying GitHub's
own message and the operation that failed; the token appears in no message and no log line.
"""

import logging
import shutil
import subprocess
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import anyio
import httpx

from ..config import TOKEN_ENVS, Config
from .port import UNSET, Comment, Event, GitHubError, Issue, Milestone

logger = logging.getLogger(__name__)

API_VERSION = "2022-11-28"
PAGE_SIZE = 100

SNAPSHOT_QUERY = """
query($owner: String!, $name: String!, $cursor: String, $since: DateTime, $labels: [String!]) {
  repository(owner: $owner, name: $name) {
    issues(first: 100, after: $cursor, labels: $labels, filterBy: {since: $since},
           orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number fullDatabaseId title body state stateReason url createdAt updatedAt
        author { login }
        labels(first: 50) { nodes { name } }
        milestone { number }
        assignees(first: 10) { nodes { login } }
        parent { number }
        subIssues(first: 100) { nodes { number } }
        blockedBy(first: 50) { nodes { number } }
      }
    }
  }
}
"""


def _token_from_gh(api_url: str) -> str | None:
    """The token the gh CLI holds for this host, when gh is installed and logged in."""
    if shutil.which("gh") is None:
        return None
    host = httpx.URL(api_url).host
    command = ["gh", "auth", "token"]
    if host != "api.github.com":
        command += ["--hostname", host.removeprefix("api.")]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _issue_from_rest(data: dict[str, Any]) -> Issue:
    """An issue from a REST response. REST does not carry links; the tracker keeps those from the snapshot."""
    return Issue(
        number=data["number"],
        id=data["id"],
        title=data["title"],
        body=data.get("body") or "",
        state=data["state"],
        state_reason=data.get("state_reason"),
        labels=[label["name"] if isinstance(label, dict) else label for label in data.get("labels", [])],
        milestone=(data.get("milestone") or {}).get("number"),
        assignees=[a["login"] for a in data.get("assignees") or []],
        url=data.get("html_url", ""),
        author=(data.get("user") or {}).get("login", ""),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
    )


def _issue_from_graphql(node: dict[str, Any]) -> Issue:
    reason = node.get("stateReason")
    return Issue(
        number=node["number"],
        id=int(node["fullDatabaseId"]),
        title=node["title"],
        body=node.get("body") or "",
        state=node["state"].lower(),
        state_reason=reason.lower() if reason else None,
        labels=[label["name"] for label in node["labels"]["nodes"]],
        milestone=(node.get("milestone") or {}).get("number"),
        assignees=[a["login"] for a in node["assignees"]["nodes"]],
        parent=(node.get("parent") or {}).get("number"),
        sub_issues=[s["number"] for s in node["subIssues"]["nodes"]],
        blocked_by=[b["number"] for b in node["blockedBy"]["nodes"]],
        url=node.get("url", ""),
        author=(node.get("author") or {}).get("login", ""),
        created_at=node.get("createdAt", ""),
        updated_at=node.get("updatedAt", ""),
    )


def _milestone(data: dict[str, Any]) -> Milestone:
    return Milestone(
        data["number"], data["title"], data.get("description") or "", data["state"], data.get("html_url", "")
    )


def _event(data: dict[str, Any]) -> Event:
    kind = data.get("event", "")
    actor = (data.get("actor") or data.get("user") or {}).get("login", "")
    detail = ""
    if kind in ("labeled", "unlabeled"):
        detail = (data.get("label") or {}).get("name", "")
    elif kind == "renamed":
        detail = (data.get("rename") or {}).get("to", "")
    elif kind == "closed":
        detail = data.get("state_reason") or ""
    elif kind == "commented":
        detail = (data.get("body") or "").strip().split("\n")[0]
    elif kind in ("milestoned", "demilestoned"):
        detail = (data.get("milestone") or {}).get("title", "")
    elif kind in ("assigned", "unassigned"):
        detail = (data.get("assignee") or {}).get("login", "")
    elif kind == "cross-referenced":
        source = (data.get("source") or {}).get("issue") or {}
        detail = f"#{source['number']}" if source.get("number") else ""
    return Event(kind, actor, data.get("created_at") or data.get("submitted_at") or "", detail)


class HttpGitHub:
    def __init__(self, config: Config, transport: httpx.AsyncBaseTransport | None = None):
        self.repo = config.require_repo()
        self._owner, self._name = self.repo.split("/", 1)
        self._config = config
        self._token = config.token
        self.last_seen_at: str | None = None
        self._client = httpx.AsyncClient(
            base_url=config.api_url,
            transport=transport,
            timeout=30.0,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "gh-project-mcp",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- transport ----------------------------------------------------------------------------------------------

    async def _authorization(self) -> str:
        if self._token is None:
            self._token = await anyio.to_thread.run_sync(_token_from_gh, self._config.api_url)
        if not self._token:
            raise GitHubError(
                f"no GitHub token: set {' or '.join(TOKEN_ENVS)} in the server's environment, or log in with "
                "`gh auth login`. Nothing was sent"
            )
        return f"Bearer {self._token}"

    async def _send(self, operation: str, method: str, url: str, **kwargs: Any) -> httpx.Response:
        headers = {"Authorization": await self._authorization()}
        try:
            response = await self._client.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as error:
            # The exception's text names the URL at most; the headers, and so the token, are not in it.
            raise GitHubError(
                f"could not reach GitHub: {type(error).__name__}: {error}", operation=operation
            ) from error
        try:
            seen = parsedate_to_datetime(response.headers["date"]).astimezone(UTC)
            self.last_seen_at = seen.strftime("%Y-%m-%dT%H:%M:%SZ")
        except (KeyError, TypeError, ValueError):
            pass  # no usable Date header; the tracker falls back to the newest record it has seen
        if response.status_code >= 400:
            raise self._error(response, operation)
        return response

    def _error(self, response: httpx.Response, operation: str) -> GitHubError:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        message = payload.get("message") or response.reason_phrase or "request failed"
        details = [
            e.get("message") or f"{e.get('field', '')} {e.get('code', '')}".strip()
            for e in payload.get("errors") or []
            if isinstance(e, dict)
        ]
        details = [d for d in details if d]
        if details:
            message += ": " + "; ".join(details)
        status = response.status_code
        if status in (403, 429) and response.headers.get("retry-after"):
            message = f"secondary rate limit; retry after {response.headers['retry-after']} seconds ({message})"
        elif status in (403, 429) and response.headers.get("x-ratelimit-remaining") == "0":
            reset = response.headers.get("x-ratelimit-reset", "")
            at = datetime.fromtimestamp(int(reset), tz=UTC).strftime("%H:%M:%S UTC") if reset.isdigit() else "?"
            message = f"rate limit exhausted; it resets at {at} ({message})"
        elif status == 401:
            message = f"the token was rejected ({message}). Check {' / '.join(TOKEN_ENVS)} or run `gh auth status`"
        elif status == 404:
            message = f"{message}. The repository {self.repo} may not exist, or the token cannot see it"
        return GitHubError(message, status=status, operation=operation)

    async def _rest(self, operation: str, method: str, path: str, **kwargs: Any) -> Any:
        response = await self._send(operation, method, f"/repos/{self.repo}{path}", **kwargs)
        return response.json() if response.content else None

    async def _pages(self, operation: str, path: str, **params: Any) -> list[dict[str, Any]]:
        """Every item of a REST listing, following pagination to the end."""
        items: list[dict[str, Any]] = []
        url: str | None = f"/repos/{self.repo}{path}"
        query: dict[str, Any] | None = {"per_page": PAGE_SIZE, **params}
        while url:
            response = await self._send(operation, "GET", url, params=query)
            items += response.json()
            url, query = response.links.get("next", {}).get("url"), None
        return items

    async def _graphql(self, operation: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        response = await self._send(operation, "POST", "/graphql", json={"query": query, "variables": variables})
        payload = response.json()
        if payload.get("errors"):
            first = payload["errors"][0]
            status = 404 if first.get("type") == "NOT_FOUND" else None
            messages = "; ".join(e.get("message", "") for e in payload["errors"])
            raise GitHubError(messages, status=status, operation=operation)
        return payload["data"]

    # -- issues -------------------------------------------------------------------------------------------------

    async def list_issues(self, since: str | None = None, labels: list[str] | None = None) -> list[Issue]:
        issues: list[Issue] = []
        cursor = None
        while True:
            variables = {"owner": self._owner, "name": self._name, "cursor": cursor, "since": since, "labels": labels}
            data = await self._graphql("list issues", SNAPSHOT_QUERY, variables)
            if data.get("repository") is None:
                raise GitHubError(f"the repository {self.repo} was not found", status=404, operation="list issues")
            page = data["repository"]["issues"]
            issues += [_issue_from_graphql(node) for node in page["nodes"]]
            if not page["pageInfo"]["hasNextPage"]:
                return issues
            cursor = page["pageInfo"]["endCursor"]

    async def create_issue(
        self,
        title: str,
        body: str,
        labels: list[str],
        milestone: int | None = None,
        assignees: list[str] | None = None,
    ) -> Issue:
        payload: dict[str, Any] = {"title": title, "body": body, "labels": labels}
        if milestone is not None:
            payload["milestone"] = milestone
        if assignees:
            payload["assignees"] = assignees
        return _issue_from_rest(await self._rest("create issue", "POST", "/issues", json=payload))

    async def update_issue(
        self,
        number: int,
        *,
        title: str | None = None,
        body: str | None = None,
        labels: list[str] | None = None,
        state: str | None = None,
        state_reason: str | None = None,
        milestone: Any = UNSET,
        assignees: list[str] | None = None,
    ) -> Issue:
        given = {"title": title, "body": body, "labels": labels, "state": state, "assignees": assignees}
        payload = {name: value for name, value in given.items() if value is not None}
        if state == "closed" and state_reason:
            payload["state_reason"] = state_reason
        if milestone is not UNSET:
            payload["milestone"] = milestone
        return _issue_from_rest(await self._rest(f"update issue #{number}", "PATCH", f"/issues/{number}", json=payload))

    # -- comments and timeline ----------------------------------------------------------------------------------

    async def list_comments(self, number: int) -> list[Comment]:
        items = await self._pages(f"list comments on #{number}", f"/issues/{number}/comments")
        return [
            Comment(c["id"], c.get("body") or "", (c.get("user") or {}).get("login", ""), c["created_at"])
            for c in items
        ]

    async def add_comment(self, number: int, body: str) -> Comment:
        c = await self._rest(f"comment on #{number}", "POST", f"/issues/{number}/comments", json={"body": body})
        return Comment(c["id"], c.get("body") or "", (c.get("user") or {}).get("login", ""), c["created_at"])

    async def list_events(self, number: int) -> list[Event]:
        items = await self._pages(f"list the timeline of #{number}", f"/issues/{number}/timeline")
        return [_event(item) for item in items]

    # -- links --------------------------------------------------------------------------------------------------

    async def add_sub_issue(self, parent: int, child: int, child_id: int) -> None:
        operation = f"add sub-issue #{child} to #{parent}"
        await self._rest(operation, "POST", f"/issues/{parent}/sub_issues", json={"sub_issue_id": child_id})

    async def remove_sub_issue(self, parent: int, child: int, child_id: int) -> None:
        operation = f"remove sub-issue #{child} from #{parent}"
        await self._rest(operation, "DELETE", f"/issues/{parent}/sub_issue", json={"sub_issue_id": child_id})

    async def add_blocked_by(self, number: int, blocker: int, blocker_id: int) -> None:
        operation = f"mark #{number} blocked by #{blocker}"
        await self._rest(operation, "POST", f"/issues/{number}/dependencies/blocked_by", json={"issue_id": blocker_id})

    async def remove_blocked_by(self, number: int, blocker: int, blocker_id: int) -> None:
        operation = f"unmark #{number} blocked by #{blocker}"
        await self._rest(operation, "DELETE", f"/issues/{number}/dependencies/blocked_by/{blocker_id}")

    # -- milestones and labels ----------------------------------------------------------------------------------

    async def list_milestones(self) -> list[Milestone]:
        return [_milestone(m) for m in await self._pages("list milestones", "/milestones", state="all")]

    async def create_milestone(self, title: str, description: str) -> Milestone:
        payload = {"title": title, "description": description}
        return _milestone(await self._rest("create milestone", "POST", "/milestones", json=payload))

    async def update_milestone(
        self, number: int, *, title: str | None = None, description: str | None = None, state: str | None = None
    ) -> Milestone:
        given = {"title": title, "description": description, "state": state}
        payload = {name: value for name, value in given.items() if value is not None}
        return _milestone(
            await self._rest(f"update milestone {number}", "PATCH", f"/milestones/{number}", json=payload)
        )

    async def list_labels(self) -> list[str]:
        return [label["name"] for label in await self._pages("list labels", "/labels")]

    async def create_label(self, name: str, colour: str, description: str) -> None:
        payload = {"name": name, "color": colour, "description": description[:100]}
        await self._rest(f"create label {name}", "POST", "/labels", json=payload)
