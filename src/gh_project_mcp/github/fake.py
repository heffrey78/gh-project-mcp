"""GitHub in memory (ADR-0004): what the test suite talks to instead of the network.

It refuses what GitHub refuses for the operations the server uses (a second parent, a missing issue, a link to
itself), counts requests so the request budget can be asserted, and keeps a log of writes so a test can show that
a refused call or a read changed nothing. `behind_the_back` edits an issue the way a person on github.com would:
without the server knowing.
"""

import copy
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from .port import UNSET, Comment, Event, GitHubError, Issue, Milestone

PAGE_SIZE = 100
MAX_SUB_ISSUES = 100


class FakeGitHub:
    def __init__(self, repo: str = "octo/sandbox"):
        self.repo = repo
        self.issues: dict[int, Issue] = {}
        self.comments: dict[int, list[Comment]] = {}
        self.events: dict[int, list[Event]] = {}
        self.milestones: dict[int, Milestone] = {}
        self.labels: dict[str, tuple[str, str]] = {}
        self.requests = 0
        self.writes: list[tuple[str, Any]] = []
        self.user = "octocat"
        self._clock = datetime(2026, 1, 1, tzinfo=UTC)
        self.last_seen_at: str | None = None
        self._next_comment = 1

    # -- test helpers -------------------------------------------------------------------------------------------

    def _now(self) -> str:
        self._clock += timedelta(seconds=1)
        return self._clock.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _url(self, kind: str, number: int) -> str:
        return f"https://github.com/{self.repo}/{kind}/{number}"

    def _event(self, number: int, kind: str, detail: str = "", actor: str | None = None) -> None:
        self.events.setdefault(number, []).append(Event(kind, actor or self.user, self._now(), detail))

    def behind_the_back(self, number: int, actor: str = "a-person", **changes: Any) -> None:
        """Change an issue as someone on github.com would. No request is counted and no write is logged."""
        issue = self.issues[number]
        for name, value in changes.items():
            if name == "parent":
                if issue.parent is not None:
                    self.issues[issue.parent].sub_issues.remove(number)
                if value is not None:
                    self.issues[value].sub_issues.append(number)
            setattr(issue, name, value)
        if changes.get("state") == "closed" and "state_reason" not in changes:
            issue.state_reason = "completed"
        if set(changes) - {"parent", "blocked_by"}:
            issue.updated_at = self._now()  # a link change alone leaves updated_at alone, as on GitHub
        else:
            self._now()
        self._event(number, "edited_on_github", ", ".join(sorted(changes)), actor)

    def reset_counters(self) -> None:
        self.requests = 0
        self.writes = []

    # -- internals ----------------------------------------------------------------------------------------------

    def _read(self, pages: int = 1) -> None:
        self.requests += pages
        self.last_seen_at = self._clock.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _write(self, operation: str, detail: Any) -> None:
        self.requests += 1
        self.writes.append((operation, detail))
        self.last_seen_at = self._clock.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _issue(self, number: int, operation: str) -> Issue:
        if number not in self.issues:
            raise GitHubError("Not Found", status=404, operation=f"{operation} #{number}")
        return self.issues[number]

    def _use_labels(self, labels: list[str]) -> None:
        # GitHub creates a label named on an issue when the repository does not have it yet.
        for label in labels:
            self.labels.setdefault(label, ("ededed", ""))

    def _check_milestone(self, milestone: int | None, operation: str) -> None:
        if milestone is not None and milestone not in self.milestones:
            raise GitHubError("Validation Failed: milestone does not exist", status=422, operation=operation)

    # -- issues -------------------------------------------------------------------------------------------------

    async def list_issues(self, since: str | None = None, labels: list[str] | None = None) -> list[Issue]:
        found = [i for i in self.issues.values() if since is None or i.updated_at >= since]
        if labels is not None:
            found = [i for i in found if set(i.labels) & set(labels)]
        self._read(max(1, math.ceil(len(found) / PAGE_SIZE)))
        return copy.deepcopy(sorted(found, key=lambda i: i.number))

    async def list_changes(self, since: str, labels: list[str]) -> list[Issue]:
        open_records = [i for i in self.issues.values() if i.state == "open" and set(i.labels) & set(labels)]
        changed = [i for i in self.issues.values() if i.updated_at >= since]
        self._read(max(1, math.ceil(len(open_records) / PAGE_SIZE), math.ceil(len(changed) / PAGE_SIZE)))
        found = {i.number: i for i in [*open_records, *changed]}
        return copy.deepcopy(sorted(found.values(), key=lambda i: i.number))

    async def create_issue(
        self,
        title: str,
        body: str,
        labels: list[str],
        milestone: int | None = None,
        assignees: list[str] | None = None,
    ) -> Issue:
        self._check_milestone(milestone, "create issue")
        if not title.strip():
            raise GitHubError("Validation Failed: title can't be blank", status=422, operation="create issue")
        number = max(self.issues, default=0) + 1
        now = self._now()
        issue = Issue(
            number=number,
            id=1000 + number,
            title=title,
            body=body,
            labels=list(labels),
            milestone=milestone,
            assignees=list(assignees or []),
            url=self._url("issues", number),
            author=self.user,
            created_at=now,
            updated_at=now,
        )
        self._use_labels(labels)
        self.issues[number] = issue
        self._write("create_issue", number)
        self._event(number, "created")
        return copy.deepcopy(issue)

    async def update_issue(
        self,
        number: int,
        *,
        title: str | None = None,
        body: str | None = None,
        labels: list[str] | None = None,
        state: str | None = None,
        state_reason: str | None = None,
        milestone: Any = UNSET,
        assignees: list[str] | None = None,
    ) -> Issue:
        issue = self._issue(number, "update issue")
        if milestone is not UNSET:
            self._check_milestone(milestone, f"update issue #{number}")
        changed = []
        if title is not None and title != issue.title:
            issue.title = title
            changed.append("title")
            self._event(number, "renamed", title)
        if body is not None and body != issue.body:
            issue.body = body
            changed.append("body")
            self._event(number, "body_edited")
        if labels is not None and sorted(labels) != sorted(issue.labels):
            for label in labels:
                if label not in issue.labels:
                    self._event(number, "labeled", label)
            for label in issue.labels:
                if label not in labels:
                    self._event(number, "unlabeled", label)
            self._use_labels(labels)
            issue.labels = list(labels)
            changed.append("labels")
        if state is not None and state != issue.state:
            issue.state = state
            issue.state_reason = (state_reason or "completed") if state == "closed" else "reopened"
            changed.append("state")
            self._event(number, "closed" if state == "closed" else "reopened", issue.state_reason)
        elif state == "closed" and state_reason and state_reason != issue.state_reason:
            issue.state_reason = state_reason
            changed.append("state_reason")
            self._event(number, "closed", state_reason)
        if milestone is not UNSET and milestone != issue.milestone:
            issue.milestone = milestone
            changed.append("milestone")
            self._event(number, "milestoned" if milestone else "demilestoned", str(milestone or ""))
        if assignees is not None and assignees != issue.assignees:
            issue.assignees = list(assignees)
            changed.append("assignees")
            self._event(number, "assigned", ", ".join(assignees))
        issue.updated_at = self._now()
        self._write("update_issue", (number, tuple(changed)))
        return copy.deepcopy(issue)

    # -- comments and timeline ----------------------------------------------------------------------------------

    async def list_comments(self, number: int) -> list[Comment]:
        self._issue(number, "list comments")
        self._read()
        return copy.deepcopy(self.comments.get(number, []))

    async def add_comment(self, number: int, body: str) -> Comment:
        issue = self._issue(number, "comment")
        comment = Comment(self._next_comment, body, self.user, self._now())
        self._next_comment += 1
        self.comments.setdefault(number, []).append(comment)
        issue.updated_at = comment.created_at
        self._write("add_comment", number)
        self._event(number, "commented", body.splitlines()[0] if body else "")
        return copy.deepcopy(comment)

    async def list_events(self, number: int) -> list[Event]:
        self._issue(number, "list events")
        self._read()
        return copy.deepcopy(self.events.get(number, []))

    # -- links --------------------------------------------------------------------------------------------------

    def _ancestors(self, number: int) -> list[int]:
        out = []
        current = self.issues[number].parent
        while current is not None:
            out.append(current)
            current = self.issues[current].parent
        return out

    async def add_sub_issue(self, parent: int, child: int, child_id: int) -> None:
        operation = f"add sub-issue #{child} to #{parent}"
        parent_issue, child_issue = self._issue(parent, operation), self._issue(child, operation)
        if child_issue.id != child_id:
            raise GitHubError("The sub-issue ID does not match an issue", status=404, operation=operation)
        if parent == child or child in self._ancestors(parent):
            raise GitHubError(
                "Validation Failed: a sub-issue cannot be its own ancestor", status=422, operation=operation
            )
        if child_issue.parent is not None:
            raise GitHubError("Validation Failed: Sub issue may only have one parent", status=422, operation=operation)
        if len(parent_issue.sub_issues) >= MAX_SUB_ISSUES:
            raise GitHubError("Validation Failed: too many sub-issues", status=422, operation=operation)
        child_issue.parent = parent
        parent_issue.sub_issues.append(child)
        self._now()  # GitHub does not bump updated_at for a link change (seen 2026-10-03)
        self._write("add_sub_issue", (parent, child))
        self._event(parent, "sub_issue_added", f"#{child}")
        self._event(child, "parent_issue_added", f"#{parent}")

    async def remove_sub_issue(self, parent: int, child: int, child_id: int) -> None:
        operation = f"remove sub-issue #{child} from #{parent}"
        parent_issue, child_issue = self._issue(parent, operation), self._issue(child, operation)
        if child_issue.parent != parent:
            raise GitHubError("Not Found", status=404, operation=operation)
        child_issue.parent = None
        parent_issue.sub_issues.remove(child)
        self._now()  # GitHub does not bump updated_at for a link change (seen 2026-10-03)
        self._write("remove_sub_issue", (parent, child))
        self._event(parent, "sub_issue_removed", f"#{child}")
        self._event(child, "parent_issue_removed", f"#{parent}")

    async def add_blocked_by(self, number: int, blocker: int, blocker_id: int) -> None:
        operation = f"mark #{number} blocked by #{blocker}"
        issue, blocking = self._issue(number, operation), self._issue(blocker, operation)
        if blocking.id != blocker_id:
            raise GitHubError("The blocking issue ID does not match an issue", status=404, operation=operation)
        if number == blocker:
            raise GitHubError("Validation Failed: an issue cannot block itself", status=422, operation=operation)
        if blocker in issue.blocked_by:
            raise GitHubError("Validation Failed: the dependency already exists", status=422, operation=operation)
        issue.blocked_by.append(blocker)
        self._now()  # GitHub does not bump updated_at for a link change (seen 2026-10-03)
        self._write("add_blocked_by", (number, blocker))
        self._event(number, "blocked_by_added", f"#{blocker}")
        self._event(blocker, "blocking_added", f"#{number}")

    async def remove_blocked_by(self, number: int, blocker: int, blocker_id: int) -> None:
        operation = f"unmark #{number} blocked by #{blocker}"
        issue = self._issue(number, operation)
        self._issue(blocker, operation)
        if blocker not in issue.blocked_by:
            raise GitHubError("Not Found", status=404, operation=operation)
        issue.blocked_by.remove(blocker)
        self._now()  # GitHub does not bump updated_at for a link change (seen 2026-10-03)
        self._write("remove_blocked_by", (number, blocker))
        self._event(number, "blocked_by_removed", f"#{blocker}")
        self._event(blocker, "blocking_removed", f"#{number}")

    # -- milestones and labels ----------------------------------------------------------------------------------

    async def list_milestones(self) -> list[Milestone]:
        self._read()
        return copy.deepcopy(sorted(self.milestones.values(), key=lambda m: m.number))

    async def create_milestone(self, title: str, description: str) -> Milestone:
        if any(m.title == title for m in self.milestones.values()):
            raise GitHubError(
                "Validation Failed: a milestone with this title exists", status=422, operation="create milestone"
            )
        number = max(self.milestones, default=0) + 1
        milestone = Milestone(number, title, description, "open", self._url("milestone", number))
        self.milestones[number] = milestone
        self._write("create_milestone", number)
        return copy.deepcopy(milestone)

    async def update_milestone(
        self, number: int, *, title: str | None = None, description: str | None = None, state: str | None = None
    ) -> Milestone:
        if number not in self.milestones:
            raise GitHubError("Not Found", status=404, operation=f"update milestone {number}")
        milestone = self.milestones[number]
        if title is not None:
            milestone.title = title
        if description is not None:
            milestone.description = description
        if state is not None:
            milestone.state = state
        self._write("update_milestone", number)
        return copy.deepcopy(milestone)

    async def list_labels(self) -> list[str]:
        self._read()
        return sorted(self.labels)

    async def create_label(self, name: str, colour: str, description: str) -> None:
        if name in self.labels:
            raise GitHubError("Validation Failed: label already exists", status=422, operation=f"create label {name}")
        self.labels[name] = (colour, description)
        self._write("create_label", name)
