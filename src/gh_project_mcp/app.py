"""What a tool call runs against: the configuration, the GitHub client and the tracker snapshot."""

import anyio

from .config import Config
from .github.port import GitHub
from .github.readonly import ReadOnlyGitHub
from .status import Vocabulary
from .tracker import Tracker


class App:
    def __init__(self, config: Config, github: GitHub | None = None):
        self.config = config
        self.vocabulary = Vocabulary(config.label_prefix)
        self._github = github
        self._tracker: Tracker | None = None
        # A client may send calls concurrently. They share one snapshot, so they run one at a time.
        self.lock = anyio.Lock()

    @property
    def github(self) -> GitHub:
        """The client, built on first use so the server starts and lists its tools with nothing configured."""
        if self._github is None:
            self.config.require_repo()
            from .github.http import HttpGitHub  # the only import of the network client outside github/

            self._github = HttpGitHub(self.config)
        if self.config.read_only and not isinstance(self._github, ReadOnlyGitHub):
            self._github = ReadOnlyGitHub(self._github)
        return self._github

    async def tracker(self) -> Tracker:
        """The snapshot, brought up to date. Every tool call starts here."""
        if self._tracker is None:
            self._tracker = Tracker(self.github, self.vocabulary)
        await self._tracker.refresh()
        return self._tracker

    async def aclose(self) -> None:
        close = getattr(self._github, "aclose", None)
        if close is not None:
            await close()
