"""The dashboard: what needs attention (REQ-0005-FUNC-00).

Every section is computed by the predicates in rules.py that the status tool and the query filters use, so the
dashboard cannot disagree with a refusal. It reads; it never writes, and it never repairs what it reports.
"""

from typing import Any

from .. import rules
from ..app import App
from ..kinds import RECORD_KINDS, REQUIREMENT, TASK
from ..registry import Result, tool
from ..status import STATUSES
from ..tracker import Tracker
from .common import brief, row
from .projects import project_progress
from .records import explain_empty_ready

_PLURAL = {"requirement": "Requirements", "task": "Tasks", "decision": "Decisions"}


def counts(tracker: Tracker) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for kind in RECORD_KINDS:
        records = tracker.records(kind)
        out[kind] = {s: n for s in STATUSES[kind] if (n := sum(1 for r in records if r.status == s))}
    return out


def blocked(tracker: Tracker) -> list[dict[str, Any]]:
    """Every Blocked task, with the reason it was given."""
    return [{**brief(t), "reason": t.doc.get("blocked_reason")} for t in tracker.records(TASK) if t.status == "Blocked"]


def waiting(tracker: Tracker) -> list[dict[str, Any]]:
    """Every open record that waits on unfinished work, with what it waits on."""
    out = []
    for record in tracker.records():
        unmet = rules.unmet_blockers(tracker, record)
        if unmet and not rules.is_settled(record):
            out.append({**brief(record), "waits_on": [b.number for b in unmet]})
    return out


@tool(
    "get_status",
    "The dashboard: counts by status, projects, tasks ready to start, blocked and waiting work with reasons, "
    "requirements whose work is done and await a decision, and drift (state on GitHub that breaks a rule).",
)
async def get_status(app: App, args: dict[str, Any]) -> Result:
    tracker = await app.tracker()
    lines = [f"Tracker: {app.github.repo}"]
    by_status = counts(tracker)
    if not tracker.records():
        lines.append(
            "No records yet: no issue carries a kind label "
            f"({', '.join(app.vocabulary.kind_labels)}). Start with create_requirement."
        )
    for kind in RECORD_KINDS:
        if by_status[kind]:
            total = sum(by_status[kind].values())
            parts = ", ".join(f"{status} {n}" for status, n in by_status[kind].items())
            lines.append(f"{_PLURAL[kind]} ({total}): {parts}")

    projects = [project_progress(tracker, m) for m in tracker.milestones.values() if m.state == "open"]
    if projects:
        lines.append("\nProjects:")
        lines += [
            f"- {p['number']} {p['title']}: requirements {p['requirements']}, "
            f"tasks {p['tasks_complete']}/{p['tasks']} complete"
            for p in projects
        ]

    ready = rules.ready_tasks(tracker)
    if ready:
        lines.append(f"\nReady to start ({len(ready)}):")
        lines += [f"- {row(t)}" for t in ready]
    elif tracker.records(TASK):
        lines.append("\n" + explain_empty_ready(tracker))

    stuck = blocked(tracker)
    if stuck:
        lines.append(f"\nBlocked ({len(stuck)}):")
        lines += [f"- {row(tracker.get(b['number']))}: {b['reason'] or 'no reason given'}" for b in stuck]

    held = waiting(tracker)
    if held:
        lines.append(f"\nWaiting on other work ({len(held)}):")
        for item in held:
            on = ", ".join(f"#{n} ({tracker.get(n).status})" for n in item["waits_on"])
            lines.append(f"- {row(tracker.get(item['number']))}: waits on {on}")

    complete = [r for r in tracker.records(REQUIREMENT) if rules.is_work_complete(tracker, r)]
    if complete:
        lines.append(f"\nWork complete, decision pending ({len(complete)}):")
        lines += [f"- {row(r)}: every task under it is finished; it is not yet Implemented" for r in complete]

    drifted = rules.drift(tracker)
    if drifted:
        lines.append(f"\nDrift ({len(drifted)}): state on GitHub that the lifecycle's rules would not produce")
        lines += [f"- #{record.number} {problem}" for record, problem in drifted]

    data = {
        "repo": app.github.repo,
        "counts": by_status,
        "projects": projects,
        "ready": [brief(t) for t in ready],
        "blocked": stuck,
        "waiting": held,
        "work_complete": [brief(r) for r in complete],
        "drift": [{"number": record.number, "problem": problem} for record, problem in drifted],
    }
    return Result("\n".join(lines), data)
