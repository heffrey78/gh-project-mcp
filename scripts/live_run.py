#!/usr/bin/env python3
"""Drive a whole lifecycle through the server over stdio, against a real sandbox repository.

Usage: python scripts/live_run.py owner/some-sandbox [transcript.md]

Every tool is called at least once, and two calls are refused on purpose. The server runs as a client would start it,
with a call log. This writes real issues: the repository's name must contain "sandbox".
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from mcp import Client, StdioServerParameters

EXPECTED_REFUSALS = {"refused: through Approved", "refused: rewrite an accepted decision"}


async def run(repo: str, transcript: list[str], log_path: str) -> list[str]:
    env = {**os.environ, "GH_PROJECT_REPO": repo, "GH_PROJECT_CALL_LOG": log_path}
    params = StdioServerParameters(command=sys.executable, args=["-m", "gh_project_mcp.server"], env=env)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    problems: list[str] = []
    numbers: dict[str, int] = {}

    async with Client(params) as client:

        async def call(label: str, tool: str, **arguments):
            result = await client.call_tool(tool, arguments)
            text = "".join(getattr(block, "text", "") for block in result.content)
            transcript.append(f"### {label}\n\n`{tool}({json.dumps(arguments)})`\n\n```\n{text}\n```\n")
            if result.is_error and label not in EXPECTED_REFUSALS:
                problems.append(f"{label}: {text}")
            if not result.is_error and label in EXPECTED_REFUSALS:
                problems.append(f"{label}: was not refused")
            return result.structured_content or {}

        def number(name: str, data: dict) -> int:
            numbers[name] = data["number"]
            return data["number"]

        await call("setup", "setup_repository")
        await call("status, before", "get_status")
        await call(
            "project",
            "save_project",
            title=f"Live run {stamp}",
            purpose="Prove the server against real GitHub.",
            success_criteria=["Every tool works"],
        )
        project = f"Live run {stamp}"
        req = number(
            "req",
            await call(
                "requirement",
                "create_requirement",
                title="Search stays fast",
                type="NFUNC",
                priority="P1",
                current_state="A query takes 900 ms.",
                desired_state="Search stays quick.",
                project=project,
            ),
        )
        await call(
            "fill the thin requirement",
            "update_record",
            id=req,
            fields={"acceptance_criteria": ["p95 under 50 ms"], "validation_metrics": ["p95 at 10k notes"]},
        )
        other = number(
            "other",
            await call(
                "second requirement",
                "create_requirement",
                title="Export works",
                type="FUNC",
                priority="P3",
                current_state="No export.",
                desired_state="Markdown export.",
                acceptance_criteria=["A note exports"],
            ),
        )
        await call("refused: through Approved", "set_status", ids=other, status="Implemented")
        await call("approve", "set_status", ids=f"#{req}", status="Approved", comment="Approved for the live run")
        old = number(
            "decision",
            await call(
                "decision",
                "create_decision",
                title="Scan every note",
                context="Small sets.",
                decision="Scan.",
                addresses=[req],
            ),
        )
        await call("accept", "set_status", ids=old, status="Accepted")
        await call("refused: rewrite an accepted decision", "update_record", id=old, fields={"decision": "Index."})
        await call(
            "amend", "update_record", id=old, amendment="Scanning measured 900 ms at 10k notes.", reason="Benchmark"
        )
        new = number(
            "newer",
            await call(
                "newer decision",
                "create_decision",
                title="Use an index",
                context="Scanning is too slow.",
                decision="Build an inverted index.",
                addresses=[req],
            ),
        )
        await call("supersede", "link_records", source=new, type="supersedes", target=old)
        await call("accept newer", "set_status", ids=new, status="Accepted")
        await call("read superseded", "get_record", id=old)
        build = number(
            "build",
            await call(
                "task",
                "create_task",
                title="Build the index",
                parent=req,
                priority="P1",
                test_plan=["unit tests"],
                effort="M",
            ),
        )
        tokenise = number(
            "tokenise", await call("subtask", "create_task", title="Tokenise notes", parent=build, priority="P2")
        )
        bench = number(
            "bench",
            await call(
                "task blocked by another",
                "create_task",
                title="Benchmark",
                parent=req,
                priority="P1",
                test_plan=["run the benchmark"],
                blocked_by=[build],
            ),
        )
        await call("ready", "query_records", ready=True)
        await call("dashboard, mid-run", "get_status")
        await call("start", "set_status", ids=tokenise, status="In Progress")
        await call("block", "set_status", ids=tokenise, status="Blocked", comment="Waiting on a tokeniser choice")
        await call("dashboard, blocked", "get_status")
        await call(
            "finish subtask", "set_status", ids=tokenise, status="Complete", commit="abc1234", evidence="9 tests pass"
        )
        await call("finish parent", "set_status", ids=build, status="Complete", evidence="index builds")
        await call("extra link", "link_records", source=other, type="blocked_by", target=req)
        await call("remove it", "unlink_records", source=other, type="blocked_by", target=req)
        await call("bench, two steps", "set_status", ids=[bench], status="In Progress")
        await call("bench done", "set_status", ids=bench, status="Complete", evidence="p95 37 ms")
        await call("comment", "add_comment", id=req, comment="Live run: all work done.")
        await call("work complete", "query_records", work_complete=True)
        await call("validate", "set_status", ids=req, status="Validated", evidence="p95 37 ms at 10k notes")
        await call("trace", "get_record", id=req, include=["comments", "history"])
        await call("project view", "get_record", project=project)
        await call("search", "query_records", search="index", kind="decision")
        with tempfile.TemporaryDirectory() as directory:
            await call("export", "export_docs", output_directory=directory, project=project)

        # Drift: what a person might do on github.com, behind the server's back.
        edit = ["gh", "issue", "edit", str(other), "--repo", repo, "--add-label", "status:approved,status:under-review"]
        await asyncio.to_thread(subprocess.run, edit, check=True, capture_output=True)
        drift = await call("drift made by hand", "get_status")
        if not any(d["number"] == other for d in drift.get("drift", [])):
            problems.append("drift made by hand was not reported")
        await call("retire", "set_status", ids=other, status="Deprecated", comment="Live run over")
        await call("close project", "save_project", project=project, state="closed")
        await call("status, after", "get_status")
    transcript.append(f"Records: {json.dumps(numbers)}\n")
    return problems


def main() -> int:
    if len(sys.argv) < 2 or "sandbox" not in sys.argv[1].split("/")[-1].lower():
        print("usage: live_run.py owner/<name containing sandbox> [transcript.md]")
        return 2
    repo = sys.argv[1]
    transcript: list[str] = [f"# Live run against {repo}\n"]
    handle, log = tempfile.mkstemp(suffix=".jsonl")
    os.close(handle)
    started = time.monotonic()
    problems = asyncio.run(run(repo, transcript, log))
    calls = [json.loads(line) for line in Path(log).read_text().splitlines()]
    tools = sorted({c["tool"] for c in calls})
    summary = (
        f"{len(calls)} calls to {len(tools)} tools in {time.monotonic() - started:.0f} s; "
        f"{sum(c['isError'] for c in calls)} errors; median {sorted(c['ms'] for c in calls)[len(calls) // 2]} ms"
    )
    transcript.insert(1, f"{summary}\n\nTools called: {', '.join(tools)}\n")
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text("\n".join(transcript))
    print(summary)
    print("\n".join(f"PROBLEM: {p}" for p in problems) or "No problems.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
