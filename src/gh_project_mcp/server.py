"""The MCP server: listing, validation, routing, the call log (ADR-0005).

Built on the SDK's low-level Server so that a call's validation and its refusal message are this module's own:
a refused call is logged like any other, and says which argument was wrong and what would have been accepted.
stdout carries the protocol and nothing else; everything here logs to stderr.
"""

import difflib
import json
import logging
import sys
import time
from datetime import UTC, datetime
from typing import Any

import anyio
import jsonschema
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from . import __version__, tools  # noqa: F401  (importing tools registers them)
from .app import App
from .config import Config, ConfigError
from .github.port import GitHubError
from .prompts import prompt_definitions, render_prompt
from .registry import TOOLS, Result, ToolError
from .rules import StatusRefused
from .tracker import NotARecord

logger = logging.getLogger(__name__)

INSTRUCTIONS = (
    "Software lifecycle tracking on GitHub issues. Requirements, architecture decisions and tasks are issues in one "
    "repository; records are addressed by issue number. Start with get_status. Approving and validating a "
    "requirement are the owner's decisions: ask before moving a requirement to Approved or Validated."
)

# How close a parameter name has to be to count as the one that was meant (lifecycle-mcp roadmap R19).
NEIGHBOUR_RATIO = 0.8

# What a handler may raise to refuse a call. Anything else is a bug and is logged with its traceback.
REFUSALS = (ToolError, StatusRefused, NotARecord, GitHubError, ConfigError)


class CallRefused(Exception):
    """A call the server did not carry out. `kind` says what refused it, for the call log."""

    def __init__(self, message: str, kind: str, rejected: dict[str, str] | None = None):
        super().__init__(message)
        self.kind = kind
        self.rejected = rejected


def tool_definitions() -> list[types.Tool]:
    """Every tool the server lists; calls are validated against these same schemas."""
    return [types.Tool(name=t.name, description=t.description, input_schema=t.schema) for t in TOOLS.values()]


def _type_name(schema: dict[str, Any]) -> str:
    declared = schema.get("type")
    if isinstance(declared, list):
        declared = " or ".join(declared)
    if not isinstance(declared, str):
        return "another type"
    return f"an {declared}" if declared[0] in "aeiou" else f"a {declared}"


def _accepting_neighbour(schema: dict[str, Any], error: jsonschema.ValidationError) -> str | None:
    """A parameter beside the refused one, close in name, whose own schema accepts the refused value."""
    if error.validator != "type" or len(error.absolute_path) != 1:
        return None
    parameter = error.absolute_path[0]
    properties = schema.get("properties", {})
    if not isinstance(parameter, str) or parameter not in properties:
        return None
    matches = []
    for name, subschema in properties.items():
        if name == parameter:
            continue
        ratio = difflib.SequenceMatcher(None, parameter, name).ratio()
        validator = jsonschema.validators.validator_for(subschema)(subschema)
        if ratio >= NEIGHBOUR_RATIO and validator.is_valid(error.instance):
            matches.append((ratio, name))
    return max(matches)[1] if matches else None


def validate(name: str, arguments: dict[str, Any]) -> None:
    """Refuse arguments that do not match the tool's schema, naming the field at fault."""
    schema = TOOLS[name].schema
    try:
        jsonschema.validate(instance=arguments, schema=schema)
    except jsonschema.ValidationError as error:
        message = error.message
        path = [str(part) for part in error.absolute_path]
        if path and error.validator != "additionalProperties":
            message = f"{'.'.join(path)}: {message}"
        if error.validator == "additionalProperties" and not path:
            declared = list(schema.get("properties", {}))
            for extra in sorted(set(arguments) - set(declared)):
                close = difflib.get_close_matches(extra, declared, n=1, cutoff=0.6)
                message += f". {extra}: did you mean {close[0]}?" if close else ""
            message += f". {name} takes: {', '.join(declared) or 'no arguments'}"
        neighbour = _accepting_neighbour(schema, error)
        if neighbour is not None:
            message += (
                f". {path[0]} takes {_type_name(error.schema)}; {neighbour} takes "
                f"{_type_name(schema['properties'][neighbour])} and accepts what you passed"
            )
        # The log gets the rule and the parameter, never the value: jsonschema quotes the value in its message.
        rejected = {"rule": str(error.validator)}
        if path:
            rejected["param"] = path[0]
        raise CallRefused(f"Input validation error: {message}", "validation", rejected) from error


async def route(app: App, name: str, arguments: dict[str, Any]) -> Result:
    """Run one tool call, or raise CallRefused saying why not."""
    tool = TOOLS.get(name)
    if tool is None:
        raise CallRefused(f"Unknown tool: {name}. This server lists: {', '.join(TOOLS)}", "unknown_tool")
    validate(name, arguments)
    if tool.writes and app.config.read_only:
        raise CallRefused(
            f"{name} writes to GitHub and the server is in read-only mode (GH_PROJECT_READ_ONLY). Nothing was sent.",
            "read_only",
        )
    try:
        async with app.lock:
            return await tool.handler(app, arguments)
    except REFUSALS as refusal:
        raise CallRefused(str(refusal), "handler") from refusal
    except Exception as error:
        logger.exception("Error handling %s", name)
        raise CallRefused(f"Error handling {name}: {error}", "handler") from error


def _record_call(app: App, name: str, arguments: dict[str, Any], started: float, **entry: Any) -> None:
    """Append the call to the call log when one is configured; never fails the call. Argument names, not values."""
    if not app.config.call_log:
        return
    record = {
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "tool": name,
        "arg_names": sorted(arguments),
        "ms": round((time.monotonic() - started) * 1000),
        **{key: value for key, value in entry.items() if value is not None},
    }
    try:
        with open(app.config.call_log, "a", encoding="utf-8") as log:
            log.write(json.dumps(record) + "\n")
    except OSError as error:
        logger.warning("Could not write call log %s: %s", app.config.call_log, error)


async def call_tool(app: App, name: str, arguments: dict[str, Any] | None) -> types.CallToolResult:
    """One tool call from request to result: routed, logged, and returned as text plus structured data."""
    arguments = arguments or {}
    started = time.monotonic()
    try:
        result = await route(app, name, arguments)
    except CallRefused as refused:
        text = str(refused)
        _record_call(
            app,
            name,
            arguments,
            started,
            isError=True,
            response_chars=len(text),
            error_kind=refused.kind,
            rejected=refused.rejected,
        )
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=True)
    text = result.render()
    _record_call(app, name, arguments, started, isError=False, response_chars=len(text))
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)], structured_content=result.structured() or None
    )


def build_server(app: App) -> Server:
    async def on_list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=tool_definitions())

    async def on_call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        return await call_tool(app, params.name, params.arguments)

    async def on_list_prompts(ctx: Any, params: Any) -> types.ListPromptsResult:
        return types.ListPromptsResult(prompts=prompt_definitions())

    async def on_get_prompt(ctx: Any, params: types.GetPromptRequestParams) -> types.GetPromptResult:
        return render_prompt(params.name, params.arguments)

    return Server(
        "gh-project-mcp",
        version=__version__,
        instructions=INSTRUCTIONS,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
        on_list_prompts=on_list_prompts,
        on_get_prompt=on_get_prompt,
    )


async def amain() -> None:
    app = App(Config.from_env())
    server = build_server(app)
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    finally:
        await app.aclose()


def main() -> None:
    """Entry point for the gh-project-mcp command."""
    logging.basicConfig(
        level=logging.INFO, stream=sys.stderr, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # a line per request drowns everything else
    try:
        anyio.run(amain)
    except KeyboardInterrupt:
        logger.info("Server shutting down")


if __name__ == "__main__":
    main()
