"""The guard in conftest.py is the reason this suite cannot touch GitHub (REQ-0001-NFUNC-00)."""

import asyncio
import socket
import subprocess

import pytest

from tests.conftest import GuardError


def test_socket_connection_is_refused():
    with pytest.raises(GuardError, match="network guard"), socket.socket() as sock:
        sock.connect(("api.github.com", 443))


def test_create_connection_is_refused():
    with pytest.raises(GuardError, match="network guard"):
        socket.create_connection(("api.github.com", 443), timeout=1)


def test_subprocess_is_refused():
    with pytest.raises(GuardError, match="spawn a subprocess"):
        subprocess.run(["gh", "auth", "token"], check=False)


async def test_async_subprocess_is_refused():
    with pytest.raises(GuardError, match="spawn a subprocess"):
        await asyncio.create_subprocess_exec("gh", "auth", "token")


def test_developer_configuration_does_not_leak(monkeypatch):
    import os

    assert "GH_PROJECT_REPO" not in os.environ
    assert "GH_TOKEN" not in os.environ
