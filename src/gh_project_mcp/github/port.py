"""The GitHub operations the server needs, as an interface (ADR-0004).

Handlers and the tracker talk to this and nothing else. `HttpGitHub` implements it against the API and `FakeGitHub`
in memory, so tests cannot reach GitHub by construction. Signatures carry plain dataclasses, never GitHub's JSON.
"""

from dataclasses import dataclass, field
from typing import Protocol


class GitHubError(Exception):
    """GitHub, or the access layer in front of it, refused an operation."""

    def __init__(self, message: str, *, status: int | None = None, operation: str = ""):
        super().__init__(message)
        self.status = status
        self.operation = operation

    def __str__(self) -> str:
        where = f" ({self.operation})" if self.operation else ""
        code = f"GitHub {self.status}: " if self.status else ""
        return f"{code}{self.args[0]}{where}"


@dataclass
class Issue:
    number: int
    id: int  # the database ID, which the sub-issue and dependency endpoints take instead of the number
    title: str
    body: str = ""
    state: str = "open"
    state_reason: str | None = None
    labels: list[str] = field(default_factory=list)
    milestone: int | None = None
    assignees: list[str] = field(default_factory=list)
    parent: int | None = None
    sub_issues: list[int] = field(default_factory=list)
    blocked_by: list[int] = field(default_factory=list)
    url: str = ""
    author: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Comment:
    id: int
    body: str
    author: str = ""
    created_at: str = ""


@dataclass
class Milestone:
    number: int
    title: str
    description: str = ""
    state: str = "open"
    url: str = ""


@dataclass
class Event:
    """One entry of an issue's timeline."""

    kind: str  # labeled, closed, reopened, commented, sub_issue_added, ...
    actor: str = ""
    created_at: str = ""
    detail: str = ""


class _Unset:
    def __repr__(self) -> str:
        return "UNSET"


# "Leave it as it is", for a parameter where None means "clear it".
UNSET = _Unset()


class GitHub(Protocol):
    """One repository's issues, labels, milestones and links."""

    repo: str
    # GitHub's own clock at the last response, as an ISO timestamp; None before the first. The tracker anchors its
    # refresh cursor to it, never to the local clock.
    last_seen_at: str | None

    async def list_issues(self, since: str | None = None, labels: list[str] | None = None) -> list[Issue]:
        """Issues (not pull requests), open and closed.

        With `since`, those updated at or after it; with `labels`, those carrying at least one of them.
        """

    async def create_issue(
        self,
        title: str,
        body: str,
        labels: list[str],
        milestone: int | None = None,
        assignees: list[str] | None = None,
    ) -> Issue: ...

    async def update_issue(
        self,
        number: int,
        *,
        title: str | None = None,
        body: str | None = None,
        labels: list[str] | None = None,
        state: str | None = None,
        state_reason: str | None = None,
        milestone: int | None | _Unset = UNSET,
        assignees: list[str] | None = None,
    ) -> Issue:
        """Change the named parts in one request. `labels` replaces the whole set."""

    async def list_comments(self, number: int) -> list[Comment]: ...

    async def add_comment(self, number: int, body: str) -> Comment: ...

    async def list_events(self, number: int) -> list[Event]: ...

    async def add_sub_issue(self, parent: int, child: int, child_id: int) -> None: ...

    async def remove_sub_issue(self, parent: int, child: int, child_id: int) -> None: ...

    async def add_blocked_by(self, number: int, blocker: int, blocker_id: int) -> None: ...

    async def remove_blocked_by(self, number: int, blocker: int, blocker_id: int) -> None: ...

    async def list_milestones(self) -> list[Milestone]: ...

    async def create_milestone(self, title: str, description: str) -> Milestone: ...

    async def update_milestone(
        self, number: int, *, title: str | None = None, description: str | None = None, state: str | None = None
    ) -> Milestone: ...

    async def list_labels(self) -> list[str]: ...

    async def create_label(self, name: str, colour: str, description: str) -> None: ...
