"""What the tools share: reading IDs, naming records, finding projects."""

import re
from typing import Any

from ..github.port import Milestone
from ..registry import ToolError
from ..tracker import Record, Tracker

_ID = re.compile(r"#?(\d+)")


def parse_id(value: Any) -> int:
    """An issue number from 12, "12" or "#12"."""
    match = _ID.fullmatch(str(value).strip())
    if isinstance(value, bool) or not match:
        raise ToolError(f'{value!r} is not an issue number; pass 12 or "#12"')
    return int(match.group(1))


def parse_ids(value: Any) -> list[int]:
    """One ID or a list of them, without repeats."""
    values = value if isinstance(value, list) else [value]
    if not values:
        raise ToolError("no IDs were given")
    return list(dict.fromkeys(parse_id(v) for v in values))


def row(record: Record) -> str:
    """One record on one line."""
    details = ", ".join(part for part in (record.status, record.priority) if part)
    return f"#{record.number} {record.title} [{details}]"


def brief(record: Record) -> dict[str, Any]:
    """One record as data, without its fields."""
    out = {"number": record.number, "kind": record.kind, "title": record.title, "status": record.status}
    if record.priority:
        out["priority"] = record.priority
    return out


def rows(records: list[Record], indent: str = "") -> str:
    return "\n".join(f"{indent}- {row(r)}" for r in records)


def resolve_project(tracker: Tracker, reference: Any) -> Milestone:
    """A project by milestone number or exact title, or a refusal listing the ones there are."""
    milestone = tracker.find_project(reference)
    if milestone is None:
        known = ", ".join(f"{m.number} ({m.title})" for m in tracker.milestones.values()) or "none"
        raise ToolError(f"No project {reference!r}. Projects are milestones, named by number or title: {known}")
    return milestone


def project_name(tracker: Tracker, record: Record) -> str | None:
    milestone = tracker.milestones.get(record.issue.milestone) if record.issue.milestone else None
    return milestone.title if milestone else None


def expect_kind(record: Record, *kinds: str, role: str) -> None:
    if record.kind not in kinds:
        raise ToolError(f"{role} must be a {' or '.join(kinds)}; #{record.number} is a {record.kind}")
