#!/usr/bin/env python3
"""Start the server over stdio the way a client does, and check the handshake and that stdout is clean.

Usage: python scripts/mcp_handshake_smoke.py [command ...]   (default: this interpreter, -m gh_project_mcp.server)

No repository or token is configured, so nothing reaches GitHub: the server must still start, list its tools and
answer a call with how to configure it. Exits non-zero, saying what went wrong, on any failure.
"""

import json
import os
import queue
import subprocess
import sys
import threading
import time

TIMEOUT = 30

REQUESTS = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "0"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "prompts/list"},
    {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "get_status", "arguments": {}}},
]  # fmt: skip


def main() -> int:
    command = sys.argv[1:] or [sys.executable, "-m", "gh_project_mcp.server"]
    env = {k: v for k, v in os.environ.items() if not k.startswith("GH_PROJECT_")}
    try:
        server = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
        )
    except OSError as error:
        print(f"FAIL: could not run {' '.join(command)}: {error}")
        return 1

    # Closing stdin ends the session, so it stays open until every answer is in.
    lines: queue.Queue[str | None] = queue.Queue()
    threading.Thread(
        target=lambda: [lines.put(line) for line in server.stdout] + [lines.put(None)], daemon=True
    ).start()
    errors: list[str] = []
    threading.Thread(target=lambda: errors.extend(server.stderr), daemon=True).start()
    for request in REQUESTS:
        server.stdin.write(json.dumps(request) + "\n")
    server.stdin.flush()

    wanted = {request["id"] for request in REQUESTS if "id" in request}
    responses: dict[int, dict] = {}
    deadline = time.monotonic() + TIMEOUT
    failure = None
    while wanted - set(responses) and failure is None:
        try:
            line = lines.get(timeout=max(0.1, deadline - time.monotonic()))
        except queue.Empty:
            failure = f"no answer to request(s) {sorted(wanted - set(responses))} within {TIMEOUT} seconds"
            break
        if line is None:
            failure = f"the server exited before answering request(s) {sorted(wanted - set(responses))}"
            break
        try:
            message = json.loads(line)
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                raise ValueError
        except ValueError:
            failure = f"stdout carried something that is not JSON-RPC: {line[:200]!r}"
            break
        if "id" in message:
            responses[message["id"]] = message
    server.stdin.close()
    try:
        server.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.kill()
    if failure:
        print(f"FAIL: {failure}")
        print("stderr:\n" + "".join(errors)[-2000:])
        return 1

    problems = []
    if "result" not in responses.get(1, {}):
        problems.append("initialize did not succeed")
    tools = responses.get(2, {}).get("result", {}).get("tools", [])
    if not tools:
        problems.append("tools/list returned no tools")
    if len(responses.get(3, {}).get("result", {}).get("prompts", [])) != 2:
        problems.append("prompts/list did not return the two prompts")
    call = responses.get(4, {}).get("result", {})
    told = "".join(block.get("text", "") for block in call.get("content", []))
    if not call.get("isError") or "GH_PROJECT_REPO" not in told:
        problems.append("an unconfigured call did not say how to configure the repository")
    if problems:
        print("FAIL: " + "; ".join(problems))
        print("stderr:\n" + "".join(errors)[-2000:])
        return 1
    print(f"OK: handshake, {len(tools)} tools, 2 prompts, clean stdout ({' '.join(command)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
