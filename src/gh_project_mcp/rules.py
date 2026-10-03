"""The lifecycle's rules, each defined once and used twice (ADR-0006).

The server holds its own writes to these rules: a status move follows the kind's transition map, never passes
through a stop status, and the always-on rules refuse in every mode. Anyone can still edit an issue on github.com,
so the same predicates run over the snapshot as drift checks, which report and never repair.

GH_PROJECT_RULES picks how the risky-but-legal moves are treated: `warn` (the default) says why a move was risky,
`enforce` refuses it, `off` checks nothing.
"""

import logging
import os
from collections import deque
from typing import Any

from .kinds import DECISION, REQUIREMENT, TASK
from .status import DONE, SETTLED, STATUSES, SUPERSEDED
from .tracker import Record, Tracker

logger = logging.getLogger(__name__)

RULES_ENV = "GH_PROJECT_RULES"
OFF, WARN, ENFORCE = "off", "warn", "enforce"
MODES = (OFF, WARN, ENFORCE)

TRANSITIONS: dict[str, dict[str, tuple[str, ...]]] = {
    REQUIREMENT: {
        "Draft": ("Under Review", "Deprecated"),
        "Under Review": ("Draft", "Approved", "Deprecated"),
        "Approved": ("Implemented", "Draft", "Deprecated"),
        "Implemented": ("Validated", "Approved", "Deprecated"),
        "Validated": ("Deprecated",),
        "Deprecated": ("Draft",),
    },
    # A task may move between any two statuses; the workflow rules say which moves are risky.
    TASK: {status: tuple(s for s in STATUSES[TASK] if s != status) for status in STATUSES[TASK]},
    DECISION: {
        "Proposed": ("Accepted", "Rejected"),
        "Accepted": ("Proposed",),
        "Rejected": ("Proposed",),
        SUPERSEDED: (),
    },
}

# A move may end at one of these but never pass through it on the way somewhere else. Approved and Validated are
# the owner's decisions. Deprecated is here so that retiring a requirement is never a step in reviving it: without
# it, Deprecated -> Draft would give every backward move a path.
STOP_STATUSES: dict[str, tuple[str, ...]] = {
    REQUIREMENT: ("Approved", "Validated", "Deprecated"),
    TASK: (),
    DECISION: (),
}

# A requirement has to be here before work on it starts.
WORKABLE = ("Approved", "Implemented")
# Where a requirement can be when its work is done and only the decision is missing.
BEFORE_IMPLEMENTED = ("Draft", "Under Review", "Approved")


class StatusRefused(Exception):
    """A status move, or a write, that the rules do not allow. Nothing has been written."""


def rules_mode() -> str:
    value = os.environ.get(RULES_ENV, "").strip().lower()
    if not value:
        return WARN
    if value in MODES:
        return value
    logger.warning("%s=%r is not one of %s; using %s", RULES_ENV, value, ", ".join(MODES), WARN)
    return WARN


def check(reasons: list[str], action: str) -> list[str]:
    """Apply the mode to the reasons an action is risky: the warnings to return, or a refusal."""
    mode = rules_mode()
    if mode == OFF or not reasons:
        return []
    if mode == ENFORCE:
        raise StatusRefused(f"Refused: {action}. " + " ".join(reasons) + f" ({RULES_ENV}=enforce)")
    return reasons


def _search(kind: str, start: str, goal: str, stops: tuple[str, ...]) -> list[str] | None:
    queue, seen = deque([[start]]), {start}
    while queue:
        path = queue.popleft()
        if path[-1] == goal:
            return path
        if path[-1] in stops and len(path) > 1:
            continue  # a stop status ends a path; it is never a step on one
        for step in TRANSITIONS[kind].get(path[-1], ()):
            if step not in seen:
                seen.add(step)
                queue.append([*path, step])
    return None


def path(kind: str, start: str, goal: str) -> list[str]:
    """The statuses a record passes through from start to goal, both included. Always on."""
    if goal not in STATUSES[kind]:
        raise StatusRefused(f"{goal!r} is not a {kind} status; a {kind} is one of {', '.join(STATUSES[kind])}")
    if start == goal:
        raise StatusRefused(f"already {goal}")
    if kind == DECISION and goal == SUPERSEDED:
        raise StatusRefused(
            "Superseded comes from a link, not a status move: link_records(source=<newer decision>, "
            "type='supersedes', target=<this one>)"
        )
    if kind == DECISION and start == SUPERSEDED:
        raise StatusRefused("it is Superseded; remove the supersedes link with unlink_records to bring it back")
    found = _search(kind, start, goal, STOP_STATUSES[kind])
    if found:
        return found
    through = _search(kind, start, goal, ())
    if through:
        stop = next(s for s in through[1:-1] if s in STOP_STATUSES[kind])
        raise StatusRefused(
            f"{start} to {goal} passes through {stop}, which is a decision of its own and is never made on the "
            f"way to something else. Move it to {stop} first"
        )
    raise StatusRefused(f"a {kind} cannot go from {start} to {goal}")


# -- predicates over the snapshot -------------------------------------------------------------------------------


def _names(records: list[Record]) -> str:
    return ", ".join(f"#{r.number} ({r.status})" for r in records)


def is_settled(record: Record) -> bool:
    return record.status in SETTLED[record.kind]


def is_done(record: Record) -> bool:
    return record.status in DONE[record.kind]


def unmet_blockers(tracker: Tracker, record: Record) -> list[Record]:
    """What a record waits on that has not finished."""
    return [b for b in tracker.blockers(record.number) if not is_done(b)]


def open_subtasks(tracker: Tracker, record: Record) -> list[Record]:
    return [c for c in tracker.children(record.number) if c.kind == TASK and not is_settled(c)]


def open_tasks(tracker: Tracker, requirement: Record) -> list[Record]:
    return [t for t in tracker.leaf_tasks(requirement.number) if not is_settled(t)]


def is_ready(tracker: Tracker, task: Record) -> bool:
    """Ready to start: not started, nothing it waits on is unfinished, and its requirement is approved."""
    if task.kind != TASK or task.status != "Not Started":
        return False
    if any(c.kind == TASK for c in tracker.children(task.number)) or unmet_blockers(tracker, task):
        return False
    requirement = tracker.requirement_of(task.number)
    return requirement is None or requirement.status in WORKABLE


def ready_tasks(tracker: Tracker) -> list[Record]:
    """Highest priority first; a task with no priority label sorts last."""
    ready = [t for t in tracker.records(TASK) if is_ready(tracker, t)]
    return sorted(ready, key=lambda t: (t.priority or "P9", t.number))


def is_work_complete(tracker: Tracker, requirement: Record) -> bool:
    """Every task under it is finished, and nobody has yet said the requirement is implemented."""
    if requirement.kind != REQUIREMENT or requirement.status not in BEFORE_IMPLEMENTED:
        return False
    tasks = tracker.leaf_tasks(requirement.number)
    return bool(tasks) and all(is_settled(t) for t in tasks) and any(is_done(t) for t in tasks)


def always_on(tracker: Tracker, record: Record, goal: str) -> None:
    """The rules no mode switches off, because they protect what the statuses mean."""
    if record.kind == REQUIREMENT and goal == "Validated":
        still_open = open_tasks(tracker, record)
        if still_open:
            raise StatusRefused(
                f"cannot be Validated while tasks under it are open: {_names(still_open)}. Complete or abandon "
                "them first"
            )


def move_reasons(tracker: Tracker, record: Record, goal: str) -> list[str]:
    """Why a legal status move is risky, for the mode to warn about or refuse."""
    reasons = []
    if record.kind == TASK:
        if goal in ("In Progress", "Complete"):
            waiting = unmet_blockers(tracker, record)
            abandoned = [b for b in waiting if b.status == "Abandoned"]
            unfinished = [b for b in waiting if b not in abandoned]
            if unfinished:
                reasons.append(f"It waits on work that is not finished: {_names(unfinished)}.")
            if abandoned:
                reasons.append(
                    f"It waits on abandoned work that will never finish: {_names(abandoned)}. Remove the link "
                    "with unlink_records, or abandon this task too."
                )
            requirement = tracker.requirement_of(record.number)
            if requirement is not None and requirement.status not in (*WORKABLE, "Validated"):
                reasons.append(f"Its requirement #{requirement.number} is {requirement.status}, not Approved.")
        if goal == "Complete":
            subtasks = open_subtasks(tracker, record)
            if subtasks:
                reasons.append(f"It has open subtasks: {_names(subtasks)}.")
            if record.status == "Not Started":
                reasons.append("It was never started.")
            if record.status == "Blocked":
                reasons.append("It is still Blocked.")
        if record.status == "Complete":
            reasons.append("It was Complete: this reopens finished work.")
    if record.kind == REQUIREMENT and goal == "Implemented":
        still_open = open_tasks(tracker, record)
        if still_open:
            reasons.append(f"Tasks under it are still open: {_names(still_open)}.")
    return reasons


def new_task_reasons(parent_requirement: Record | None) -> list[str]:
    if parent_requirement is not None and parent_requirement.status not in WORKABLE:
        return [
            f"Requirement #{parent_requirement.number} is {parent_requirement.status}: work is being planned "
            "against a requirement nobody has approved."
        ]
    return []


def thin_reasons(kind: str, fields: dict[str, Any], priority: str | None) -> list[str]:
    """Which fields a new record of its kind usually needs and lacks."""
    reasons = []
    if kind == REQUIREMENT:
        if not fields.get("acceptance_criteria"):
            reasons.append("No acceptance_criteria: every requirement needs them to be checkable later.")
        if fields.get("type") == "NFUNC" and not fields.get("validation_metrics"):
            reasons.append("No validation_metrics: an NFUNC requirement needs the number that settles it.")
    elif kind == TASK and priority in ("P0", "P1") and not fields.get("test_plan"):
        reasons.append(f"No test_plan: a {priority} task needs one to show when it is done.")
    return reasons


def drift(tracker: Tracker) -> list[tuple[Record, str]]:
    """Records whose state on GitHub the server's own rules would not have produced. Reported, never repaired."""
    found: list[tuple[Record, str]] = []
    for record in tracker.records():
        found += [(record, problem) for problem in record.problems]
        if record.issue.body.strip() and not record.doc.recognised:
            # Someone wrote this issue by hand. An empty body is merely thin, and the server can produce one.
            found.append((record, "its body holds no fields the server recognises"))
        if record.kind == REQUIREMENT and record.status == "Validated":
            still_open = open_tasks(tracker, record)
            if still_open:
                found.append((record, f"is Validated while tasks under it are open: {_names(still_open)}"))
        if record.kind == TASK:
            requirement = tracker.requirement_of(record.number)
            if requirement is None and not is_settled(record):
                found.append((record, "implements no requirement: it is not a sub-issue of one"))
            elif (
                requirement is not None
                and record.status == "In Progress"
                and requirement.status not in (*WORKABLE, "Validated")  # Validated with open work is reported above
            ):
                found.append(
                    (record, f"is In Progress under requirement #{requirement.number}, which is {requirement.status}")
                )
        if record.kind == DECISION:
            successors = [s for s in tracker.superseded_by(record.number) if s.status != "Rejected"]
            if record.status == SUPERSEDED and not successors:
                found.append((record, "is Superseded but no decision names it in a Supersedes section"))
            if record.status != SUPERSEDED and successors:
                found.append((record, f"is {record.status} though {_names(successors)} supersedes it"))
    return found
