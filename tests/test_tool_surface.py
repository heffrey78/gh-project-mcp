"""The tool surface is small and stays small (ADR-0005, REQ-0001-INTF-00).

Every definition is sent to the client with every request. Adding a tool or a parameter means raising the budget in
the same change, which is the point: the cost is seen when it is incurred.
"""

import ast
import json
from pathlib import Path

from gh_project_mcp.prompts import prompt_definitions, render_prompt
from gh_project_mcp.registry import TOOLS
from gh_project_mcp.surface import definition_sizes
from tests.helpers import call, text

ROOT = Path(__file__).parent.parent
BUDGET = json.loads((ROOT / "tests" / "tool_surface_budget.json").read_text())
SOURCE = ROOT / "src" / "gh_project_mcp"


def test_tool_count_is_within_budget():
    assert len(TOOLS) <= BUDGET["max_tools"], "raise max_tools in tests/tool_surface_budget.json in the same change"


def test_definition_size_is_within_budget():
    sizes = definition_sizes()
    assert sum(sizes.values()) <= BUDGET["max_chars"], (
        f"tool definitions total {sum(sizes.values())} chars; the budget is {BUDGET['max_chars']}. "
        f"Largest: {sorted(sizes.items(), key=lambda item: -item[1])[:3]}. Trim, or raise the budget in the same change"
    )


def test_the_budget_itself_stays_under_the_requirements_ceiling():
    """REQ-0001-INTF-00: at most 16 tools and 9,000 characters. The budget may tighten, not exceed that."""
    assert BUDGET["max_tools"] <= 16 and BUDGET["max_chars"] <= 9000


def test_every_tool_and_parameter_has_a_description_or_a_plain_name():
    for tool in TOOLS.values():
        assert tool.description and len(tool.description) > 20, tool.name


def _is_args(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "args"


def _argument_reads(function: ast.AST) -> set[str]:
    """The keys a handler reads from `args`, as written: args["x"], args.get("x"), "x" in args."""
    found = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Subscript) and _is_args(node.value) and isinstance(node.slice, ast.Constant):
            found.add(node.slice.value)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and _is_args(node.func.value)
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            found.add(node.args[0].value)
        elif (
            isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Constant)
            and any(map(_is_args, node.comparators))
        ):
            found.add(node.left.value)
    return found


def test_no_handler_reads_a_parameter_its_schema_does_not_declare():
    for path in (SOURCE / "tools").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name in TOOLS:
                undeclared = _argument_reads(node) - set(TOOLS[node.name].schema["properties"])
                assert not undeclared, f"{node.name} reads {undeclared}, which its schema does not declare"


def test_no_tool_declares_a_parameter_nothing_reads():
    """The other direction: a declared parameter is read somewhere in its tool's module, or is a field of a kind,
    which the create and update tools pass to the body codec by name."""
    from gh_project_mcp.kinds import FIELDS

    field_names = {spec.name for specs in FIELDS.values() for spec in specs}
    for path in (SOURCE / "tools").glob("*.py"):
        tree = ast.parse(path.read_text())
        read_in_module = _argument_reads(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name in TOOLS:
                declared = set(TOOLS[node.name].schema["properties"])
                unread = declared - read_in_module - field_names
                assert not unread, f"{node.name} declares {unread}, which nothing in {path.name} reads"


def test_only_the_github_package_touches_the_network_or_spawns_a_process():
    """ADR-0004: handlers get the port. Nothing outside github/ imports httpx or subprocess."""
    for path in SOURCE.rglob("*.py"):
        if "github" in path.relative_to(SOURCE).parts:
            continue
        imported = set()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module.split(".")[0])
        assert not imported & {"httpx", "subprocess", "socket", "requests", "urllib"}, path.name


def test_prompts_render_and_name_only_real_tools():
    names = [p.name for p in prompt_definitions()]
    assert names == ["capture_requirement", "reconcile_requirements"]
    capture = render_prompt("capture_requirement", {"about": "faster search"}).messages[0].content.text
    assert capture.endswith('What they said they need:\n"faster search"')
    assert render_prompt("capture_requirement").messages[0].content.text in capture
    reconcile = render_prompt("reconcile_requirements", {"source": "the transcript", "source_kind": "transcript"})
    assert reconcile.messages[0].content.text.endswith("The source is: transcript\n\nThe source:\nthe transcript")

    import re

    for name in names:
        prompt = render_prompt(name).messages[0].content.text
        mentioned = set(
            re.findall(r"\b((?:create|update|get|query|set|link|unlink|save|add|export|setup)_[a-z_]+)\b", prompt)
        )
        assert mentioned and mentioned <= {*TOOLS, *names}, f"{name} mentions {mentioned - set(TOOLS)}"
        # Every field the capture guide names is one create_requirement takes.
    fields = set(
        re.findall(
            r"^- ([a-z_]+)(?:, ([a-z_]+))*:", render_prompt("capture_requirement").messages[0].content.text, re.M
        )
    )
    named = {name for group in fields for name in group if name}
    assert named <= set(TOOLS["create_requirement"].schema["properties"]), named


def test_an_unknown_prompt_lists_the_ones_offered():
    import pytest

    with pytest.raises(ValueError, match="Unknown prompt: interview. This server offers: capture_requirement"):
        render_prompt("interview")


async def test_setup_repository_creates_labels_once(app, github):
    github.labels["task"] = ("ffffff", "ours already")
    first = await call(app, "setup_repository")
    assert text(first).startswith("octo/sandbox: 13 labels in use, 12 created:\n- requirement\n- decision\n- P0")
    assert github.labels["status:blocked"] == ("bfd4f2", "Task: Blocked") and github.labels["task"][0] == "ffffff"
    github.reset_counters()
    second = await call(app, "setup_repository")
    assert text(second) == "octo/sandbox: 13 labels in use, 0 created; all were already there."
    assert github.writes == [] and second.structured_content["created"] == []


async def test_a_label_prefix_applies_to_every_label(github):
    from gh_project_mcp.app import App
    from gh_project_mcp.config import Config

    app = App(Config(repo=github.repo, label_prefix="lc:"), github)
    await call(app, "create_requirement", title="R", type="FUNC", priority="P1", current_state="a", desired_state="b",
               acceptance_criteria=["c"])  # fmt: skip
    await call(app, "set_status", ids=1, status="Approved")
    assert sorted(github.issues[1].labels) == ["lc:P1", "lc:requirement", "lc:status:approved"]
    assert all(name.startswith("lc:") for name in github.labels)
    # A repository's own `task` label means nothing to a prefixed server.
    await github.create_issue("Not ours", "", ["task"])
    assert (await call(app, "get_status")).structured_content["counts"]["task"] == {}
