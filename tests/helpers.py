"""Build a tracker straight into FakeGitHub, as if the issues had always been there."""

from gh_project_mcp.body import new_body
from gh_project_mcp.github.fake import FakeGitHub
from gh_project_mcp.github.port import Issue
from gh_project_mcp.status import Vocabulary, encode

VOCABULARY = Vocabulary()
_DEFAULT_FIELDS = {
    "requirement": {"type": "FUNC", "current_state": "It does not.", "desired_state": "It does."},
    "decision": {"context": "We had to choose.", "decision": "We chose."},
    "task": {"user_story": "Do the thing."},
}


def seed(
    github: FakeGitHub,
    kind: str,
    title: str = "",
    status: str | None = None,
    *,
    priority: str | None = "default",
    parent: int | None = None,
    blocked_by: tuple[int, ...] = (),
    fields: dict | None = None,
    body: str | None = None,
    milestone: int | None = None,
    extra_labels: tuple[str, ...] = (),
    vocabulary: Vocabulary = VOCABULARY,
) -> int:
    """Put a record in the fake without counting a request or logging a write; returns its number."""
    number = max(github.issues, default=0) + 1
    if priority == "default":
        priority = None if kind == "decision" else "P2"  # a decision has no priority
    labels = [vocabulary.kind_label(kind)] + ([vocabulary.priority_label(priority)] if priority else [])
    labels, state, reason = encode(vocabulary, kind, status, labels) if status else (labels, "open", None)
    now = github._now()
    github.issues[number] = Issue(
        number=number,
        id=1000 + number,
        title=title or f"{kind.title()} {number}",
        body=new_body(kind, {**_DEFAULT_FIELDS[kind], **(fields or {})}) if body is None else body,
        state=state,
        state_reason=reason,
        labels=[*labels, *extra_labels],
        milestone=milestone,
        parent=parent,
        blocked_by=list(blocked_by),
        url=f"https://github.com/{github.repo}/issues/{number}",
        author=github.user,
        created_at=now,
        updated_at=now,
    )
    if parent is not None:
        github.issues[parent].sub_issues.append(number)
    return number


async def call(app, tool: str, /, **arguments):
    """Call a tool the way a client does: through validation, routing and the call log."""
    from gh_project_mcp.server import call_tool

    return await call_tool(app, tool, arguments)


def text(result) -> str:
    return result.content[0].text
