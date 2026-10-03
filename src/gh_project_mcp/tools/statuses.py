"""Moving records through their lifecycles (REQ-0002-FUNC-00, ADR-0006)."""

from typing import Any

from .. import rules
from ..app import App
from ..body import edit_body
from ..github.port import GitHubError
from ..kinds import TASK
from ..registry import ID, Result, ToolError, tool
from ..rules import StatusRefused
from ..status import STATUSES, encode
from ..tracker import Record, Tracker
from . import trail
from .common import parse_ids


def _goal(record: Record, wanted: str) -> str:
    """The status meant, matched without regard to case."""
    for status in STATUSES[record.kind]:
        if status.lower() == wanted.strip().lower():
            return status
    raise StatusRefused(
        f"{wanted!r} is not a {record.kind} status; a {record.kind} is one of {', '.join(STATUSES[record.kind])}"
    )


async def _move(app: App, tracker: Tracker, record: Record, args: dict[str, Any]) -> dict[str, Any]:
    """Move one record, or raise StatusRefused before anything is written."""
    goal = _goal(record, args["status"])
    comment, commit, evidence = args.get("comment"), args.get("commit"), args.get("evidence")
    noting = record.status == goal and bool(commit or evidence or (goal == "Blocked" and comment))
    # Recording evidence on a task that is already Complete, or a new reason on one already Blocked, is not a
    # move: it writes the facts and leaves the status where it is.
    path = [goal] if noting else rules.path(record.kind, record.status, goal)

    reasons: list[str] = []
    for step in path[1:]:
        rules.always_on(tracker, record, step)
        reasons += [r for r in rules.move_reasons(tracker, record, step) if r not in reasons]
    warnings = rules.check(reasons, f"move #{record.number} to {goal}")

    changes: dict[str, Any] = {}
    if record.kind == TASK:
        edits: dict[str, Any] = {}
        if goal == "Blocked" and comment:
            edits["blocked_reason"] = comment
        elif goal != "Blocked" and record.doc.get("blocked_reason"):
            edits["blocked_reason"] = None
        if commit:
            edits["commit"] = commit
        if evidence:
            edits["evidence"] = evidence
        if edits:
            changes["body"] = edit_body(record.issue.body, TASK, edits)
    if not noting:
        changes["labels"], changes["state"], reason = encode(app.vocabulary, record.kind, goal, record.issue.labels)
        if reason:
            changes["state_reason"] = reason
    if changes:
        tracker.put(await app.github.update_issue(record.number, **changes))
    # The label change is on the timeline already; a comment is worth a request only when it says more than that.
    if comment or commit or evidence or len(path) > 2:
        await app.github.add_comment(record.number, trail.status_comment(path, comment, commit, evidence))

    moved: dict[str, Any] = {"id": record.number, "from": record.status, "to": goal}
    if len(path) > 2:
        moved["path"] = path
    if warnings:
        moved["warnings"] = warnings
    return moved


@tool(
    "set_status",
    "Move records to a status. Requirement: Draft, Under Review, Approved, Implemented, Validated, Deprecated. "
    "Task: Not Started, In Progress, Blocked, Complete, Abandoned. Decision: Proposed, Accepted, Rejected. "
    "Walks the allowed path, never through Approved or Validated. A Blocked task keeps `comment` as its reason; "
    "a task keeps `commit` and `evidence`.",
    {
        "ids": {"type": ["integer", "string", "array"], "items": ID, "description": "One issue number or a list"},
        "status": {"type": "string"},
        "comment": {"type": "string"},
        "commit": {"type": "string"},
        "evidence": {"type": "string", "description": "Test result or check behind the move"},
    },
    required=("ids", "status"),
    writes=True,
)
async def set_status(app: App, args: dict[str, Any]) -> Result:
    tracker = await app.tracker()
    results: list[dict[str, Any]] = []
    lines: list[str] = []
    for number in parse_ids(args["ids"]):
        try:
            # Each record moves on its own: one refusal does not hold back the others.
            moved = await _move(app, tracker, tracker.get(number), args)
        except (StatusRefused, LookupError) as refused:
            results.append({"id": number, "error": str(refused)})
            lines.append(f"#{number}: refused: {refused}")
            continue
        except GitHubError as failed:
            # The records before this one have moved; saying so matters more than stopping.
            results.append({"id": number, "error": str(failed)})
            lines.append(f"#{number}: failed: {failed}")
            continue
        results.append(moved)
        steps = moved.get("path") or ([moved["from"], moved["to"]] if moved["from"] != moved["to"] else [moved["to"]])
        lines.append(f"#{number}: {trail.ARROW.join(steps)}" + (" (noted)" if len(steps) == 1 else ""))
        lines += [f"  warning: {w}" for w in moved.get("warnings", [])]

    refused = [r for r in results if "error" in r]
    if len(refused) == len(results):
        raise ToolError("\n".join(lines) + "\nNo record moved.")
    if len(results) > 1:
        lines.append(f"Moved {len(results) - len(refused)}, refused {len(refused)}.")
    return Result("\n".join(lines), {"results": results, "moved": len(results) - len(refused), "refused": len(refused)})
