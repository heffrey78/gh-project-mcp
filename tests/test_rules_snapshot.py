"""The rules as predicates over a snapshot (ADR-0006): the same definitions refuse a move and report drift."""

import pytest

from gh_project_mcp import rules
from gh_project_mcp.github.fake import FakeGitHub
from gh_project_mcp.rules import StatusRefused
from gh_project_mcp.tracker import Tracker
from tests.helpers import VOCABULARY, seed


@pytest.fixture
def github():
    return FakeGitHub()


async def _tracker(github) -> Tracker:
    tracker = Tracker(github, VOCABULARY)
    await tracker.refresh()
    return tracker


async def test_ready_means_not_started_unblocked_and_approved(github):
    approved = seed(github, "requirement", status="Approved")
    draft = seed(github, "requirement")
    done = seed(github, "task", status="Complete", parent=approved)
    started = seed(github, "task", status="In Progress", parent=approved)
    ready_p2 = seed(github, "task", parent=approved, blocked_by=(done,))
    waiting = seed(github, "task", parent=approved, blocked_by=(started,), priority="P0")
    under_draft = seed(github, "task", parent=draft, priority="P0")
    parent = seed(github, "task", parent=approved, priority="P0")
    ready_p1 = seed(github, "task", parent=parent, priority="P1")
    orphan = seed(github, "task", priority=None)
    tracker = await _tracker(github)

    assert [t.number for t in rules.ready_tasks(tracker)] == [ready_p1, ready_p2, orphan]
    assert [b.number for b in rules.unmet_blockers(tracker, tracker.get(waiting))] == [started]
    assert not rules.is_ready(tracker, tracker.get(under_draft))
    assert not rules.is_ready(tracker, tracker.get(parent))  # worked through its subtask


async def test_work_complete_is_all_tasks_settled_and_the_decision_missing(github):
    finished = seed(github, "requirement", status="Approved")
    seed(github, "task", status="Complete", parent=finished)
    seed(github, "task", status="Abandoned", parent=finished)
    unfinished = seed(github, "requirement", status="Approved")
    seed(github, "task", status="Complete", parent=unfinished)
    seed(github, "task", status="Blocked", parent=unfinished)
    no_tasks = seed(github, "requirement", status="Approved")
    all_abandoned = seed(github, "requirement", status="Approved")
    seed(github, "task", status="Abandoned", parent=all_abandoned)
    already = seed(github, "requirement", status="Implemented")
    seed(github, "task", status="Complete", parent=already)
    tracker = await _tracker(github)

    complete = [r.number for r in tracker.records("requirement") if rules.is_work_complete(tracker, r)]
    assert complete == [finished]
    assert no_tasks not in complete and all_abandoned not in complete


async def test_validated_with_an_open_task_is_refused_in_every_mode(github, monkeypatch):
    requirement = seed(github, "requirement", status="Implemented")
    parent = seed(github, "task", status="Complete", parent=requirement)
    open_leaf = seed(github, "task", status="In Progress", parent=parent)
    tracker = await _tracker(github)
    for mode in ("off", "warn", "enforce"):
        monkeypatch.setenv("GH_PROJECT_RULES", mode)
        with pytest.raises(StatusRefused, match=rf"cannot be Validated while tasks under it are open: #{open_leaf}"):
            rules.always_on(tracker, tracker.get(requirement), "Validated")
    rules.always_on(tracker, tracker.get(requirement), "Deprecated")


async def test_reasons_a_task_move_is_risky(github):
    draft = seed(github, "requirement")
    approved = seed(github, "requirement", status="Approved")
    unfinished = seed(github, "task", status="In Progress", parent=approved)
    abandoned = seed(github, "task", status="Abandoned", parent=approved)
    task = seed(github, "task", parent=approved, blocked_by=(unfinished, abandoned))
    subtask = seed(github, "task", parent=task)
    under_draft = seed(github, "task", parent=draft)
    blocked = seed(github, "task", status="Blocked", parent=approved)
    complete = seed(github, "task", status="Complete", parent=approved)
    tracker = await _tracker(github)

    start = rules.move_reasons(tracker, tracker.get(task), "In Progress")
    assert start == [
        f"It waits on work that is not finished: #{unfinished} (In Progress).",
        f"It waits on abandoned work that will never finish: #{abandoned} (Abandoned). Remove the link with "
        "unlink_records, or abandon this task too.",
    ]
    finish = rules.move_reasons(tracker, tracker.get(task), "Complete")
    assert finish[2:] == [f"It has open subtasks: #{subtask} (Not Started).", "It was never started."]
    assert rules.move_reasons(tracker, tracker.get(under_draft), "In Progress") == [
        f"Its requirement #{draft} is Draft, not Approved."
    ]
    assert rules.move_reasons(tracker, tracker.get(blocked), "Complete") == ["It is still Blocked."]
    assert rules.move_reasons(tracker, tracker.get(complete), "In Progress") == [
        "It was Complete: this reopens finished work."
    ]
    assert rules.move_reasons(tracker, tracker.get(task), "Blocked") == []
    assert rules.move_reasons(tracker, tracker.get(task), "Abandoned") == []


async def test_implemented_with_open_tasks_is_risky(github):
    requirement = seed(github, "requirement", status="Approved")
    seed(github, "task", status="Complete", parent=requirement)
    still_open = seed(github, "task", parent=requirement)
    tracker = await _tracker(github)
    assert rules.move_reasons(tracker, tracker.get(requirement), "Implemented") == [
        f"Tasks under it are still open: #{still_open} (Not Started)."
    ]
    assert rules.move_reasons(tracker, tracker.get(requirement), "Deprecated") == []


async def test_a_task_planned_against_an_unapproved_requirement_is_risky(github):
    draft, approved = seed(github, "requirement"), seed(github, "requirement", status="Approved")
    tracker = await _tracker(github)
    assert "Requirement #1 is Draft" in rules.new_task_reasons(tracker.get(draft))[0]
    assert rules.new_task_reasons(tracker.get(approved)) == []
    assert rules.new_task_reasons(None) == []


async def test_a_well_formed_tracker_has_no_drift(github):
    requirement = seed(github, "requirement", status="Validated")
    seed(github, "task", status="Complete", parent=requirement)
    old = seed(github, "decision", status="Superseded", fields={"addresses": [requirement]})
    seed(github, "decision", status="Accepted", fields={"addresses": [requirement], "supersedes": [old]})
    seed(github, "task", status="Abandoned")  # retired work under nothing is not worth chasing
    tracker = await _tracker(github)
    assert rules.drift(tracker) == []


async def test_drift_is_what_the_servers_own_rules_would_not_have_produced(github):
    validated = seed(github, "requirement", status="Validated")
    open_task = seed(github, "task", status="In Progress", parent=validated)
    draft = seed(github, "requirement")
    early = seed(github, "task", status="In Progress", parent=draft)
    two_labels = seed(github, "requirement", status="Approved", extra_labels=("status:under-review",))
    by_hand = seed(github, "task", parent=validated, body="please fix the thing")
    orphan = seed(github, "task")
    stale = seed(github, "decision", status="Superseded")
    replaced = seed(github, "decision", status="Accepted")
    replacement = seed(github, "decision", status="Accepted", fields={"supersedes": [replaced]})
    tracker = await _tracker(github)

    found = {(record.number, message) for record, message in rules.drift(tracker)}
    assert found == {
        (
            validated,
            f"is Validated while tasks under it are open: #{open_task} (In Progress), #{by_hand} (Not Started)",
        ),
        (early, f"is In Progress under requirement #{draft}, which is Draft"),
        (two_labels, "has 2 status labels (Under Review, Approved); read as Approved"),
        (by_hand, "its body holds no fields the server recognises"),
        (orphan, "implements no requirement: it is not a sub-issue of one"),
        (stale, "is Superseded but no decision names it in a Supersedes section"),
        (replaced, f"is Accepted though #{replacement} (Accepted) supersedes it"),
    }


async def test_finished_records_are_not_chased_for_how_they_were_written(github):
    seed(github, "task", status="Complete", body="written by hand")
    seed(github, "requirement", status="Deprecated", body="never mind")
    assert rules.drift(await _tracker(github)) == []


async def test_a_parent_finished_through_its_subtasks_counts_as_started(github):
    requirement = seed(github, "requirement", status="Approved")
    parent = seed(github, "task", parent=requirement)
    seed(github, "task", status="Complete", parent=parent)
    seed(github, "task", status="Abandoned", parent=parent)
    lone = seed(github, "task", parent=requirement)
    tracker = await _tracker(github)
    assert rules.move_reasons(tracker, tracker.get(parent), "Complete") == []
    assert rules.move_reasons(tracker, tracker.get(lone), "Complete") == ["It was never started."]
