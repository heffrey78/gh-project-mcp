"""Suite-wide guards.

lifecycle-mcp's test suite once created 1,049 real issues on its own upstream repository, because its fixtures
ran the real GitHub code path whenever `gh` was authenticated. Every write this server makes goes to GitHub, so
here a test cannot reach the network or spawn a process unless it is marked as meaning to.
"""

import asyncio
import socket
import subprocess

import pytest


class GuardError(AssertionError):
    """A test tried to leave the process."""


def _refuse(what: str):
    def refused(*args, **kwargs):
        raise GuardError(
            f"network guard: this test tried to {what}. Tests run against FakeGitHub; only tests marked "
            "github_live (network) or smoke (subprocess) may leave the process. See tests/conftest.py"
        )

    return refused


@pytest.fixture(autouse=True)
def network_guard(request, monkeypatch):
    """Fail any test that opens a socket connection or spawns a subprocess."""
    live = request.node.get_closest_marker("github_live") is not None
    smoke = request.node.get_closest_marker("smoke") is not None
    if not live:
        monkeypatch.setattr(socket.socket, "connect", _refuse("open a network connection"))
        monkeypatch.setattr(socket.socket, "connect_ex", _refuse("open a network connection"))
        monkeypatch.setattr(socket, "getaddrinfo", _refuse("resolve a host name"))
    if not (live or smoke):
        # Popen stays a class (libraries subscript it in annotations); creating one is what is refused.
        monkeypatch.setattr(subprocess.Popen, "__init__", _refuse("spawn a subprocess"))
        monkeypatch.setattr(asyncio, "create_subprocess_exec", _refuse("spawn a subprocess"))
        monkeypatch.setattr(asyncio, "create_subprocess_shell", _refuse("spawn a subprocess"))
    # A developer's own configuration must not leak into a test and aim it at a real repository.
    for name in ("GH_PROJECT_REPO", "GH_TOKEN", "GITHUB_TOKEN", "GH_PROJECT_RULES", "GH_PROJECT_READ_ONLY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def github():
    from gh_project_mcp.github.fake import FakeGitHub

    return FakeGitHub()


@pytest.fixture
def app(github):
    from gh_project_mcp.app import App
    from gh_project_mcp.config import Config

    return App(Config(repo=github.repo), github)
