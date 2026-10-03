"""What an issue's labels and state mean, and the labels and state that mean a status (ADR-0002).

Status is stored once. A closed issue's status is its close reason; an open issue's status is its one status label,
or the kind's first status when it has none. Nothing outside this module reads a label name or a close reason.
"""

from dataclasses import dataclass, field

from .kinds import DECISION, PRIORITIES, RECORD_KINDS, REQUIREMENT, TASK

OPEN, CLOSED = "open", "closed"
COMPLETED, NOT_PLANNED = "completed", "not_planned"

# Every status of a kind, in lifecycle order.
STATUSES: dict[str, tuple[str, ...]] = {
    REQUIREMENT: ("Draft", "Under Review", "Approved", "Implemented", "Validated", "Deprecated"),
    TASK: ("Not Started", "In Progress", "Blocked", "Complete", "Abandoned"),
    DECISION: ("Proposed", "Accepted", "Rejected", "Superseded"),
}
FIRST_STATUS = {kind: statuses[0] for kind, statuses in STATUSES.items()}

# The open statuses that need a label; an open issue with none is at the kind's first status.
_OPEN_SLUGS: dict[str, dict[str, str]] = {
    REQUIREMENT: {"Under Review": "under-review", "Approved": "approved", "Implemented": "implemented"},
    TASK: {"In Progress": "in-progress", "Blocked": "blocked"},
    DECISION: {},
}
# What closing means: (closed as completed, closed as not planned).
_CLOSED: dict[str, tuple[str, str]] = {
    REQUIREMENT: ("Validated", "Deprecated"),
    TASK: ("Complete", "Abandoned"),
    DECISION: ("Accepted", "Rejected"),
}
SUPERSEDED = "Superseded"
_SUPERSEDED_SLUG = "superseded"
_ALL_SLUGS = (*(slug for slugs in _OPEN_SLUGS.values() for slug in slugs.values()), _SUPERSEDED_SLUG)

# Finished one way or the other: nothing more will happen to it.
SETTLED = {TASK: ("Complete", "Abandoned"), REQUIREMENT: ("Validated", "Deprecated"), DECISION: STATUSES[DECISION][1:]}
# Finished in the way that lets what waits on it go ahead.
DONE = {TASK: ("Complete",), REQUIREMENT: ("Implemented", "Validated"), DECISION: ("Accepted",)}

_COLOURS = {
    REQUIREMENT: "1d76db",
    DECISION: "5319e7",
    TASK: "0e8a16",
    "P0": "b60205",
    "P1": "d93f0b",
    "P2": "fbca04",
    "P3": "c5def5",
    "status": "bfd4f2",
}


@dataclass(frozen=True)
class LabelDefinition:
    name: str
    colour: str
    description: str


@dataclass(frozen=True)
class Vocabulary:
    """The label names this server uses, behind an optional prefix so they cannot collide with a repository's own."""

    prefix: str = ""

    def kind_label(self, kind: str) -> str:
        return f"{self.prefix}{kind}"

    def priority_label(self, priority: str) -> str:
        return f"{self.prefix}{priority}"

    def status_label(self, slug: str) -> str:
        return f"{self.prefix}status:{slug}"

    @property
    def kind_labels(self) -> list[str]:
        return [self.kind_label(kind) for kind in RECORD_KINDS]

    def kinds_in(self, labels: list[str]) -> list[str]:
        return [kind for kind in RECORD_KINDS if self.kind_label(kind) in labels]

    def priority_in(self, labels: list[str]) -> str | None:
        return next((p for p in PRIORITIES if self.priority_label(p) in labels), None)

    def _status_slugs_in(self, labels: list[str]) -> list[str]:
        """The status labels on an issue that are this server's, as slugs.

        A repository may have `status:` labels of its own. They are not ours to read or to remove.
        """
        mine = {self.status_label(slug): slug for slug in _ALL_SLUGS}
        return [mine[label] for label in labels if label in mine]

    def without_status(self, labels: list[str]) -> list[str]:
        mine = {self.status_label(slug) for slug in _ALL_SLUGS}
        return [label for label in labels if label not in mine]

    def without_priority(self, labels: list[str]) -> list[str]:
        priorities = {self.priority_label(p) for p in PRIORITIES}
        return [label for label in labels if label not in priorities]

    def definitions(self) -> list[LabelDefinition]:
        """Every label the server may apply, for setup_repository."""
        out = [
            LabelDefinition(self.kind_label(REQUIREMENT), _COLOURS[REQUIREMENT], "Lifecycle: a requirement"),
            LabelDefinition(self.kind_label(DECISION), _COLOURS[DECISION], "Lifecycle: an architecture decision"),
            LabelDefinition(self.kind_label(TASK), _COLOURS[TASK], "Lifecycle: an implementation task"),
        ]
        out += [LabelDefinition(self.priority_label(p), _COLOURS[p], f"Priority {p[1]}") for p in PRIORITIES]
        for kind in RECORD_KINDS:
            for status, slug in _OPEN_SLUGS[kind].items():
                out.append(LabelDefinition(self.status_label(slug), _COLOURS["status"], f"{kind.title()}: {status}"))
        out.append(
            LabelDefinition(self.status_label(_SUPERSEDED_SLUG), _COLOURS["status"], "Decision: replaced by a newer")
        )
        return out


@dataclass
class Derived:
    kind: str
    status: str
    priority: str | None
    problems: list[str] = field(default_factory=list)  # what about the labels and state breaks the conventions


def derive(vocabulary: Vocabulary, labels: list[str], state: str, state_reason: str | None) -> Derived | None:
    """The kind, status and priority an issue's labels and state mean, or None when it is not a record."""
    kinds = vocabulary.kinds_in(labels)
    if not kinds:
        return None
    kind = kinds[0]
    problems = []
    if len(kinds) > 1:
        problems.append(f"has {len(kinds)} kind labels ({', '.join(kinds)}); read as a {kind}")

    slugs = vocabulary._status_slugs_in(labels)
    by_slug = {slug: status for status, slug in _OPEN_SLUGS[kind].items()}
    superseded = kind == DECISION and _SUPERSEDED_SLUG in slugs
    foreign = [s for s in slugs if s not in by_slug and not (kind == DECISION and s == _SUPERSEDED_SLUG)]
    if foreign:
        names = ", ".join(vocabulary.status_label(s) for s in foreign)
        problems.append(f"carries {names}, which is not a {kind} status")

    if state == CLOSED:
        completed, retired = _CLOSED[kind]
        status = SUPERSEDED if superseded else (retired if state_reason in (NOT_PLANNED, "duplicate") else completed)
    else:
        if superseded:
            problems.append("is open but labelled superseded; a superseded decision is closed")
        mine = [by_slug[s] for s in slugs if s in by_slug]
        if len(mine) > 1:
            # Read as the furthest along, and say so: the labels alone cannot tell which was meant.
            mine.sort(key=STATUSES[kind].index)
            problems.append(f"has {len(mine)} status labels ({', '.join(mine)}); read as {mine[-1]}")
        status = mine[-1] if mine else FIRST_STATUS[kind]
    return Derived(kind, status, vocabulary.priority_in(labels), problems)


def encode(vocabulary: Vocabulary, kind: str, status: str, labels: list[str]) -> tuple[list[str], str, str | None]:
    """The labels, state and close reason that put a record at a status, keeping its other labels."""
    if status not in STATUSES[kind]:
        raise ValueError(f"{status!r} is not a {kind} status; a {kind} is one of {', '.join(STATUSES[kind])}")
    kept = vocabulary.without_status(labels)
    completed, retired = _CLOSED[kind]
    if status == SUPERSEDED:
        return kept + [vocabulary.status_label(_SUPERSEDED_SLUG)], CLOSED, NOT_PLANNED
    if status == completed:
        return kept, CLOSED, COMPLETED
    if status == retired:
        return kept, CLOSED, NOT_PLANNED
    slug = _OPEN_SLUGS[kind].get(status)
    return kept + ([vocabulary.status_label(slug)] if slug else []), OPEN, None
