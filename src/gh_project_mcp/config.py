"""Configuration, all of it from the environment.

The repository is named, never inferred: lifecycle-mcp took it from the working directory's origin remote, and that
is how its test issues reached the upstream repository (ADR-0004).
"""

import os
import re
from dataclasses import dataclass

REPO_ENV = "GH_PROJECT_REPO"
API_URL_ENV = "GH_PROJECT_API_URL"
READ_ONLY_ENV = "GH_PROJECT_READ_ONLY"
LABEL_PREFIX_ENV = "GH_PROJECT_LABEL_PREFIX"
CALL_LOG_ENV = "GH_PROJECT_CALL_LOG"
TOKEN_ENVS = ("GH_TOKEN", "GITHUB_TOKEN")

DEFAULT_API_URL = "https://api.github.com"
_ON = {"1", "true", "yes", "on"}
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+")


class ConfigError(Exception):
    """The server is not configured to do what was asked. The message says how to configure it."""


@dataclass(frozen=True)
class Config:
    repo: str | None = None
    api_url: str = DEFAULT_API_URL
    read_only: bool = False
    label_prefix: str = ""
    call_log: str | None = None
    token: str | None = None  # None: taken from `gh auth token` at first use

    @classmethod
    def from_env(cls) -> "Config":
        env = os.environ
        return cls(
            repo=env.get(REPO_ENV, "").strip() or None,
            api_url=env.get(API_URL_ENV, "").strip().rstrip("/") or DEFAULT_API_URL,
            read_only=env.get(READ_ONLY_ENV, "").strip().lower() in _ON,
            label_prefix=env.get(LABEL_PREFIX_ENV, ""),
            call_log=env.get(CALL_LOG_ENV) or None,
            token=next((env[name].strip() for name in TOKEN_ENVS if env.get(name, "").strip()), None),
        )

    def require_repo(self) -> str:
        if not self.repo:
            raise ConfigError(
                f"No repository is configured, so nothing was sent to GitHub. Set {REPO_ENV}=owner/name in the "
                "server's environment, for example: claude mcp add gh-project gh-project-mcp "
                f"-e {REPO_ENV}=owner/name"
            )
        if not _REPO.fullmatch(self.repo):
            raise ConfigError(f"{REPO_ENV}={self.repo!r} is not of the form owner/name")
        return self.repo
