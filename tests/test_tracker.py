"""The snapshot (ADR-0001, REQ-0002-NFUNC-00): few requests, own writes visible, GitHub's edits seen."""

import pytest

from gh_project_mcp.github.fake import FakeGitHub
from gh_project_mcp.tracker import NotARecord, Tracker
from tests.helpers import VOCABULARY, seed


@pytest.fixture
def github():
    return FakeGitHub()


async def _tracker(github) -> Tracker:
    tracker = Tracker(github, VOCABULARY)
    await tracker.refresh()
    return tracker


async def test_cold_load_of_200_records_takes_three_requests_and_a_refresh_one(github):
    requirement = seed(github, "requirement", status="Approved")
    for _ in range(199):
        seed(github, "task", parent=requirement)
    tracker = await _tracker(github)
    assert len(tracker.records()) == 200
    assert github.requests == 3  # two pages of issues and the milestones
    await tracker.refresh()
    assert github.requests == 4 and github.writes == []


async def test_issues_without_a_kind_label_are_not_records(github):
    task = seed(github, "task")
    await github.create_issue("A bug report", "it broke", ["bug"])
    tracker = await _tracker(github)
    assert [r.number for r in tracker.records()] == [task]
    with pytest.raises(NotARecord, match="#2 is not a lifecycle record in octo/sandbox"):
        tracker.get(2)
    assert tracker.find(2) is None


async def test_a_change_on_github_is_seen_at_the_next_refresh(github):
    requirement = seed(github, "requirement", status="Approved")
    task, other = seed(github, "task"), seed(github, "task")
    tracker = await _tracker(github)
    assert tracker.get(task).status == "Not Started" and tracker.children(requirement) == []

    github.behind_the_back(task, state="closed", parent=requirement, blocked_by=[other])
    github.behind_the_back(other, labels=["bug"])  # someone took the kind label off
    await tracker.refresh()

    assert tracker.get(task).status == "Complete"
    assert [r.number for r in tracker.children(requirement)] == [task]
    assert tracker.requirement_of(task).number == requirement
    assert tracker.find(other) is None
    assert tracker.blockers(task) == []  # it points at an issue that is no longer a record


async def test_own_writes_are_visible_without_a_request(github):
    requirement = seed(github, "requirement", status="Approved")
    tracker = await _tracker(github)
    github.reset_counters()

    issue = await github.create_issue("New task", "", ["task", "P1"])
    await github.add_sub_issue(requirement, issue.number, issue.id)
    record = tracker.put(issue)
    tracker.set_parent(issue.number, requirement)
    requests_for_the_writes = github.requests

    assert (record.kind, record.status, record.priority) == ("task", "Not Started", "P1")
    assert tracker.parent(issue.number).number == requirement
    assert [r.number for r in tracker.children(requirement)] == [issue.number]
    assert github.requests == requests_for_the_writes


async def test_put_keeps_links_a_write_response_does_not_carry(github):
    requirement = seed(github, "requirement", status="Approved")
    blocker = seed(github, "task", parent=requirement)
    task = seed(github, "task", parent=requirement, blocked_by=(blocker,))
    tracker = await _tracker(github)
    updated = await github.update_issue(task, labels=["task", "status:in-progress"])
    updated.parent, updated.blocked_by = None, []  # as a REST response would be
    record = tracker.put(updated)
    assert record.status == "In Progress"
    assert tracker.parent(task).number == requirement and tracker.blockers(task)[0].number == blocker


async def test_links_set_and_removed_locally(github):
    a, b, c = seed(github, "requirement"), seed(github, "task"), seed(github, "task")
    tracker = await _tracker(github)
    tracker.set_parent(b, a)
    tracker.set_parent(c, b)
    tracker.set_blocked_by(c, b, True)
    tracker.set_blocked_by(c, b, True)
    assert [r.number for r in tracker.descendants(a)] == [b, c]
    assert [r.number for r in tracker.blocking(b)] == [c] and tracker.get(c).issue.blocked_by == [b]
    tracker.set_parent(c, a)
    assert [r.number for r in tracker.children(a)] == [b, c] and tracker.children(b) == []
    assert tracker.put(await github.update_issue(c, title="renamed")).issue.parent == a
    tracker.set_parent(c, None)
    tracker.set_blocked_by(c, b, False)
    assert tracker.parent(c) is None and tracker.blockers(c) == []


async def test_leaf_tasks_count_a_parent_through_its_subtasks(github):
    requirement = seed(github, "requirement", status="Approved")
    parent = seed(github, "task", parent=requirement)
    leaf_a, leaf_b = seed(github, "task", parent=parent), seed(github, "task", parent=parent)
    deep = seed(github, "task", parent=leaf_b)
    alone = seed(github, "task", parent=requirement)
    tracker = await _tracker(github)
    assert [t.number for t in tracker.leaf_tasks(requirement)] == [leaf_a, deep, alone]
    assert tracker.requirement_of(deep).number == requirement
    assert [r.number for r in tracker.ancestors(deep)] == [leaf_b, parent, requirement]


async def test_decisions_are_found_from_the_requirement_they_address(github):
    requirement = seed(github, "requirement")
    old = seed(github, "decision", status="Superseded", fields={"addresses": [requirement]})
    new = seed(github, "decision", fields={"addresses": [requirement], "supersedes": [old]})
    seed(github, "decision")
    tracker = await _tracker(github)
    assert [d.number for d in tracker.decisions_addressing(requirement)] == [old, new]
    assert [d.number for d in tracker.superseded_by(old)] == [new]


async def test_labels_are_ensured_once(github):
    github.labels["task"] = ("ffffff", "already here")
    tracker = await _tracker(github)
    github.reset_counters()
    created = await tracker.ensure_labels()
    assert "task" not in created and "requirement" in created and "status:in-progress" in created
    assert github.labels["task"] == ("ffffff", "already here")
    assert github.requests == 1 + len(created)
    assert await tracker.ensure_labels() == [] and github.requests == 1 + len(created)


async def test_projects_are_found_by_number_or_title(github):
    milestone = await github.create_milestone("Autumn release", "Ship it.")
    requirement = seed(github, "requirement", milestone=milestone.number)
    tracker = await _tracker(github)
    assert tracker.find_project(1).title == "Autumn release"
    assert tracker.find_project("autumn release").number == 1
    assert tracker.find_project("Winter") is None
    assert [r.number for r in tracker.in_project(1)] == [requirement]


async def test_a_milestone_made_on_github_is_picked_up_when_an_issue_uses_it(github):
    task = seed(github, "task")
    tracker = await _tracker(github)
    made = await github.create_milestone("Made by hand", "free text")
    github.behind_the_back(task, milestone=made.number)
    await tracker.refresh()
    assert tracker.find_project("Made by hand").description == "free text"


async def test_a_busy_repositorys_other_issues_are_not_fetched_after_a_cold_load(github):
    """The first refresh starts from when the listing was answered, not from the newest record."""
    seed(github, "task")  # an old record
    for _ in range(1000):
        await github.create_issue("Somebody's bug report", "", ["bug"])  # a second of the fake's clock each
    github.reset_counters()
    tracker = await _tracker(github)
    assert len(tracker.records()) == 1 and github.requests == 2
    github.reset_counters()
    await tracker.refresh()
    assert github.requests == 1  # one page: the two minutes before the listing, not all thousand issues
    github.behind_the_back(1, state="closed")
    await tracker.refresh()
    assert tracker.get(1).status == "Complete"


async def test_a_change_made_during_the_cold_listing_is_not_missed(github):
    task = seed(github, "task")
    tracker = Tracker(github, VOCABULARY)
    original = github.list_issues

    async def slow_listing(since=None, labels=None):
        issues = await original(since=since, labels=labels)
        github.behind_the_back(task, state="closed")  # lands after the page was read, before the cursor is set
        return issues

    github.list_issues = slow_listing
    await tracker.refresh()
    assert tracker.get(task).status == "Not Started"
    github.list_issues = original
    await tracker.refresh()
    assert tracker.get(task).status == "Complete"
