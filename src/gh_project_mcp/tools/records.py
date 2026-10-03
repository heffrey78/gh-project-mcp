"""Creating, reading, editing and finding records (REQ-0001-FUNC-00)."""

from typing import Any

import jsonschema

from .. import rules
from ..app import App
from ..body import edit_body, new_body
from ..github.port import UNSET, Comment, Event, GitHubError
from ..kinds import (
    CHECKLIST,
    DECISION,
    PRIORITIES,
    RECORD_KINDS,
    REQUIREMENT,
    TASK,
    editable_fields,
    field_properties,
    field_specs,
)
from ..registry import ID, IDS, Result, ToolError, tool
from ..status import DONE, FIRST_STATUS, STATUSES
from ..tracker import Record, Tracker
from . import trail
from .common import brief, expect_kind, parse_id, parse_ids, project_name, resolve_project, row, rows

_PRIORITY = {"enum": list(PRIORITIES)}
_PROJECT = {"type": ["integer", "string"], "description": "Milestone number or title"}
_TEXT = {"type": "string"}

# Requirement statuses at which an edit needs a reason: someone has reviewed the text being changed.
_REVIEWED = STATUSES[REQUIREMENT][2:]


def _fields_from(args: dict[str, Any], kind: str) -> dict[str, Any]:
    names = {spec.name for spec in editable_fields(kind)}
    return {name: value for name, value in args.items() if name in names}


async def _create(
    app: App,
    tracker: Tracker,
    kind: str,
    args: dict[str, Any],
    fields: dict[str, Any],
    *,
    priority: str | None,
    milestone: int | None,
    reasons: list[str],
) -> tuple[Record, list[str]]:
    """Create the issue for a new record. Rules are applied before anything is written."""
    reasons = reasons + rules.thin_reasons(kind, fields, priority)
    warnings = rules.check(reasons, f"create this {kind}")
    try:
        body = new_body(kind, fields)
    except ValueError as error:
        raise ToolError(str(error)) from error
    await tracker.ensure_labels()
    labels = [app.vocabulary.kind_label(kind)] + ([app.vocabulary.priority_label(priority)] if priority else [])
    assignees = [args["assignee"]] if args.get("assignee") else None
    issue = await app.github.create_issue(args["title"], body, labels, milestone=milestone, assignees=assignees)
    return tracker.put(issue), warnings


def _created(record: Record, warnings: list[str], extra: str = "") -> Result:
    text = f"Created {record.kind} #{record.number}: {record.title}\n{record.url}\nStatus: {record.status}{extra}"
    return Result(text, {**brief(record), "url": record.url}, warnings)


@tool(
    "create_requirement",
    "Create a requirement as an issue. It starts in Draft; approving it is the owner's decision.",
    {
        "title": _TEXT,
        "priority": _PRIORITY,
        **field_properties(REQUIREMENT),
        "project": _PROJECT,
    },
    required=("title", "type", "priority", "current_state", "desired_state"),
    writes=True,
)
async def create_requirement(app: App, args: dict[str, Any]) -> Result:
    tracker = await app.tracker()
    milestone = resolve_project(tracker, args["project"]).number if "project" in args else None
    fields = _fields_from(args, REQUIREMENT)
    record, warnings = await _create(
        app, tracker, REQUIREMENT, args, fields, priority=args["priority"], milestone=milestone, reasons=[]
    )
    return _created(record, warnings)


@tool(
    "create_decision",
    "Record an architecture decision (ADR) as an issue. It starts Proposed and is editable until it is decided.",
    {
        "title": _TEXT,
        **field_properties(DECISION),
        "addresses": {**IDS, "description": "Requirements it addresses"},
        "project": _PROJECT,
    },
    required=("title", "context", "decision"),
    writes=True,
)
async def create_decision(app: App, args: dict[str, Any]) -> Result:
    tracker = await app.tracker()
    addresses = parse_ids(args["addresses"]) if args.get("addresses") else []
    for number in addresses:
        expect_kind(tracker.get(number), REQUIREMENT, role="addresses")
    milestone = resolve_project(tracker, args["project"]).number if "project" in args else None
    if milestone is None and addresses:
        milestone = tracker.get(addresses[0]).issue.milestone
    fields = {**_fields_from(args, DECISION), "addresses": addresses}
    record, warnings = await _create(
        app, tracker, DECISION, args, fields, priority=None, milestone=milestone, reasons=[]
    )
    return _created(record, warnings)


@tool(
    "create_task",
    "Create a task as a sub-issue of the requirement it implements, or of a parent task.",
    {
        "title": _TEXT,
        "parent": {**ID, "description": "The requirement it implements, or a parent task"},
        "priority": _PRIORITY,
        **field_properties(TASK),
        "blocked_by": {**IDS, "description": "Tasks that must finish first"},
        "assignee": {"type": "string", "description": "GitHub login"},
    },
    required=("title", "parent", "priority"),
    writes=True,
)
async def create_task(app: App, args: dict[str, Any]) -> Result:
    tracker = await app.tracker()
    parent = tracker.get(parse_id(args["parent"]))
    expect_kind(parent, REQUIREMENT, TASK, role="parent")
    blockers = [tracker.get(n) for n in parse_ids(args["blocked_by"])] if args.get("blocked_by") else []
    requirement = parent if parent.kind == REQUIREMENT else tracker.requirement_of(parent.number)
    record, warnings = await _create(
        app,
        tracker,
        TASK,
        args,
        _fields_from(args, TASK),
        priority=args["priority"],
        milestone=parent.issue.milestone,
        reasons=rules.new_task_reasons(requirement),
    )
    # The issue exists from here on, so a link that fails is reported with the number, not swallowed.
    try:
        await app.github.add_sub_issue(parent.number, record.number, record.issue.id)
        tracker.set_parent(record.number, parent.number)
        for blocker in blockers:
            await app.github.add_blocked_by(record.number, blocker.number, blocker.issue.id)
            tracker.set_blocked_by(record.number, blocker.number, True)
    except GitHubError as error:
        raise ToolError(
            f"Created task #{record.number} ({record.url}) but could not finish linking it under #{parent.number}: "
            f"{error}. Link it with link_records, or close it."
        ) from error
    waits = f"\nBlocked by: {', '.join(f'#{b.number}' for b in blockers)}" if blockers else ""
    return _created(record, warnings, f"\nUnder: {row(parent)}{waits}")


def _validate_fields(kind: str, fields: dict[str, Any]) -> None:
    specs = {spec.name: spec for spec in editable_fields(kind)}
    unknown = [name for name in fields if name not in specs]
    if unknown:
        managed = [s.name for s in field_specs(kind) if s.managed and s.name in unknown]
        hint = f" ({', '.join(managed)} is set by set_status or link_records)" if managed else ""
        raise ToolError(
            f"A {kind} has no field {', '.join(unknown)}{hint}. Its fields are: {', '.join(specs)}. "
            "title, priority and project are parameters of their own"
        )
    for name, value in fields.items():
        try:
            jsonschema.validate(value, {"anyOf": [specs[name].schema(), {"type": "null"}]})
        except jsonschema.ValidationError:
            shape = "a list of strings" if specs[name].shape in ("list", CHECKLIST) else "a string"
            choices = f", one of {', '.join(specs[name].choices)}" if specs[name].choices else ""
            raise ToolError(f"fields.{name} must be {shape}{choices}, or null to remove it") from None


@tool(
    "update_record",
    "Edit a record in place: only what you name changes. `fields` holds the kind's own fields, as in its create "
    "tool; null removes one. A requirement at Approved or later needs `reason`. A decided decision is not "
    "rewritten: pass `amendment` to add a dated correction, or supersede it.",
    {
        "id": ID,
        "title": _TEXT,
        "priority": _PRIORITY,
        "project": {**_PROJECT, "description": "Milestone number or title; empty string for none"},
        "assignee": {"type": "string", "description": "GitHub login; empty string for none"},
        "fields": {"type": "object"},
        "reason": _TEXT,
        "amendment": _TEXT,
    },
    required=("id",),
    writes=True,
)
async def update_record(app: App, args: dict[str, Any]) -> Result:
    tracker = await app.tracker()
    record = tracker.get(parse_id(args["id"]))
    fields = args.get("fields") or {}
    _validate_fields(record.kind, fields)
    content = [name for name in ("title", "priority") if name in args] + list(fields)
    if "amendment" in args:
        return await _amend(app, record, args, content)
    if not content and "project" not in args and "assignee" not in args:
        raise ToolError("Nothing to change: pass title, priority, project, assignee, fields or amendment")
    if record.kind == DECISION and content and record.status != FIRST_STATUS[DECISION]:
        raise ToolError(
            f"Decision #{record.number} is {record.status} and is not rewritten. To correct it, pass `amendment`; "
            "to change direction, create a new decision and link_records(source=<new>, type='supersedes', "
            f"target={record.number})"
        )
    if record.kind == REQUIREMENT and content and record.status in _REVIEWED and not args.get("reason"):
        raise ToolError(
            f"Requirement #{record.number} is {record.status}: editing it needs `reason`, which is posted on the "
            "issue so reviewers see why reviewed text changed"
        )
    if "priority" in args and record.kind == DECISION:
        raise ToolError("A decision has no priority")
    if "assignee" in args and record.kind != TASK:
        raise ToolError("Only a task has an assignee")

    changes: dict[str, Any] = {}
    changed: list[str] = []
    if "title" in args and args["title"] != record.title:
        changes["title"] = args["title"]
        changed.append("title")
    if "priority" in args and args["priority"] != record.priority:
        labels = app.vocabulary.without_priority(record.issue.labels)
        changes["labels"] = [*labels, app.vocabulary.priority_label(args["priority"])]
        changed.append("priority")
    if fields:
        try:
            body = edit_body(record.issue.body, record.kind, fields)
        except ValueError as error:
            raise ToolError(str(error)) from error
        if body != record.issue.body:
            before = record.doc.fields()
            after = {**before, **fields}
            changes["body"] = body
            changed += [name for name in fields if (after.get(name) or None) != before.get(name)]
    milestone: Any = UNSET
    if "project" in args:
        milestone = resolve_project(tracker, args["project"]).number if str(args["project"]).strip() else None
        if milestone != record.issue.milestone:
            changes["milestone"] = milestone
            changed.append("project")
    if "assignee" in args:
        assignees = [args["assignee"]] if args["assignee"] else []
        if assignees != record.issue.assignees:
            changes["assignees"] = assignees
            changed.append("assignee")
    if not changes:
        return Result(f"#{record.number} already holds those values; nothing was written.", {"changed": []})

    record = tracker.put(await app.github.update_issue(record.number, **changes))
    followed = []
    if "milestone" in changes:
        # Work follows its requirement into the project.
        for below in tracker.descendants(record.number):
            if below.issue.milestone != changes["milestone"]:
                tracker.put(await app.github.update_issue(below.number, milestone=changes["milestone"]))
                followed.append(below.number)
    if args.get("reason"):
        await app.github.add_comment(record.number, trail.edit_comment(changed, args["reason"]))
    text = f"Updated {record.kind} #{record.number}: changed {', '.join(changed)}"
    if followed:
        text += f"\nMoved with it: {', '.join(f'#{n}' for n in followed)}"
    return Result(text, {"number": record.number, "changed": changed, "followed": followed})


async def _amend(app: App, record: Record, args: dict[str, Any], content: list[str]) -> Result:
    if record.kind != DECISION:
        raise ToolError(f"Only a decision takes an amendment; #{record.number} is a {record.kind}. Edit its fields")
    if content or "project" in args:
        raise ToolError("Pass `amendment` on its own: it adds a correction and edits nothing")
    if record.status not in DONE[DECISION]:
        raise ToolError(
            f"Decision #{record.number} is {record.status}. An amendment corrects an Accepted decision"
            + ("; a Proposed one is simply edited: pass `fields`" if record.status == "Proposed" else "")
        )
    await app.github.add_comment(record.number, trail.amendment_comment(args["amendment"], args.get("reason")))
    return Result(
        f"Amended decision #{record.number}. Its text is unchanged; the amendment shows beneath it.",
        {"number": record.number, "amended": True},
    )


@tool(
    "add_comment",
    "Comment on a record's issue.",
    {"id": ID, "comment": _TEXT},
    required=("id", "comment"),
    writes=True,
)
async def add_comment(app: App, args: dict[str, Any]) -> Result:
    tracker = await app.tracker()
    record = tracker.get(parse_id(args["id"]))
    if not args["comment"].strip():
        raise ToolError("The comment is empty")
    await app.github.add_comment(record.number, args["comment"])
    return Result(f"Commented on {record.kind} #{record.number}.", {"number": record.number})


# -- reading ----------------------------------------------------------------------------------------------------


def _tree(tracker: Tracker, number: int, depth: int = 0) -> list[str]:
    lines = []
    for child in tracker.children(number):
        lines.append(f"{'  ' * depth}- {row(child)}")
        lines += _tree(tracker, child.number, depth + 1)
    return lines


def progress(tracker: Tracker, record: Record) -> tuple[int, int] | None:
    """Leaf tasks complete and leaf tasks that count (abandoned ones do not), or None when there are none."""
    counted = [t for t in tracker.leaf_tasks(record.number) if t.status != "Abandoned"]
    return (sum(1 for t in counted if t.status == "Complete"), len(counted)) if counted else None


def links(tracker: Tracker, record: Record) -> dict[str, list[Record]]:
    """A record's links from its own end; only the kinds of link it has."""
    found = {
        "parent": [p for p in [tracker.parent(record.number)] if p],
        "children": tracker.children(record.number),
        "blocked_by": tracker.blockers(record.number),
        "blocking": tracker.blocking(record.number),
    }
    if record.kind == REQUIREMENT:
        found["decisions"] = tracker.decisions_addressing(record.number)
    if record.kind == DECISION:
        found["addresses"] = tracker._known(record.doc.get("addresses") or [])
        found["supersedes"] = tracker._known(record.doc.get("supersedes") or [])
        found["superseded_by"] = tracker.superseded_by(record.number)
    return {name: records for name, records in found.items() if records}


def field_lines(record: Record, amended: list[Comment] | None = None) -> list[str]:
    """A record's fields as text, each under its heading; amendments sit directly beneath the decision."""
    lines: list[str] = []
    for spec in field_specs(record.kind):
        value = record.doc.get(spec.name)
        if value is None or spec.shape in ("attr", "refs"):
            continue
        lines.append(f"\n{spec.heading}:")
        if spec.shape == CHECKLIST:
            lines += [f"- [{'x' if done else ' '}] {text}" for text, done in record.doc.checklist(spec.name)]
        elif isinstance(value, list):
            lines += [f"- {item}" for item in value]
        else:
            lines.append(str(value))
        if spec.name == "decision" and amended:
            lines += [f"> {trail.amendment_text(c)}" for c in amended]
    return lines


def describe(
    tracker: Tracker,
    record: Record,
    comments: list[Comment] | None = None,
    events: list[Event] | None = None,
    amended: list[Comment] | None = None,
) -> Result:
    doc = record.doc
    facts = [f"Status: {record.status}"]
    facts += [f"Priority: {record.priority}"] if record.priority else []
    attrs = [s for s in field_specs(record.kind) if s.shape == "attr"]
    facts += [f"{s.heading}: {doc.get(s.name)}" for s in attrs if doc.get(s.name)]
    project = project_name(tracker, record)
    facts += [f"Project: {project}"] if project else []
    facts += [f"Assignee: {', '.join(record.issue.assignees)}"] if record.issue.assignees else []
    lines = [f"{record.kind.title()} #{record.number}: {record.title}", record.url, " | ".join(facts)]
    done = progress(tracker, record)
    if done:
        lines.append(f"Progress: {done[0]}/{done[1]} tasks complete")
    lines += [f"Problem: #{record.number} {problem}" for problem in record.problems]

    lines += field_lines(record, amended)
    if doc.other_sections:
        lines.append(f"\nOther sections in the issue: {', '.join(doc.other_sections)}")

    found = links(tracker, record)
    titles = {
        "parent": "Under",
        "children": "Tasks" if record.kind == REQUIREMENT else "Subtasks",
        "blocked_by": "Blocked by",
        "blocking": "Blocking",
        "decisions": "Decisions",
        "addresses": "Addresses",
        "supersedes": "Supersedes",
        "superseded_by": "Superseded by",
    }
    for name, records in found.items():
        lines.append(f"\n{titles[name]}:")
        lines += _tree(tracker, record.number) if name == "children" else [f"- {row(r)}" for r in records]

    if comments is not None:
        lines.append(f"\nComments ({len(comments)}):")
        lines += [f"- {c.created_at[:10]} {c.author}: {c.body.strip()}" for c in comments]
    if events is not None:
        lines.append(f"\nHistory ({len(events)}):")
        lines += [f"- {e.created_at} {e.actor}: {e.kind}{' ' + e.detail if e.detail else ''}" for e in events]

    data = {
        **brief(record),
        "url": record.url,
        "fields": doc.fields(),
        "links": {name: [r.number for r in records] for name, records in found.items()},
    }
    if project:
        data["project"] = project
    if record.problems:
        data["problems"] = record.problems
    if amended:
        data["amendments"] = [trail.amendment_text(c) for c in amended]
    if comments is not None:
        data["comments"] = [{"author": c.author, "at": c.created_at, "body": c.body} for c in comments]
    if events is not None:
        data["history"] = [{"at": e.created_at, "actor": e.actor, "event": e.kind, "detail": e.detail} for e in events]
    return Result("\n".join(lines), data)


@tool(
    "get_record",
    "One record in full: fields, status and its links from its own end (a requirement shows its task tree and "
    "decisions); comments and timeline on request. Pass `project` instead of `id` for a project.",
    {
        "id": ID,
        "project": _PROJECT,
        "include": {"type": "array", "items": {"enum": ["comments", "history"]}},
    },
)
async def get_record(app: App, args: dict[str, Any]) -> Result:
    tracker = await app.tracker()
    if ("id" in args) == ("project" in args):
        raise ToolError("Pass either `id` (an issue number) or `project` (a milestone number or title)")
    if "project" in args:
        from .projects import describe_project

        await tracker.refresh_milestones()
        return describe_project(tracker, resolve_project(tracker, args["project"]))
    record = tracker.get(parse_id(args["id"]))
    include = args.get("include") or []
    fetched = None
    # A decided decision's amendments are part of reading it, so its comments are fetched whether asked for or not.
    if "comments" in include or (record.kind == DECISION and record.status != FIRST_STATUS[DECISION]):
        fetched = await app.github.list_comments(record.number)
    events = await app.github.list_events(record.number) if "history" in include else None
    comments = fetched if "comments" in include else None
    return describe(tracker, record, comments, events, trail.amendments(fetched or []))


def matches(record: Record, terms: list[str]) -> bool:
    haystack = f"{record.title}\n{record.issue.body}".lower()
    return all(term in haystack for term in terms)


def explain_empty_ready(tracker: Tracker) -> str:
    """Which kind of nothing: no work left, everything waiting, or only work already started."""
    tasks = [t for t in tracker.records(TASK) if not rules.is_settled(t)]
    if not tasks:
        return "No tasks are ready to start: no open tasks remain."
    started = [t for t in tasks if t.status == "In Progress"]
    blocked = [t for t in tasks if t.status == "Blocked"]
    not_started = [t for t in tasks if t.status == "Not Started"]
    waiting = [t for t in not_started if rules.unmet_blockers(tracker, t)]
    unapproved = [
        t
        for t in not_started
        if t not in waiting and (r := tracker.requirement_of(t.number)) and r.status not in rules.WORKABLE
    ]
    parts = []
    if started:
        parts.append(f"{len(started)} already In Progress")
    if blocked:
        parts.append(f"{len(blocked)} Blocked")
    if waiting:
        parts.append(f"{len(waiting)} waiting on unfinished work")
    if unapproved:
        parts.append(f"{len(unapproved)} under a requirement that is not Approved")
    return f"No tasks are ready to start: of {len(tasks)} open, {', '.join(parts) or 'none can start'}."


@tool(
    "query_records",
    "Find records. Filters combine. Returns one line per record; pass `full` for every field.",
    {
        "kind": {"enum": list(RECORD_KINDS)},
        "status": _TEXT,
        "priority": _PRIORITY,
        "project": _PROJECT,
        "search": {"type": "string", "description": "Words that must all appear in the title or body"},
        "ready": {"type": "boolean", "description": "Tasks that can start now, highest priority first"},
        "work_complete": {
            "type": "boolean",
            "description": "Requirements whose tasks are all finished but that are not yet Implemented",
        },
        "full": {"type": "boolean"},
        "limit": {"type": "integer", "minimum": 1},
    },
)
async def query_records(app: App, args: dict[str, Any]) -> Result:
    tracker = await app.tracker()
    if args.get("ready"):
        found = rules.ready_tasks(tracker)
    elif args.get("work_complete"):
        found = [r for r in tracker.records(REQUIREMENT) if rules.is_work_complete(tracker, r)]
    else:
        found = tracker.records()
    if "kind" in args:
        found = [r for r in found if r.kind == args["kind"]]
    if "status" in args:
        wanted = args["status"].strip().lower()
        if wanted not in {s.lower() for statuses in STATUSES.values() for s in statuses}:
            known = "; ".join(f"{kind}: {', '.join(statuses)}" for kind, statuses in STATUSES.items())
            raise ToolError(f"{args['status']!r} is not a status. {known}")
        found = [r for r in found if r.status.lower() == wanted]
    if "priority" in args:
        found = [r for r in found if r.priority == args["priority"]]
    if "project" in args:
        milestone = resolve_project(tracker, args["project"]).number
        found = [r for r in found if r.issue.milestone == milestone]
    if args.get("search"):
        terms = args["search"].lower().split()
        found = [r for r in found if matches(r, terms)]

    total = len(found)
    shown = found[: args["limit"]] if "limit" in args else found
    if not shown:
        text = (
            explain_empty_ready(tracker) if args.get("ready") and total == 0 and len(args) == 1 else "No records match."
        )
        return Result(text, {"count": 0, "records": []})
    if args.get("full"):
        records = [{**brief(r), "url": r.url, "fields": r.doc.fields()} for r in shown]
        text = "\n\n".join(
            "\n".join([f"#{r.number} [{r.kind}] {r.title} [{r.status}]", *field_lines(r)]) for r in shown
        )
    else:
        records = [brief(r) for r in shown]
        mixed = len({r.kind for r in shown}) > 1
        text = "\n".join(f"- {'[' + r.kind + '] ' if mixed else ''}{row(r)}" for r in shown)
    if total > len(shown):
        text += f"\n({len(shown)} of {total} shown)"
    return Result(text, {"count": total, "records": records})


__all__ = ["describe", "field_lines", "links", "progress", "rows"]
