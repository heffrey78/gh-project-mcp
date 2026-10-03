"""The tracker as documents and a diagram (REQ-0007-FUNC-00).

Output is deterministic: records in number order, no timestamps, so an unchanged tracker exports identical bytes
and a diff of two exports shows what changed in the tracker.
"""

import re
from pathlib import Path
from typing import Any

import anyio

from ..app import App
from ..body import Document
from ..github.port import Comment, Milestone
from ..kinds import DECISION, PROJECT, REQUIREMENT, REQUIREMENT_TYPES, TASK
from ..registry import Result, ToolError, tool
from ..status import STATUSES
from ..tracker import Record, Tracker
from . import trail
from .common import resolve_project
from .records import field_lines, progress

_RETIRED = ("Deprecated", "Abandoned", "Rejected")
_CLASS = {
    "Draft": "todo", "Not Started": "todo", "Proposed": "todo",
    "Under Review": "active", "Approved": "active", "In Progress": "active",
    "Blocked": "blocked",
    "Implemented": "done", "Validated": "done", "Complete": "done", "Accepted": "done",
    "Superseded": "retired", "Deprecated": "retired", "Abandoned": "retired", "Rejected": "retired",
}  # fmt: skip
_CLASS_DEFS = (
    "classDef todo fill:#f6f8fa,stroke:#8c959f,color:#24292f",
    "classDef active fill:#ddf4ff,stroke:#0969da,color:#24292f",
    "classDef blocked fill:#ffebe9,stroke:#cf222e,color:#24292f",
    "classDef done fill:#dafbe1,stroke:#1a7f37,color:#24292f",
    "classDef retired fill:#eaeef2,stroke:#afb8c1,color:#57606a",
)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "tracker"


def _heading(record: Record, level: str = "###") -> str:
    priority = f", {record.priority}" if record.priority else ""
    return f"{level} [#{record.number}]({record.url}) {record.title}\n\n**Status:** {record.status}{priority}"


def _attrs(record: Record) -> str:
    doc = record.doc
    pairs = [(s.heading, doc.get(s.name)) for s in doc._specs.values() if s.shape == "attr" and doc.get(s.name)]
    return " | ".join(f"**{label}:** {value}" for label, value in pairs)


def _entry(tracker: Tracker, record: Record, amended: list[Comment] | None = None, level: str = "###") -> list[str]:
    lines = [_heading(record, level)]
    attrs = _attrs(record)
    if attrs:
        lines[0] += f" | {attrs}"
    done = progress(tracker, record)
    if done:
        lines.append(f"**Progress:** {done[0]}/{done[1]} tasks complete")
    if record.kind == TASK:
        parent = tracker.parent(record.number)
        if parent:
            lines.append(f"**Under:** #{parent.number} {parent.title}")
    if record.kind == DECISION:
        for field, label in (("addresses", "Addresses"), ("supersedes", "Supersedes")):
            numbers = record.doc.get(field)
            if numbers:
                lines.append(f"**{label}:** {', '.join(f'#{n}' for n in numbers)}")
        by = tracker.superseded_by(record.number)
        if by:
            lines.append(f"**Superseded by:** {', '.join(f'#{d.number}' for d in by)}")
    if record.kind == REQUIREMENT:
        decisions = tracker.decisions_addressing(record.number)
        if decisions:
            lines.append(f"**Decisions:** {', '.join(f'#{d.number}' for d in decisions)}")
    body = "\n".join(field_lines(record, amended)).strip()
    return ["\n\n".join(lines)] + ([body] if body else [])


def _project_intro(milestone: Milestone) -> list[str]:
    """A project's stored purpose, never a summary written at export time."""
    doc = Document(milestone.description, PROJECT)
    lines = [doc.get("purpose")] if doc.get("purpose") else []
    for name, heading in (("success_criteria", "Success criteria"), ("out_of_scope", "Out of scope")):
        if doc.get(name):
            lines.append(f"**{heading}:**\n" + "\n".join(f"- {item}" for item in doc.get(name)))
    return lines


def _by_type(tracker: Tracker, requirements: list[Record], level: str) -> list[str]:
    out = []
    for kind in (*REQUIREMENT_TYPES, None):
        of_type = [
            r for r in requirements if (r.doc.get("type") if r.doc.get("type") in REQUIREMENT_TYPES else None) == kind
        ]
        if of_type:
            out.append(f"{level} {kind or 'Untyped'}")
            for record in of_type:
                out += _entry(tracker, record, level=level + "#")
    return out


def requirements_document(tracker: Tracker, title: str, records: list[Record], project: Milestone | None) -> str:
    parts = [f"# {title}: Requirements"]
    requirements = [r for r in records if r.kind == REQUIREMENT]
    if project is not None:
        parts += _project_intro(project) + _by_type(tracker, requirements, "##")
    else:
        for milestone in sorted(tracker.milestones.values(), key=lambda m: m.number):
            members = [r for r in requirements if r.issue.milestone == milestone.number]
            parts.append(f"## Project: {milestone.title}" + (" (closed)" if milestone.state == "closed" else ""))
            parts += _project_intro(milestone) + _by_type(tracker, members, "###")
        loose = [r for r in requirements if r.issue.milestone not in tracker.milestones]
        if loose:
            parts += (["## In no project"] if tracker.milestones else []) + _by_type(tracker, loose, "###")
    if not requirements:
        parts.append("No requirements.")
    return "\n\n".join(parts) + "\n"


def decisions_document(
    tracker: Tracker, title: str, records: list[Record], project: Milestone | None, amended: dict[int, list[Comment]]
) -> str:
    parts = [f"# {title}: Architecture decisions"] + (_project_intro(project) if project else [])
    decisions = [r for r in records if r.kind == DECISION]
    for record in decisions:
        parts += _entry(tracker, record, amended.get(record.number), level="##")
    if not decisions:
        parts.append("No decisions.")
    return "\n\n".join(parts) + "\n"


def tasks_document(tracker: Tracker, title: str, records: list[Record], project: Milestone | None) -> str:
    parts = [f"# {title}: Tasks"] + (_project_intro(project) if project else [])
    tasks = [r for r in records if r.kind == TASK]
    for status in STATUSES[TASK]:
        of_status = [t for t in tasks if t.status == status]
        if of_status:
            parts.append(f"## {status}")
            for record in of_status:
                parts += _entry(tracker, record)
    if not tasks:
        parts.append("No tasks.")
    return "\n\n".join(parts) + "\n"


def _label(record: Record) -> str:
    title = re.sub(r'["\[\]{}<>|]', "'", record.title)
    return f'{record.kind[0].upper()}{record.number}["#{record.number} {title}"]:::{_CLASS[record.status]}'


def diagram(tracker: Tracker, records: list[Record], limit: int | None) -> tuple[str, dict[str, int]]:
    """A Mermaid graph of the records and their links, and what was drawn and left out."""
    live = [r for r in records if r.status not in _RETIRED]
    drawn: list[Record] = []
    for kind in (REQUIREMENT, DECISION, TASK):
        of_kind = [r for r in live if r.kind == kind]
        drawn += of_kind[:limit] if limit else of_kind
    ids = {r.number: f"{r.kind[0].upper()}{r.number}" for r in drawn}
    lines = ["graph TD"] + [f"    {_label(r)}" for r in drawn]
    for record in drawn:
        me = ids[record.number]
        parent = record.issue.parent
        if parent in ids:
            lines.append(
                f"    {me} -->|{'implements' if tracker.get(parent).kind == REQUIREMENT else 'part of'}| {ids[parent]}"
            )
        lines += [f"    {me} -.->|blocked by| {ids[n]}" for n in record.issue.blocked_by if n in ids]
        if record.kind == DECISION:
            lines += [f"    {me} -->|addresses| {ids[n]}" for n in record.doc.get("addresses") or [] if n in ids]
            lines += [f"    {me} ==>|supersedes| {ids[n]}" for n in record.doc.get("supersedes") or [] if n in ids]
    lines += [f"    {definition}" for definition in _CLASS_DEFS]
    stats = {"drawn": len(drawn), "retired_left_out": len(records) - len(live), "over_limit": len(live) - len(drawn)}
    return "\n".join(lines) + "\n", stats


def _write(directory: Path, files: dict[str, str]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for filename, content in files.items():
        (directory / filename).write_text(content, encoding="utf-8")


@tool(
    "export_docs",
    "Write the tracker as Markdown files: requirements, decisions, tasks, and a Mermaid diagram of the links. "
    "With `project`, only that project's records, each document opening with its purpose.",
    {
        "output_directory": {"type": "string", "description": "Default: exports"},
        "project": {"type": ["integer", "string"], "description": "Milestone number or title"},
        "name": {"type": "string", "description": "File name prefix"},
        "diagram": {"type": "boolean", "description": "Default true"},
        "limit": {"type": "integer", "minimum": 1, "description": "Most records of a kind in the diagram"},
    },
)
async def export_docs(app: App, args: dict[str, Any]) -> Result:
    tracker = await app.tracker()
    await tracker.refresh_milestones()
    project = resolve_project(tracker, args["project"]) if "project" in args else None
    records = tracker.in_project(project.number) if project else tracker.records()
    title = project.title if project else app.github.repo.split("/")[-1]
    name = _slug(args.get("name") or title)

    # Amendments are comments, so a decided decision costs one request each; nothing else here does.
    amended = {}
    for record in records:
        if record.kind == DECISION and record.status in ("Accepted", "Superseded"):
            found = trail.amendments(await app.github.list_comments(record.number))
            if found:
                amended[record.number] = found

    files = {
        f"{name}-requirements.md": requirements_document(tracker, title, records, project),
        f"{name}-decisions.md": decisions_document(tracker, title, records, project, amended),
        f"{name}-tasks.md": tasks_document(tracker, title, records, project),
    }
    stats = None
    if args.get("diagram", True):
        graph, stats = diagram(tracker, records, args.get("limit"))
        files[f"{name}-diagram.md"] = f"# {title}: Records and links\n\n```mermaid\n{graph}```\n"

    directory = Path(args.get("output_directory") or "exports")
    try:
        await anyio.to_thread.run_sync(_write, directory, files)
    except OSError as error:
        raise ToolError(f"Could not write to {directory}: {error}") from error

    paths = [str(directory / filename) for filename in files]
    lines = [f"Exported {len(records)} records from {app.github.repo}:"] + [f"- {path}" for path in paths]
    if stats:
        lines.append(
            f"Diagram: {stats['drawn']} records drawn, {stats['retired_left_out']} retired left out, "
            f"{stats['over_limit']} over the limit."
        )
    return Result("\n".join(lines), {"files": paths, "records": len(records), **({"diagram": stats} if stats else {})})
