"""Projects as milestones (REQ-0004-FUNC-00)."""

from tests.helpers import call, seed, text

REQUIREMENT = {"title": "R", "type": "FUNC", "priority": "P2", "current_state": "a", "desired_state": "b"}


async def test_a_project_is_a_milestone_that_opens_with_its_purpose(app, github):
    result = await call(
        app, "save_project", title="v1", purpose="Ship the first version.",
        success_criteria=["Every tool works live"], out_of_scope=["Projects v2 boards"],
    )  # fmt: skip
    assert text(result) == "Created project 1: v1\nhttps://github.com/octo/sandbox/milestone/1"
    assert github.milestones[1].description == (
        "Ship the first version.\n\n## Success criteria\n\n- Every tool works live\n\n"
        "## Out of scope\n\n- Projects v2 boards"
    )
    assert (await call(app, "save_project", title="v1", purpose="Again.")).is_error
    assert "needs `title` and `purpose`" in text(await call(app, "save_project", title="v2"))


async def test_requirements_join_at_birth_and_their_tasks_follow(app, github):
    await call(app, "save_project", title="v1", purpose="Ship.")
    await call(app, "create_requirement", **REQUIREMENT, project="v1")
    await call(app, "create_decision", title="D", context="c", decision="d", addresses=[1])
    await call(app, "create_task", title="T", parent=1, priority="P3")
    await call(app, "create_task", title="Sub", parent=3, priority="P3")
    assert [github.issues[n].milestone for n in (1, 2, 3, 4)] == [1, 1, 1, 1]
    unknown = await call(app, "create_requirement", **REQUIREMENT, project="nope")
    assert unknown.is_error and "No project 'nope'" in text(unknown)


async def test_moving_a_requirement_moves_the_work_under_it(app, github):
    await call(app, "save_project", title="v1", purpose="Ship.")
    await call(app, "save_project", title="v2", purpose="Later.")
    requirement = seed(github, "requirement", milestone=1)
    task = seed(github, "task", parent=requirement, milestone=1)
    subtask = seed(github, "task", parent=task, milestone=1)
    result = await call(app, "update_record", id=requirement, project="v2")
    assert text(result) == f"Updated requirement #1: changed project\nMoved with it: #{task}, #{subtask}"
    assert [github.issues[n].milestone for n in (requirement, task, subtask)] == [2, 2, 2]
    await call(app, "update_record", id=requirement, project="")
    assert [github.issues[n].milestone for n in (requirement, task, subtask)] == [None, None, None]


async def test_edit_close_and_reopen(app, github):
    await call(app, "save_project", title="v1", purpose="Ship.", success_criteria=["One"])
    edited = await call(app, "save_project", project="v1", title="Version 1", success_criteria=["One", "Two"])
    assert text(edited) == "Updated project 1 (Version 1): changed title, description"
    assert github.milestones[1].description == "Ship.\n\n## Success criteria\n\n- One\n- Two"
    await call(app, "save_project", project=1, state="closed")
    assert github.milestones[1].state == "closed"
    assert "Projects:" not in text(await call(app, "get_status"))
    await call(app, "save_project", project=1, state="open")
    assert "Projects:\n- 1 Version 1" in text(await call(app, "get_status"))
    assert "nothing was written" in text(await call(app, "save_project", project=1, state="open"))


async def test_a_milestone_made_by_hand_reads_as_a_project(app, github):
    await github.create_milestone("Autumn", "Everything we promised for the autumn release.")
    requirement = seed(github, "requirement", "Search", "Approved", milestone=1)
    seed(github, "task", status="Complete", parent=requirement, milestone=1)
    seed(github, "task", parent=requirement, milestone=1)
    seed(github, "decision", "Index", fields={"addresses": [requirement]}, milestone=1)
    result = await call(app, "get_record", project="autumn")
    assert text(result) == (
        "Project 1: Autumn\nhttps://github.com/octo/sandbox/milestone/1\n"
        "State: open | Requirements: 1 | Tasks: 1/2 complete\n"
        "\nPurpose:\nEverything we promised for the autumn release.\n"
        "\nRequirements:\n- #1 Search [Approved, P2]\n"
        "\nDecisions:\n- #4 Index [Proposed]"
    )
    assert result.structured_content["fields"] == {"purpose": "Everything we promised for the autumn release."}
    # Editing one list leaves the hand-written purpose as it was.
    await call(app, "save_project", project=1, out_of_scope=["Mobile"])
    assert github.milestones[1].description == (
        "Everything we promised for the autumn release.\n\n## Out of scope\n\n- Mobile"
    )
