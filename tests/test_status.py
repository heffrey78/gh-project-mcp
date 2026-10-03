"""Status is derived from labels and state, one way and back (ADR-0002, REQ-0002-FUNC-00)."""

import pytest

from gh_project_mcp.status import FIRST_STATUS, STATUSES, Vocabulary, derive, encode

V = Vocabulary()
PAIRS = [(kind, status) for kind, statuses in STATUSES.items() for status in statuses]


def test_there_are_fifteen_statuses():
    assert len(PAIRS) == 15


@pytest.mark.parametrize(("kind", "status"), PAIRS)
def test_every_status_encodes_to_something_that_derives_back(kind, status):
    labels, state, reason = encode(V, kind, status, [kind, "P1", "status:blocked", "bug"])
    derived = derive(V, labels, state, reason)
    assert (derived.kind, derived.status, derived.priority, derived.problems) == (kind, status, "P1", [])
    # Other labels are kept and the old status label is gone unless it is the new one.
    assert "bug" in labels and (status == "Blocked") == ("status:blocked" in labels)


def test_no_two_statuses_of_a_kind_share_an_encoding():
    for kind, statuses in STATUSES.items():
        encodings = {
            (tuple(sorted(labels)), state, reason)
            for labels, state, reason in (encode(V, kind, s, [kind]) for s in statuses)
        }
        assert len(encodings) == len(statuses)


@pytest.mark.parametrize("kind", STATUSES)
def test_an_open_issue_with_only_a_kind_label_is_at_the_first_status(kind):
    assert derive(V, [kind], "open", None).status == FIRST_STATUS[kind]
    assert derive(V, [kind], "open", "reopened").status == FIRST_STATUS[kind]


def test_an_issue_without_a_kind_label_is_not_a_record():
    assert derive(V, ["bug", "status:approved", "P0"], "open", None) is None


@pytest.mark.parametrize(
    ("kind", "reason", "status"),
    [
        ("task", "completed", "Complete"),
        ("task", None, "Complete"),  # older issues carry no close reason
        ("task", "not_planned", "Abandoned"),
        ("task", "duplicate", "Abandoned"),
        ("requirement", "completed", "Validated"),
        ("requirement", "not_planned", "Deprecated"),
        ("decision", "completed", "Accepted"),
        ("decision", "not_planned", "Rejected"),
    ],
)
def test_closing_on_github_is_a_status(kind, reason, status):
    # Closed by hand or by a pull request: the open-status label is still there and does not matter.
    derived = derive(V, [kind, "status:in-progress" if kind == "task" else kind], "closed", reason)
    assert derived.status == status and derived.problems == []


def test_two_status_labels_are_a_problem_read_as_the_furthest():
    derived = derive(V, ["requirement", "status:approved", "status:under-review"], "open", None)
    assert derived.status == "Approved"
    assert derived.problems == ["has 2 status labels (Under Review, Approved); read as Approved"]


def test_a_repositorys_own_status_labels_are_left_alone():
    """lifecycle-mcp's own repository has status:complete and status:not-started. They are not ours."""
    labels = ["task", "status:not-started", "status:needs-triage", "status:in-progress"]
    derived = derive(V, labels, "open", None)
    assert (derived.status, derived.problems) == ("In Progress", [])
    moved, _, _ = encode(V, "task", "Blocked", labels)
    assert moved == ["task", "status:not-started", "status:needs-triage", "status:blocked"]
    assert V.without_status(labels) == ["task", "status:not-started", "status:needs-triage"]


def test_a_status_label_of_another_kind_is_a_problem():
    derived = derive(V, ["requirement", "status:in-progress"], "open", None)
    assert derived.status == "Draft"
    assert derived.problems == ["carries status:in-progress, which is not a requirement status"]


def test_two_kind_labels_are_a_problem():
    derived = derive(V, ["task", "requirement"], "open", None)
    assert derived.kind == "requirement" and "2 kind labels" in derived.problems[0]


def test_superseded_is_a_closed_decision_with_the_label():
    assert derive(V, ["decision", "status:superseded"], "closed", "not_planned").status == "Superseded"
    assert derive(V, ["decision", "status:superseded"], "closed", "completed").status == "Superseded"
    still_open = derive(V, ["decision", "status:superseded"], "open", None)
    assert still_open.status == "Proposed" and "open but labelled superseded" in still_open.problems[0]


def test_a_prefix_keeps_the_labels_apart_from_a_repositorys_own():
    prefixed = Vocabulary("lc:")
    assert derive(prefixed, ["task", "status:blocked"], "open", None) is None
    labels, state, _ = encode(prefixed, "task", "Blocked", ["lc:task", "lc:P0", "status:mine"])
    assert labels == ["lc:task", "lc:P0", "status:mine", "lc:status:blocked"] and state == "open"
    assert derive(prefixed, labels, state, None).status == "Blocked"
    assert derive(prefixed, labels, state, None).priority == "P0"


def test_encode_refuses_a_status_of_another_kind():
    with pytest.raises(ValueError, match="'Approved' is not a task status"):
        encode(V, "task", "Approved", ["task"])


def test_definitions_cover_every_label_encode_can_produce():
    defined = {d.name for d in V.definitions()}
    for kind, status in PAIRS:
        labels, _, _ = encode(V, kind, status, [kind, "P0", "P1", "P2", "P3"])
        assert set(labels) <= defined
