"""The same behaviour tests run against FakeGitHub always, and against the real client only when asked.

A live run needs GH_PROJECT_LIVE_REPO=owner/name, and the name must contain "sandbox": these tests create issues.
"""

import os

import pytest

from gh_project_mcp.github.fake import FakeGitHub

LIVE_REPO_ENV = "GH_PROJECT_LIVE_REPO"


def live_repo() -> str | None:
    repo = os.environ.get(LIVE_REPO_ENV, "").strip()
    if not repo:
        return None
    if "sandbox" not in repo.split("/")[-1].lower():
        raise pytest.UsageError(
            f"{LIVE_REPO_ENV}={repo}: live tests create and close issues, so the repository's name must contain "
            "'sandbox'"
        )
    return repo


@pytest.fixture(params=["fake", pytest.param("live", marks=pytest.mark.github_live)])
async def port(request):
    """A GitHub to test against, and the issues a test created closed afterwards when it is the real one."""
    if request.param == "fake":
        yield FakeGitHub()
        return
    repo = live_repo()
    if repo is None:
        pytest.skip(f"set {LIVE_REPO_ENV} to a sandbox repository to run live contract tests")
    from gh_project_mcp.config import Config
    from gh_project_mcp.github.http import HttpGitHub

    github = HttpGitHub(Config(repo=repo))
    before = {issue.number for issue in await github.list_issues()}
    try:
        yield github
    finally:
        for issue in await github.list_issues():
            if issue.number not in before and issue.state == "open":
                await github.update_issue(issue.number, state="closed", state_reason="not_planned")
        await github.aclose()
