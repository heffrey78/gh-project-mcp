"""Links between records, kept in GitHub's own features where it has them (REQ-0003-FUNC-00, ADR-0003)."""

from typing import Any

from ..app import App
from ..body import edit_body
from ..kinds import DECISION, REQUIREMENT, TASK
from ..registry import ID, Result, ToolError, tool
from ..status import SUPERSEDED, encode
from ..tracker import Record, Tracker
from . import trail
from .common import expect_kind, parse_id, row

CHILD_OF, BLOCKED_BY, ADDRESSES, SUPERSEDES = "child_of", "blocked_by", "addresses", "supersedes"
LINK_TYPES = (CHILD_OF, BLOCKED_BY, ADDRESSES, SUPERSEDES)

_PROPERTIES = {
    "source": ID,
    "type": {"enum": list(LINK_TYPES)},
    "target": ID,
}


def _ends(tracker: Tracker, args: dict[str, Any]) -> tuple[Record, Record]:
    source, target = tracker.get(parse_id(args["source"])), tracker.get(parse_id(args["target"]))
    if source.number == target.number:
        raise ToolError(f"#{source.number} cannot be linked to itself")
    kind = args["type"]
    if kind == CHILD_OF:
        expect_kind(source, TASK, role="the source of child_of")
        expect_kind(target, REQUIREMENT, TASK, role="the target of child_of")
    elif kind == BLOCKED_BY:
        expect_kind(source, TASK, REQUIREMENT, role="the source of blocked_by")
        expect_kind(target, TASK, REQUIREMENT, role="the target of blocked_by")
    elif kind == ADDRESSES:
        expect_kind(source, DECISION, role="the source of addresses")
        expect_kind(target, REQUIREMENT, role="the target of addresses")
    else:
        expect_kind(source, DECISION, role="the source of supersedes")
        expect_kind(target, DECISION, role="the target of supersedes")
    return source, target


def _waits_on(tracker: Tracker, record: Record, other: int, seen: set[int] | None = None) -> bool:
    """Whether a record waits, directly or through others, on another."""
    seen = seen or set()
    for blocker in tracker.blockers(record.number):
        if blocker.number == other:
            return True
        if blocker.number not in seen:
            seen.add(blocker.number)
            if _waits_on(tracker, blocker, other, seen):
                return True
    return False


async def _set_refs(app: App, tracker: Tracker, decision: Record, field: str, numbers: list[int]) -> None:
    body = edit_body(decision.issue.body, DECISION, {field: numbers})
    tracker.put(await app.github.update_issue(decision.number, body=body))


@tool(
    "link_records",
    "Link two records; reads `source type target`. child_of: a task under a requirement or task (one parent). "
    "blocked_by: source waits on target. addresses: a decision addresses a requirement. supersedes: a newer "
    "decision replaces an older one, which becomes Superseded.",
    _PROPERTIES,
    required=("source", "type", "target"),
    writes=True,
)
async def link_records(app: App, args: dict[str, Any]) -> Result:
    tracker = await app.tracker()
    source, target = _ends(tracker, args)
    kind = args["type"]
    note = ""

    if kind == CHILD_OF:
        parent = tracker.parent(source.number)
        if parent is not None:
            raise ToolError(
                f"#{source.number} is already under {row(parent)}; an issue has one parent. Remove that link "
                f"first: unlink_records(source={source.number}, type='child_of', target={parent.number})"
            )
        if source.issue.parent is not None:
            raise ToolError(f"#{source.number} is already a sub-issue of #{source.issue.parent}, which is not a record")
        if target in tracker.descendants(source.number):
            raise ToolError(f"#{target.number} is under #{source.number}; putting it above would make a loop")
        await app.github.add_sub_issue(target.number, source.number, source.issue.id)
        tracker.set_parent(source.number, target.number)
        if source.issue.milestone != target.issue.milestone and target.issue.milestone is not None:
            # A task follows the requirement it implements into its project.
            tracker.put(await app.github.update_issue(source.number, milestone=target.issue.milestone))

    elif kind == BLOCKED_BY:
        if target.number in source.issue.blocked_by:
            raise ToolError(f"#{source.number} is already blocked by #{target.number}")
        if _waits_on(tracker, target, source.number):
            raise ToolError(f"#{target.number} already waits on #{source.number}; this would make a loop")
        await app.github.add_blocked_by(source.number, target.number, target.issue.id)
        tracker.set_blocked_by(source.number, target.number, True)

    elif kind == ADDRESSES:
        current = source.doc.get("addresses") or []
        if target.number in current:
            raise ToolError(f"Decision #{source.number} already addresses #{target.number}")
        await _set_refs(app, tracker, source, "addresses", [*current, target.number])

    else:
        if source.status in ("Rejected", SUPERSEDED):
            raise ToolError(f"Decision #{source.number} is {source.status}; it cannot supersede another")
        if target.status == SUPERSEDED:
            by = ", ".join(f"#{d.number}" for d in tracker.superseded_by(target.number)) or "another decision"
            raise ToolError(f"Decision #{target.number} is already Superseded, by {by}")
        if source in _superseded_chain(tracker, target):
            raise ToolError(f"#{target.number} supersedes #{source.number}; this would make a loop")
        current = source.doc.get("supersedes") or []
        await _set_refs(app, tracker, source, "supersedes", [*current, target.number])
        labels, state, reason = encode(app.vocabulary, DECISION, SUPERSEDED, target.issue.labels)
        tracker.put(await app.github.update_issue(target.number, labels=labels, state=state, state_reason=reason))
        await app.github.add_comment(target.number, f"{trail.SUPERSEDED_MARK} #{source.number}: {source.title}")
        note = f"\n#{target.number} is now Superseded (was {target.status})."

    text = f"Linked: #{source.number} {kind} #{target.number}{note}"
    return Result(text, {"source": source.number, "type": kind, "target": target.number})


def _superseded_chain(tracker: Tracker, decision: Record) -> list[Record]:
    """The decisions a decision supersedes, and the ones those supersede."""
    out: list[Record] = []
    stack = [decision]
    while stack:
        for older in tracker._known(stack.pop().doc.get("supersedes") or []):
            if older not in out:
                out.append(older)
                stack.append(older)
    return out


@tool(
    "unlink_records",
    "Remove a link made with link_records. Removing `supersedes` returns the older decision to Accepted.",
    _PROPERTIES,
    required=("source", "type", "target"),
    writes=True,
)
async def unlink_records(app: App, args: dict[str, Any]) -> Result:
    tracker = await app.tracker()
    source, target = _ends(tracker, args)
    kind = args["type"]
    missing = ToolError(f"There is no link #{source.number} {kind} #{target.number}")
    note = ""

    if kind == CHILD_OF:
        if source.issue.parent != target.number:
            raise missing
        await app.github.remove_sub_issue(target.number, source.number, source.issue.id)
        tracker.set_parent(source.number, None)
    elif kind == BLOCKED_BY:
        if target.number not in source.issue.blocked_by:
            raise missing
        await app.github.remove_blocked_by(source.number, target.number, target.issue.id)
        tracker.set_blocked_by(source.number, target.number, False)
    else:
        field = "addresses" if kind == ADDRESSES else "supersedes"
        current = source.doc.get(field) or []
        if target.number not in current:
            raise missing
        await _set_refs(app, tracker, source, field, [n for n in current if n != target.number])
        if kind == SUPERSEDES and target.status == SUPERSEDED and not tracker.superseded_by(target.number):
            labels, state, reason = encode(app.vocabulary, DECISION, "Accepted", target.issue.labels)
            tracker.put(await app.github.update_issue(target.number, labels=labels, state=state, state_reason=reason))
            await app.github.add_comment(target.number, f"No longer superseded by #{source.number}; Accepted again.")
            note = f"\n#{target.number} is Accepted again."

    text = f"Unlinked: #{source.number} {kind} #{target.number}{note}"
    return Result(text, {"source": source.number, "type": kind, "target": target.number})
