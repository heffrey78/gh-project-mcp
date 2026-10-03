# gh-project-mcp v1: lifecycle tracking on GitHub issues - Requirements Documentation

Generated on: 2026-10-03 08:11:04

**Project**: PROJ-0001 [Active]

**Purpose**: Build gh-project-mcp, an MCP server that gives an agent lifecycle-mcp's discipline (requirements that can disagree with the code, decisions that are not rewritten, tasks traced to the requirement they implement, human gates on approval and validation) with GitHub issues as the only store. It is lifecycle in spirit, built from the ground up: where GitHub already has a native feature (sub-issues, blocked-by dependencies, milestones, comments, the issue timeline, closing a task from a pull request) the server uses it instead of re-creating lifecycle-mcp's SQLite tables, so everything the agent records is readable, editable and linkable by a person on github.com with nothing installed.

**Success Criteria**:
- An agent can take a piece of work from requirement through decision and tasks to a validated requirement using only gh-project-mcp tools, and every record it made is a normal issue a person can read and edit on github.com
- The server keeps no database: deleting its process state loses nothing, and two machines pointed at the same repository see the same tracker
- The test suite runs with no network access and cannot create, edit or close anything on GitHub
- The tool listing is smaller than lifecycle-mcp's 25 tools and its size is held by a budget test
- A live run against a sandbox repository exercises every tool end to end

**Out of Scope**:
- Feature parity with lifecycle-mcp: its short-ID aliases, SQL dump/restore, HTML viewer, revision counters and field-edit event table are not carried over; GitHub's issue numbers, repository, web UI and edit history replace them
- GitHub Projects v2 boards and custom fields (needs the `project` token scope and is not portable across repositories); may follow as a later optional mirror
- Organisation-only features such as issue types
- Migrating an existing lifecycle.db into GitHub issues
- Multi-repository trackers: one server instance targets one repository
- Webhooks or any long-running sync process

## FUNC Requirements

### REQ-0001-FUNC-00: Requirements, decisions and tasks are GitHub issues a person can read and edit

- **Status**: Implemented
- **Priority**: P0
- **Risk Level**: Medium
- **Author**: Claude
- **Projects**: PROJ-0001: gh-project-mcp v1: lifecycle tracking on GitHub issues
- **Created**: 2026-10-02 18:50:56
- **Updated**: 2026-10-02 19:33:34

**Current State**: lifecycle-mcp keeps every record in a local SQLite file. Nobody can see a requirement without the server or an exported snapshot, the file cannot be diffed or merged, and its optional GitHub sync mirrors only tasks, one way, with its own conflict detection.

**Desired State**: Each requirement, architecture decision and task is one GitHub issue whose labels say what kind it is and whose body holds its fields as ordinary Markdown sections, created, read and edited through the server and equally usable on github.com.

**Business Value**: The tracker stops being a file only the agent can open. The owner reviews, corrects and discusses records where they already work.

**Functional Requirements**:
- Create a requirement (type, priority, current state, desired state, acceptance criteria, and the optional lists lifecycle-mcp carries), a decision (context, decision, options considered, consequences, drivers) and a task (user story, acceptance criteria, implementation plan, test plan, definition of done, effort)
- Read one record by issue number with its fields, status, links and comments
- Edit a record's fields in place, changing only the named fields and leaving every other part of the body as it was
- Query records by kind, status, priority, project and free text
- Acceptance criteria and definition-of-done items are rendered as GitHub task-list checkboxes
- An issue a person labelled by hand, with a body the server did not write, is still read as a record of that kind with whatever fields can be found

**Acceptance Criteria**:
- Creating each of the three kinds produces an issue with the kind label, the priority label and a body whose sections match the fields passed
- Parsing a body the server rendered and rendering it again yields identical text (round trip), for every kind
- Editing one field of an issue to which a person added an unrecognised section and free text leaves that section and text byte-for-byte unchanged
- A record is addressed by its issue number everywhere; `12` and `#12` are both accepted
- An issue with the kind label and an empty body reads as a record with empty fields, not an error

**Business Rules**:
- A decision's text is editable only while it is Proposed; a decided one takes a dated amendment comment or is superseded by a new decision
- Editing a requirement at Approved or later requires a reason, which is posted as a comment on the issue

**Out of Scope**:
- Deleting issues: GitHub needs admin rights for it and closing as not planned is the native way to retire a mistake
- Short-ID aliases and the REQ-/TASK-/ADR- identifier scheme

**Comments**:
- **MCP User** (2026-10-02 18:53:35): Approved by Claude on 2026-10-02 under the owner's instruction to plan the project, record requirements and ADRs, and then create tasks to execute. Written by Claude from the owner's brief and a reading of lifecycle-mcp; the owner has not yet read this text. Send back to Draft or edit with a reason if it does not match intent.
- **MCP User** (2026-10-02 19:33:34): Implemented by Claude on 2026-10-02. Every task under it is Complete with its evidence recorded on the task, and each acceptance criterion was checked against a named test: 245 tests pass with no network, lint is clean, and the handshake smoke passes against an isolated install of the command from a clean copy of the tree. Not Validated, and not mine to validate: everything that writes has been proven against the in-memory GitHub only. The live run (TASK-0016) is waiting on the owner, and read paths alone have been run against real GitHub. Nothing is committed; the owner has not asked for commits.

---

### REQ-0002-FUNC-00: Status lifecycles with human gates, held in labels and issue state

- **Status**: Implemented
- **Priority**: P0
- **Risk Level**: Medium
- **Author**: Claude
- **Projects**: PROJ-0001: gh-project-mcp v1: lifecycle tracking on GitHub issues
- **Created**: 2026-10-02 18:50:56
- **Updated**: 2026-10-02 19:33:34

**Current State**: A GitHub issue is only open or closed. lifecycle-mcp's value is the path between: a requirement cannot be built before it is approved or validated while its work is open, and those two decisions belong to a person. Its eight requirement statuses, though, made status moves 47% of all calls in the usage evidence, most of them walking records through intermediate states.

**Desired State**: Every record has a lifecycle status derived from its status label and its open/closed state, moved only along an allowed path, with Approved and Validated as stops that are never passed through on the way elsewhere.

**Business Value**: Keeps the one thing a plain issue tracker lacks: a requirement's state means something, and the two decisions that matter stay with a person.

**Functional Requirements**:
- Requirement: Draft, Under Review, Approved, Implemented, Validated (closed as completed), Deprecated (closed as not planned)
- Task: Not Started, In Progress, Blocked, Complete (closed as completed), Abandoned (closed as not planned)
- Decision: Proposed (open), Accepted (closed as completed), Rejected (closed as not planned), Superseded (closed, set only by a supersedes link)
- One status tool moves one record or a list of records, walking the shortest allowed path and reporting each step and a result per record
- Risky moves (starting or completing a task with unfinished dependencies, completing a task with open sub-tasks, marking a requirement Implemented while its tasks are open) warn by default, are refused under enforce and unchecked under off
- A move to Blocked keeps its comment as the blocked reason; a move to Complete can carry a commit and evidence

**Acceptance Criteria**:
- Draft to Approved walks through Under Review in one call and reports the path
- A move that would pass through Approved or Validated to reach another status is refused and nothing on GitHub changes
- A requirement cannot reach Validated while a task under it is open, in every rules mode
- A task closed on github.com or by a merged pull request reads as Complete with no server involvement
- An open issue with a kind label and no status label reads as the kind's first status (Draft, Not Started, Proposed)
- A list of IDs moves each on its own: refusals are reported per ID while the others still move

**Business Rules**:
- Approved and Validated are the owner's decisions: the server never reaches them as a side effect of another move
- Nothing moves on its own: when all of a requirement's tasks are complete the tracker says so and the person decides

**Out of Scope**:
- lifecycle-mcp's Architecture and Ready requirement statuses, dropped as intermediate states that only added calls
- The TDD/INTG decision status chain

**Comments**:
- **MCP User** (2026-10-02 18:53:35): Approved by Claude on 2026-10-02 under the owner's instruction to plan the project, record requirements and ADRs, and then create tasks to execute. Written by Claude from the owner's brief and a reading of lifecycle-mcp; the owner has not yet read this text. Send back to Draft or edit with a reason if it does not match intent.
- **MCP User** (2026-10-02 19:33:34): Implemented by Claude on 2026-10-02. Every task under it is Complete with its evidence recorded on the task, and each acceptance criterion was checked against a named test: 245 tests pass with no network, lint is clean, and the handshake smoke passes against an isolated install of the command from a clean copy of the tree. Not Validated, and not mine to validate: everything that writes has been proven against the in-memory GitHub only. The live run (TASK-0016) is waiting on the owner, and read paths alone have been run against real GitHub. Nothing is committed; the owner has not asked for commits.

---

### REQ-0003-FUNC-00: Traceability through GitHub's native links

- **Status**: Implemented
- **Priority**: P0
- **Risk Level**: Medium
- **Author**: Claude
- **Projects**: PROJ-0001: gh-project-mcp v1: lifecycle tracking on GitHub issues
- **Created**: 2026-10-02 18:50:56
- **Updated**: 2026-10-03 12:10:43

**Current State**: lifecycle-mcp stores every link in its own relationships table with twelve relationship types. GitHub now has sub-issues (with a progress summary) and blocked-by dependencies as first-class features, visible in the issue UI, which a private link table would duplicate and contradict.

**Desired State**: A requirement's tasks are its sub-issues, a task's subtasks are its sub-issues, a dependency is a GitHub blocked-by link, and a decision names the requirements it addresses and the decision it supersedes in its own body, so the whole trace is visible on github.com.

**Business Value**: Traceability a person can see and click through without asking the agent.

**Functional Requirements**:
- Creating a task attaches it as a sub-issue of the requirement it implements, or of a parent task
- Link and unlink tools cover: parent (sub-issue), blocked-by (dependency), addresses (decision to requirement) and supersedes (newer decision to older)
- A supersedes link moves the older decision to Superseded in the same call
- Reading a record shows its links from its own end: a requirement lists its tasks with progress and the decisions that address it
- A trace of a requirement returns the requirement, its decisions, and its task tree with statuses
- Circular parents and self-links are refused before any write

**Acceptance Criteria**:
- A task created for requirement #N appears under #N's sub-issues on github.com
- A sub-issue or dependency added by hand on github.com shows up in the server's next read
- Requirement progress counts leaf tasks only: a task with subtasks is counted through them
- Linking decision B supersedes decision A closes A with the superseded label and a comment naming B, and A's details name B
- A task is never offered a second parent: the refusal names the one it has

**Technical Constraints**:
- A GitHub issue has at most one parent, so a task implements exactly one requirement; further requirements it touches are named in its body
- GitHub limits sub-issues to 100 per parent and eight levels of nesting

**Out of Scope**:
- lifecycle-mcp's informs, refines, conflicts and relates link types: a mention in a comment already cross-references two issues

**Comments**:
- **MCP User** (2026-10-02 18:53:35): Approved by Claude on 2026-10-02 under the owner's instruction to plan the project, record requirements and ADRs, and then create tasks to execute. Written by Claude from the owner's brief and a reading of lifecycle-mcp; the owner has not yet read this text. Send back to Draft or edit with a reason if it does not match intent.
- **MCP User** (2026-10-03 12:10:43): Implemented by Claude on 2026-10-03, after the live run. Every task under it is Complete with evidence. Tests cannot reach the network (guard), the access layer passed its contract tests against a real private sandbox, and links are native sub-issues and blocked-by links checked on github.com. Validation is the owner's.

---

### REQ-0004-FUNC-00: Projects are milestones with a stated purpose

- **Status**: Implemented
- **Priority**: P1
- **Risk Level**: Low
- **Author**: Claude
- **Projects**: PROJ-0001: gh-project-mcp v1: lifecycle tracking on GitHub issues
- **Created**: 2026-10-02 18:50:56
- **Updated**: 2026-10-02 19:33:34

**Current State**: lifecycle-mcp groups requirements into projects with its own table and part_of links. GitHub already has a grouping with a title, a description, an open/closed state and a progress bar: the milestone.

**Desired State**: A project is a GitHub milestone whose description holds its purpose, success criteria and what is out of scope; a requirement joins it by being assigned to the milestone, and its tasks follow it.

**Business Value**: Epics and roadmap items with a purpose on record, using the grouping GitHub users already know.

**Functional Requirements**:
- Create a project: title, purpose, success criteria, out of scope
- Edit a project and close or reopen it
- Assign a requirement to a project when creating it or afterwards; tasks created under the requirement take the same milestone
- Query records by project
- The dashboard lists open projects with their requirement and task progress

**Acceptance Criteria**:
- Creating a project creates a milestone whose description opens with the purpose
- A task created under a requirement in a project carries that milestone
- A milestone created by hand on github.com with a free-text description reads as a project whose purpose is that text
- Exported documents for a project open with its stored purpose

**Technical Constraints**:
- An issue has one milestone, so a requirement is in at most one project (lifecycle-mcp allowed several)

**Comments**:
- **MCP User** (2026-10-02 18:53:35): Approved by Claude on 2026-10-02 under the owner's instruction to plan the project, record requirements and ADRs, and then create tasks to execute. Written by Claude from the owner's brief and a reading of lifecycle-mcp; the owner has not yet read this text. Send back to Draft or edit with a reason if it does not match intent.
- **MCP User** (2026-10-02 19:33:34): Implemented by Claude on 2026-10-02. Every task under it is Complete with its evidence recorded on the task, and each acceptance criterion was checked against a named test: 245 tests pass with no network, lint is clean, and the handshake smoke passes against an isolated install of the command from a clean copy of the tree. Not Validated, and not mine to validate: everything that writes has been proven against the in-memory GitHub only. The live run (TASK-0016) is waiting on the owner, and read paths alone have been run against real GitHub. Nothing is committed; the owner has not asked for commits.

---

### REQ-0005-FUNC-00: A dashboard that says what needs attention, including drift made on github.com

- **Status**: Implemented
- **Priority**: P1
- **Risk Level**: Medium
- **Author**: Claude
- **Projects**: PROJ-0001: gh-project-mcp v1: lifecycle tracking on GitHub issues
- **Created**: 2026-10-02 18:50:56
- **Updated**: 2026-10-02 19:33:34

**Current State**: GitHub shows lists of issues, not what to do next. lifecycle-mcp's dashboard answers that (ready, blocked and why, work complete with the decision pending), but it can assume every change went through its own rules. Here anyone can relabel or close an issue on github.com.

**Desired State**: One call reports the tracker's health: counts by status, tasks ready to start, blocked and waiting work with reasons, requirements whose work is complete and only the decision is missing, and records whose state on GitHub breaks a rule, reported and never silently repaired.

**Business Value**: Tells the agent and the owner what to do next, and keeps the tracker honest when people edit it directly.

**Functional Requirements**:
- Counts of requirements, tasks and decisions by status, and progress per open project
- Ready to start: Not Started tasks under an Approved-or-later requirement whose blockers are all Complete, highest priority first
- Blocked: every Blocked task with its reason and every task waiting on an open blocker, naming it
- Work complete, decision pending: requirements whose tasks are all Complete or Abandoned but that are not Implemented
- Drift: records with two status labels, a requirement Validated while a task under it is open, a task in progress under a requirement that is not approved, a record with a kind label and a body with no recognisable fields
- The same definitions back the query filters `ready` and `work_complete`

**Acceptance Criteria**:
- Each section appears only when it has rows, and an empty ready list says which case it is: nothing left, everything waiting, or only in-progress work
- A requirement closed as completed on github.com with an open task is listed under drift, and no write is made
- The dashboard's figures are also returned as structured data
- The dashboard names the repository it is reading

**Business Rules**:
- A signal that always fires teaches the reader to ignore it: no section lists a record on the day it was created merely for being new
- The server reports drift; it never corrects a person's edit

**Comments**:
- **MCP User** (2026-10-02 18:53:35): Approved by Claude on 2026-10-02 under the owner's instruction to plan the project, record requirements and ADRs, and then create tasks to execute. Written by Claude from the owner's brief and a reading of lifecycle-mcp; the owner has not yet read this text. Send back to Draft or edit with a reason if it does not match intent.
- **MCP User** (2026-10-02 19:33:34): Implemented by Claude on 2026-10-02. Every task under it is Complete with its evidence recorded on the task, and each acceptance criterion was checked against a named test: 245 tests pass with no network, lint is clean, and the handshake smoke passes against an isolated install of the command from a clean copy of the tree. Not Validated, and not mine to validate: everything that writes has been proven against the in-memory GitHub only. The live run (TASK-0016) is waiting on the owner, and read paths alone have been run against real GitHub. Nothing is committed; the owner has not asked for commits.

---

### REQ-0006-FUNC-00: Every change leaves its trail on the issue

- **Status**: Implemented
- **Priority**: P1
- **Risk Level**: Low
- **Author**: Claude
- **Projects**: PROJ-0001: gh-project-mcp v1: lifecycle tracking on GitHub issues
- **Created**: 2026-10-02 18:50:56
- **Updated**: 2026-10-02 19:33:34

**Current State**: lifecycle-mcp logs field edits, status changes and comments in its own event table and keeps commit and evidence columns on tasks. GitHub already records label changes, closes, body edits and comments on each issue's timeline, attributed and dated.

**Desired State**: The reason behind a status move, the evidence behind a completed task and the correction to a decided decision are recorded on the issue itself: each status move posts a comment, so GitHub's timeline is the history, and the facts that are current (why a task is blocked, the commit and evidence behind its completion) are also kept as sections of the issue body, so they can be read without fetching comments.

**Business Value**: The reasoning behind a completed task survives the hand-off, in the place a reviewer will look.

**Functional Requirements**:
- Comment on any record
- A status move's comment, commit and evidence are posted as one comment on the issue in a recognisable form
- A Blocked task's reason is kept in a `Blocked reason` body section while it is Blocked and removed when it leaves; a task's commit and evidence are kept in an `Evidence` body section until replaced
- An amendment to an Accepted decision is a dated comment marked as an amendment and shown directly beneath the decision in details and export
- A history view returns an issue's timeline: creation, label and state changes, body edits, comments, links

**Acceptance Criteria**:
- Completing a task with commit and evidence produces a comment naming both, and reading the task shows them
- Moving a Blocked task elsewhere stops showing the old reason
- Amending an Accepted decision leaves the issue body unchanged
- History lists events oldest first and includes changes made on github.com

**Out of Scope**:
- Per-field before and after values: GitHub keeps body edit history and shows it in the UI
- Revision counters

**Comments**:
- **MCP User** (2026-10-02 18:53:35): Approved by Claude on 2026-10-02 under the owner's instruction to plan the project, record requirements and ADRs, and then create tasks to execute. Written by Claude from the owner's brief and a reading of lifecycle-mcp; the owner has not yet read this text. Send back to Draft or edit with a reason if it does not match intent.
- **MCP User** (2026-10-02 19:33:34): Implemented by Claude on 2026-10-02. Every task under it is Complete with its evidence recorded on the task, and each acceptance criterion was checked against a named test: 245 tests pass with no network, lint is clean, and the handshake smoke passes against an isolated install of the command from a clean copy of the tree. Not Validated, and not mine to validate: everything that writes has been proven against the in-memory GitHub only. The live run (TASK-0016) is waiting on the owner, and read paths alone have been run against real GitHub. Nothing is committed; the owner has not asked for commits.

---

### REQ-0007-FUNC-00: Export the tracker as Markdown documents and a Mermaid diagram

- **Status**: Implemented
- **Priority**: P2
- **Risk Level**: Low
- **Author**: Claude
- **Projects**: PROJ-0001: gh-project-mcp v1: lifecycle tracking on GitHub issues
- **Created**: 2026-10-02 18:51:46
- **Updated**: 2026-10-02 19:33:34

**Current State**: Issues are scattered pages. There is no single document that reads top to bottom as the requirements, the decisions behind them and the work done, the way lifecycle-mcp's export does.

**Desired State**: One tool writes requirements, decisions and tasks documents for the whole tracker or one project, each opening with the project's stored purpose, and one tool draws the record graph as Mermaid.

**Business Value**: A document to hand to someone who will not click through fifty issues, and decisions readable in the repository as files.

**Functional Requirements**:
- Requirements document grouped by project then type, decisions document with amendments beneath each decision, tasks document grouped by status with commit and evidence
- Each record links back to its issue URL
- A Mermaid graph of requirements, tasks and decisions with their links, coloured by status, optionally limited to one project
- Exports are deterministic: an unchanged tracker exports identical bytes

**Acceptance Criteria**:
- Exporting one project writes only its records and opens with its purpose
- Running the export twice against an unchanged tracker produces identical files
- The diagram response says what was drawn and what a limit left out

**Comments**:
- **MCP User** (2026-10-02 18:53:35): Approved by Claude on 2026-10-02 under the owner's instruction to plan the project, record requirements and ADRs, and then create tasks to execute. Written by Claude from the owner's brief and a reading of lifecycle-mcp; the owner has not yet read this text. Send back to Draft or edit with a reason if it does not match intent.
- **MCP User** (2026-10-02 19:33:34): Implemented by Claude on 2026-10-02. Every task under it is Complete with its evidence recorded on the task, and each acceptance criterion was checked against a named test: 245 tests pass with no network, lint is clean, and the handshake smoke passes against an isolated install of the command from a clean copy of the tree. Not Validated, and not mine to validate: everything that writes has been proven against the in-memory GitHub only. The live run (TASK-0016) is waiting on the owner, and read paths alone have been run against real GitHub. Nothing is committed; the owner has not asked for commits.

---

## INTF Requirements

### REQ-0001-INTF-00: A small, strict tool surface with prompts for capture and reconciliation

- **Status**: Implemented
- **Priority**: P0
- **Risk Level**: Medium
- **Author**: Claude
- **Projects**: PROJ-0001: gh-project-mcp v1: lifecycle tracking on GitHub issues
- **Created**: 2026-10-02 18:51:46
- **Updated**: 2026-10-02 19:33:34

**Current State**: lifecycle-mcp lists 25 tools, about 17,000 characters of definitions sent on every request. Its usage evidence shows per-kind create/update/status/query tools repeating the same field lists, nine tools never called in two full sessions, and refused calls that were invisible until validation moved into the server.

**Desired State**: The server lists a small set of kind-generic tools whose total definition size is held by a budget test, refuses undeclared or mistyped arguments by name with a suggestion, returns the same facts as text and as structured data, and offers requirement capture and reconciliation as MCP prompts rather than tools.

**Business Value**: Every tool definition costs the client context on every request; a smaller surface is cheaper and easier for an agent to choose from.

**Functional Requirements**:
- Tools are generic over record kind where the behaviour is the same: one get, one query, one status, one comment, one link and one unlink tool serve all kinds
- Every tool schema sets additionalProperties false; a refused call names the field at fault and, when a near-named sibling parameter would have accepted the value, names it
- Tool failures reach the client with isError true
- Create tools return the new issue number and URL, status tools the old and new status per record, queries the matching records, each also as structuredContent
- New records that are thin for their kind (a requirement with no acceptance criteria, an NFUNC requirement with no validation metrics, a P0/P1 task with no test plan) say so through the workflow rules
- Prompts `capture_requirement` and `reconcile_requirements`, adapted from lifecycle-mcp, costing nothing against the tool budget
- An optional call log appends one JSON line per call: tool, argument names (never values), duration, error kind, response size

**Acceptance Criteria**:
- A budget file holds the tool count and total definition size, and a test fails when either is exceeded
- The server lists at most 16 tools
- An ID parameter accepts `12` or `#12`, and the status tool's `ids` accepts one ID or a list, so the commonest call cannot be refused for its shape
- Where a refused parameter has a near-named sibling in the same schema that would accept the value, the refusal names it
- Query results are compact by default (number, title, status, priority per record) and never return every field of every record unless asked
- No tool declares a parameter its handler ignores, and no handler reads a parameter the schema does not declare

**Non-Functional Requirements**:
- Tool definitions total no more than 9,000 characters of compact JSON

**Validation Metrics**:
- tools/list definition size in compact JSON characters, measured by the budget test: at most 9,000 (lifecycle-mcp: about 17,000)
- Tool count: at most 16 (lifecycle-mcp: 25)

**Comments**:
- **MCP User** (2026-10-02 18:53:35): Approved by Claude on 2026-10-02 under the owner's instruction to plan the project, record requirements and ADRs, and then create tasks to execute. Written by Claude from the owner's brief and a reading of lifecycle-mcp; the owner has not yet read this text. Send back to Draft or edit with a reason if it does not match intent.
- **MCP User** (2026-10-02 19:33:34): Implemented by Claude on 2026-10-02. Every task under it is Complete with its evidence recorded on the task, and each acceptance criterion was checked against a named test: 245 tests pass with no network, lint is clean, and the handshake smoke passes against an isolated install of the command from a clean copy of the tree. Not Validated, and not mine to validate: everything that writes has been proven against the in-memory GitHub only. The live run (TASK-0016) is waiting on the owner, and read paths alone have been run against real GitHub. Nothing is committed; the owner has not asked for commits.

---

## NFUNC Requirements

### REQ-0001-NFUNC-00: Tests and development can never touch a real repository

- **Status**: Implemented
- **Priority**: P0
- **Risk Level**: High
- **Author**: Claude
- **Projects**: PROJ-0001: gh-project-mcp v1: lifecycle tracking on GitHub issues
- **Created**: 2026-10-02 18:51:46
- **Updated**: 2026-10-03 12:10:43

**Current State**: lifecycle-mcp's test suite created 1,049 real "Test Task" issues on its own upstream repository before anyone noticed, because fixtures ran the real GitHub code path whenever `gh` was authenticated. A server whose every write goes to GitHub makes that mistake far easier to repeat.

**Desired State**: The test suite runs against an in-memory GitHub and fails any test that opens a network connection or spawns `gh` or `git`; talking to a real repository is a separately marked, opt-in run against a named sandbox.

**Business Value**: The mistake that cost the original project a thousand junk issues cannot happen here.

**Functional Requirements**:
- An in-memory fake implements the same interface as the real GitHub client: issues, labels, comments, milestones, sub-issues, dependencies, timeline
- A suite-wide fixture fails any test that opens a socket or spawns a subprocess
- Live tests are marked `github_live`, skipped unless `GH_PROJECT_LIVE_REPO` names a sandbox, refuse to run against any repository whose name does not contain `sandbox`, and close what they create
- The server writes only protocol messages to stdout; logging goes to stderr

**Acceptance Criteria**:
- `uv run pytest` passes with networking disabled
- A test that calls the real client without the live marker fails with a message naming the guard
- A handshake smoke test starts the installed server and finds stdout to be pure JSON-RPC
- The real client and the fake are exercised by the same contract tests, the real one only in the live run

**Validation Metrics**:
- Network connections opened by the default test run: 0, enforced by the guard fixture
- Issues created on any real repository by the default test run: 0
- Default suite wall time under 30 seconds

**Comments**:
- **MCP User** (2026-10-02 18:53:35): Approved by Claude on 2026-10-02 under the owner's instruction to plan the project, record requirements and ADRs, and then create tasks to execute. Written by Claude from the owner's brief and a reading of lifecycle-mcp; the owner has not yet read this text. Send back to Draft or edit with a reason if it does not match intent.
- **MCP User** (2026-10-03 12:10:43): Implemented by Claude on 2026-10-03, after the live run. Every task under it is Complete with evidence. Tests cannot reach the network (guard), the access layer passed its contract tests against a real private sandbox, and links are native sub-issues and blocked-by links checked on github.com. Validation is the owner's.

---

### REQ-0002-NFUNC-00: The tracker reads fast and stays inside GitHub's rate limits

- **Status**: Implemented
- **Priority**: P1
- **Risk Level**: Medium
- **Author**: Claude
- **Projects**: PROJ-0001: gh-project-mcp v1: lifecycle tracking on GitHub issues
- **Created**: 2026-10-02 18:51:46
- **Updated**: 2026-10-03 12:10:43

**Current State**: With SQLite a dashboard is one local query. Against GitHub a naive dashboard is one request per issue plus one per issue for its sub-issues and dependencies: hundreds of requests and tens of seconds for a modest tracker, against a limit of 5,000 requests an hour.

**Desired State**: Reading the whole tracker costs a small, bounded number of requests that grows with pages of 100 records rather than with records, and repeated reads within a session reuse what was fetched.

**Business Value**: The agent calls the dashboard many times a session; it has to be cheap enough to call without thinking.

**Functional Requirements**:
- One paginated GraphQL query returns every lifecycle issue with its body, labels, state, milestone, parent, sub-issue and blocked-by links
- The snapshot is held in memory for the life of the process, updated in place by the server's own writes, and refreshed by asking only for issues updated since the last fetch
- Comments and timelines are fetched only for the records a call needs, never for the whole tracker

**Acceptance Criteria**:
- A cold dashboard over 200 records makes at most 4 requests
- A warm dashboard makes one request per 100 open records, and at most 1 when 100 or fewer are open
- A change made on github.com between two calls is visible in the second, including a sub-issue or blocked-by link added to an open record
- The request count per tool call is asserted in tests against the fake

**Validation Metrics**:
- Requests for a cold dashboard over 200 records: at most 4, counted by the fake in a test (measured: 3)
- Requests for a warm dashboard: one per 100 open records (measured on real GitHub with few open records: 1)
- Requests to create a task under a requirement: at most 4 (measured: 3)

**Comments**:
- **MCP User** (2026-10-02 18:53:35): Approved by Claude on 2026-10-02 under the owner's instruction to plan the project, record requirements and ADRs, and then create tasks to execute. Written by Claude from the owner's brief and a reading of lifecycle-mcp; the owner has not yet read this text. Send back to Draft or edit with a reason if it does not match intent.
- **MCP User** (2026-10-02 19:33:34): Implemented by Claude on 2026-10-02. Every task under it is Complete with its evidence recorded on the task, and each acceptance criterion was checked against a named test: 245 tests pass with no network, lint is clean, and the handshake smoke passes against an isolated install of the command from a clean copy of the tree. Not Validated, and not mine to validate: everything that writes has been proven against the in-memory GitHub only. The live run (TASK-0016) is waiting on the owner, and read paths alone have been run against real GitHub. Nothing is committed; the owner has not asked for commits.

---

## TECH Requirements

### REQ-0001-TECH-00: GitHub is the only store, reached through one access layer aimed at an explicitly named repository

- **Status**: Implemented
- **Priority**: P0
- **Risk Level**: High
- **Author**: Claude
- **Projects**: PROJ-0001: gh-project-mcp v1: lifecycle tracking on GitHub issues
- **Created**: 2026-10-02 18:51:46
- **Updated**: 2026-10-03 12:10:43

**Current State**: lifecycle-mcp's GitHub code shells out to `gh` per call, infers the repository from the working directory's origin remote, swallows failures into None, and treats the local database as the truth. That inference once sent test issues to the upstream repository.

**Desired State**: All reads and writes go through a single GitHub access layer that talks to one repository named in configuration, authenticates with a token from the environment or the gh CLI, surfaces API failures as tool errors with GitHub's own message, and keeps no state on disk.

**Business Value**: One place to reason about auth, limits and failure, and no way to write to a repository nobody named.

**Functional Requirements**:
- The repository is named by `GH_PROJECT_REPO=owner/name`; without it the server starts, lists its tools and answers every call with how to set it
- Token from `GH_TOKEN` or `GITHUB_TOKEN`, else `gh auth token`; a missing or rejected token is reported as such
- The labels the server needs are created on first write when missing, and a setup tool creates them all and reports what it did
- Pagination is followed to the end; rate-limit and abuse responses are reported with the reset time rather than retried blindly
- A read-only mode (`GH_PROJECT_READ_ONLY=on`) refuses every write before any request is made
- GitHub Enterprise hosts are reachable by setting the API base URL

**Acceptance Criteria**:
- With no repository configured, no request is made to GitHub
- A 404, 403 or 422 from GitHub reaches the client as an error carrying GitHub's message and the request that failed
- Killing and restarting the server loses nothing: the next read shows the same tracker
- In read-only mode every write tool is refused and names the setting
- The token never appears in a log line, an error message or the call log

**Technical Constraints**:
- Needs only the `repo` token scope
- Sub-issue and dependency writes need the issue's node or database ID, not its number

**Comments**:
- **MCP User** (2026-10-02 18:53:35): Approved by Claude on 2026-10-02 under the owner's instruction to plan the project, record requirements and ADRs, and then create tasks to execute. Written by Claude from the owner's brief and a reading of lifecycle-mcp; the owner has not yet read this text. Send back to Draft or edit with a reason if it does not match intent.
- **MCP User** (2026-10-03 12:10:43): Implemented by Claude on 2026-10-03, after the live run. Every task under it is Complete with evidence. Tests cannot reach the network (guard), the access layer passed its contract tests against a real private sandbox, and links are native sub-issues and blocked-by links checked on github.com. Validation is the owner's.

---

### REQ-0002-TECH-00: Installable package with CI, documentation and a working first run

- **Status**: Implemented
- **Priority**: P1
- **Risk Level**: Low
- **Author**: Claude
- **Projects**: PROJ-0001: gh-project-mcp v1: lifecycle tracking on GitHub issues
- **Created**: 2026-10-02 18:51:46
- **Updated**: 2026-10-02 19:33:34

**Current State**: The repository is empty. lifecycle-mcp's first-contact failures were an unpinned MCP SDK that broke fresh installs, output on stdout that corrupted the protocol, and documentation whose tool counts went stale.

**Desired State**: `uv tool install .` yields a `gh-project-mcp` command that a client can register in one line, with pinned dependencies, lint and tests in CI, a README that takes a newcomer from install to first requirement, and a CLAUDE.md holding the rules a contributor cannot infer from the code.

**Business Value**: Someone other than its author can install and use it.

**Functional Requirements**:
- Python package under `src/gh_project_mcp` with entry point `gh-project-mcp`, built on the MCP SDK 2.x low-level server
- Dependencies pinned to compatible ranges with a committed lockfile
- `make lint` and `make test` run exactly what CI runs
- GitHub Actions workflow: lint, tests on the supported Python versions, install-and-handshake smoke
- README: what it is and how it differs from lifecycle-mcp, install, configuration, the label and body conventions, tool reference, workflow rules
- CLAUDE.md and a CHANGELOG

**Acceptance Criteria**:
- From a fresh clone, `uv sync` then `uv run pytest` passes
- The handshake smoke test passes against the installed command
- The README's tool list is checked against the server's tool listing by a test
- ruff passes with print() banned in `src/`

**Technical Constraints**:
- Python 3.11 or later
- `mcp>=2.2,<3`; runtime dependencies limited to mcp, httpx and jsonschema

**Comments**:
- **MCP User** (2026-10-02 18:53:35): Approved by Claude on 2026-10-02 under the owner's instruction to plan the project, record requirements and ADRs, and then create tasks to execute. Written by Claude from the owner's brief and a reading of lifecycle-mcp; the owner has not yet read this text. Send back to Draft or edit with a reason if it does not match intent.
- **MCP User** (2026-10-02 19:33:34): Implemented by Claude on 2026-10-02. Every task under it is Complete with its evidence recorded on the task, and each acceptance criterion was checked against a named test: 245 tests pass with no network, lint is clean, and the handshake smoke passes against an isolated install of the command from a clean copy of the tree. Not Validated, and not mine to validate: everything that writes has been proven against the in-memory GitHub only. The live run (TASK-0016) is waiting on the owner, and read paths alone have been run against real GitHub. Nothing is committed; the owner has not asked for commits.

---

