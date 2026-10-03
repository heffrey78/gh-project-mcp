"""The tools, each declared once (ADR-0005).

One declaration gives a tool its listing, the schema its calls are validated against and the function that runs
it, so the three cannot drift apart. Every schema refuses fields it does not declare.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .app import App


class ToolError(Exception):
    """A tool call that cannot be carried out. The client receives the message with isError true."""


@dataclass
class Result:
    """What a tool returns: text for the model to read, and the same facts as data."""

    text: str
    data: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def render(self) -> str:
        if not self.warnings:
            return self.text
        return self.text + "\n\nWarnings:\n" + "\n".join(f"- {w}" for w in self.warnings)

    def structured(self) -> dict[str, Any]:
        return {**self.data, "warnings": self.warnings} if self.warnings else self.data


Handler = Callable[["App", dict[str, Any]], Awaitable[Result]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    handler: Handler
    writes: bool  # changes something on GitHub, so refused in read-only mode before any request


TOOLS: dict[str, Tool] = {}

# An issue number: 12, "12" or "#12".
ID = {"type": ["integer", "string"]}
IDS = {"type": "array", "items": ID}


def tool(
    name: str,
    description: str,
    properties: dict[str, Any] | None = None,
    required: tuple[str, ...] = (),
    *,
    writes: bool = False,
) -> Callable[[Handler], Handler]:
    """Declare a tool. The decorated function is its handler."""

    def register(handler: Handler) -> Handler:
        if name in TOOLS:
            raise ValueError(f"tool {name} is declared twice")
        schema: dict[str, Any] = {"type": "object", "properties": properties or {}, "additionalProperties": False}
        if required:
            schema["required"] = list(required)
        TOOLS[name] = Tool(name, description, schema, handler, writes)
        return handler

    return register
