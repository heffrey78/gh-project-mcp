"""The body codec (ADR-0002, REQ-0001-FUNC-00): fields round-trip, and a person's text survives an edit."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gh_project_mcp.body import Document, clean_item, clean_text, edit_body, new_body
from gh_project_mcp.kinds import ATTR, CHECKLIST, LEAD, LIST, PROJECT, RECORD_KINDS, REFS, field_specs

ALL_KINDS = (*RECORD_KINDS, PROJECT)

# Text that tries to look like the codec's own syntax.
_awkward = st.sampled_from(
    ["## Heading", "\\## escaped", "- bullet", "- [ ] box", "- [x] done", "```", "~~~", "**Type:** FUNC", "#12", "·"]
)
_text = st.lists(st.one_of(st.text(max_size=30), _awkward), max_size=5).map("\n".join)


def _value(spec):
    if spec.shape == ATTR:
        return st.sampled_from(spec.choices) if spec.choices else st.from_regex(r"[0-9a-f]{7,12}", fullmatch=True)
    if spec.shape == REFS:
        return st.lists(st.integers(min_value=1, max_value=99999), max_size=4, unique=True)
    if spec.shape in (LIST, CHECKLIST):
        return st.lists(_text, max_size=4)
    return _text


def _fields(kind):
    specs = field_specs(kind)
    return st.fixed_dictionaries({}, optional={spec.name: _value(spec) for spec in specs})


def _stored(kind, fields):
    """What a record should read back as: the cleaned values, without the empty ones."""
    expected = {}
    for spec in field_specs(kind):
        value = fields.get(spec.name)
        if spec.shape in (LIST, CHECKLIST):
            value = [item for item in (clean_item(v) for v in value or []) if item]
        elif spec.shape in (LEAD,) or spec.shape == "text":
            value = clean_text(value) if value is not None else None
        if value:
            expected[spec.name] = value
    return expected


@pytest.mark.parametrize("kind", ALL_KINDS)
@settings(max_examples=300, deadline=None)
@given(data=st.data())
def test_fields_round_trip(kind, data):
    fields = data.draw(_fields(kind))
    body = new_body(kind, fields)
    document = Document(body, kind)
    assert document.fields() == _stored(kind, fields)
    # Reading does not change the text, and writing the same values again does not either.
    assert document.render() == body
    assert edit_body(body, kind, document.fields()) == body


@pytest.mark.parametrize("kind", RECORD_KINDS)
@settings(max_examples=200, deadline=None)
@given(data=st.data())
def test_any_text_renders_back_unchanged(kind, data):
    text = data.draw(_text)
    assert Document(text, kind).render() == text


def test_new_requirement_body_reads_as_markdown():
    body = new_body(
        "requirement",
        {
            "type": "NFUNC",
            "risk": "Medium",
            "current_state": "Search is slow.",
            "desired_state": "Search is fast.",
            "acceptance_criteria": ["Under 50 ms at p95", "Measured by the benchmark"],
            "out_of_scope": ["Ranking"],
        },
    )
    assert body == (
        "**Type:** NFUNC · **Risk:** Medium\n\n"
        "## Current state\n\nSearch is slow.\n\n"
        "## Desired state\n\nSearch is fast.\n\n"
        "## Acceptance criteria\n\n- [ ] Under 50 ms at p95\n- [ ] Measured by the benchmark\n\n"
        "## Out of scope\n\n- Ranking"
    )


HAND_EDITED = (
    "**Type:** FUNC · **Risk:** Low\n"
    "\n"
    "Jeff: discussed with the team on Tuesday.\n"
    "\n"
    "## Current state\n"
    "\n"
    "Nothing.\n"
    "\n"
    "## Notes from review\n"
    "We should   revisit this.\n"
    "### A sub-heading\n"
    "\n"
    "```\n## not a heading\n```\n"
    "## Acceptance criteria\n"
    "\n"
    "- [x] First\n"
    "- [ ] Second\n"
    "\n"
    "## Appendix\n"
    "\n"
    "trailing text"
)


def test_edit_leaves_a_persons_text_alone():
    edited = edit_body(HAND_EDITED, "requirement", {"desired_state": "Something.", "risk": "High"})
    document = Document(edited, "requirement")
    assert document.get("desired_state") == "Something."
    assert document.get("risk") == "High" and document.get("type") == "FUNC"
    # The unrecognised sections, the free text and the untouched fields are there byte for byte.
    for kept in (
        "Jeff: discussed with the team on Tuesday.\n",
        "## Notes from review\nWe should   revisit this.\n### A sub-heading\n\n```\n## not a heading\n```\n",
        "## Acceptance criteria\n\n- [x] First\n- [ ] Second\n\n",
        "## Appendix\n\ntrailing text",
        "## Current state\n\nNothing.\n\n",
    ):
        assert kept in edited
    assert document.other_sections == ["Notes from review", "Appendix"]
    # The new section went where the kind's order puts it: after Current state.
    assert edited.index("## Current state") < edited.index("## Desired state") < edited.index("## Notes from review")


def test_ticked_boxes_survive_an_edit_of_the_list():
    edited = edit_body(HAND_EDITED, "requirement", {"acceptance_criteria": ["Second", "First", "Third"]})
    assert Document(edited, "requirement").checklist("acceptance_criteria") == [
        ("Second", False),
        ("First", True),
        ("Third", False),
    ]


def test_removing_a_field_removes_its_section_only():
    edited = edit_body(HAND_EDITED, "requirement", {"current_state": None, "risk": ""})
    assert "## Current state" not in edited
    assert edited.startswith("**Type:** FUNC\n\nJeff: discussed")
    assert "## Notes from review\nWe should   revisit this." in edited


@pytest.mark.parametrize("body", ["", None, "   \n"])
def test_empty_body_is_a_record_with_no_fields(body):
    document = Document(body, "task")
    assert document.fields() == {} and not document.recognised


def test_body_the_server_did_not_write():
    document = Document("Just a sentence someone typed.\n\n## Steps\n1. one\n2. two", "task")
    assert document.fields() == {} and not document.recognised
    assert document.other_sections == ["Steps"]
    edited = edit_body(document.render(), "task", {"effort": "S", "test_plan": ["run it"]})
    assert edited == (
        "**Effort:** S\n\nJust a sentence someone typed.\n\n## Steps\n1. one\n2. two\n\n## Test plan\n\n- run it"
    )


def test_headings_are_matched_loosely_and_lists_read_tolerantly():
    document = Document(
        "## ACCEPTANCE CRITERIA:\r\n* [X] one\r\n* two\r\n   continued\r\n\r\n## test plan ##\n1. a\n2) b\n", "task"
    )
    assert document.checklist("acceptance_criteria") == [("one", True), ("two\ncontinued", False)]
    assert document.get("test_plan") == ["a", "b"]


def test_a_second_section_of_the_same_name_is_not_the_field():
    document = Document("## Context\n\nfirst\n\n## Context\n\nsecond\n", "decision")
    assert document.get("context") == "first"
    edited = edit_body(document.render(), "decision", {"context": "changed"})
    assert "## Context\n\nchanged\n\n## Context\n\nsecond" in edited


def test_references_are_issue_numbers():
    body = new_body("decision", {"addresses": ["#12", 7, "12"], "decision": "Do it."})
    assert body == "## Decision\n\nDo it.\n\n## Addresses\n\n- #12\n- #7"
    assert Document(body, "decision").get("addresses") == [12, 7]
    assert Document("## Addresses\nsee #3 and also #44\n", "decision").get("addresses") == [3, 44]
    with pytest.raises(ValueError, match="not an issue number"):
        new_body("decision", {"addresses": ["twelve"]})


def test_a_choice_field_refuses_other_values():
    with pytest.raises(ValueError, match="type must be one of FUNC"):
        new_body("requirement", {"type": "FEATURE"})


def test_project_description_is_its_purpose():
    body = new_body("project", {"purpose": "Ship v1.", "success_criteria": ["It works"]})
    assert body == "Ship v1.\n\n## Success criteria\n\n- It works"
    by_hand = Document("Everything for the autumn release.", "project")
    assert by_hand.get("purpose") == "Everything for the autumn release."
    assert edit_body(by_hand.render(), "project", {"out_of_scope": ["Mobile"]}) == (
        "Everything for the autumn release.\n\n## Out of scope\n\n- Mobile"
    )
