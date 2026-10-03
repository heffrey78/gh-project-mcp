"""Transition maps and the paths through them (ADR-0006, REQ-0002-FUNC-00)."""

import itertools

import pytest

from gh_project_mcp import rules
from gh_project_mcp.rules import STOP_STATUSES, TRANSITIONS, StatusRefused, path
from gh_project_mcp.status import STATUSES


def test_draft_to_approved_walks_through_review():
    assert path("requirement", "Draft", "Approved") == ["Draft", "Under Review", "Approved"]


def test_a_move_may_end_at_a_stop_but_not_pass_through_one():
    assert path("requirement", "Approved", "Implemented") == ["Approved", "Implemented"]
    assert path("requirement", "Implemented", "Validated") == ["Implemented", "Validated"]
    with pytest.raises(StatusRefused, match="passes through Approved.*Move it to Approved first"):
        path("requirement", "Draft", "Implemented")
    with pytest.raises(StatusRefused, match="passes through Approved"):
        path("requirement", "Under Review", "Validated")
    # Implemented is not a stop, so Approved reaches Validated in one call; the gates apply at each step.
    assert path("requirement", "Approved", "Validated") == ["Approved", "Implemented", "Validated"]


@pytest.mark.parametrize("kind", STATUSES)
def test_no_path_has_a_stop_status_inside_it(kind):
    for start, goal in itertools.permutations(STATUSES[kind], 2):
        try:
            found = path(kind, start, goal)
        except StatusRefused:
            continue
        assert found[0] == start and found[-1] == goal
        assert not set(found[1:-1]) & set(STOP_STATUSES[kind])
        assert all(b in TRANSITIONS[kind][a] for a, b in itertools.pairwise(found))


def test_every_transition_names_real_statuses():
    for kind, table in TRANSITIONS.items():
        assert set(table) == set(STATUSES[kind])
        assert all(set(targets) <= set(STATUSES[kind]) for targets in table.values())


def test_a_task_moves_between_any_two_statuses_in_one_step():
    for start, goal in itertools.permutations(STATUSES["task"], 2):
        assert path("task", start, goal) == [start, goal]


def test_refusals_say_what_to_do_instead():
    with pytest.raises(StatusRefused, match="already Draft"):
        path("requirement", "Draft", "Draft")
    with pytest.raises(StatusRefused, match="'Ready' is not a requirement status; a requirement is one of Draft"):
        path("requirement", "Draft", "Ready")
    with pytest.raises(StatusRefused, match="link_records"):
        path("decision", "Accepted", "Superseded")
    with pytest.raises(StatusRefused, match="unlink_records"):
        path("decision", "Superseded", "Accepted")
    # Retiring a requirement is never a step in reviving it.
    with pytest.raises(StatusRefused, match="Validated to Approved passes through Deprecated"):
        path("requirement", "Validated", "Approved")
    assert path("requirement", "Deprecated", "Draft") == ["Deprecated", "Draft"]
    with pytest.raises(StatusRefused, match="cannot go from Superseded to Proposed|unlink_records"):
        path("decision", "Superseded", "Proposed")


def test_a_decision_goes_back_through_proposed():
    assert path("decision", "Accepted", "Rejected") == ["Accepted", "Proposed", "Rejected"]


def test_mode_decides_what_a_risky_move_gets(monkeypatch):
    reasons = ["It was never started."]
    assert rules.check(reasons, "move #1 to Complete") == reasons
    assert rules.check([], "move #1 to Complete") == []
    monkeypatch.setenv("GH_PROJECT_RULES", "off")
    assert rules.check(reasons, "move #1 to Complete") == []
    monkeypatch.setenv("GH_PROJECT_RULES", "enforce")
    with pytest.raises(StatusRefused, match="Refused: move #1 to Complete. It was never started."):
        rules.check(reasons, "move #1 to Complete")
    assert rules.check([], "move #1 to Complete") == []
    monkeypatch.setenv("GH_PROJECT_RULES", "strict")
    assert rules.rules_mode() == "warn"


def test_thin_records():
    assert rules.thin_reasons("requirement", {"type": "FUNC", "acceptance_criteria": ["x"]}, "P1") == []
    assert "acceptance_criteria" in rules.thin_reasons("requirement", {"type": "FUNC"}, "P1")[0]
    nfunc = rules.thin_reasons("requirement", {"type": "NFUNC", "acceptance_criteria": ["x"]}, "P1")
    assert len(nfunc) == 1 and "validation_metrics" in nfunc[0]
    assert "test_plan" in rules.thin_reasons("task", {}, "P0")[0]
    assert rules.thin_reasons("task", {}, "P2") == []
    assert rules.thin_reasons("task", {"test_plan": ["run it"]}, "P0") == []
    assert rules.thin_reasons("decision", {}, None) == []
