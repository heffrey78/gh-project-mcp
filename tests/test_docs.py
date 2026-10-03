"""The documentation says what the code does (REQ-0002-TECH-00).

lifecycle-mcp's CLAUDE.md said "22 tools" while the server listed 32. These tests are why that cannot happen here.
"""

import re
from pathlib import Path

import pytest

from gh_project_mcp.kinds import DECISION, REQUIREMENT, TASK, editable_fields
from gh_project_mcp.registry import TOOLS
from gh_project_mcp.rules import STOP_STATUSES
from gh_project_mcp.status import STATUSES, Vocabulary
from gh_project_mcp.surface import definition_sizes

ROOT = Path(__file__).parent.parent
README = (ROOT / "README.md").read_text()
CLAUDE = (ROOT / "CLAUDE.md").read_text()


def test_the_readme_lists_exactly_the_tools_the_server_does():
    listed = re.findall(r"^- `([a-z_]+)` - ", README, re.M)
    assert listed == sorted(listed, key=listed.index) and set(listed) == set(TOOLS)
    assert len(listed) == len(TOOLS), "a tool is listed twice"
    assert f"The server lists {len(TOOLS)} tools" in README


def test_every_environment_variable_the_code_reads_is_documented():
    read = set()
    for path in (ROOT / "src").rglob("*.py"):
        read |= set(re.findall(r'"(GH_PROJECT_[A-Z_]+|GH_TOKEN|GITHUB_TOKEN)"', path.read_text()))
    assert read >= {"GH_PROJECT_REPO", "GH_PROJECT_RULES", "GH_TOKEN"}
    undocumented = {name for name in read if f"`{name}`" not in README}
    assert not undocumented


@pytest.mark.parametrize(
    ("tool", "kind"), [("create_requirement", REQUIREMENT), ("create_decision", DECISION), ("create_task", TASK)]
)
def test_the_readme_names_every_parameter_of_the_create_tools(tool, kind):
    paragraph = next(p for p in README.split("\n\n") if p.startswith(f"`{tool}` takes"))
    named = set(re.findall(r"`([a-z_]+)`", paragraph)) - {tool}
    assert named == set(TOOLS[tool].schema["properties"])
    assert {spec.name for spec in editable_fields(kind)} <= named


def test_the_readme_names_every_status_and_label():
    for statuses in STATUSES.values():
        for status in statuses:
            assert status in README, status
    table = README[README.index("### Statuses") : README.index("`setup_repository` creates the labels")]
    for kind, statuses in STATUSES.items():
        row = next(line for line in table.splitlines() if line.startswith(f"| {kind.title()} "))
        assert all(status in row for status in statuses), kind
    for kind in ("requirement", "decision", "task"):
        assert f"`{Vocabulary().kind_label(kind)}`" in README
    assert all(stop in README for stop in STOP_STATUSES[REQUIREMENT][:2])


def test_the_comparison_with_lifecycle_mcp_states_the_real_surface():
    assert f"| Tools | 25, about 17,000 characters of definitions | {len(TOOLS)}, under 9,000 |" in README
    assert sum(definition_sizes().values()) < 9000


def test_claude_md_names_modules_and_tests_that_exist():
    for module in re.findall(r"^- `([a-z_/]+\.py)`", CLAUDE, re.M):
        assert (ROOT / "src" / "gh_project_mcp" / module).exists(), module
    for mentioned in re.findall(r"`(tests/[a-z_/]+\.(?:py|json))`", CLAUDE):
        assert (ROOT / mentioned).exists(), mentioned
    tests = "\n".join(path.read_text() for path in (ROOT / "tests").rglob("test_*.py"))
    for name in re.findall(r"`(test_[a-z_]+)`", CLAUDE):
        assert f"def {name}(" in tests, name
    for target in re.findall(r"^make ([a-z]+)", CLAUDE, re.M):
        assert f"\n{target}:" in (ROOT / "Makefile").read_text(), target


def test_the_quick_start_commands_exist():
    assert (ROOT / "scripts" / "mcp_handshake_smoke.py").exists()
    assert 'gh-project-mcp = "gh_project_mcp.server:main"' in (ROOT / "pyproject.toml").read_text()
    for target in re.findall(r"^make ([a-z]+)", README, re.M):
        assert f"\n{target}:" in (ROOT / "Makefile").read_text(), target
