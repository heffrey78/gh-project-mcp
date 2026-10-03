"""Status moves through the server (REQ-0002-FUNC-00, REQ-0006-FUNC-00, ADR-0006)."""

import pytest

from gh_project_mcp.body import Document
from tests.helpers import call, seed, text


async def test_draft_to_approved_walks_the_path_in_one_write(app, github):
    requirement = seed(github, "requirement")
    await call(app, "get_status")
    github.reset_counters()
    result = await call(app, "set_status", ids=requirement, status="Approved", comment="Jeff approved it")
    assert text(result) == "#1: Draft → Under Review → Approved"
    assert result.structured_content == {
        "results": [{"id": 1, "from": "Draft", "to": "Approved", "path": ["Draft", "Under Review", "Approved"]}],
        "moved": 1,
        "refused": 0,
    }
    assert [w[0] for w in github.writes] == ["update_issue", "add_comment"]
    assert sorted(github.issues[requirement].labels) == ["P2", "requirement", "status:approved"]
    assert github.comments[requirement][0].body == "**Status:** Draft → Under Review → Approved\n\nJeff approved it"


async def test_a_one_step_move_with_nothing_to_say_posts_no_comment(app, github):
    task = seed(github, "task", parent=seed(github, "requirement", status="Approved"))
    await call(app, "set_status", ids=f"#{task}", status="in progress")
    assert github.issues[task].labels[-1] == "status:in-progress" and task not in github.comments


async def test_a_move_through_approved_is_refused_and_nothing_is_written(app, github):
    requirement = seed(github, "requirement")
    github.reset_counters()
    result = await call(app, "set_status", ids=requirement, status="Implemented")
    assert result.is_error
    assert "#1: refused: Draft to Implemented passes through Approved" in text(result)
    assert text(result).endswith("No record moved.") and github.writes == []


@pytest.mark.parametrize("mode", ["off", "warn", "enforce"])
async def test_validated_with_an_open_task_is_refused_in_every_mode(app, github, monkeypatch, mode):
    monkeypatch.setenv("GH_PROJECT_RULES", mode)
    requirement = seed(github, "requirement", status="Implemented")
    task = seed(github, "task", status="In Progress", parent=requirement)
    github.reset_counters()
    result = await call(app, "set_status", ids=requirement, status="Validated")
    assert result.is_error and f"cannot be Validated while tasks under it are open: #{task}" in text(result)
    assert github.writes == []


async def test_validating_closes_the_issue_as_completed(app, github):
    requirement = seed(github, "requirement", status="Approved")
    seed(github, "task", status="Complete", parent=requirement)
    result = await call(app, "set_status", ids=requirement, status="Validated", evidence="172 tests pass")
    assert text(result) == "#1: Approved → Implemented → Validated"
    issue = github.issues[requirement]
    assert (issue.state, issue.state_reason, sorted(issue.labels)) == ("closed", "completed", ["P2", "requirement"])
    assert github.comments[requirement][0].body == (
        "**Status:** Approved → Implemented → Validated\n**Evidence:** 172 tests pass"
    )


async def test_risky_task_moves_warn_refuse_or_pass_by_mode(app, github, monkeypatch):
    requirement = seed(github, "requirement", status="Approved")
    blocker = seed(github, "task", parent=requirement)
    task = seed(github, "task", parent=requirement, blocked_by=(blocker,))

    warned = await call(app, "set_status", ids=task, status="In Progress")
    assert not warned.is_error
    assert text(warned) == (
        f"#{task}: Not Started → In Progress\n"
        f"  warning: It waits on work that is not finished: #{blocker} (Not Started)."
    )
    assert warned.structured_content["results"][0]["warnings"] == [
        f"It waits on work that is not finished: #{blocker} (Not Started)."
    ]

    monkeypatch.setenv("GH_PROJECT_RULES", "enforce")
    github.reset_counters()
    refused = await call(app, "set_status", ids=task, status="Complete")
    assert refused.is_error and f"Refused: move #{task} to Complete." in text(refused) and github.writes == []

    monkeypatch.setenv("GH_PROJECT_RULES", "off")
    silent = await call(app, "set_status", ids=task, status="Complete")
    assert text(silent) == f"#{task}: In Progress → Complete"


async def test_each_id_moves_on_its_own(app, github):
    requirement = seed(github, "requirement", status="Approved")
    first, done = seed(github, "task", parent=requirement), seed(github, "task", status="Complete", parent=requirement)
    result = await call(app, "set_status", ids=[first, done, 99, first], status="Complete")
    assert not result.is_error
    assert text(result) == (
        f"#{first}: Not Started → Complete\n  warning: It was never started.\n"
        f"#{done}: refused: already Complete\n"
        "#99: refused: #99 is not a lifecycle record in octo/sandbox: no issue with that number carries a kind "
        "label (requirement, decision, task)\n"
        "Moved 1, refused 2."
    )
    data = result.structured_content
    assert (data["moved"], data["refused"]) == (1, 2)
    assert data["results"][1] == {"id": done, "error": "already Complete"}
    assert github.issues[first].state == "closed"


async def test_a_status_of_another_kind_is_refused_naming_the_kinds_own(app, github):
    task = seed(github, "task")
    result = await call(app, "set_status", ids=task, status="Approved")
    assert result.is_error and "'Approved' is not a task status; a task is one of Not Started, In Progress" in text(
        result
    )


async def test_blocked_keeps_its_reason_until_the_task_leaves(app, github):
    task = seed(github, "task", status="In Progress", parent=seed(github, "requirement", status="Approved"))
    await call(app, "set_status", ids=task, status="Blocked", comment="Waiting for the API key")
    assert Document(github.issues[task].body, "task").get("blocked_reason") == "Waiting for the API key"
    assert "Blocked reason:\nWaiting for the API key" in text(await call(app, "get_record", id=task))

    noted = await call(app, "set_status", ids=task, status="Blocked", comment="Still waiting; asked again")
    assert text(noted) == f"#{task}: Blocked (noted)"
    assert Document(github.issues[task].body, "task").get("blocked_reason") == "Still waiting; asked again"
    again = await call(app, "set_status", ids=task, status="Blocked")
    assert again.is_error and "already Blocked" in text(again)

    await call(app, "set_status", ids=task, status="In Progress")
    assert Document(github.issues[task].body, "task").get("blocked_reason") is None
    assert "Blocked reason" not in text(await call(app, "get_record", id=task))
    assert len(github.comments[task]) == 2  # the trail keeps both reasons


async def test_commit_and_evidence_stay_on_the_task(app, github):
    task = seed(github, "task", status="In Progress", parent=seed(github, "requirement", status="Approved"))
    await call(
        app, "set_status", ids=task, status="Complete", commit="abc1234", evidence="12 tests pass", comment="Done."
    )
    issue = github.issues[task]
    assert (issue.state, issue.state_reason) == ("closed", "completed") and "status:in-progress" not in issue.labels
    assert github.comments[task][0].body == (
        "**Status:** In Progress → Complete\n**Commit:** abc1234\n**Evidence:** 12 tests pass\n\nDone."
    )
    shown = await call(app, "get_record", id=task)
    assert "Commit: abc1234" in text(shown) and "Evidence:\n12 tests pass" in text(shown)
    assert shown.structured_content["fields"]["commit"] == "abc1234"

    # A later move that says nothing about them leaves them; new values replace them.
    await call(app, "set_status", ids=task, status="In Progress")
    assert Document(github.issues[task].body, "task").get("evidence") == "12 tests pass"
    await call(app, "set_status", ids=task, status="Complete", evidence="14 tests pass")
    fields = Document(github.issues[task].body, "task").fields()
    assert (fields["commit"], fields["evidence"]) == ("abc1234", "14 tests pass")

    noted = await call(app, "set_status", ids=task, status="Complete", commit="def5678")
    assert text(noted) == f"#{task}: Complete (noted)"
    assert Document(github.issues[task].body, "task").get("commit") == "def5678"
    assert github.issues[task].state == "closed"


async def test_a_task_closed_on_github_reads_as_complete(app, github):
    requirement = seed(github, "requirement", status="Approved")
    task = seed(github, "task", status="In Progress", parent=requirement)
    await call(app, "get_status")
    github.behind_the_back(task, state="closed")  # a merged pull request said "Closes #2"
    github.reset_counters()
    assert (await call(app, "get_record", id=task)).structured_content["status"] == "Complete"
    assert github.writes == []
    assert [
        r["number"] for r in (await call(app, "query_records", work_complete=True)).structured_content["records"]
    ] == [requirement]


async def test_reopening_and_abandoning(app, github):
    task = seed(github, "task", status="Complete", parent=seed(github, "requirement", status="Approved"))
    reopened = await call(app, "set_status", ids=task, status="In Progress")
    assert "It was Complete: this reopens finished work." in text(reopened)
    assert (github.issues[task].state, github.issues[task].state_reason) == ("open", "reopened")
    await call(app, "set_status", ids=task, status="Abandoned", comment="Not needed after all")
    assert (github.issues[task].state, github.issues[task].state_reason) == ("closed", "not_planned")
    assert "status:in-progress" not in github.issues[task].labels


async def test_a_decision_is_accepted_rejected_and_never_superseded_by_a_status_move(app, github):
    decision = seed(github, "decision")
    await call(app, "set_status", ids=decision, status="Accepted")
    assert (github.issues[decision].state, github.issues[decision].state_reason) == ("closed", "completed")
    rejected = await call(app, "set_status", ids=decision, status="Rejected")
    assert text(rejected) == f"#{decision}: Accepted → Proposed → Rejected"
    assert github.issues[decision].state_reason == "not_planned"
    superseded = await call(app, "set_status", ids=decision, status="Superseded")
    assert superseded.is_error and "Superseded comes from a link" in text(superseded)


async def test_a_deprecated_requirement_can_be_revived(app, github):
    requirement = seed(github, "requirement", status="Approved")
    await call(app, "set_status", ids=requirement, status="Deprecated", comment="Out of scope for v1")
    assert github.issues[requirement].state_reason == "not_planned"
    await call(app, "set_status", ids=requirement, status="Draft")
    assert github.issues[requirement].state == "open" and github.issues[requirement].labels == ["requirement", "P2"]


async def test_a_github_failure_part_way_through_a_list_is_reported_per_record(app, github):
    from gh_project_mcp.github.port import GitHubError

    requirement = seed(github, "requirement", status="Approved")
    first, second, third = (seed(github, "task", parent=requirement) for _ in range(3))
    await call(app, "get_status")
    real = github.update_issue

    async def flaky(number, **changes):
        if number == second:
            raise GitHubError("Server Error", status=502, operation=f"update issue #{number}")
        return await real(number, **changes)

    github.update_issue = flaky
    result = await call(app, "set_status", ids=[first, second, third], status="In Progress")
    assert not result.is_error
    assert text(result) == (
        f"#{first}: Not Started → In Progress\n"
        f"#{second}: failed: GitHub 502: Server Error (update issue #{second})\n"
        f"#{third}: Not Started → In Progress\n"
        "Moved 2, refused 1."
    )
    assert github.issues[second].labels == ["task", "P2"]
