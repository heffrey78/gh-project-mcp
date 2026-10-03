# gh-project-mcp v1: lifecycle tracking on GitHub issues - Tasks Documentation

Generated on: 2026-10-02 15:33:38

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

## Complete Tasks

### TASK-0001-00-00: Scaffold the repository: package, tooling, CI and the network guard

- **Status**: Complete
- **Priority**: P0
- **Effort**: S
- **Assignee**: Claude
- **Created**: 2026-10-02 18:54:34
- **Updated**: 2026-10-02 18:58:48
- **Evidence**: uv sync ok on Python 3.12.4; `uv run --extra test pytest`: 5 passed (tests/test_network_guard.py: socket connect, create_connection, subprocess.run, asyncio subprocess all refused; developer env does not leak); `ruff check` and `ruff format --check` clean.

**User Story**: As a contributor, I want a repository where `uv sync`, `make lint` and `make test` work from the first commit, and where no test can reach the network, so every later task lands on safe ground.

**Acceptance Criteria**:
- uv sync && uv run pytest passes on an empty suite plus the guard's own tests
- A test that opens a socket fails naming the guard; one that spawns a subprocess does too
- make lint passes

**Implementation Plan**:
- git init on main; .gitignore (lifecycle.db and WAL files, exports, .venv, caches)
- pyproject.toml: src layout, entry point gh-project-mcp, deps mcp>=2.2,<3, httpx, jsonschema; test and dev extras; ruff config with T20; pytest config with the github_live marker
- tests/conftest.py: autouse guard that fails any test opening a socket or spawning a subprocess, lifted only by the github_live marker
- Makefile with lint and test targets; .github/workflows/test.yml running the same
- uv lock

**Test Plan**:
- tests/test_network_guard.py: socket.create_connection and subprocess.run each raise inside a test
- Run make lint and make test locally

**Definition of Done**:
- First commit on main with lint and tests green

**Linked Requirements**:
- REQ-0001-NFUNC-00: Tests and development can never touch a real repository
- REQ-0002-TECH-00: Installable package with CI, documentation and a working first run

**Comments**:
- **MCP User** (2026-10-02 18:58:48): Not committed: the owner has not asked for commits, so 'first commit on main' in the definition of done is left to them. Repository initialised on main with pyproject, Makefile, CI workflow, .gitignore and the guard.

---

### TASK-0002-00-00: Record model and Markdown body codec

- **Status**: Complete
- **Priority**: P0
- **Effort**: M
- **Assignee**: Claude
- **Created**: 2026-10-02 18:54:34
- **Updated**: 2026-10-02 19:09:22
- **Evidence**: tests/test_body.py: 20 passed. Hypothesis round trip for all four kinds (300 examples each, with text that imitates headings, bullets, checkboxes, fences and attribute lines); any text renders back unchanged; hand-edited body keeps unknown sections, free text and untouched fields byte for byte; ticked boxes survive a list edit; CRLF and loose headings read. kinds.py and body.py import nothing from the GitHub or MCP layers.

**User Story**: As the server, I need to turn a record's fields into an issue body a person would be happy to read, and turn any body back into fields without losing what a person added.

**Acceptance Criteria**:
- render(parse(b)) == b for every server-rendered body of every kind
- Unrecognised sections and free text survive a field edit byte for byte
- Empty and heading-less bodies parse to empty fields with the text kept as a block
- A consequences object with positive and negative lists round-trips

**Implementation Plan**:
- kinds.py: field specs per kind (requirement, decision, task, project): name, heading, shape (text, list, checklist, attribute, issue references), required
- body.py: parse(body, kind) -> fields + ordered unrecognised blocks; render(fields, blocks, kind); apply_edit that changes named fields only
- Leading attribute line for type/risk/effort/origin; tolerant heading matching (case, trailing colon)
- Checklists keep each item's checked state across edits when the item text is unchanged

**Test Plan**:
- Hypothesis round-trip property per kind over generated field values, including Markdown-looking text and text containing '## '
- Example tests for hand-edited bodies: renamed heading, reordered sections, extra section, CRLF line endings
- Checkbox state preservation test

**Definition of Done**:
- Codec has no imports from the GitHub or MCP layers
- Tests green

**Linked Requirements**:
- REQ-0001-FUNC-00: Requirements, decisions and tasks are GitHub issues a person can read and edit

**Comments**:
- **MCP User** (2026-10-02 19:09:22): Design as amended in ADR-0002: segment preservation. One normalisation is deliberate and documented in clean_item: a code fence inside a list item is escaped, since the codec cannot see where a fence inside a bullet ends.

---

### TASK-0003-00-00: Status derivation, transition maps and workflow rules

- **Status**: Complete
- **Priority**: P0
- **Effort**: M
- **Assignee**: Claude
- **Created**: 2026-10-02 18:54:34
- **Updated**: 2026-10-02 19:09:22
- **Evidence**: tests/test_status.py, tests/test_rules_paths.py, tests/test_rules_snapshot.py: 55 passed. All 15 kind/status pairs encode and derive back; no two statuses of a kind share an encoding; no path has a stop status inside it (all permutations, all kinds); each rule predicate and seven drift cases tested on hand-built snapshots; modes off/warn/enforce.

**User Story**: As the server, I need one place that says what status a set of labels and an issue state mean, which moves are allowed, and which are risky, so refusals and drift reports use the same definitions.

**Acceptance Criteria**:
- Every kind/status pair encodes to labels+state that derive back to the same status
- Draft -> Approved yields the path through Under Review; Draft -> Implemented is refused because it would pass through Approved
- Two status labels, or a status label on a closed issue that contradicts its close reason, yields a problem and a best-effort status
- Mode off returns no warnings, warn returns them, enforce raises

**Implementation Plan**:
- status.py: derive(kind, labels, state, state_reason) -> status + problems; encode(kind, status) -> labels to set and state to reach
- rules.py: transition map per kind, stop statuses, shortest path that never passes through a stop, rules mode from GH_PROJECT_RULES
- Predicates over a snapshot: unfinished blockers, open sub-tasks, open tasks under a requirement, thin record reasons
- Label vocabulary and prefix configuration in one module

**Test Plan**:
- Table test over all 15 kind/status combinations in both directions
- Path tests for every pair of requirement statuses, asserting no path contains a stop status in its interior
- Rule predicate tests on small hand-built snapshots

**Definition of Done**:
- No other module inspects label names or close reasons
- Tests green

**Linked Requirements**:
- REQ-0002-FUNC-00: Status lifecycles with human gates, held in labels and issue state

**Comments**:
- **MCP User** (2026-10-02 19:09:22): One addition beyond the plan: Deprecated is also a status a path cannot pass through. With Deprecated -> Draft allowed (GitHub has no delete, so a retired requirement must be revivable), every backward move would otherwise have found a route through Deprecated.

---

### TASK-0004-00-00: GitHub port, in-memory fake and contract tests

- **Status**: Complete
- **Priority**: P0
- **Effort**: M
- **Assignee**: Claude
- **Created**: 2026-10-02 18:54:34
- **Updated**: 2026-10-02 19:09:22
- **Evidence**: tests/contract/test_port.py: 15 passed against FakeGitHub (15 live variants deselected, awaiting TASK-0016); tests/test_fake.py: 5 passed (250 issues list in 3 requests; writes logged, reads not; behind_the_back leaves counters untouched; returned issues are copies).

**User Story**: As a developer, I want an in-memory GitHub that behaves like the real one for the operations we use, so every handler can be tested end to end with no network and drift can be staged behind the server's back.

**Acceptance Criteria**:
- Fake refuses a second parent, an unknown label on create when labels are not auto-created, and a missing issue with the status codes GitHub uses
- Every port method is covered by a contract test
- Fake exposes request counts and a log of writes for assertions

**Implementation Plan**:
- github/port.py: GitHub Protocol, IssueData/CommentData/MilestoneData/EventData dataclasses, GitHubError
- github/fake.py: issues, labels, comments, milestones, sub-issues (one parent, cycle refusal), blocked-by, timeline events, updated_at bumping, request counter and write log
- tests/contract/: one module of behaviour tests parametrised over the implementation, run against the fake by default

**Test Plan**:
- Contract tests per port method: happy path and each refusal
- Snapshot paging test with 250 issues at page size 100
- since= refresh returns only issues updated after the cursor

**Definition of Done**:
- Contract suite green against the fake
- Port has no GitHub JSON in its signatures

**Linked Requirements**:
- REQ-0001-NFUNC-00: Tests and development can never touch a real repository
- REQ-0001-TECH-00: GitHub is the only store, reached through one access layer aimed at an explicitly named repository

**Comments**:
- **MCP User** (2026-10-02 19:09:22): Deviation from the acceptance criteria: the fake does not refuse an unknown label, because GitHub does not either: it creates a label named on an issue. The contract test asserts that behaviour instead. The contract suite includes test_link_changes_are_seen_by_since, which is ADR-0001's open risk stated as a test for the live run.

---

### TASK-0005-00-00: HTTP GitHub client: REST and GraphQL over httpx, auth and error mapping

- **Status**: Complete
- **Priority**: P0
- **Effort**: L
- **Assignee**: Claude
- **Created**: 2026-10-02 18:54:34
- **Updated**: 2026-10-02 19:26:14
- **Evidence**: tests/test_http.py: 21 passed, all through httpx.MockTransport with no socket opened: token and API version headers, GraphQL snapshot pagination and link fields, REST payloads carrying only what is named, link endpoints taking database IDs, Link-header pagination, 401/403 rate limit/secondary limit/404/422/502 mapped to GitHubError with GitHub's message and the operation, token absent from every error and log line, no request without a token or without a repository, enterprise base URL, read-only refusals. The snapshot query and the OR semantics of its label filter were verified read-only against heffrey78/lifecycle-mcp on 2026-10-02 (cost 1 point per page).

**User Story**: As a user, I want the server to talk to my repository with the token I already have, and to tell me plainly when GitHub refuses something.

**Acceptance Criteria**:
- Unit tests drive HttpGitHub through httpx.MockTransport with recorded-shape responses for each operation
- 401, 403 rate limit, 404 and 422 each produce a GitHubError with GitHub's message
- No request is made when the repository is not configured; the error says how to set it
- The token does not appear in any raised message or log record

**Implementation Plan**:
- github/http.py: HttpGitHub implementing the port; GraphQL snapshot query with pagination; REST for issue create/update, labels, comments, milestones, sub_issues, dependencies/blocked_by, timeline
- config.py: GH_PROJECT_REPO, GH_PROJECT_API_URL, GH_PROJECT_READ_ONLY, token from GH_TOKEN / GITHUB_TOKEN else `gh auth token`, resolved lazily at first use
- Map non-2xx and GraphQL errors to GitHubError with status, message and operation; rate-limit responses carry the reset time; token redacted everywhere
- Read-only wrapper refusing writes before any request

**Test Plan**:
- httpx.MockTransport tests per operation asserting method, path, body and pagination following
- Error mapping table test
- Token redaction test scanning caplog and exception text
- Read-only mode test: every write method raises and the transport sees zero requests

**Definition of Done**:
- Only github/ imports httpx or subprocess, enforced by a test
- Tests green offline

**Linked Requirements**:
- REQ-0001-TECH-00: GitHub is the only store, reached through one access layer aimed at an explicitly named repository

**Comments**:
- **MCP User** (2026-10-02 19:26:14): Found while building: GraphQL `databaseId` is a 32-bit Int and current issue IDs exceed it (5622321494), so the client reads `fullDatabaseId`. Not yet exercised against real writes: that is TASK-0016.

---

### TASK-0006-00-00: Tracker snapshot: load, cache and incrementally refresh the record graph

- **Status**: Complete
- **Priority**: P0
- **Effort**: M
- **Assignee**: Claude
- **Created**: 2026-10-02 18:54:34
- **Updated**: 2026-10-02 19:26:14
- **Evidence**: tests/test_tracker.py: 11 passed. Cold load of 200 records: 3 requests (two pages and the milestones); refresh: 1; own writes visible with no request; a close, re-parent, new blocker and removed kind label made behind the server's back are all seen at the next refresh; leaf tasks counted through subtasks.

**User Story**: As the server, I need the whole tracker in memory after a handful of requests, kept current cheaply, so queries and the dashboard are computed locally.

**Acceptance Criteria**:
- Cold load of 200 records costs at most 3 requests against the fake; a warm refresh costs 1
- A change made directly on the fake between two reads is visible in the second
- Own writes are visible without an extra read request

**Implementation Plan**:
- tracker.py: Tracker holding records by number with kind, status, priority, milestone, parent, children, blocked_by, blocking, and decision link sections
- load(): paginated snapshot; refresh(): since-cursor update before each read; apply(): fold the server's own writes in without a refetch
- Lazy label bootstrap on first write: create only the labels that are missing
- Lookups used by rules and handlers: leaf tasks of a requirement, open blockers, decisions addressing a requirement

**Test Plan**:
- Request-count assertions for cold load, warm refresh, and read-after-own-write
- Behind-the-back mutation test: close, relabel, re-parent on the fake, then read
- Leaf-task counting test with a three-level task tree

**Definition of Done**:
- Handlers have a single object to ask for records and links
- Tests green

**Linked Requirements**:
- REQ-0001-TECH-00: GitHub is the only store, reached through one access layer aimed at an explicitly named repository
- REQ-0002-NFUNC-00: The tracker reads fast and stays inside GitHub's rate limits

**Comments**:
- **MCP User** (2026-10-02 19:26:14): Two changes from the plan. The cold load asks only for issues carrying a kind label, so a repository's other issues cost nothing (the original's own repository has 2,170); a refresh asks for every issue updated since, which is how a record that lost its label is dropped. And the tree is derived from each child's `parent`, not the parent's list, so the two ends cannot disagree when only one was refreshed.

---

### TASK-0007-00-00: MCP server core: tool registry, strict validation, structured results, call log, budget

- **Status**: Complete
- **Priority**: P0
- **Effort**: M
- **Assignee**: Claude
- **Created**: 2026-10-02 18:54:34
- **Updated**: 2026-10-02 19:26:14
- **Evidence**: tests/test_server.py: 15 passed, including a real MCP client (mcp.Client, SDK 2.2.0) listing and calling tools and prompts in memory. tests/test_tool_surface.py: budget holds at 14 tools and 8,915 characters against a ceiling of 16 and 9,000. `make smoke`: handshake, 14 tools, 2 prompts, clean stdout, against both the module and the installed gh-project-mcp command; the same script fails a server that prints to stdout.

**User Story**: As an agent, I want a server whose tool list is small and whose refusals tell me exactly which argument was wrong and what to pass instead.

**Acceptance Criteria**:
- An undeclared argument is refused naming it; a list passed to a singular ID names the plural sibling
- A handler exception reaches the client as isError with its message
- Budget test fails when a tool is added without raising the budget
- Handshake smoke: initialize, tools/list and one call succeed with clean stdout

**Implementation Plan**:
- registry.py: Tool(name, description, schema, handler, writes) and a decorator; additionalProperties false applied to every schema
- server.py: low-level mcp Server with on_list_tools/on_call_tool/on_list_prompts/on_get_prompt; jsonschema validation with the near-neighbour suggestion; ToolError -> isError; text + structuredContent results
- Call log to GH_PROJECT_CALL_LOG: tool, argument names, ms, isError, error_kind, response size
- tests/tool_surface_budget.json and its test; scripts/tool_surface_report.py
- scripts/mcp_handshake_smoke.py using the SDK client over stdio

**Test Plan**:
- Routing tests with a toy tool: validation refusal, neighbour suggestion, handler error, structured result
- Call log test: one line per call, no argument values, refused calls included
- Budget test
- Stdout purity test via subprocess under the github_live-free smoke marker in CI

**Definition of Done**:
- Server starts with no repository configured and lists its tools
- Tests green

**Linked Requirements**:
- REQ-0001-INTF-00: A small, strict tool surface with prompts for capture and reconciliation

**Comments**:
- **MCP User** (2026-10-02 19:26:14): Beyond the plan: an undeclared argument now names the declared one it resembles ("ids: did you mean id?") and lists what the tool takes.

---

### TASK-0008-00-00: Record tools: create, get, update, query, comment

- **Status**: Complete
- **Priority**: P0
- **Effort**: L
- **Assignee**: Claude
- **Created**: 2026-10-02 18:54:34
- **Updated**: 2026-10-02 19:26:40
- **Evidence**: tests/test_tools_records.py: 27 passed, every call through the server's routing against the fake. Creates return number and URL with the expected labels, body and parent; a task costs 3 requests (budget 4); thin records and tasks under an unapproved requirement warn, refuse under enforce and are silent under off with an empty write log on refusal; update changes only named fields and leaves a hand-added note and section byte for byte; an unknown field is refused listing the kind's fields; an Accepted decision is refused pointing at amendment, and an amendment leaves the body unchanged and shows beneath the decision; queries are compact unless `full`.

**User Story**: As an agent, I want to write a requirement, decision or task as an issue, read it back with its links, change a field and find records by status, without knowing the label or body conventions.

**Acceptance Criteria**:
- Each create returns number and URL and the issue on the fake has the expected labels, body and parent
- Creating a task under a Draft requirement warns (refused under enforce)
- update_record with a field the kind does not have is refused listing the kind's fields
- Editing an Accepted decision's text is refused pointing at amendment; an amendment leaves the body unchanged
- query_records returns compact rows and full fields only when asked

**Implementation Plan**:
- create_requirement, create_decision, create_task: render body, set kind and priority labels, milestone, parent sub-issue link for tasks; thin-record warnings
- get_record: fields, status, links from its own end, blocked reason, commit and evidence, amendments, comments
- update_record: fields object validated against the kind; reason required for requirements at Approved or later and posted as a comment; decisions editable only while Proposed, else amendment
- query_records: kind, status, priority, project, search, ready, work_complete; compact rows by default
- add_comment

**Test Plan**:
- Per-tool tests through the routing function against the fake
- Edit test on a body with a hand-added section
- Request-count test: creating a task under a requirement costs at most 4 requests
- Thin record warnings per kind, in warn and enforce modes

**Definition of Done**:
- A requirement, a decision and a task can be created, read, edited and found through MCP calls against the fake
- Budget raised to match and tests green

**Linked Requirements**:
- REQ-0001-FUNC-00: Requirements, decisions and tasks are GitHub issues a person can read and edit
- REQ-0006-FUNC-00: Every change leaves its trail on the issue

**Comments**:
- **MCP User** (2026-10-02 19:26:14): Implemented together in one pass over src/gh_project_mcp/tools/, after an end-to-end run of the whole lifecycle against the fake.
- **MCP User** (2026-10-02 19:26:40): The fake caught a real limit during this work: GitHub allows a parent 100 sub-issues. A task that is created but cannot be attached is now reported with its number and URL rather than left orphaned silently (test_a_task_that_cannot_be_attached_is_reported_with_its_number).

---

### TASK-0009-00-00: Status tool: set_status with path walking, gates, bulk moves and evidence

- **Status**: Complete
- **Priority**: P0
- **Effort**: M
- **Assignee**: Claude
- **Created**: 2026-10-02 18:55:22
- **Updated**: 2026-10-02 19:26:40
- **Evidence**: tests/test_tools_status.py: 16 passed. Draft to Approved reports its path and makes one issue update and one comment; a path through Approved is refused with an empty write log; Validated with an open task is refused in off, warn and enforce; risky task moves warn, refuse and pass by mode; a mixed list moves the valid records and reports each refusal; blocked reason kept in the body and removed on leaving; commit and evidence stay until replaced; a task closed on github.com reads as Complete with no write.

**User Story**: As an agent, I want one call to move one or many records to a status, be told the path taken and anything risky about it, and attach the commit and evidence behind a completed task.

**Acceptance Criteria**:
- Draft -> Approved in one call reports the path; a path through a stop status is refused with no write
- Validated with an open task is refused in every mode
- Completing a task with open blockers warns in warn mode, is refused in enforce, silent in off
- A mixed list moves the valid records and reports the refused ones
- A multi-step move makes one label/state write and one comment

**Implementation Plan**:
- set_status(ids, status, comment, commit, evidence): per record derive current status, compute path, run always-on rules then mode rules, write final labels and state once, post one status comment
- Blocked keeps the comment as reason; details read reason, commit and evidence back from the latest status comments
- Superseded refused here: it comes only from a supersedes link
- Per-ID results with moved and refused counts; error only when none moved

**Test Plan**:
- Tests per rule in each mode against the fake, asserting the fake's write log is empty on refusal
- Bulk move test with one refusal among three
- Evidence round trip: complete with commit and evidence, then get_record shows them
- Blocked reason shown, then gone after leaving Blocked

**Definition of Done**:
- All three kinds movable through their full lifecycles against the fake
- Tests green

**Linked Requirements**:
- REQ-0002-FUNC-00: Status lifecycles with human gates, held in labels and issue state
- REQ-0006-FUNC-00: Every change leaves its trail on the issue

**Comments**:
- **MCP User** (2026-10-02 19:26:14): Implemented together in one pass over src/gh_project_mcp/tools/, after an end-to-end run of the whole lifecycle against the fake.
- **MCP User** (2026-10-02 19:26:40): One behaviour beyond the plan: set_status to the status a record already has, when it carries evidence, a commit or a new blocked reason, records those and reports "(noted)" instead of refusing as "already Complete". Without it there was no way to attach evidence to a task a pull request had closed.

---

### TASK-0010-00-00: Link tools: parent, blocked-by, addresses, supersedes, and requirement trace

- **Status**: Complete
- **Priority**: P0
- **Effort**: M
- **Assignee**: Claude
- **Created**: 2026-10-02 18:55:22
- **Updated**: 2026-10-02 19:26:40
- **Evidence**: tests/test_tools_links.py: 12 passed. Each link type created, read from both ends and removed; a second parent is refused naming the existing one and the call that removes it; self-links, parent loops and dependency loops refused with an empty write log; supersedes closes the older decision with the label and a comment in the same call, and unlink returns it to Accepted; links made directly on the fake appear in the next read; progress counts leaf tasks.

**User Story**: As an agent, I want to say that one task waits on another, that a decision addresses a requirement, or that a new decision replaces an old one, and have that show on github.com.

**Acceptance Criteria**:
- A second parent, a self-link and a parent cycle are each refused before any write
- Supersedes moves the older decision to Superseded in the same call and unlink restores it to Accepted
- A link added directly on the fake appears in get_record
- Trace counts leaf tasks only

**Implementation Plan**:
- link_records(source, type, target) and unlink_records for parent, blocked_by, addresses, supersedes; kind checks per type
- parent and blocked_by through the native APIs; addresses and supersedes by editing the decision's body section
- supersedes closes the older decision with the superseded label and a comment naming the newer
- get_record(trace=true) for a requirement: decisions addressing it and its task tree with statuses and leaf progress

**Test Plan**:
- Per link type: create, read from both ends, remove
- Refusal tests asserting an empty write log
- Supersede and un-supersede test
- Trace test over a requirement with two decisions and a three-level task tree

**Definition of Done**:
- Tests green; budget raised to match

**Linked Requirements**:
- REQ-0003-FUNC-00: Traceability through GitHub's native links

**Comments**:
- **MCP User** (2026-10-02 19:26:14): Implemented together in one pass over src/gh_project_mcp/tools/, after an end-to-end run of the whole lifecycle against the fake.
- **MCP User** (2026-10-02 19:26:40): Deviation from the plan: there is no separate trace option. get_record on a requirement always shows its decisions and its whole task tree with statuses and leaf progress, which is the trace; a flag for it would have been a parameter that changes nothing.

---

### TASK-0011-00-00: Projects as milestones: save_project and project-scoped queries

- **Status**: Complete
- **Priority**: P1
- **Effort**: S
- **Assignee**: Claude
- **Created**: 2026-10-02 18:55:22
- **Updated**: 2026-10-02 19:26:40
- **Evidence**: tests/test_tools_projects.py: 5 passed. A project is a milestone whose description opens with the purpose; requirements join at creation and tasks, subtasks and decisions follow; moving a requirement moves the work under it; edit, close and reopen; a hand-made milestone with free text reads as a project with that purpose and an edit of one list leaves the purpose untouched; a closed project leaves the dashboard.

**User Story**: As an owner, I want to group requirements into a project with a stated purpose that shows as a milestone with a progress bar on github.com.

**Acceptance Criteria**:
- Creating a project creates a milestone whose description opens with the purpose
- A task created under a requirement in a project carries the milestone
- A hand-made milestone with free text reads as a project with that purpose
- Closing a project removes it from the dashboard's list

**Implementation Plan**:
- save_project: create when no project is named, otherwise edit title, purpose, success criteria, out of scope, or close/reopen
- Milestone description rendered and parsed by the body codec with the project field spec
- project parameter on the create tools and update_record; tasks inherit their requirement's milestone
- Project filter in query_records; get_record on a project reference shows purpose and member progress

**Test Plan**:
- Create, edit, close and reopen through the routing function
- Inheritance test for tasks and subtasks
- Hand-made milestone read test

**Definition of Done**:
- Tests green; budget raised to match

**Linked Requirements**:
- REQ-0004-FUNC-00: Projects are milestones with a stated purpose

**Comments**:
- **MCP User** (2026-10-02 19:26:14): Implemented together in one pass over src/gh_project_mcp/tools/, after an end-to-end run of the whole lifecycle against the fake.

---

### TASK-0012-00-00: Dashboard: get_status with ready, blocked, decision-pending and drift sections

- **Status**: Complete
- **Priority**: P1
- **Effort**: M
- **Assignee**: Claude
- **Created**: 2026-10-02 18:55:22
- **Updated**: 2026-10-02 19:26:40
- **Evidence**: tests/test_tools_dashboard.py: 8 passed. Every section asserted as exact text and as structured data on one hand-built tracker; sections absent when empty; drift staged behind the server's back (closed-as-validated with open work, two status labels, a hand-written body, a hand-made orphan task) is reported with an empty write log; dashboard and query filters return the same sets. Request counts at 200 records: cold 3 (budget 4), warm 1 (budget 1), a change on GitHub seen in 1, new task 3 (budget 4), status move 2.

**User Story**: As an agent starting a session, I want one call that tells me what to work on next, what is stuck and why, what is waiting for the owner's decision, and what someone changed on github.com that breaks the rules.

**Acceptance Criteria**:
- Sections appear only when they have rows
- Each drift case in REQ-0005 is detected when staged on the fake, and get_status makes no write
- Cold dashboard over 200 records at most 4 requests, warm at most 1
- query_records(ready=true) and the dashboard's ready section return the same set

**Implementation Plan**:
- get_status: counts by kind and status, open projects with progress, ready, blocked and waiting, work complete decision pending, drift
- Each section computed by the predicates in rules.py that set_status and query_records use
- Empty-ready explanation: nothing left, everything waiting, or only in-progress work
- Text plus structuredContent; header names the repository

**Test Plan**:
- One test per section on a hand-built tracker
- One test per drift case staged behind the server's back, asserting an empty write log
- Request-count tests at 200 records
- Consistency test between the dashboard and the query filters

**Definition of Done**:
- Tests green; budget raised to match

**Linked Requirements**:
- REQ-0002-NFUNC-00: The tracker reads fast and stays inside GitHub's rate limits
- REQ-0005-FUNC-00: A dashboard that says what needs attention, including drift made on github.com

**Comments**:
- **MCP User** (2026-10-02 19:26:14): Implemented together in one pass over src/gh_project_mcp/tools/, after an end-to-end run of the whole lifecycle against the fake.
- **MCP User** (2026-10-02 19:26:40): Found by reading the real output of an end-to-end run rather than by a test: a task created with only a title was being reported as drift ('body holds no fields'), a signal firing on the server's own output. An empty body is now treated as thin, not drift, and test_a_new_record_is_not_reported_for_being_new holds that.

---

### TASK-0013-00-00: Export: Markdown documents and Mermaid diagram

- **Status**: Complete
- **Priority**: P2
- **Effort**: M
- **Assignee**: Claude
- **Created**: 2026-10-02 18:55:22
- **Updated**: 2026-10-02 19:26:40
- **Evidence**: tests/test_tools_export.py: 5 passed. The requirements document is asserted whole against expected text; one project's export holds only its records and each document opens with its stored purpose; two exports of an unchanged tracker are byte-identical; amendments sit beneath their decision; the diagram draws implements, blocked-by, addresses and supersedes edges and reports drawn, retired and over-limit counts.

**User Story**: As an owner, I want the tracker as documents I can hand to someone, and a picture of how the records connect.

**Acceptance Criteria**:
- Exporting one project writes only its records
- Two exports of an unchanged tracker are byte-identical
- The diagram response states counts drawn and omitted

**Implementation Plan**:
- export_docs(project, output_directory, include, diagram): requirements, decisions and tasks documents, each opening with project purpose
- Decisions rendered with amendments beneath; tasks with commit and evidence; every record linked to its issue URL
- Mermaid graph with status colours and labelled edges, optional limit, reporting what was left out
- Deterministic ordering and no timestamps in the output

**Test Plan**:
- Golden-file tests for each document on a fixed fake tracker
- Determinism test: export twice and compare bytes
- Diagram limit test

**Definition of Done**:
- Tests green; budget raised to match

**Linked Requirements**:
- REQ-0007-FUNC-00: Export the tracker as Markdown documents and a Mermaid diagram

**Comments**:
- **MCP User** (2026-10-02 19:26:14): Implemented together in one pass over src/gh_project_mcp/tools/, after an end-to-end run of the whole lifecycle against the fake.

---

### TASK-0014-00-00: Prompts and setup: capture_requirement, reconcile_requirements, setup_repository

- **Status**: Complete
- **Priority**: P1
- **Effort**: S
- **Assignee**: Claude
- **Created**: 2026-10-02 18:55:22
- **Updated**: 2026-10-02 19:26:40
- **Evidence**: tests/test_tool_surface.py: 10 passed. Both prompts list and render with their arguments, over a real MCP client too (tests/test_server.py); every tool name a prompt mentions is in the registry and every field the capture guide names is a create_requirement parameter; setup_repository creates 12 missing labels, leaves an existing one alone and creates nothing the second time; a label prefix applies to every label.

**User Story**: As a new user, I want one call that prepares my repository's labels, and prompts that guide my model to write a good requirement or reconcile a codebase against the tracker.

**Acceptance Criteria**:
- prompts/list returns both prompts and prompts/get renders each with its arguments
- Every tool name a prompt mentions exists in the registry, checked by a test
- setup_repository run twice creates nothing the second time

**Implementation Plan**:
- prompts.py: both prompts adapted from lifecycle-mcp to this server's tools, fields and issue numbers
- setup_repository: create missing labels with colours and descriptions, report created and already present; safe to repeat
- Reconcile prompt searches with query_records(search=...) per candidate, as the original learned to

**Test Plan**:
- Prompt rendering tests
- Prompt-mentions-real-tools test
- setup_repository idempotence test against the fake

**Definition of Done**:
- Tests green; budget raised to match

**Linked Requirements**:
- REQ-0001-INTF-00: A small, strict tool surface with prompts for capture and reconciliation
- REQ-0001-TECH-00: GitHub is the only store, reached through one access layer aimed at an explicitly named repository

**Comments**:
- **MCP User** (2026-10-02 19:26:14): Implemented together in one pass over src/gh_project_mcp/tools/, after an end-to-end run of the whole lifecycle against the fake.

---

### TASK-0015-00-00: Documentation: README, CLAUDE.md, CHANGELOG, and docs checked against the tool list

- **Status**: Complete
- **Priority**: P1
- **Effort**: S
- **Assignee**: Claude
- **Created**: 2026-10-02 18:55:22
- **Updated**: 2026-10-02 19:31:23
- **Evidence**: tests/test_docs.py: 9 passed. The README's tool list equals the registry's; every environment variable the source reads is documented; the README names every parameter of the three create tools, every status and every kind label; the comparison table states the real tool count; CLAUDE.md names only modules, tests and make targets that exist. `make lint`, `make test` (241 passed, 15 live tests deselected, 11 s) and `make smoke` all pass.

**User Story**: As a newcomer, I want to go from clone to my first requirement on GitHub by following the README, and as a contributor I want the rules I cannot infer from the code.

**Acceptance Criteria**:
- Every environment variable the code reads is documented, checked by a test
- README tool list test passes
- A fresh-clone walkthrough of the README's quick start works against the fake-backed smoke

**Implementation Plan**:
- README: what it is, how it differs from lifecycle-mcp, install, configuration, label and body conventions with an example issue, tool reference, workflow rules, drift, limits
- CLAUDE.md: commands, module map, the rules (stdout, strict inputs, budget, network guard, one codec, one status derivation, reads never write)
- CHANGELOG 0.1.0
- tests/test_docs_tool_lists.py: README's tool list equals the registry's

**Test Plan**:
- Docs tool list test
- Environment variable documentation test

**Definition of Done**:
- Docs committed; tests green

**Linked Requirements**:
- REQ-0002-TECH-00: Installable package with CI, documentation and a working first run

**Comments**:
- **MCP User** (2026-10-02 19:31:23): Two things for the owner. The README's quick start clones https://github.com/heffrey78/gh-project-mcp.git, which does not exist yet. And pyproject declares MIT, as lifecycle-mcp does, but no LICENSE file was added: that is the owner's to choose. While checking the docs against a real repository (read-only, heffrey78/lifecycle-mcp), the first refresh after a cold load turned out to fetch every issue updated since the newest record: 20 requests there. The cursor now starts from GitHub's own clock; measured afterwards at cold 2, warm 1.

---

## Blocked Tasks

### TASK-0016-00-00: Live verification against a sandbox GitHub repository

- **Status**: Blocked
- **Priority**: P0
- **Effort**: M
- **Assignee**: Claude
- **Created**: 2026-10-02 18:55:22
- **Updated**: 2026-10-02 19:33:33

**User Story**: As the owner, I want proof that the server does on real GitHub what it does on the fake, before I trust it with a real repository.

**Acceptance Criteria**:
- Contract suite passes live
- Every tool is called at least once in the scripted run with no error results other than deliberate refusals
- Each disagreement between fake and GitHub is fixed in the fake with a contract test
- ADR-0001's refresh risk is settled with evidence and the decision amended if needed

**Implementation Plan**:
- Owner go-ahead needed: create a private sandbox repository (name containing `sandbox`) and allow issues to be created in it
- Run the contract suite against HttpGitHub with GH_PROJECT_LIVE_REPO set
- Drive a full lifecycle through the MCP server over stdio: setup, project, requirement, decision, tasks with a dependency, status moves to Validated, supersede a decision, dashboard, export
- Verify the open questions: do sub-issue and dependency changes bump updated_at (ADR-0001 risk), GraphQL field names and limits, close reasons on reopen
- Record request counts and the call log; fix the fake wherever it disagreed with GitHub

**Test Plan**:
- uv run pytest -m github_live with the sandbox configured
- Scripted stdio session with GH_PROJECT_CALL_LOG, summarised in docs/live-run.md
- Manual check on github.com: sub-issue tree, blocked-by, milestone progress, comments

**Definition of Done**:
- docs/live-run.md records the run, its request counts and what changed because of it
- Sandbox issues closed

**Linked Requirements**:
- REQ-0001-NFUNC-00: Tests and development can never touch a real repository
- REQ-0001-TECH-00: GitHub is the only store, reached through one access layer aimed at an explicitly named repository
- REQ-0003-FUNC-00: Traceability through GitHub's native links

**Comments**:
- **MCP User** (2026-10-02 19:33:33): Waiting on the owner. The live run creates a GitHub repository and issues in it, which is outward-facing and was not asked for. Needed: either the owner creates a private repository whose name contains `sandbox` (for example heffrey78/gh-project-sandbox) or says to create one. Then: `GH_PROJECT_LIVE_REPO=<repo> uv run --extra test pytest -m github_live` (15 contract tests, already written), followed by the scripted lifecycle over stdio. Done so far without writing anything: the HTTP client's read paths ran against heffrey78/lifecycle-mcp in read-only mode on 2026-10-02 (GraphQL snapshot across 20 pages, milestones, labels, comments, timeline; cold dashboard 2 requests, warm 1).

---

