"""Routing, validation, refusals and the call log (ADR-0005, REQ-0001-INTF-00)."""

import json

import pytest
from mcp import Client

from gh_project_mcp import registry, server
from gh_project_mcp.app import App
from gh_project_mcp.config import Config
from gh_project_mcp.registry import Result, ToolError
from tests.helpers import call, seed, text


@pytest.fixture
def toy_tools(monkeypatch):
    """Two tools declared for the test alone, so the routing can be exercised without GitHub."""
    monkeypatch.setattr(registry, "TOOLS", dict(registry.TOOLS))
    monkeypatch.setattr(server, "TOOLS", registry.TOOLS)

    @registry.tool(
        "toy_read",
        "A toy.",
        {"record_id": {"type": "string"}, "record_ids": {"type": "array", "items": {"type": "string"}}},
    )
    async def toy_read(app, args):
        if args.get("record_id") == "boom":
            raise RuntimeError("the handler broke")
        if args.get("record_id") == "no":
            raise ToolError("refused by the handler")
        return Result("read it", {"seen": sorted(args)}, warnings=["thin"] if args.get("record_ids") else [])

    @registry.tool("toy_write", "A toy that writes.", writes=True)
    async def toy_write(app, args):
        return Result("wrote it")


async def test_a_result_is_text_and_the_same_facts_as_data(app, toy_tools):
    result = await call(app, "toy_read", record_id="a")
    assert not result.is_error and text(result) == "read it"
    assert result.structured_content == {"seen": ["record_id"]}


async def test_warnings_are_in_the_text_and_the_data(app, toy_tools):
    result = await call(app, "toy_read", record_ids=["a"])
    assert text(result) == "read it\n\nWarnings:\n- thin"
    assert result.structured_content == {"seen": ["record_ids"], "warnings": ["thin"]}


async def test_an_undeclared_argument_is_refused_by_name(app, toy_tools):
    result = await call(app, "toy_read", record_idz="a", colour="red")
    assert result.is_error
    assert "'colour', 'record_idz' were unexpected" in text(result)
    assert "record_idz: did you mean record_id?" in text(result)
    assert "toy_read takes: record_id, record_ids" in text(result)


async def test_a_wrong_type_names_the_sibling_that_would_have_taken_it(app, toy_tools):
    result = await call(app, "toy_read", record_id=["a", "b"])
    assert result.is_error
    assert text(result) == (
        "Input validation error: record_id: ['a', 'b'] is not of type 'string'. record_id takes a string; "
        "record_ids takes an array and accepts what you passed"
    )


async def test_handler_refusals_and_bugs_both_reach_the_client_as_errors(app, toy_tools):
    refused = await call(app, "toy_read", record_id="no")
    assert refused.is_error and text(refused) == "refused by the handler"
    broken = await call(app, "toy_read", record_id="boom")
    assert broken.is_error and text(broken) == "Error handling toy_read: the handler broke"


async def test_an_unknown_tool_lists_the_real_ones(app):
    result = await call(app, "get_requirement_details", id=1)
    assert result.is_error and "Unknown tool: get_requirement_details" in text(result) and "get_record" in text(result)


async def test_read_only_refuses_a_write_before_any_request(github, toy_tools):
    app = App(Config(repo=github.repo, read_only=True), github)
    result = await call(app, "toy_write")
    assert result.is_error and "read-only mode (GH_PROJECT_READ_ONLY)" in text(result)
    assert github.requests == 0
    assert not (await call(app, "toy_read")).is_error


async def test_every_real_write_tool_is_refused_in_read_only_mode(github):
    seed(github, "requirement")
    app = App(Config(repo=github.repo, read_only=True), github)
    arguments = {
        "create_requirement": {
            "title": "t", "type": "FUNC", "priority": "P1", "current_state": "a", "desired_state": "b",
        },
        "create_decision": {"title": "t", "context": "c", "decision": "d"},
        "create_task": {"title": "t", "parent": 1, "priority": "P1"},
        "update_record": {"id": 1, "title": "x"},
        "set_status": {"ids": 1, "status": "Under Review"},
        "add_comment": {"id": 1, "comment": "c"},
        "link_records": {"source": 1, "type": "blocked_by", "target": 1},
        "unlink_records": {"source": 1, "type": "blocked_by", "target": 1},
        "save_project": {"title": "p", "purpose": "q"},
        "setup_repository": {},
    }  # fmt: skip
    writers = {name for name, tool in registry.TOOLS.items() if tool.writes}
    assert writers == set(arguments)
    for name, args in arguments.items():
        result = await call(app, name, **args)
        assert result.is_error and "read-only" in text(result), name
    assert (github.requests, github.writes) == (0, [])
    assert not (await call(app, "get_status")).is_error


async def test_the_read_only_client_refuses_a_write_that_slipped_past(github):
    from gh_project_mcp.github.port import GitHubError

    app = App(Config(repo=github.repo, read_only=True), github)
    assert await app.github.list_issues() == []
    with pytest.raises(GitHubError, match="read-only mode"):
        await app.github.create_issue("t", "b", [])
    assert github.writes == []


async def test_with_no_repository_the_server_answers_and_says_how_to_set_one():
    app = App(Config())
    assert len(server.tool_definitions()) == len(registry.TOOLS)
    result = await call(app, "get_status")
    assert result.is_error
    assert "No repository is configured, so nothing was sent to GitHub. Set GH_PROJECT_REPO=owner/name" in text(result)


async def test_a_malformed_repository_name_is_refused():
    result = await call(App(Config(repo="not a repo")), "get_status")
    assert result.is_error and "is not of the form owner/name" in text(result)


async def test_the_call_log_records_names_not_values(github, tmp_path, toy_tools):
    log = tmp_path / "calls.jsonl"
    app = App(Config(repo=github.repo, call_log=str(log)), github)
    await call(app, "toy_read", record_id="secret-value")
    await call(app, "toy_read", record_id=["secret-list"])
    await call(app, "no_such_tool", x=1)
    await call(app, "toy_read", record_id="no")
    lines = [json.loads(line) for line in log.read_text().splitlines()]
    assert [(e["tool"], e["isError"], e.get("error_kind")) for e in lines] == [
        ("toy_read", False, None),
        ("toy_read", True, "validation"),
        ("no_such_tool", True, "unknown_tool"),
        ("toy_read", True, "handler"),
    ]
    assert lines[0]["arg_names"] == ["record_id"] and lines[0]["response_chars"] == len("read it")
    assert lines[1]["rejected"] == {"rule": "type", "param": "record_id"}
    assert "secret" not in log.read_text()


async def test_a_call_log_that_cannot_be_written_does_not_fail_the_call(github, tmp_path, toy_tools):
    app = App(Config(repo=github.repo, call_log=str(tmp_path / "missing" / "calls.jsonl")), github)
    assert not (await call(app, "toy_read")).is_error


async def test_every_schema_refuses_undeclared_fields():
    for tool in registry.TOOLS.values():
        assert tool.schema["additionalProperties"] is False, tool.name
        assert set(tool.schema.get("required", [])) <= set(tool.schema["properties"]), tool.name


async def test_a_client_lists_and_calls_tools_and_prompts_over_mcp(app, github):
    """The real protocol, in memory: what a client sees is what the registry declares."""
    seed(github, "requirement", "Search is fast", "Approved")
    async with Client(server.build_server(app)) as client:
        listed = await client.list_tools()
        assert [t.name for t in listed.tools] == list(registry.TOOLS)
        assert all(t.input_schema["additionalProperties"] is False for t in listed.tools)

        status = await client.call_tool("get_status", {})
        assert not status.is_error and "Requirements (1): Approved 1" in status.content[0].text
        assert status.structured_content["counts"]["requirement"] == {"Approved": 1}

        refused = await client.call_tool("get_record", {"ids": [1]})
        assert refused.is_error and "ids: did you mean id?" in refused.content[0].text

        prompts = await client.list_prompts()
        assert [p.name for p in prompts.prompts] == ["capture_requirement", "reconcile_requirements"]
        prompt = await client.get_prompt("capture_requirement", {"about": "faster search"})
        assert "faster search" in prompt.messages[0].content.text


async def test_concurrent_calls_run_one_at_a_time(app, github, toy_tools):
    import anyio

    running, overlapped = 0, False

    @registry.tool("toy_slow", "A toy that takes its time.")
    async def toy_slow(app, args):
        nonlocal running, overlapped
        running += 1
        overlapped = overlapped or running > 1
        await anyio.sleep(0.01)
        running -= 1
        return Result("done")

    async with anyio.create_task_group() as group:
        for _ in range(5):
            group.start_soon(call, app, "toy_slow")
    assert not overlapped
