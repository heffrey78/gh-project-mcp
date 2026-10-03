"""The real client, driven through httpx.MockTransport: no socket is opened (ADR-0004, REQ-0001-TECH-00)."""

import json
import logging

import httpx
import pytest

from gh_project_mcp.config import Config
from gh_project_mcp.github import http as http_module
from gh_project_mcp.github.http import HttpGitHub
from gh_project_mcp.github.port import GitHubError

TOKEN = "ghp_SECRETsecretSECRETsecret1234"
ONE_PARENT = "Sub issue may only have one parent"
REST_ISSUE = {
    "number": 7, "id": 5622321494, "title": "T", "body": None, "state": "closed", "state_reason": "not_planned",
    "labels": [{"name": "task"}, {"name": "P1"}], "milestone": {"number": 2}, "assignees": [{"login": "octocat"}],
    "html_url": "https://github.com/octo/sandbox/issues/7", "user": {"login": "octocat"},
    "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-02T00:00:00Z",
}  # fmt: skip


def node(number, **over):
    base = {
        "number": number, "fullDatabaseId": str(5_000_000_000 + number), "title": f"Issue {number}", "body": "b",
        "state": "OPEN", "stateReason": None, "url": f"https://github.com/octo/sandbox/issues/{number}",
        "createdAt": "2026-01-01T00:00:00Z", "updatedAt": "2026-01-01T00:00:00Z", "author": {"login": "octocat"},
        "labels": {"nodes": [{"name": "task"}]}, "milestone": None, "assignees": {"nodes": []}, "parent": None,
        "subIssues": {"nodes": []}, "blockedBy": {"nodes": []},
    }  # fmt: skip
    return {**base, **over}


def client(handler, **config):
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    github = HttpGitHub(Config(repo="octo/sandbox", token=TOKEN, **config), transport=httpx.MockTransport(record))
    return github, seen


def body(request: httpx.Request) -> dict:
    return json.loads(request.content)


async def test_requests_carry_the_token_and_the_api_version():
    github, seen = client(lambda r: httpx.Response(200, json=[]))
    await github.list_labels()
    request = seen[0]
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.headers["x-github-api-version"] == "2022-11-28"
    assert str(request.url) == "https://api.github.com/repos/octo/sandbox/labels?per_page=100"


async def test_the_snapshot_follows_pagination_and_reads_links():
    pages = [
        {"nodes": [node(1, subIssues={"nodes": [{"number": 2}]}, milestone={"number": 3})],
         "pageInfo": {"hasNextPage": True, "endCursor": "CUR"}},
        {"nodes": [node(2, parent={"number": 1}, blockedBy={"nodes": [{"number": 9}]}, state="CLOSED",
                        stateReason="NOT_PLANNED", body=None)],
         "pageInfo": {"hasNextPage": False, "endCursor": None}},
    ]  # fmt: skip

    def handler(request):
        cursor = body(request)["variables"]["cursor"]
        return httpx.Response(200, json={"data": {"repository": {"issues": pages[0 if cursor is None else 1]}}})

    github, seen = client(handler)
    issues = await github.list_issues(since="2026-01-01T00:00:00Z", labels=["task", "requirement"])
    assert len(seen) == 2 and [body(r)["variables"]["cursor"] for r in seen] == [None, "CUR"]
    variables = body(seen[0])["variables"]
    assert (variables["owner"], variables["name"]) == ("octo", "sandbox")
    assert (variables["since"], variables["labels"]) == ("2026-01-01T00:00:00Z", ["task", "requirement"])
    first, second = issues
    assert (first.number, first.id, first.sub_issues, first.milestone) == (1, 5_000_000_001, [2], 3)
    assert (second.parent, second.blocked_by, second.state, second.state_reason) == (1, [9], "closed", "not_planned")
    assert second.body == "" and second.labels == ["task"]


async def test_create_and_update_send_only_what_is_named():
    github, seen = client(lambda r: httpx.Response(200, json=REST_ISSUE))
    created = await github.create_issue("T", "body", ["task"], milestone=2, assignees=["octocat"])
    assert (seen[0].method, seen[0].url.path) == ("POST", "/repos/octo/sandbox/issues")
    assert body(seen[0]) == {"title": "T", "body": "body", "labels": ["task"], "milestone": 2, "assignees": ["octocat"]}
    # An ID past 2^31, a null body, and label objects all come back as plain values.
    assert (created.id, created.body, created.labels, created.milestone) == (5622321494, "", ["task", "P1"], 2)
    assert (created.state_reason, created.assignees) == ("not_planned", ["octocat"])

    await github.update_issue(7, labels=["task"], state="closed", state_reason="completed")
    assert (seen[1].method, seen[1].url.path) == ("PATCH", "/repos/octo/sandbox/issues/7")
    assert body(seen[1]) == {"labels": ["task"], "state": "closed", "state_reason": "completed"}
    await github.update_issue(7, milestone=None)
    assert body(seen[2]) == {"milestone": None}
    await github.update_issue(7, state="open", state_reason="ignored")
    assert body(seen[3]) == {"state": "open"}


async def test_link_endpoints_take_database_ids():
    github, seen = client(lambda r: httpx.Response(204))
    await github.add_sub_issue(1, 2, 5002)
    await github.remove_sub_issue(1, 2, 5002)
    await github.add_blocked_by(2, 3, 5003)
    await github.remove_blocked_by(2, 3, 5003)
    assert [(r.method, r.url.path) for r in seen] == [
        ("POST", "/repos/octo/sandbox/issues/1/sub_issues"),
        ("DELETE", "/repos/octo/sandbox/issues/1/sub_issue"),
        ("POST", "/repos/octo/sandbox/issues/2/dependencies/blocked_by"),
        ("DELETE", "/repos/octo/sandbox/issues/2/dependencies/blocked_by/5003"),
    ]
    assert [body(r) for r in seen[:3]] == [{"sub_issue_id": 5002}, {"sub_issue_id": 5002}, {"issue_id": 5003}]


async def test_rest_listings_follow_the_link_header():
    def handler(request):
        if "page=2" in str(request.url):
            return httpx.Response(200, json=[{"id": 2, "body": "second", "user": {"login": "b"}, "created_at": "t2"}])
        link = '<https://api.github.com/repos/octo/sandbox/issues/1/comments?per_page=100&page=2>; rel="next"'
        first = [{"id": 1, "body": "first", "user": {"login": "a"}, "created_at": "t1"}]
        return httpx.Response(200, json=first, headers={"link": link})

    github, seen = client(handler)
    comments = await github.list_comments(1)
    assert [(c.body, c.author) for c in comments] == [("first", "a"), ("second", "b")] and len(seen) == 2


async def test_milestones_labels_and_timeline():
    def handler(request):
        if request.url.path.endswith("/timeline"):
            return httpx.Response(200, json=[
                {"event": "labeled", "actor": {"login": "a"}, "created_at": "t1", "label": {"name": "task"}},
                {"event": "commented", "user": {"login": "b"}, "created_at": "t2", "body": "first line\nmore"},
                {"event": "closed", "actor": {"login": "a"}, "created_at": "t3", "state_reason": "completed"},
                {"event": "committed"},
            ])  # fmt: skip
        if "milestones" in request.url.path:
            milestone = {"number": 1, "title": "v1", "description": None, "state": "open", "html_url": "u"}
            return httpx.Response(200, json=[milestone] if request.method == "GET" else milestone)
        return httpx.Response(201, json={})

    github, seen = client(handler)
    events = await github.list_events(1)
    assert [(e.kind, e.actor, e.detail) for e in events] == [
        ("labeled", "a", "task"), ("commented", "b", "first line"), ("closed", "a", "completed"), ("committed", "", ""),
    ]  # fmt: skip
    (listed,) = await github.list_milestones()
    assert (listed.title, listed.description) == ("v1", "") and "state=all" in str(seen[1].url)
    await github.update_milestone(1, state="closed")
    assert (seen[2].method, body(seen[2])) == ("PATCH", {"state": "closed"})
    await github.create_label("task", "0e8a16", "x" * 150)
    assert body(seen[3]) == {"name": "task", "color": "0e8a16", "description": "x" * 100}


@pytest.mark.parametrize(
    ("response", "status", "expected"),
    [
        (httpx.Response(401, json={"message": "Bad credentials"}), 401, "the token was rejected (Bad credentials)"),
        (httpx.Response(404, json={"message": "Not Found"}), 404,
         "Not Found. The repository octo/sandbox may not exist, or the token cannot see it"),
        (httpx.Response(422, json={"message": "Validation Failed", "errors": [{"message": ONE_PARENT}]}),
         422, "Validation Failed: Sub issue may only have one parent"),
        (httpx.Response(422, json={"message": "Validation Failed", "errors": [{"field": "title", "code": "missing"}]}),
         422, "Validation Failed: title missing"),
        (httpx.Response(403, json={"message": "API rate limit exceeded"},
                        headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1767225600"}),
         403, "rate limit exhausted; it resets at 00:00:00 UTC (API rate limit exceeded)"),
        (httpx.Response(403, json={"message": "You have exceeded a secondary rate limit"},
                        headers={"retry-after": "60"}),
         403, "secondary rate limit; retry after 60 seconds"),
        (httpx.Response(502, text="<html>Bad Gateway</html>"), 502, "Bad Gateway"),
    ],
)  # fmt: skip
async def test_failures_carry_githubs_message_and_the_operation(response, status, expected):
    github, _ = client(lambda r: response)
    with pytest.raises(GitHubError) as refused:
        await github.update_issue(7, title="x")
    assert refused.value.status == status
    assert expected in str(refused.value) and str(refused.value).endswith("(update issue #7)")
    assert str(refused.value).startswith(f"GitHub {status}: ")


async def test_graphql_errors_and_a_missing_repository():
    errors = {"errors": [{"type": "NOT_FOUND", "message": "Could not resolve to a Repository"}]}
    github, _ = client(lambda r: httpx.Response(200, json=errors))
    with pytest.raises(GitHubError, match="Could not resolve to a Repository") as refused:
        await github.list_issues()
    assert refused.value.status == 404
    github, _ = client(lambda r: httpx.Response(200, json={"data": {"repository": None}}))
    with pytest.raises(GitHubError, match="the repository octo/sandbox was not found"):
        await github.list_issues()


async def test_a_network_failure_is_a_github_error():
    def handler(request):
        raise httpx.ConnectError("name resolution failed")

    github, _ = client(handler)
    with pytest.raises(GitHubError, match="could not reach GitHub: ConnectError: name resolution failed"):
        await github.list_labels()


async def test_the_token_never_appears_in_an_error_or_a_log(caplog):
    caplog.set_level(logging.DEBUG)
    responses = [
        httpx.Response(401, json={"message": "Bad credentials"}),
        httpx.Response(500, json={"message": "Server Error"}),
    ]
    for response in responses:
        github, _ = client(lambda r, response=response: response)
        with pytest.raises(GitHubError) as refused:
            await github.create_issue("t", "b", [])
        assert TOKEN not in str(refused.value) and TOKEN not in repr(refused.value)
    assert TOKEN not in caplog.text


async def test_without_a_token_nothing_is_sent(monkeypatch):
    monkeypatch.setattr(http_module, "_token_from_gh", lambda api_url: None)
    seen = []
    github = HttpGitHub(Config(repo="octo/sandbox"), transport=httpx.MockTransport(lambda r: seen.append(r)))
    with pytest.raises(GitHubError, match="no GitHub token: set GH_TOKEN or GITHUB_TOKEN"):
        await github.list_labels()
    assert seen == []


async def test_the_gh_cli_token_is_asked_for_once(monkeypatch):
    asked = []
    monkeypatch.setattr(http_module, "_token_from_gh", lambda api_url: asked.append(api_url) or "from-gh")
    github = HttpGitHub(
        Config(repo="octo/sandbox"), transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))
    )
    await github.list_labels()
    await github.list_labels()
    assert asked == ["https://api.github.com"]


async def test_an_enterprise_host_is_a_base_url():
    github, seen = client(lambda r: httpx.Response(200, json=[]), api_url="https://ghe.example.com/api/v3")
    await github.list_labels()
    assert str(seen[0].url).startswith("https://ghe.example.com/api/v3/repos/octo/sandbox/labels")


def test_a_client_needs_a_repository():
    from gh_project_mcp.config import ConfigError

    with pytest.raises(ConfigError, match="No repository is configured"):
        HttpGitHub(Config())


def test_configuration_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("GH_PROJECT_REPO", " octo/sandbox ")
    monkeypatch.setenv("GH_PROJECT_API_URL", "https://ghe.example.com/api/v3/")
    monkeypatch.setenv("GH_PROJECT_READ_ONLY", "On")
    monkeypatch.setenv("GH_PROJECT_LABEL_PREFIX", "lc:")
    monkeypatch.setenv("GH_PROJECT_CALL_LOG", "/tmp/calls.jsonl")
    monkeypatch.setenv("GITHUB_TOKEN", "from-github-token")
    config = Config.from_env()
    assert config == Config(
        repo="octo/sandbox", api_url="https://ghe.example.com/api/v3", read_only=True, label_prefix="lc:",
        call_log="/tmp/calls.jsonl", token="from-github-token",
    )  # fmt: skip
    monkeypatch.setenv("GH_TOKEN", "from-gh-token")
    assert Config.from_env().token == "from-gh-token"
    for name in ("GH_PROJECT_REPO", "GH_PROJECT_API_URL", "GH_PROJECT_READ_ONLY", "GH_PROJECT_LABEL_PREFIX",
                 "GH_PROJECT_CALL_LOG", "GITHUB_TOKEN", "GH_TOKEN"):  # fmt: skip
        monkeypatch.delenv(name)
    assert Config.from_env() == Config()
