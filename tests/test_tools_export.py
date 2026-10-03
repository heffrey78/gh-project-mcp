"""Export (REQ-0007-FUNC-00): documents that open with a project's purpose, and deterministic output."""

from tests.helpers import call, seed, text


def _tracker(github):
    github.milestones[1] = __import__("gh_project_mcp.github.port", fromlist=["Milestone"]).Milestone(
        1, "Search v1", "Make search usable at 10k notes.\n\n## Success criteria\n\n- p95 under 50 ms", "open",
        "https://github.com/octo/sandbox/milestone/1",
    )  # fmt: skip
    search = seed(github, "requirement", "Search is fast", "Approved", priority="P1", milestone=1,
                  fields={"type": "NFUNC", "acceptance_criteria": ["Under 50 ms"]})  # fmt: skip
    seed(github, "requirement", "Export works", milestone=None)
    old = seed(github, "decision", "Scan every note", "Superseded", fields={"addresses": [search]}, milestone=1)
    seed(
        github, "decision", "Use an index", "Accepted", fields={"addresses": [search], "supersedes": [old]}, milestone=1
    )
    build = seed(github, "task", "Build index", "Complete", parent=search, milestone=1,
                 fields={"commit": "abc1234", "evidence": "12 tests pass"})  # fmt: skip
    seed(github, "task", "Benchmark", parent=search, blocked_by=(build,), milestone=1)
    seed(github, "task", "Dropped idea", "Abandoned", parent=search, milestone=1)
    return search


async def test_whole_tracker_export(app, github, tmp_path):
    _tracker(github)
    await github.add_comment(4, "**Amendment**\n\nThe index is 40 MB, not 10.\n\n**Reason:** Measured")
    result = await call(app, "export_docs", output_directory=str(tmp_path))
    assert text(result) == (
        "Exported 7 records from octo/sandbox:\n"
        f"- {tmp_path}/sandbox-requirements.md\n- {tmp_path}/sandbox-decisions.md\n"
        f"- {tmp_path}/sandbox-tasks.md\n- {tmp_path}/sandbox-diagram.md\n"
        "Diagram: 6 records drawn, 1 retired left out, 0 over the limit."
    )
    requirements = (tmp_path / "sandbox-requirements.md").read_text()
    assert requirements == (
        "# sandbox: Requirements\n\n"
        "## Project: Search v1\n\n"
        "Make search usable at 10k notes.\n\n"
        "**Success criteria:**\n- p95 under 50 ms\n\n"
        "### NFUNC\n\n"
        "#### [#1](https://github.com/octo/sandbox/issues/1) Search is fast\n\n"
        "**Status:** Approved, P1 | **Type:** NFUNC\n\n"
        "**Progress:** 1/2 tasks complete\n\n"
        "**Decisions:** #3, #4\n\n"
        "Current state:\nIt does not.\n\nDesired state:\nIt does.\n\nAcceptance criteria:\n- [ ] Under 50 ms\n\n"
        "## In no project\n\n"
        "### FUNC\n\n"
        "#### [#2](https://github.com/octo/sandbox/issues/2) Export works\n\n"
        "**Status:** Draft, P2 | **Type:** FUNC\n\n"
        "Current state:\nIt does not.\n\nDesired state:\nIt does.\n"
    )
    decisions = (tmp_path / "sandbox-decisions.md").read_text()
    assert "## [#4](https://github.com/octo/sandbox/issues/4) Use an index\n\n**Status:** Accepted\n\n" in decisions
    assert "**Addresses:** #1\n\n**Supersedes:** #3" in decisions and "**Superseded by:** #4" in decisions
    # The amendment sits directly beneath the decision it corrects.
    assert (
        "Decision:\nWe chose.\n> Amendment (2026-01-01, octocat): The index is 40 MB, not 10. Reason: Measured"
        in decisions
    )
    tasks = (tmp_path / "sandbox-tasks.md").read_text()
    assert tasks.index("## Not Started") < tasks.index("## Complete") < tasks.index("## Abandoned")
    assert "**Status:** Complete, P2 | **Commit:** abc1234\n\n**Under:** #1 Search is fast" in tasks
    assert "Evidence:\n12 tests pass" in tasks


async def test_one_project_holds_only_its_records_and_opens_with_its_purpose(app, github, tmp_path):
    _tracker(github)
    result = await call(app, "export_docs", output_directory=str(tmp_path), project="Search v1", diagram=False)
    assert result.structured_content["records"] == 6 and len(result.structured_content["files"]) == 3
    for kind in ("requirements", "decisions", "tasks"):
        document = (tmp_path / f"search-v1-{kind}.md").read_text()
        assert document.split("\n\n")[1] == "Make search usable at 10k notes.", kind
        assert "Export works" not in document
    assert not (tmp_path / "search-v1-diagram.md").exists()


async def test_an_unchanged_tracker_exports_identical_bytes(app, github, tmp_path):
    _tracker(github)
    first, second = tmp_path / "a", tmp_path / "b"
    await call(app, "export_docs", output_directory=str(first), name="x")
    await call(app, "get_status")  # a refresh in between changes nothing
    await call(app, "export_docs", output_directory=str(second), name="x")
    names = sorted(p.name for p in first.iterdir())
    assert names == ["x-decisions.md", "x-diagram.md", "x-requirements.md", "x-tasks.md"]
    for name in names:
        assert (first / name).read_bytes() == (second / name).read_bytes(), name


async def test_the_diagram_draws_links_and_says_what_it_left_out(app, github, tmp_path):
    _tracker(github)
    result = await call(app, "export_docs", output_directory=str(tmp_path), limit=1)
    assert result.structured_content["diagram"] == {"drawn": 3, "retired_left_out": 1, "over_limit": 3}
    await call(app, "export_docs", output_directory=str(tmp_path))
    diagram = (tmp_path / "sandbox-diagram.md").read_text()
    for line in (
        '    R1["#1 Search is fast"]:::active',
        '    D3["#3 Scan every note"]:::retired',
        "    T5 -->|implements| R1",
        "    T6 -.->|blocked by| T5",
        "    D4 -->|addresses| R1",
        "    D4 ==>|supersedes| D3",
    ):
        assert line in diagram, line
    assert "Dropped idea" not in diagram and diagram.startswith(
        "# sandbox: Records and links\n\n```mermaid\ngraph TD\n"
    )


async def test_an_empty_tracker_and_a_bad_directory(app, github, tmp_path):
    await call(app, "export_docs", output_directory=str(tmp_path))
    assert (tmp_path / "sandbox-requirements.md").read_text() == "# sandbox: Requirements\n\nNo requirements.\n"
    blocker = tmp_path / "file"
    blocker.write_text("x")
    refused = await call(app, "export_docs", output_directory=str(blocker / "sub"))
    assert refused.is_error and "Could not write to" in text(refused)
