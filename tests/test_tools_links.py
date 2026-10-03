"""Links through GitHub's own features (REQ-0003-FUNC-00, ADR-0003)."""

from gh_project_mcp.body import Document
from tests.helpers import call, seed, text


async def link(app, source, kind, target, tool="link_records"):
    return await call(app, tool, source=source, type=kind, target=target)


async def test_child_of_makes_a_sub_issue(app, github):
    requirement, task = seed(github, "requirement"), seed(github, "task")
    result = await link(app, task, "child_of", requirement)
    assert text(result) == f"Linked: #{task} child_of #{requirement}"
    assert github.issues[task].parent == requirement and github.issues[requirement].sub_issues == [task]
    assert f"- #{task} Task 2" in text(await call(app, "get_record", id=requirement))


async def test_a_task_joins_its_requirements_project(app, github):
    milestone = await github.create_milestone("v1", "Ship.")
    requirement, task = seed(github, "requirement", milestone=milestone.number), seed(github, "task")
    await link(app, task, "child_of", requirement)
    assert github.issues[task].milestone == milestone.number


async def test_an_issue_has_one_parent_and_the_refusal_names_it(app, github):
    first, second = seed(github, "requirement", "First"), seed(github, "requirement")
    task = seed(github, "task", parent=first)
    await call(app, "get_status")
    github.reset_counters()
    result = await link(app, task, "child_of", second)
    assert result.is_error
    assert f"#{task} is already under #{first} First [Draft, P2]; an issue has one parent" in text(result)
    assert f"unlink_records(source={task}, type='child_of', target={first})" in text(result)
    assert github.writes == []


async def test_loops_and_self_links_are_refused_before_any_write(app, github):
    requirement = seed(github, "requirement")
    top = seed(github, "task", parent=requirement)
    below = seed(github, "task", parent=top)
    orphan = seed(github, "task")
    await link(app, orphan, "child_of", below)
    await link(app, top, "blocked_by", orphan)
    github.reset_counters()

    assert "cannot be linked to itself" in text(await link(app, top, "child_of", top))
    await call(app, "unlink_records", source=top, type="child_of", target=requirement)
    github.reset_counters()
    loop = await link(app, top, "child_of", orphan)
    assert loop.is_error and f"#{orphan} is under #{top}; putting it above would make a loop" in text(loop)
    waits = await link(app, orphan, "blocked_by", top)
    assert waits.is_error and f"#{top} already waits on #{orphan}; this would make a loop" in text(waits)
    again = await link(app, top, "blocked_by", orphan)
    assert again.is_error and "already blocked by" in text(again)
    assert github.writes == []


async def test_each_link_type_takes_the_right_kinds(app, github):
    requirement, task, decision = seed(github, "requirement"), seed(github, "task"), seed(github, "decision")
    cases = [
        (requirement, "child_of", task, "the source of child_of must be a task; #1 is a requirement"),
        (task, "child_of", decision, "the target of child_of must be a requirement or task; #3 is a decision"),
        (decision, "blocked_by", task, "the source of blocked_by must be a task or requirement"),
        (task, "addresses", requirement, "the source of addresses must be a decision"),
        (decision, "addresses", task, "the target of addresses must be a requirement"),
        (decision, "supersedes", requirement, "the target of supersedes must be a decision"),
    ]
    for source, kind, target, message in cases:
        result = await link(app, source, kind, target)
        assert result.is_error and message in text(result), kind
    assert github.writes == []
    unknown = await link(app, task, "depends", requirement)
    assert (
        unknown.is_error
        and "type: 'depends' is not one of ['child_of', 'blocked_by', 'addresses', 'supersedes']" in text(unknown)
    )


async def test_blocked_by_is_a_github_dependency_read_from_both_ends(app, github):
    requirement = seed(github, "requirement", status="Approved")
    first, second = seed(github, "task", parent=requirement), seed(github, "task", parent=requirement)
    await link(app, second, "blocked_by", first)
    assert github.issues[second].blocked_by == [first]
    assert "Blocking:\n- #3 Task 3" in text(await call(app, "get_record", id=first))
    assert [r["number"] for r in (await call(app, "query_records", ready=True)).structured_content["records"]] == [
        first
    ]

    removed = await link(app, second, "blocked_by", first, tool="unlink_records")
    assert text(removed) == f"Unlinked: #{second} blocked_by #{first}" and github.issues[second].blocked_by == []
    missing = await link(app, second, "blocked_by", first, tool="unlink_records")
    assert missing.is_error and f"There is no link #{second} blocked_by #{first}" in text(missing)


async def test_a_link_made_on_github_shows_in_the_next_read(app, github):
    requirement = seed(github, "requirement", status="Approved")
    first, second = seed(github, "task"), seed(github, "task")
    await call(app, "get_status")
    github.behind_the_back(first, parent=requirement)
    github.behind_the_back(second, parent=requirement, blocked_by=[first])
    shown = await call(app, "get_record", id=requirement)
    assert shown.structured_content["links"]["children"] == [first, second]
    assert "Blocked by:\n- #2 Task 2" in text(await call(app, "get_record", id=second))


async def test_addresses_is_kept_in_the_decisions_body(app, github):
    requirement, other = seed(github, "requirement"), seed(github, "requirement")
    decision = seed(github, "decision", status="Accepted", fields={"addresses": [requirement]})
    await link(app, decision, "addresses", other)
    assert Document(github.issues[decision].body, "decision").get("addresses") == [requirement, other]
    assert "Decisions:\n- #3 Decision 3 [Accepted]" in text(await call(app, "get_record", id=other))
    assert (await link(app, decision, "addresses", other)).is_error
    await link(app, decision, "addresses", requirement, tool="unlink_records")
    assert Document(github.issues[decision].body, "decision").get("addresses") == [other]
    assert "Decisions" not in text(await call(app, "get_record", id=requirement))


async def test_supersedes_retires_the_older_decision_in_the_same_call(app, github):
    old, new = seed(github, "decision", "Use SQLite", "Accepted"), seed(github, "decision", "Use GitHub")
    result = await link(app, new, "supersedes", old)
    assert text(result) == f"Linked: #{new} supersedes #{old}\n#{old} is now Superseded (was Accepted)."
    issue = github.issues[old]
    assert (issue.state, sorted(issue.labels)) == ("closed", ["decision", "status:superseded"])
    assert github.comments[old][0].body == f"**Superseded by** #{new}: Use GitHub"
    assert Document(github.issues[new].body, "decision").get("supersedes") == [old]

    shown = await call(app, "get_record", id=old)
    assert shown.structured_content["status"] == "Superseded"
    assert f"Superseded by:\n- #{new} Use GitHub [Proposed]" in text(shown)
    assert f"Supersedes:\n- #{old} Use SQLite [Superseded]" in text(await call(app, "get_record", id=new))
    assert (await call(app, "get_status")).structured_content["drift"] == []


async def test_unlinking_supersedes_brings_the_older_decision_back(app, github):
    old, new = seed(github, "decision", status="Accepted"), seed(github, "decision")
    await link(app, new, "supersedes", old)
    moved = await call(app, "set_status", ids=old, status="Accepted")
    assert moved.is_error and "remove the supersedes link with unlink_records" in text(moved)
    result = await link(app, new, "supersedes", old, tool="unlink_records")
    assert text(result) == f"Unlinked: #{new} supersedes #{old}\n#{old} is Accepted again."
    assert (github.issues[old].state_reason, github.issues[old].labels) == ("completed", ["decision"])
    assert Document(github.issues[new].body, "decision").get("supersedes") is None


async def test_supersedes_refuses_what_makes_no_sense(app, github):
    old, new = seed(github, "decision", status="Accepted"), seed(github, "decision")
    rejected, another = seed(github, "decision", status="Rejected"), seed(github, "decision")
    await link(app, new, "supersedes", old)
    github.reset_counters()
    assert f"Decision #{old} is already Superseded, by #{new}" in text(await link(app, another, "supersedes", old))
    assert f"Decision #{rejected} is Rejected; it cannot supersede another" in text(
        await link(app, rejected, "supersedes", new)
    )
    assert "it cannot supersede another" in text(await link(app, old, "supersedes", new))
    assert github.writes == []


async def test_requirement_progress_counts_leaf_tasks(app, github):
    requirement = seed(github, "requirement", status="Approved")
    parent = seed(github, "task", status="In Progress", parent=requirement)
    seed(github, "task", status="Complete", parent=parent)
    seed(github, "task", parent=parent)
    seed(github, "task", status="Complete", parent=requirement)
    assert "Progress: 2/3 tasks complete" in text(await call(app, "get_record", id=requirement))
