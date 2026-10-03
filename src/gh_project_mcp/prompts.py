"""Prompts the server offers clients, adapted from lifecycle-mcp.

A prompt is text the client's own model fills in and then passes to a tool. Nothing is kept on the server between
calls, and prompts are a separate MCP primitive from tools, so they cost nothing against the tool surface budget.

The reconcile prompt searches per candidate rather than opening with the whole set, because the whole set does not
fit: lifecycle-mcp's first real run of it asked for 25 requirements and got back more than a client would accept.
"""

from mcp import types

CAPTURE_REQUIREMENT = "capture_requirement"
RECONCILE_REQUIREMENTS = "reconcile_requirements"

_GUIDE = """Write a requirement, then create it with the create_requirement tool. It becomes a GitHub issue.

Ask the person what they need, in their words, and fill these fields yourself. Do not ask them to name fields.

Required:
- title: what changes, in a few words
- type: FUNC (behaviour), NFUNC (speed, size, reliability), TECH (how it is built), BUS (policy), INTF (an interface)
- priority: P0 urgent, P1 next, P2 soon, P3 someday
- current_state: what happens today, concretely. Name the thing that is wrong, not the absence of the fix
- desired_state: what should happen instead, in one sentence

Worth filling, and warned about when missing:
- acceptance_criteria: how anyone can tell it is done. One line each, checkable without you in the room. They
  become checkboxes on the issue
- validation_metrics: for NFUNC, the number that settles it, such as "search p95 under 50 ms at 10k notes".
  A requirement about speed with no number cannot be checked later, only argued about

Fill when they apply:
- functional_requirements: what it has to do, one line each
- nonfunctional_requirements, technical_constraints, business_rules
- out_of_scope: what this deliberately does not cover, so it stops coming up
- business_value: why it is worth doing
- risk: High, Medium or Low
- project: the project (milestone) it belongs to. get_status lists the open ones. Pick by what each project is for,
  and ask when it is not obvious: a requirement left out of its project is missing from that project's documents

A worked example:

  create_requirement(
    title="Search stays fast as notes grow",
    type="NFUNC",
    priority="P1",
    current_state="Search runs unindexed over every note; at 10k notes a query takes about 900 ms.",
    desired_state="Search stays quick as the collection grows.",
    acceptance_criteria=["A search over 10k notes returns in under 50 ms at p95"],
    validation_metrics=["Search p95 under 50 ms at 10k notes, measured by the benchmark task"],
    out_of_scope=["Ranking quality, which #3 covers"],
  )

Create the requirement in one call once you have the fields. If something is thin the result says so, and you can
fill it in afterwards with update_record. It is created in Draft. Moving it to Approved is the person's decision:
ask, do not assume."""


_RECONCILE = """Compare what a source says about requirements with the requirements already on GitHub, then report \
and apply the difference.

The source is a transcript, a design document, a reading of a codebase, or anything else that describes what a system
has to do. You read it; the server does not. Work in this order and do not skip a step.

1. Find the candidates in the source: each thing it says the system must do, be, or be built from.
2. For each candidate, search for what may already cover it. Call query_records with kind="requirement" and
   search, using the words a stored requirement would use rather than the words the source used, and search again
   with another wording when the first finds nothing. Every word of `search` must appear in the issue's title or
   body, so two or three distinctive words find more than a sentence does.
   Do not open by asking for every requirement with `full`: the set only grows, and all of it at once is more than
   many clients accept in one result. Do not filter by status to make it fit: a Validated requirement covers a
   candidate exactly as well as a Draft one, and the ones most likely to cover a candidate are the ones already
   built.
3. Put every candidate in exactly one of four buckets, and name the stored requirement for the last three:
   - NEW: nothing stored covers it
   - AMENDS #N: a stored requirement covers it, and the source changes or adds to what it says
   - ALREADY COVERED by #N: stored, and the source says nothing new
   - CONTRADICTS #N: the source asserts something the stored requirement denies
4. Report the four buckets before you write anything, so the person can see what you are about to do, and say how
   you looked: which searches you ran, and whether you ever saw the whole set. Someone who knows you tried three
   wordings and found nothing can weigh a NEW differently from one you never checked.
5. Then apply only the first two:
   - NEW: create_requirement, with origin set to derived-from-code or derived-from-transcript, whichever the source
     was. It is created in Draft, which is where it stays until a person approves it. When the tracker has projects
     (get_status lists them), pass project for the one it plainly belongs to and say which you chose
   - AMENDS: update_record on that issue, naming only the fields that change, with a reason. Never create a second
     issue for a requirement that already exists
   - ALREADY COVERED: do nothing at all
   - CONTRADICTS: do nothing, and say so plainly. Resolving a contradiction is the reader's decision, not yours.
     A stored requirement that disagrees with the code is the tracker doing its job, not an error to clear

What the buckets are for: a requirement is worth storing because it can disagree with the code. If you quietly
rewrite stored requirements to match the source, the tracker becomes a mirror of the source and can no longer tell
anyone that something is wrong. So the default is to report, and the only silent action is doing nothing.

Cautions:
- Code is evidence of behaviour and silent about intent. It cannot tell you what was deliberately rejected, or why.
  Read the docs and decision records beside it, and when they disagree with the code, that disagreement is a finding
  worth reporting rather than something to average out
- If the tracker holds no requirements, say so in the report. Everything being new is a fact about the tracker, not
  a finding about the source
- Searching can miss, and a duplicate costs more than a question. When a candidate looks new but the area is one the
  system plainly already works in, say NEW and flag that you could not confirm it, rather than creating an issue
  that repeats one your searches did not reach
- Every record you create is an issue other people will see. Fewer, well-formed requirements a person can review in
  one sitting beat one per function

Use the capture_requirement prompt for the fields a good requirement carries."""


def prompt_definitions() -> list[types.Prompt]:
    """Every prompt this server offers."""
    return [
        types.Prompt(
            name=CAPTURE_REQUIREMENT,
            description="Guide for writing a well-formed requirement, then creating it with create_requirement",
            arguments=[
                types.PromptArgument(
                    name="about", description="What the requirement is about, in the person's own words", required=False
                )
            ],
        ),
        types.Prompt(
            name=RECONCILE_REQUIREMENTS,
            description="Compare a transcript, document or codebase against the stored requirements and apply the "
            "difference as new and amended records",
            arguments=[
                types.PromptArgument(
                    name="source", description="The text to reconcile, or where to read it", required=False
                ),
                types.PromptArgument(name="source_kind", description="transcript, code, or document", required=False),
            ],
        ),
    ]


def _message(description: str, text: str) -> types.GetPromptResult:
    content = types.TextContent(type="text", text=text)
    return types.GetPromptResult(description=description, messages=[types.PromptMessage(role="user", content=content)])


def render_prompt(name: str, arguments: dict[str, str] | None = None) -> types.GetPromptResult:
    """The text for one prompt. Raises ValueError for a name this server does not offer."""
    given = arguments or {}
    if name == CAPTURE_REQUIREMENT:
        about = given.get("about")
        text = _GUIDE if not about else f'{_GUIDE}\n\nWhat they said they need:\n"{about}"'
        return _message("Write a requirement and create it", text)
    if name == RECONCILE_REQUIREMENTS:
        text = _RECONCILE
        if given.get("source_kind"):
            text += f"\n\nThe source is: {given['source_kind']}"
        if given.get("source"):
            text += f"\n\nThe source:\n{given['source']}"
        return _message("Reconcile a source against the stored requirements", text)
    offered = ", ".join(prompt.name for prompt in prompt_definitions())
    raise ValueError(f"Unknown prompt: {name}. This server offers: {offered}")
