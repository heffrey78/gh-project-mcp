"""What only the fake has: request counts, the write log and edits behind the server's back."""

from gh_project_mcp.github.fake import FakeGitHub
from tests.helpers import seed


async def test_listing_counts_one_request_per_page_of_100():
    github = FakeGitHub()
    for _ in range(250):
        seed(github, "task")
    assert len(await github.list_issues()) == 250
    assert github.requests == 3 and github.writes == []


async def test_an_empty_listing_is_still_a_request():
    github = FakeGitHub()
    assert await github.list_issues() == [] and github.requests == 1


async def test_writes_are_logged_and_reads_are_not():
    github = FakeGitHub()
    issue = await github.create_issue("t", "b", ["task"])
    await github.list_comments(issue.number)
    await github.add_comment(issue.number, "c")
    assert [name for name, _ in github.writes] == ["create_issue", "add_comment"]
    assert github.requests == 3


async def test_behind_the_back_changes_without_a_trace_in_the_counters():
    github = FakeGitHub()
    requirement, task = seed(github, "requirement"), seed(github, "task")
    before = github.issues[task].updated_at
    github.behind_the_back(task, state="closed", parent=requirement)
    assert (github.requests, github.writes) == (0, [])
    assert github.issues[task].state_reason == "completed" and github.issues[task].updated_at > before
    assert github.issues[requirement].sub_issues == [task]


async def test_returned_issues_are_copies():
    github = FakeGitHub()
    seed(github, "task")
    (listed,) = await github.list_issues()
    listed.labels.append("mutated")
    assert "mutated" not in github.issues[1].labels


async def test_a_link_change_leaves_updated_at_alone_as_github_does():
    github = FakeGitHub()
    parent, child = seed(github, "requirement"), seed(github, "task")
    before = github.issues[child].updated_at, github.issues[parent].updated_at
    await github.add_sub_issue(parent, child, github.issues[child].id)
    await github.add_blocked_by(parent, child, github.issues[child].id)
    assert (github.issues[child].updated_at, github.issues[parent].updated_at) == before
