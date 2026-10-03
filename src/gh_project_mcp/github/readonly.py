"""A GitHub that can be read and not written (GH_PROJECT_READ_ONLY).

The server refuses a write tool before it runs; this is the second lock, so a write that slipped past a tool's
declaration still cannot reach GitHub.
"""

from typing import Any

from .port import GitHub, GitHubError

_READS = ("list_issues", "list_changes", "list_comments", "list_events", "list_milestones", "list_labels")


class ReadOnlyGitHub:
    def __init__(self, inner: GitHub):
        self._inner = inner
        self.repo = inner.repo

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._inner, name)
        if name in _READS or not callable(attribute) or name == "aclose":
            return attribute

        async def refused(*args: Any, **kwargs: Any) -> None:
            raise GitHubError(
                "the server is in read-only mode (GH_PROJECT_READ_ONLY); nothing was sent", operation=name
            )

        return refused
