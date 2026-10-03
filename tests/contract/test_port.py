"""What the server relies on GitHub to do (ADR-0004). Every test here must hold for the fake and for GitHub."""

import pytest

from gh_project_mcp.github.port import GitHubError


async def _issue(port, title="Contract test issue", labels=("contract-test",), **kwargs):
    return await port.create_issue(title, kwargs.pop("body", "body"), list(labels), **kwargs)


def _find(issues, number):
    return next(i for i in issues if i.number == number)


async def test_a_created_issue_is_listed_with_what_it_was_given(port):
    created = await _issue(port, body="first line\n\n## Section\n\ntext", labels=("contract-test", "task"))
    assert created.number > 0 and created.id > 0 and created.url.endswith(f"/issues/{created.number}")
    listed = _find(await port.list_issues(), created.number)
    assert listed.title == "Contract test issue"
    assert listed.body == "first line\n\n## Section\n\ntext"
    assert sorted(listed.labels) == ["contract-test", "task"]
    assert (listed.state, listed.parent, listed.sub_issues, listed.blocked_by) == ("open", None, [], [])
    assert listed.id == created.id and listed.updated_at


async def test_a_label_the_repository_lacks_is_created_on_use(port):
    await _issue(port, labels=("contract-test", "contract-novel-label"))
    assert "contract-novel-label" in await port.list_labels()


async def test_update_changes_only_what_is_named(port):
    issue = await _issue(port, labels=("contract-test", "task"))
    updated = await port.update_issue(issue.number, labels=["contract-test", "task", "status:blocked"])
    assert (updated.title, updated.body, updated.state) == ("Contract test issue", "body", "open")
    assert sorted(updated.labels) == ["contract-test", "status:blocked", "task"]
    updated = await port.update_issue(issue.number, body="new body")
    assert updated.body == "new body" and "status:blocked" in updated.labels


async def test_closing_carries_a_reason_and_reopening_clears_it(port):
    issue = await _issue(port)
    closed = await port.update_issue(issue.number, state="closed", state_reason="not_planned")
    assert (closed.state, closed.state_reason) == ("closed", "not_planned")
    completed = await port.update_issue(issue.number, state="closed", state_reason="completed")
    assert (completed.state, completed.state_reason) == ("closed", "completed")
    reopened = await port.update_issue(issue.number, state="open")
    assert reopened.state == "open" and reopened.state_reason in (None, "reopened")
    listed = _find(await port.list_issues(), issue.number)
    assert listed.state == "open"


async def test_labels_and_state_change_in_one_update(port):
    issue = await _issue(port, labels=("contract-test", "task", "status:in-progress"))
    updated = await port.update_issue(
        issue.number, labels=["contract-test", "task"], state="closed", state_reason="completed", body="done"
    )
    assert (updated.state, updated.state_reason, updated.body) == ("closed", "completed", "done")
    assert "status:in-progress" not in updated.labels


async def test_a_missing_issue_is_a_404(port):
    with pytest.raises(GitHubError) as refused:
        await port.update_issue(999_999_999, title="nope")
    assert refused.value.status == 404
    with pytest.raises(GitHubError) as refused:
        await port.add_comment(999_999_999, "nope")
    assert refused.value.status == 404


async def test_comments_are_listed_in_order(port):
    issue = await _issue(port)
    await port.add_comment(issue.number, "first")
    await port.add_comment(issue.number, "second\n\nwith a paragraph")
    comments = await port.list_comments(issue.number)
    assert [c.body for c in comments] == ["first", "second\n\nwith a paragraph"]
    assert all(c.author and c.created_at for c in comments)


async def test_sub_issues_show_from_both_ends(port):
    parent, child = await _issue(port, "Contract parent"), await _issue(port, "Contract child")
    await port.add_sub_issue(parent.number, child.number, child.id)
    issues = await port.list_issues()
    assert _find(issues, parent.number).sub_issues == [child.number]
    assert _find(issues, child.number).parent == parent.number
    await port.remove_sub_issue(parent.number, child.number, child.id)
    issues = await port.list_issues()
    assert _find(issues, parent.number).sub_issues == [] and _find(issues, child.number).parent is None


async def test_an_issue_has_one_parent(port):
    first, second = await _issue(port, "Contract parent 1"), await _issue(port, "Contract parent 2")
    child = await _issue(port, "Contract child")
    await port.add_sub_issue(first.number, child.number, child.id)
    with pytest.raises(GitHubError) as refused:
        await port.add_sub_issue(second.number, child.number, child.id)
    assert refused.value.status == 422


async def test_an_issue_cannot_be_under_itself(port):
    top, below = await _issue(port, "Contract top"), await _issue(port, "Contract below")
    await port.add_sub_issue(top.number, below.number, below.id)
    for parent, child in ((top, top), (below, top)):
        with pytest.raises(GitHubError) as refused:
            await port.add_sub_issue(parent.number, child.number, child.id)
        assert refused.value.status == 422


async def test_blocked_by_is_listed_and_removed(port):
    waiting, blocker = await _issue(port, "Contract waiting"), await _issue(port, "Contract blocker")
    await port.add_blocked_by(waiting.number, blocker.number, blocker.id)
    assert _find(await port.list_issues(), waiting.number).blocked_by == [blocker.number]
    with pytest.raises(GitHubError):
        await port.add_blocked_by(waiting.number, blocker.number, blocker.id)
    await port.remove_blocked_by(waiting.number, blocker.number, blocker.id)
    assert _find(await port.list_issues(), waiting.number).blocked_by == []


async def test_since_returns_what_changed_after_it(port):
    old, new = await _issue(port, "Contract old"), await _issue(port, "Contract new")
    cursor = max(i.updated_at for i in await port.list_issues())
    assert cursor >= new.updated_at
    await port.add_comment(old.number, "bump")
    changed = await port.list_issues(since=cursor)
    assert old.number in [i.number for i in changed]


async def test_link_changes_are_seen_by_since(port):
    """ADR-0001's open risk: the incremental refresh relies on a link change bumping updated_at."""
    parent, child = await _issue(port, "Contract parent"), await _issue(port, "Contract child")
    blocker = await _issue(port, "Contract blocker")
    cursor = max(i.updated_at for i in await port.list_issues())
    await port.add_sub_issue(parent.number, child.number, child.id)
    await port.add_blocked_by(child.number, blocker.number, blocker.id)
    changed = {i.number: i for i in await port.list_issues(since=cursor)}
    assert changed[child.number].parent == parent.number
    assert changed[child.number].blocked_by == [blocker.number]
    assert changed[parent.number].sub_issues == [child.number]


async def test_milestones(port):
    title = "Contract milestone"
    existing = next((m for m in await port.list_milestones() if m.title == title), None)
    milestone = existing or await port.create_milestone(title, "Purpose.\n\n## Success criteria\n\n- one")
    updated = await port.update_milestone(milestone.number, description="Changed.", state="closed")
    assert (updated.title, updated.description, updated.state) == (title, "Changed.", "closed")
    listed = next(m for m in await port.list_milestones() if m.number == milestone.number)
    assert listed.state == "closed" and listed.description == "Changed."
    await port.update_milestone(milestone.number, state="open")
    issue = await _issue(port, milestone=milestone.number)
    assert _find(await port.list_issues(), issue.number).milestone == milestone.number
    cleared = await port.update_issue(issue.number, milestone=None)
    assert cleared.milestone is None
    with pytest.raises(GitHubError) as refused:
        await _issue(port, milestone=999_999)
    assert refused.value.status == 422


async def test_the_timeline_records_what_happened(port):
    issue = await _issue(port, labels=("contract-test", "task"))
    await port.update_issue(issue.number, labels=["contract-test", "task", "status:blocked"])
    await port.add_comment(issue.number, "why")
    await port.update_issue(issue.number, state="closed", state_reason="completed")
    kinds = [e.kind for e in await port.list_events(issue.number)]
    assert {"labeled", "commented", "closed"} <= set(kinds)
    assert kinds.index("labeled") < kinds.index("commented") < kinds.index("closed")
