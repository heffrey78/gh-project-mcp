"""Preparing a repository (REQ-0001-TECH-00)."""

from typing import Any

from ..app import App
from ..registry import Result, tool


@tool(
    "setup_repository",
    "Create the labels the server uses where the repository lacks them. Safe to repeat, and optional: the first "
    "write does the same.",
    writes=True,
)
async def setup_repository(app: App, args: dict[str, Any]) -> Result:
    tracker = await app.tracker()
    tracker._labels_ready = False  # look again, whatever an earlier call found
    created = await tracker.ensure_labels()
    wanted = [definition.name for definition in app.vocabulary.definitions()]
    text = f"{app.github.repo}: {len(wanted)} labels in use, {len(created)} created"
    if created:
        text += ":\n" + "\n".join(f"- {name}" for name in created)
    else:
        text += "; all were already there."
    return Result(text, {"repo": app.github.repo, "created": created, "labels": wanted})
