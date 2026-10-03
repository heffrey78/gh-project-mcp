"""Creating, reading, editing and finding records through the server (REQ-0001-FUNC-00)."""

import pytest

from gh_project_mcp.body import Document
from tests.helpers import call, seed, text

REQUIREMENT = {
    "title": "Search stays fast",
    "type": "NFUNC",
    "priority": "P1",
    "current_state": "A query takes 900 ms.",
    "desired_state": "Search stays quick.",
    "acceptance_criteria": ["Under 50 ms at p95"],
    "validation_metrics": ["p95 under 50 ms at 10k notes"],
}


async def test_a_requirement_becomes_an_issue_with_labels_and_sections(app, github):
    result = await call(app, "create_requirement", **REQUIREMENT, risk="Low")
    assert not result.is_error
    assert text(result) == (
        "Created requirement #1: Search stays fast\nhttps://github.com/octo/sandbox/issues/1\nStatus: Draft"
    )
    assert result.structured_content == {
        "number": 1, "kind": "requirement", "title": "Search stays fast", "status": "Draft", "priority": "P1",
        "url": "https://github.com/octo/sandbox/issues/1",
    }  # fmt: skip
    issue = github.issues[1]
    assert sorted(issue.labels) == ["P1", "requirement"]
    assert issue.body == (
        "**Type:** NFUNC · **Risk:** Low\n\n"
        "## Current state\n\nA query takes 900 ms.\n\n"
        "## Desired state\n\nSearch stays quick.\n\n"
        "## Acceptance criteria\n\n- [ ] Under 50 ms at p95\n\n"
        "## Validation metrics\n\n- p95 under 50 ms at 10k notes"
    )


async def test_the_first_write_creates_the_labels_and_later_ones_do_not(app, github):
    await call(app, "create_requirement", **REQUIREMENT)
    assert github.labels["requirement"] == ("1d76db", "Lifecycle: a requirement")
    assert "status:in-progress" in github.labels
    github.reset_counters()
    await call(app, "create_requirement", **{**REQUIREMENT, "title": "Another"})
    assert github.requests == 2  # the refresh and the issue


async def test_thin_records_warn_and_are_refused_under_enforce(app, github, monkeypatch):
    thin = {k: v for k, v in REQUIREMENT.items() if k not in ("acceptance_criteria", "validation_metrics")}
    result = await call(app, "create_requirement", **thin)
    assert not result.is_error and len(result.structured_content["warnings"]) == 2
    assert "No acceptance_criteria" in text(result) and "No validation_metrics" in text(result)

    monkeypatch.setenv("GH_PROJECT_RULES", "enforce")
    github.reset_counters()
    refused = await call(app, "create_requirement", **thin)
    assert refused.is_error and text(refused).startswith("Refused: create this requirement. No acceptance_criteria")
    assert github.writes == []

    monkeypatch.setenv("GH_PROJECT_RULES", "off")
    quiet = await call(app, "create_requirement", **thin)
    assert "warnings" not in quiet.structured_content


async def test_a_bad_choice_is_refused_by_the_schema(app, github):
    result = await call(app, "create_requirement", **{**REQUIREMENT, "type": "FEATURE"})
    assert result.is_error and "type: 'FEATURE' is not one of" in text(result)
    assert github.requests == 0


async def test_a_decision_names_the_requirements_it_addresses(app, github):
    requirement = seed(github, "requirement", status="Approved")
    result = await call(
        app, "create_decision", title="Use an index", context="Scans are slow.", decision="Build an index.",
        considered_options=["Scan", "Index"], addresses=[f"#{requirement}"],
    )  # fmt: skip
    assert result.structured_content["status"] == "Proposed"
    issue = github.issues[2]
    assert issue.labels == ["decision"]
    assert issue.body.endswith("## Considered options\n\n- Scan\n- Index\n\n## Addresses\n\n- #1")

    not_a_requirement = await call(app, "create_decision", title="t", context="c", decision="d", addresses=[2])
    assert not_a_requirement.is_error and "addresses must be a requirement; #2 is a decision" in text(not_a_requirement)


async def test_a_task_is_created_under_its_requirement_in_three_requests(app, github):
    milestone = await github.create_milestone("v1", "Ship it.")
    requirement = seed(github, "requirement", status="Approved", milestone=milestone.number)
    blocker = seed(github, "task", parent=requirement)
    await call(app, "get_status")
    app._tracker._labels_ready = True
    github.reset_counters()

    result = await call(
        app, "create_task", title="Build the index", parent=requirement, priority="P1", effort="M",
        test_plan=["Run the benchmark"], acceptance_criteria=["Index is built"],
    )  # fmt: skip
    assert not result.is_error and "warnings" not in result.structured_content
    assert github.requests == 3  # refresh, create, attach
    task = github.issues[3]
    assert (task.parent, task.milestone, sorted(task.labels)) == (requirement, milestone.number, ["P1", "task"])
    assert task.body.startswith("**Effort:** M\n\n## Acceptance criteria\n\n- [ ] Index is built")
    assert "Under: #1 Requirement 1 [Approved, P2]" in text(result)

    waiting = await call(app, "create_task", title="Benchmark", parent=requirement, priority="P2", blocked_by=[blocker])
    assert github.issues[4].blocked_by == [blocker] and "Blocked by: #2" in text(waiting)


async def test_a_task_under_an_unapproved_requirement_warns(app, github, monkeypatch):
    draft = seed(github, "requirement")
    result = await call(app, "create_task", title="Early", parent=draft, priority="P2")
    assert result.structured_content["warnings"] == [
        "Requirement #1 is Draft: work is being planned against a requirement nobody has approved."
    ]
    subtask = await call(app, "create_task", title="Earlier", parent=2, priority="P2")
    assert "Requirement #1 is Draft" in text(subtask)  # the requirement above its parent task

    monkeypatch.setenv("GH_PROJECT_RULES", "enforce")
    github.reset_counters()
    refused = await call(app, "create_task", title="Refused", parent=draft, priority="P2")
    assert refused.is_error and github.writes == []


async def test_a_task_needs_a_parent_that_is_a_requirement_or_task(app, github):
    decision = seed(github, "decision")
    result = await call(app, "create_task", title="t", parent=decision, priority="P2")
    assert result.is_error and "parent must be a requirement or task; #1 is a decision" in text(result)
    missing = await call(app, "create_task", title="t", parent=99, priority="P2")
    assert missing.is_error and "#99 is not a lifecycle record in octo/sandbox" in text(missing)
    assert github.writes == []


async def test_get_record_shows_fields_links_and_progress(app, github):
    requirement = seed(github, "requirement", "Search is fast", "Approved", priority="P1")
    seed(github, "decision", "Use an index", "Accepted", fields={"addresses": [requirement]})
    parent = seed(github, "task", "Build", "In Progress", parent=requirement)
    seed(github, "task", "Tokenise", "Complete", parent=parent)
    seed(github, "task", "Rank", parent=parent, blocked_by=(4,))
    seed(github, "task", "Dropped", "Abandoned", parent=requirement)

    result = await call(app, "get_record", id="#1")
    assert text(result) == (
        "Requirement #1: Search is fast\n"
        "https://github.com/octo/sandbox/issues/1\n"
        "Status: Approved | Priority: P1 | Type: FUNC\n"
        "Progress: 1/2 tasks complete\n"
        "\nCurrent state:\nIt does not.\n"
        "\nDesired state:\nIt does.\n"
        "\nTasks:\n"
        "- #3 Build [In Progress, P2]\n"
        "  - #4 Tokenise [Complete, P2]\n"
        "  - #5 Rank [Not Started, P2]\n"
        "- #6 Dropped [Abandoned, P2]\n"
        "\nDecisions:\n- #2 Use an index [Accepted]"
    )
    assert result.structured_content["links"] == {"children": [3, 6], "decisions": [2]}
    assert result.structured_content["fields"]["type"] == "FUNC"

    task = await call(app, "get_record", id=5)
    assert "Under:\n- #3 Build [In Progress, P2]" in text(task)
    assert "Blocked by:\n- #4 Tokenise [Complete, P2]" in text(task)
    assert "Blocking:\n- #5 Rank [Not Started, P2]" in text(await call(app, "get_record", id=4))


async def test_an_issue_labelled_by_hand_reads_as_a_record(app, github):
    await github.create_issue("Fix the importer", "It drops rows.\n\n## Steps\n1. import", ["task"])
    empty = await github.create_issue("Nothing written yet", "", ["requirement"])
    result = await call(app, "get_record", id=1)
    assert not result.is_error
    assert "Status: Not Started" in text(result) and "Other sections in the issue: Steps" in text(result)
    assert result.structured_content["fields"] == {}
    assert (await call(app, "get_record", id=empty.number)).structured_content["status"] == "Draft"


async def test_comments_and_history_are_fetched_only_when_asked(app, github):
    task = seed(github, "task")
    await github.add_comment(task, "A note.")
    await call(app, "get_status")
    github.reset_counters()
    plain = await call(app, "get_record", id=task)
    assert github.requests == 1 and "Comments" not in text(plain)
    both = await call(app, "get_record", id=task, include=["comments", "history"])
    assert github.requests == 4
    assert "Comments (1):\n- 2026-01-01 octocat: A note." in text(both)
    assert "History (1):" in text(both) and "commented A note." in text(both)
    assert [e["event"] for e in both.structured_content["history"]] == ["commented"]


async def test_get_record_takes_an_id_or_a_project_not_both(app, github):
    result = await call(app, "get_record")
    assert result.is_error and "Pass either `id`" in text(result)
    assert (await call(app, "get_record", id=1, project=1)).is_error


async def test_update_changes_only_what_is_named(app, github):
    body = "**Type:** FUNC\n\nA note from Jeff.\n\n## Current state\n\nOld.\n\n## Whiteboard\n\nphoto here\n"
    number = seed(github, "requirement", body=body)
    github.reset_counters()
    result = await call(
        app, "update_record", id=number, title="Renamed", priority="P0",
        fields={"current_state": "New.", "risk": "High", "out_of_scope": ["Mobile"]},
    )  # fmt: skip
    assert text(result) == "Updated requirement #1: changed title, priority, current_state, risk, out_of_scope"
    # A cold start reads the issues and the milestones; the edit itself is one write.
    assert github.requests == 3 and [w[0] for w in github.writes] == ["update_issue"]
    issue = github.issues[number]
    assert issue.title == "Renamed" and sorted(issue.labels) == ["P0", "requirement"]
    assert issue.body == (
        # The new section follows the last of the kind's own sections; Jeff's note and his section are untouched.
        "**Type:** FUNC · **Risk:** High\n\nA note from Jeff.\n\n## Current state\n\nNew.\n\n"
        "## Out of scope\n\n- Mobile\n\n## Whiteboard\n\nphoto here"
    )


async def test_update_refuses_a_field_the_kind_does_not_have(app, github):
    task = seed(github, "task")
    result = await call(app, "update_record", id=task, fields={"desired_state": "x", "evidence": "y"})
    assert result.is_error
    assert "A task has no field desired_state, evidence (evidence is set by set_status or link_records)" in text(result)
    assert "Its fields are: effort, user_story, acceptance_criteria" in text(result)
    wrong_shape = await call(app, "update_record", id=task, fields={"test_plan": "run it"})
    assert wrong_shape.is_error and "fields.test_plan must be a list of strings" in text(wrong_shape)
    wrong_choice = await call(app, "update_record", id=task, fields={"effort": "Huge"})
    assert wrong_choice.is_error and "fields.effort must be a string, one of XS, S, M, L, XL" in text(wrong_choice)
    assert github.writes == []


async def test_null_removes_a_field_and_no_change_writes_nothing(app, github):
    task = seed(github, "task", fields={"effort": "M", "test_plan": ["a"]})
    await call(app, "update_record", id=task, fields={"test_plan": None, "effort": None})
    assert Document(github.issues[task].body, "task").fields() == {"user_story": "Do the thing."}
    github.reset_counters()
    same = await call(
        app, "update_record", id=task, title=github.issues[task].title, fields={"user_story": "Do the thing."}
    )
    assert "nothing was written" in text(same) and github.writes == []
    nothing = await call(app, "update_record", id=task)
    assert nothing.is_error and "Nothing to change" in text(nothing)


async def test_an_approved_requirement_needs_a_reason_which_is_posted(app, github):
    approved = seed(github, "requirement", status="Approved")
    refused = await call(app, "update_record", id=approved, fields={"desired_state": "Changed."})
    assert refused.is_error and "is Approved: editing it needs `reason`" in text(refused) and github.writes == []
    await call(app, "update_record", id=approved, fields={"desired_state": "Changed."}, reason="Review found a gap")
    assert [c.body for c in github.comments[approved]] == ["**Edited:** desired_state\n\nReview found a gap"]
    draft = seed(github, "requirement")
    assert not (await call(app, "update_record", id=draft, fields={"desired_state": "Changed."})).is_error


async def test_a_decided_decision_is_amended_not_rewritten(app, github):
    decision = seed(github, "decision", status="Accepted")
    before = github.issues[decision].body
    refused = await call(app, "update_record", id=decision, fields={"decision": "Something else."})
    assert refused.is_error and "is Accepted and is not rewritten" in text(refused)
    assert "pass `amendment`" in text(refused) and "type='supersedes', target=1" in text(refused)

    amended = await call(app, "update_record", id=decision, amendment="The index is 40 MB,\nnot 10.", reason="Measured")
    assert not amended.is_error and github.issues[decision].body == before
    shown = await call(app, "get_record", id=decision)
    assert (
        "Decision:\nWe chose.\n> Amendment (2026-01-01, octocat): The index is 40 MB, not 10. Reason: Measured"
        in text(shown)
    )
    assert shown.structured_content["amendments"] == [
        "Amendment (2026-01-01, octocat): The index is 40 MB, not 10. Reason: Measured"
    ]
    assert "Comments (" not in text(shown)


async def test_amendment_is_for_accepted_decisions_only(app, github):
    proposed, task = seed(github, "decision"), seed(github, "task")
    result = await call(app, "update_record", id=proposed, amendment="x")
    assert result.is_error and "a Proposed one is simply edited: pass `fields`" in text(result)
    assert (await call(app, "update_record", id=task, amendment="x")).is_error
    accepted = seed(github, "decision", status="Accepted")
    mixed = await call(app, "update_record", id=accepted, amendment="x", title="y")
    assert mixed.is_error and "Pass `amendment` on its own" in text(mixed)
    assert not (await call(app, "update_record", id=proposed, fields={"decision": "Edited while proposed."})).is_error


async def test_kind_specific_parameters_are_refused_on_other_kinds(app, github):
    decision, requirement = seed(github, "decision"), seed(github, "requirement")
    assert "A decision has no priority" in text(await call(app, "update_record", id=decision, priority="P1"))
    assert "Only a task has an assignee" in text(await call(app, "update_record", id=requirement, assignee="octocat"))
    task = seed(github, "task")
    await call(app, "update_record", id=task, assignee="octocat")
    assert github.issues[task].assignees == ["octocat"]
    await call(app, "update_record", id=task, assignee="")
    assert github.issues[task].assignees == []


async def test_add_comment(app, github):
    task = seed(github, "task")
    result = await call(app, "add_comment", id=task, comment="Looked at this today.")
    assert text(result) == "Commented on task #1." and github.comments[task][0].body == "Looked at this today."
    assert (await call(app, "add_comment", id=task, comment="  ")).is_error
    assert (await call(app, "add_comment", id=99, comment="x")).is_error


@pytest.fixture
def populated(github):
    milestone = github.milestones.setdefault(
        1, __import__("gh_project_mcp.github.port", fromlist=["Milestone"]).Milestone(1, "v1", "Ship.")
    )
    approved = seed(github, "requirement", "Search is fast", "Approved", priority="P0", milestone=milestone.number)
    seed(github, "requirement", "Export works", priority="P2", fields={"desired_state": "Notes export as Markdown."})
    seed(github, "task", "Build index", "Complete", parent=approved, priority="P1", milestone=1)
    seed(github, "task", "Benchmark search", parent=approved, priority="P0", milestone=1)
    seed(github, "decision", "Use an index", "Accepted")
    return github


async def test_query_returns_compact_rows(app, populated):
    result = await call(app, "query_records")
    assert text(result) == (
        "- [requirement] #1 Search is fast [Approved, P0]\n"
        "- [requirement] #2 Export works [Draft, P2]\n"
        "- [task] #3 Build index [Complete, P1]\n"
        "- [task] #4 Benchmark search [Not Started, P0]\n"
        "- [decision] #5 Use an index [Accepted]"
    )
    assert result.structured_content["count"] == 5
    assert result.structured_content["records"][0] == {
        "number": 1, "kind": "requirement", "title": "Search is fast", "status": "Approved", "priority": "P0",
    }  # fmt: skip


async def test_query_filters_combine(app, populated):
    async def numbers(**filters):
        return [r["number"] for r in (await call(app, "query_records", **filters)).structured_content["records"]]

    assert await numbers(kind="task") == [3, 4]
    assert await numbers(kind="task", status="complete") == [3]
    assert await numbers(priority="P0") == [1, 4]
    assert await numbers(project="v1") == [1, 3, 4]
    assert await numbers(project=1, kind="requirement") == [1]
    assert await numbers(search="export markdown") == [2]
    assert await numbers(search="SEARCH") == [1, 4]
    assert await numbers(ready=True) == [4]
    assert await numbers(kind="requirement", limit=1) == [1]
    assert text(await call(app, "query_records", kind="decision", status="Proposed")) == "No records match."


async def test_query_says_when_the_limit_cut_it_short_and_refuses_an_unknown_status(app, populated):
    limited = await call(app, "query_records", limit=2)
    assert text(limited).endswith("(2 of 5 shown)") and limited.structured_content["count"] == 5
    unknown = await call(app, "query_records", status="Ready")
    assert unknown.is_error and "'Ready' is not a status. requirement: Draft, Under Review" in text(unknown)
    no_project = await call(app, "query_records", project="v2")
    assert no_project.is_error and "No project 'v2'. Projects are milestones, named by number or title: 1 (v1)" in text(
        no_project
    )


async def test_full_returns_every_field_only_when_asked(app, populated):
    full = await call(app, "query_records", kind="requirement", status="Draft", full=True)
    assert "Desired state:\nNotes export as Markdown." in text(full)
    assert full.structured_content["records"][0]["fields"]["desired_state"] == "Notes export as Markdown."
    compact = await call(app, "query_records", kind="requirement")
    assert "fields" not in compact.structured_content["records"][0] and "Desired state" not in text(compact)


async def test_work_complete_finds_requirements_awaiting_the_decision(app, github):
    done = seed(github, "requirement", status="Approved")
    seed(github, "task", status="Complete", parent=done)
    unfinished = seed(github, "requirement", status="Approved")
    seed(github, "task", parent=unfinished)
    result = await call(app, "query_records", work_complete=True)
    assert [r["number"] for r in result.structured_content["records"]] == [done]


async def test_an_empty_ready_list_says_which_kind_of_empty(app, github):
    assert text(await call(app, "query_records", ready=True)) == "No tasks are ready to start: no open tasks remain."
    requirement, draft = seed(github, "requirement", status="Approved"), seed(github, "requirement")
    started = seed(github, "task", status="In Progress", parent=requirement)
    seed(github, "task", status="Blocked", parent=requirement)
    seed(github, "task", parent=requirement, blocked_by=(started,))
    seed(github, "task", parent=draft)
    assert text(await call(app, "query_records", ready=True)) == (
        "No tasks are ready to start: of 4 open, 1 already In Progress, 1 Blocked, 1 waiting on unfinished work, "
        "1 under a requirement that is not Approved."
    )


async def test_a_task_that_cannot_be_attached_is_reported_with_its_number(app, github):
    """GitHub allows a parent 100 sub-issues. The issue exists by then, so the refusal has to say so."""
    requirement = seed(github, "requirement", status="Approved")
    for _ in range(100):
        seed(github, "task", parent=requirement)
    result = await call(app, "create_task", title="One too many", parent=requirement, priority="P3")
    assert result.is_error
    assert (
        "Created task #102 (https://github.com/octo/sandbox/issues/102) but could not finish linking it under #1"
        in text(result)
    )
    assert "too many sub-issues" in text(result) and "Link it with link_records, or close it." in text(result)
