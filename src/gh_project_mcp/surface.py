"""How much the tool listing costs a client: every definition is sent with every request (ADR-0005)."""

import json

from .server import tool_definitions


def definition_sizes() -> dict[str, int]:
    """Each tool's tools/list entry in compact JSON, in characters."""
    return {
        tool.name: len(json.dumps(tool.model_dump(by_alias=True, exclude_none=True), separators=(",", ":")))
        for tool in tool_definitions()
    }
