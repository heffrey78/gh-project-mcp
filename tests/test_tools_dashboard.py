"""The dashboard (REQ-0005-FUNC-00, REQ-0002-NFUNC-00): what needs attention, cheaply, and without writing."""

from gh_project_mcp.app import App
from gh_project_mcp.config import Config
from tests.helpers import call, seed, text


async def test_an_empty_tracker_says_where_to_start(app, github):
    result = await call(app, "get_status")
    assert text(result) == (
        "Tracker: octo/sandbox\n"
        "No records yet: no issue carries a kind label (requirement, decision, task). Start with create_requirement."
    )
    assert result.structured_content["counts"] == {"requirement": {}, "decision": {}, "task": {}}


async def test_every_section(app, github):
    await github.create_milestone("v1", "Ship.")
    approved = seed(github, "requirement", "Search", "Approved", priority="P0", milestone=1)  # 1
    done = seed(github, "task", "Build index", "Complete", parent=approved, milestone=1)  # 2
    started = seed(github, "task", "Rank results", "In Progress", parent=approved, milestone=1)  # 3
    seed(github, "task", "Benchmark", parent=approved, blocked_by=(done,), priority="P1", milestone=1)  # 4
    seed(github, "task", "Tune", parent=approved, blocked_by=(started,), milestone=1)  # 5
    seed(github, "task", "Deploy", "Blocked", parent=approved, fields={"blocked_reason": "No server yet"})  # 6
    finished = seed(github, "requirement", "Export", "Approved")  # 7
    seed(github, "task", "Write exporter", "Complete", parent=finished)  # 8
    seed(github, "decision", "Use an index", "Accepted", fields={"addresses": [approved]})  # 9
    seed(github, "requirement", "Sync", "Validated")  # 10
    seed(github, "task", "Left open", "In Progress", parent=10)  # 11

    result = await call(app, "get_status")
    assert text(result) == (
        "Tracker: octo/sandbox\n"
        "Requirements (3): Approved 2, Validated 1\n"
        "Decisions (1): Accepted 1\n"
        "Tasks (7): Not Started 2, In Progress 2, Blocked 1, Complete 2\n"
        "\nProjects:\n- 1 v1: requirements 1, tasks 1/4 complete\n"
        "\nReady to start (1):\n- #4 Benchmark [Not Started, P1]\n"
        "\nBlocked (1):\n- #6 Deploy [Blocked, P2]: No server yet\n"
        "\nWaiting on other work (1):\n- #5 Tune [Not Started, P2]: waits on #3 (In Progress)\n"
        "\nWork complete, decision pending (1):\n"
        "- #7 Export [Approved, P2]: every task under it is finished; it is not yet Implemented\n"
        "\nDrift (1): state on GitHub that the lifecycle's rules would not produce\n"
        "- #10 is Validated while tasks under it are open: #11 (In Progress)"
    )
    data = result.structured_content
    assert data["repo"] == "octo/sandbox"
    assert data["counts"]["task"] == {"Not Started": 2, "In Progress": 2, "Blocked": 1, "Complete": 2}
    assert [t["number"] for t in data["ready"]] == [4]
    assert data["blocked"] == [
        {
            "number": 6,
            "kind": "task",
            "title": "Deploy",
            "status": "Blocked",
            "priority": "P2",
            "reason": "No server yet",
        }
    ]
    assert data["waiting"][0]["waits_on"] == [3] and data["work_complete"][0]["number"] == 7
    assert data["drift"] == [{"number": 10, "problem": "is Validated while tasks under it are open: #11 (In Progress)"}]
    assert data["projects"] == [
        {"number": 1, "title": "v1", "state": "open", "requirements": 1, "tasks": 4, "tasks_complete": 1}
    ]


async def test_a_healthy_tracker_shows_no_empty_sections(app, github):
    requirement = seed(github, "requirement", status="Approved")
    seed(github, "task", parent=requirement)
    shown = text(await call(app, "get_status"))
    assert "Ready to start (1)" in shown
    for absent in ("Blocked", "Waiting", "Work complete", "Drift", "Projects"):
        assert absent not in shown


async def test_a_new_record_is_not_reported_for_being_new(app, github):
    """A signal that always fires teaches the reader to ignore it."""
    await call(app, "create_requirement", title="R", type="FUNC", priority="P2", current_state="a", desired_state="b")
    await call(app, "set_status", ids=1, status="Approved")
    await call(app, "create_task", title="Only a title", parent=1, priority="P3")
    await call(app, "create_decision", title="D", context="c", decision="d")
    assert (await call(app, "get_status")).structured_content["drift"] == []


async def test_the_dashboard_and_the_query_filters_agree(app, github):
    requirement = seed(github, "requirement", status="Approved")
    seed(github, "task", status="Complete", parent=requirement)
    other = seed(github, "requirement", status="Approved")
    first = seed(github, "task", parent=other, priority="P0")
    seed(github, "task", parent=other, blocked_by=(first,))
    dashboard = (await call(app, "get_status")).structured_content
    ready = (await call(app, "query_records", ready=True)).structured_content
    complete = (await call(app, "query_records", work_complete=True)).structured_content
    assert dashboard["ready"] == ready["records"] and dashboard["work_complete"] == complete["records"]


async def test_drift_made_on_github_is_reported_and_nothing_is_written(app, github):
    requirement = seed(github, "requirement", status="Implemented")
    task = seed(github, "task", status="In Progress", parent=requirement)
    draft = seed(github, "requirement")
    early = seed(github, "task", parent=draft)
    await call(app, "get_status")

    github.behind_the_back(requirement, state="closed")  # validated by hand with work still open
    github.behind_the_back(early, labels=["task", "P2", "status:in-progress", "status:blocked"])
    github.behind_the_back(draft, body="can someone look at this?")
    await github.create_issue("Made by hand", "do the thing please", ["task"])
    github.reset_counters()

    result = await call(app, "get_status")
    problems = {(d["number"], d["problem"]) for d in result.structured_content["drift"]}
    assert problems == {
        (requirement, f"is Validated while tasks under it are open: #{task} (In Progress)"),
        (early, "has 2 status labels (In Progress, Blocked); read as Blocked"),
        (draft, "its body holds no fields the server recognises"),
        (5, "its body holds no fields the server recognises"),
        (5, "implements no requirement: it is not a sub-issue of one"),
    }
    assert github.writes == [] and github.requests == 1


async def test_no_read_tool_writes(app, github):
    requirement = seed(github, "requirement", status="Approved")
    seed(github, "task", parent=requirement)
    seed(github, "decision", status="Accepted", fields={"addresses": [requirement]})
    await github.create_milestone("v1", "Ship.")
    github.reset_counters()
    for name, args in (
        ("get_status", {}),
        ("get_record", {"id": 1, "include": ["comments", "history"]}),
        ("get_record", {"id": 3}),
        ("get_record", {"project": 1}),
        ("query_records", {"search": "thing", "full": True}),
    ):
        assert not (await call(app, name, **args)).is_error, name
    assert github.writes == []


async def test_request_budget_for_200_records(github):
    """REQ-0002-NFUNC-00: cold at most 4 requests, warm at most 1, a new task at most 4."""
    requirements = [seed(github, "requirement", status="Approved") for _ in range(4)]
    for index in range(196):  # 49 under each: GitHub allows a parent 100 sub-issues
        seed(github, "task", parent=requirements[index % 4], status="Complete" if index % 2 else None)
    requirement = requirements[0]
    app = App(Config(repo=github.repo), github)

    cold = await call(app, "get_status")
    assert cold.structured_content["counts"]["task"] == {"Not Started": 98, "Complete": 98}
    assert len(github.issues) == 200 and github.requests == 3

    github.reset_counters()
    await call(app, "get_status")
    assert github.requests == 1

    github.behind_the_back(5, state="closed")
    github.reset_counters()
    seen = await call(app, "get_status")
    assert seen.structured_content["counts"]["task"] == {"Not Started": 97, "Complete": 99} and github.requests == 1

    app._tracker._labels_ready = True  # labels are checked once per process, on the first write
    github.reset_counters()
    created = await call(app, "create_task", title="One more", parent=requirement, priority="P2")
    assert not created.is_error and github.requests == 3

    github.reset_counters()
    await call(app, "set_status", ids=201, status="In Progress")
    assert github.requests == 2
