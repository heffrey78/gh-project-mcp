"""Projects: milestones with a stated purpose (REQ-0004-FUNC-00, ADR-0003)."""

from typing import Any

from ..app import App
from ..body import Document, edit_body, new_body
from ..github.port import Milestone
from ..kinds import PROJECT, REQUIREMENT, TASK, field_properties
from ..registry import Result, ToolError, tool
from ..tracker import Tracker
from .common import resolve_project, row

_FIELDS = ("purpose", "success_criteria", "out_of_scope")


def project_progress(tracker: Tracker, milestone: Milestone) -> dict[str, Any]:
    """A project's members by kind, and how much of its work is finished."""
    members = tracker.in_project(milestone.number)
    tasks = [r for r in members if r.kind == TASK and r.status != "Abandoned"]
    leaves = [t for t in tasks if not any(c.kind == TASK for c in tracker.children(t.number))]
    return {
        "number": milestone.number,
        "title": milestone.title,
        "state": milestone.state,
        "requirements": sum(1 for r in members if r.kind == REQUIREMENT),
        "tasks": len(leaves),
        "tasks_complete": sum(1 for t in leaves if t.status == "Complete"),
    }


def describe_project(tracker: Tracker, milestone: Milestone) -> Result:
    doc = Document(milestone.description, PROJECT)
    progress = project_progress(tracker, milestone)
    lines = [
        f"Project {milestone.number}: {milestone.title}",
        milestone.url,
        f"State: {milestone.state} | Requirements: {progress['requirements']} | "
        f"Tasks: {progress['tasks_complete']}/{progress['tasks']} complete",
    ]
    if doc.get("purpose"):
        lines += ["\nPurpose:", doc.get("purpose")]
    for name, heading in (("success_criteria", "Success criteria"), ("out_of_scope", "Out of scope")):
        if doc.get(name):
            lines += [f"\n{heading}:"] + [f"- {item}" for item in doc.get(name)]
    members = tracker.in_project(milestone.number)
    for kind, heading in ((REQUIREMENT, "Requirements"), ("decision", "Decisions")):
        of_kind = [r for r in members if r.kind == kind]
        if of_kind:
            lines += [f"\n{heading}:"] + [f"- {row(r)}" for r in of_kind]
    return Result("\n".join(lines), {**progress, "url": milestone.url, "fields": doc.fields()})


@tool(
    "save_project",
    "Create a project (a GitHub milestone with a stated purpose), or with `project` edit, close or reopen one. "
    "Requirements join a project through their `project` parameter; their tasks follow.",
    {
        "project": {"type": ["integer", "string"], "description": "Milestone number or title to edit; omit to create"},
        "title": {"type": "string"},
        **field_properties(PROJECT),
        "state": {"enum": ["open", "closed"]},
    },
    writes=True,
)
async def save_project(app: App, args: dict[str, Any]) -> Result:
    tracker = await app.tracker()
    await tracker.refresh_milestones()
    fields = {name: args[name] for name in _FIELDS if name in args}

    if "project" not in args:
        if not args.get("title") or not args.get("purpose"):
            raise ToolError("A new project needs `title` and `purpose`; to edit one, pass `project`")
        if tracker.find_project(args["title"]) is not None:
            raise ToolError(f"A project titled {args['title']!r} exists; pass `project` to edit it")
        milestone = await app.github.create_milestone(args["title"], new_body(PROJECT, fields))
        if args.get("state") == "closed":
            milestone = await app.github.update_milestone(milestone.number, state="closed")
        tracker.put_milestone(milestone)
        text = f"Created project {milestone.number}: {milestone.title}\n{milestone.url}"
        return Result(text, {"number": milestone.number, "title": milestone.title, "url": milestone.url})

    milestone = resolve_project(tracker, args["project"])
    changes: dict[str, Any] = {}
    if "title" in args and args["title"] != milestone.title:
        changes["title"] = args["title"]
    if fields:
        description = edit_body(milestone.description, PROJECT, fields)
        if description != milestone.description:
            changes["description"] = description
    if "state" in args and args["state"] != milestone.state:
        changes["state"] = args["state"]
    if not changes:
        return Result(f"Project {milestone.number} already holds those values; nothing was written.", {"changed": []})
    milestone = await app.github.update_milestone(milestone.number, **changes)
    tracker.put_milestone(milestone)
    text = f"Updated project {milestone.number} ({milestone.title}): changed {', '.join(changes)}"
    return Result(text, {"number": milestone.number, "changed": list(changes)})
