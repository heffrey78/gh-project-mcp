"""What each kind of record holds, and how each field is written in an issue body (ADR-0002).

This is the one description of the fields. The body codec reads it to find and write sections, the tools read it
to build their schemas, and the README's field tables are checked against it.
"""

from dataclasses import dataclass
from typing import Any

REQUIREMENT, DECISION, TASK, PROJECT = "requirement", "decision", "task", "project"
RECORD_KINDS = (REQUIREMENT, DECISION, TASK)

# How a field is written in the body.
TEXT = "text"  # a section of prose
LIST = "list"  # a section of bullets
CHECKLIST = "checklist"  # a section of task-list checkboxes, which a person ticks on github.com
REFS = "refs"  # a section of issue references
ATTR = "attr"  # one entry on the leading attribute line
LEAD = "lead"  # the text before the first heading

PRIORITIES = ("P0", "P1", "P2", "P3")
REQUIREMENT_TYPES = ("FUNC", "NFUNC", "TECH", "BUS", "INTF")


@dataclass(frozen=True)
class FieldSpec:
    name: str  # the parameter name tools use
    heading: str  # the section heading, or the label on the attribute line
    shape: str
    choices: tuple[str, ...] = ()
    managed: bool = False  # written by the server on a status move, not by update_record
    describe: str = ""

    def schema(self) -> dict[str, Any]:
        """The JSON schema of a value of this field."""
        if self.shape in (LIST, CHECKLIST):
            return {"type": "array", "items": {"type": "string"}}
        if self.shape == REFS:
            return {"type": "array", "items": {"type": ["integer", "string"]}}
        if self.choices:
            return {"enum": list(self.choices)}
        return {"type": "string"}


FIELDS: dict[str, tuple[FieldSpec, ...]] = {
    REQUIREMENT: (
        FieldSpec("type", "Type", ATTR, REQUIREMENT_TYPES),
        FieldSpec("risk", "Risk", ATTR, ("High", "Medium", "Low")),
        FieldSpec("origin", "Origin", ATTR, ("stated", "derived-from-code", "derived-from-transcript")),
        FieldSpec("current_state", "Current state", TEXT),
        FieldSpec("desired_state", "Desired state", TEXT),
        FieldSpec("business_value", "Business value", TEXT),
        FieldSpec("functional_requirements", "Functional requirements", LIST),
        FieldSpec("acceptance_criteria", "Acceptance criteria", CHECKLIST),
        FieldSpec("nonfunctional_requirements", "Non-functional requirements", LIST),
        FieldSpec("technical_constraints", "Technical constraints", LIST),
        FieldSpec("business_rules", "Business rules", LIST),
        FieldSpec("validation_metrics", "Validation metrics", LIST),
        FieldSpec("out_of_scope", "Out of scope", LIST),
    ),
    DECISION: (
        FieldSpec("context", "Context", TEXT),
        FieldSpec("decision", "Decision", TEXT),
        FieldSpec("decision_drivers", "Decision drivers", LIST),
        FieldSpec("considered_options", "Considered options", LIST),
        FieldSpec("positive_consequences", "Positive consequences", LIST),
        FieldSpec("negative_consequences", "Negative consequences", LIST),
        FieldSpec("risks", "Risks", LIST),
        FieldSpec("implementation_notes", "Implementation notes", TEXT),
        FieldSpec("validation_criteria", "Validation criteria", LIST),
        FieldSpec("addresses", "Addresses", REFS, managed=True),
        FieldSpec("supersedes", "Supersedes", REFS, managed=True),
    ),
    TASK: (
        FieldSpec("effort", "Effort", ATTR, ("XS", "S", "M", "L", "XL")),
        FieldSpec("commit", "Commit", ATTR, managed=True),
        FieldSpec("user_story", "User story", TEXT),
        FieldSpec("acceptance_criteria", "Acceptance criteria", CHECKLIST),
        FieldSpec("implementation_plan", "Implementation plan", LIST),
        FieldSpec("test_plan", "Test plan", LIST),
        FieldSpec("definition_of_done", "Definition of done", CHECKLIST),
        FieldSpec("blocked_reason", "Blocked reason", TEXT, managed=True),
        FieldSpec("evidence", "Evidence", TEXT, managed=True),
    ),
    # A project is a milestone; its description is written by the same codec.
    PROJECT: (
        FieldSpec("purpose", "Purpose", LEAD),
        FieldSpec("success_criteria", "Success criteria", LIST),
        FieldSpec("out_of_scope", "Out of scope", LIST),
    ),
}


def field_specs(kind: str) -> tuple[FieldSpec, ...]:
    return FIELDS[kind]


def editable_fields(kind: str) -> tuple[FieldSpec, ...]:
    """The fields a caller may set; the rest are written by status moves and links."""
    return tuple(spec for spec in FIELDS[kind] if not spec.managed)


def field_properties(kind: str, *names: str) -> dict[str, Any]:
    """JSON schema properties for a kind's editable fields, or for the named ones."""
    specs = editable_fields(kind)
    return {spec.name: spec.schema() for spec in specs if not names or spec.name in names}
