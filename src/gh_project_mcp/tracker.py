"""The tracker as the server sees it: every lifecycle issue, in memory, with its links (ADR-0001).

This is a read cache and nothing more. GitHub is the store; the snapshot is filled by one paginated listing,
brought up to date before each tool call by asking for the issues updated since the last one, and updated in place
by the server's own writes so they are visible without another request.
"""

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from functools import cached_property

from .body import Document
from .github.port import GitHub, Issue, Milestone
from .kinds import DECISION, REQUIREMENT, TASK
from .status import Derived, Vocabulary, derive

# How far before the cold listing's answer the first refresh looks. It has to cover the listing's own duration;
# fetching a few issues twice costs nothing.
COLD_LOAD_MARGIN = timedelta(minutes=2)
_TIMESTAMP = "%Y-%m-%dT%H:%M:%SZ"


def _earlier(timestamp: str | None, by: timedelta) -> str | None:
    if not timestamp:
        return None
    return (datetime.strptime(timestamp, _TIMESTAMP).replace(tzinfo=UTC) - by).strftime(_TIMESTAMP)


class NotARecord(LookupError):
    """The number does not name a lifecycle record in this repository."""


class Record:
    """One issue read as a requirement, decision or task."""

    def __init__(self, issue: Issue, derived: Derived):
        self.issue = issue
        self.kind = derived.kind
        self.status = derived.status
        self.priority = derived.priority
        self.problems = derived.problems

    number = property(lambda self: self.issue.number)
    title = property(lambda self: self.issue.title)
    url = property(lambda self: self.issue.url)

    @cached_property
    def doc(self) -> Document:
        return Document(self.issue.body, self.kind)

    def __repr__(self) -> str:
        return f"<{self.kind} #{self.number} {self.status}>"


class Tracker:
    def __init__(self, github: GitHub, vocabulary: Vocabulary):
        self.github = github
        self.vocabulary = vocabulary
        self.milestones: dict[int, Milestone] = {}
        self._records: dict[int, Record] = {}
        self._cursor: str | None = None
        self._loaded = False
        self._labels_ready = False

    # -- keeping current ----------------------------------------------------------------------------------------

    async def refresh(self) -> None:
        """Bring the snapshot up to date: every record the first time, then only what changed since.

        The first listing asks for the issues carrying a kind label, so a repository's other issues cost nothing.
        A refresh asks for every issue updated since, labelled or not: that is how a record whose kind label
        someone removed is noticed and dropped.
        """
        cold = not (self._loaded and self._cursor is not None)
        if cold:
            issues = await self.github.list_issues(labels=self.vocabulary.kind_labels)
        else:
            issues = await self.github.list_issues(since=self._cursor)
        for issue in issues:
            self._store(issue)
            if self._cursor is None or issue.updated_at > self._cursor:
                self._cursor = issue.updated_at
        if cold:
            # The newest record may be months old in a repository that is busy with other issues, and a refresh
            # from there would fetch every one of them once. Start from when the listing was answered instead, by
            # GitHub's clock, less a margin for the time the listing took.
            answered = _earlier(self.github.last_seen_at, COLD_LOAD_MARGIN)
            self._cursor = max(filter(None, [self._cursor, answered]), default=None)
        known = set(self.milestones)
        if not self._loaded or any(i.milestone is not None and i.milestone not in known for i in issues):
            await self.refresh_milestones()
        self._loaded = True

    async def refresh_milestones(self) -> None:
        self.milestones = {m.number: m for m in await self.github.list_milestones()}

    def _store(self, issue: Issue) -> Record | None:
        derived = derive(self.vocabulary, issue.labels, issue.state, issue.state_reason)
        if derived is None:
            # Not a record, or no longer one: someone removed its kind label.
            self._records.pop(issue.number, None)
            return None
        record = Record(issue, derived)
        self._records[issue.number] = record
        return record

    def put(self, issue: Issue) -> Record:
        """Fold in an issue the server just wrote.

        A write's response does not carry the issue's links, so those are kept from the snapshot.
        """
        known = self._records.get(issue.number)
        if known is not None:
            issue.parent, issue.sub_issues, issue.blocked_by = (
                known.issue.parent,
                known.issue.sub_issues,
                known.issue.blocked_by,
            )
        record = self._store(issue)
        if record is None:
            raise NotARecord(f"#{issue.number} carries no kind label")
        return record

    def set_parent(self, child: int, parent: int | None) -> None:
        """Record a sub-issue link the server just made or removed."""
        self._records[child].issue.parent = parent

    def set_blocked_by(self, number: int, blocker: int, blocked: bool) -> None:
        """Record a dependency the server just made or removed."""
        blockers = self._records[number].issue.blocked_by
        if blocked and blocker not in blockers:
            blockers.append(blocker)
        elif not blocked and blocker in blockers:
            blockers.remove(blocker)

    def put_milestone(self, milestone: Milestone) -> None:
        self.milestones[milestone.number] = milestone

    async def ensure_labels(self) -> list[str]:
        """Create the labels the server uses that the repository lacks; returns the ones it created.

        GitHub would create a missing label on first use, but grey and undescribed. Checked once per process.
        """
        if self._labels_ready:
            return []
        existing = set(await self.github.list_labels())
        created = []
        for definition in self.vocabulary.definitions():
            if definition.name not in existing:
                await self.github.create_label(definition.name, definition.colour, definition.description)
                created.append(definition.name)
        self._labels_ready = True
        return created

    # -- reading ------------------------------------------------------------------------------------------------

    def get(self, number: int) -> Record:
        try:
            return self._records[number]
        except KeyError:
            raise NotARecord(
                f"#{number} is not a lifecycle record in {self.github.repo}: no issue with that number carries a "
                f"kind label ({', '.join(self.vocabulary.kind_labels)})"
            ) from None

    def find(self, number: int) -> Record | None:
        return self._records.get(number)

    def records(self, kind: str | None = None) -> list[Record]:
        return [r for _, r in sorted(self._records.items()) if kind is None or r.kind == kind]

    def _known(self, numbers: Iterable[int]) -> list[Record]:
        # A link can point at an issue that is not a record; it has no status the rules could read.
        return [self._records[n] for n in numbers if n in self._records]

    def children(self, number: int) -> list[Record]:
        """A record's sub-issues that are records, in GitHub's order where the snapshot knows it.

        The child's own `parent` decides membership, not the parent's list: a link changed on github.com is seen
        as soon as either end is refreshed, and the two ends can never disagree here.
        """
        order = {n: i for i, n in enumerate(self.get(number).issue.sub_issues)}
        found = [r for r in self._records.values() if r.issue.parent == number]
        return sorted(found, key=lambda r: (order.get(r.number, len(order)), r.number))

    def parent(self, number: int) -> Record | None:
        parent = self.get(number).issue.parent
        return self._records.get(parent) if parent is not None else None

    def ancestors(self, number: int) -> list[Record]:
        out: list[Record] = []
        current = self.parent(number)
        while current is not None and current not in out:
            out.append(current)
            current = self.parent(current.number)
        return out

    def requirement_of(self, number: int) -> Record | None:
        """The requirement a task implements: the nearest requirement above it."""
        return next((r for r in self.ancestors(number) if r.kind == REQUIREMENT), None)

    def descendants(self, number: int) -> list[Record]:
        out: list[Record] = []
        stack = list(reversed(self.children(number)))
        while stack:
            record = stack.pop()
            if record not in out:
                out.append(record)
                stack.extend(reversed(self.children(record.number)))
        return out

    def leaf_tasks(self, number: int) -> list[Record]:
        """The tasks under a record that have no tasks of their own: a parent is counted through its subtasks."""
        tasks = [r for r in self.descendants(number) if r.kind == TASK]
        return [t for t in tasks if not any(c.kind == TASK for c in self.children(t.number))]

    def blockers(self, number: int) -> list[Record]:
        return self._known(self.get(number).issue.blocked_by)

    def blocking(self, number: int) -> list[Record]:
        return [r for r in self.records() if number in r.issue.blocked_by]

    def decisions_addressing(self, number: int) -> list[Record]:
        return [r for r in self.records(DECISION) if number in (r.doc.get("addresses") or [])]

    def superseded_by(self, number: int) -> list[Record]:
        """The decisions that name this one in their Supersedes section."""
        return [r for r in self.records(DECISION) if number in (r.doc.get("supersedes") or [])]

    def in_project(self, milestone: int) -> list[Record]:
        return [r for r in self.records() if r.issue.milestone == milestone]

    def find_project(self, reference: int | str) -> Milestone | None:
        """A project by milestone number or exact title."""
        text = str(reference).strip()
        if text.isdigit() and int(text) in self.milestones:
            return self.milestones[int(text)]
        return next((m for m in self.milestones.values() if m.title.lower() == text.lower()), None)
