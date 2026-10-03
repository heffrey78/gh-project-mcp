# gh-project-mcp v1: lifecycle tracking on GitHub issues - Architecture Documentation

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

## ADR-0001: GitHub issues are the only store; the server keeps no database

- **Type**: ADR
- **Status**: Proposed
- **Created**: 2026-10-02 18:53:23
- **Updated**: 2026-10-02 19:33:33

- **Authors**: Claude

### Context
lifecycle-mcp is a SQLite application with an optional one-way mirror of tasks to GitHub issues. A GitHub-based successor could keep that shape (local database as truth, GitHub as a synchronised view) or make GitHub the truth. Sync is where the original's GitHub code spent its complexity: ETags, conflict detection, last-sync timestamps, and a rule that edits are 'not pushed to a linked GitHub issue'. People will edit issues on github.com whatever the server does, so any local copy is wrong as soon as they do.

### Decision
GitHub is the single source of truth. The server holds no database and writes no state to disk. It keeps an in-memory snapshot of the tracker for the life of the process, purely as a read cache. The first listing asks only for issues carrying a kind label, one GraphQL page per 100, so a repository's other issues cost nothing. Before every later tool call the snapshot is refreshed by asking for every issue updated since a cursor, labelled or not, which is also how a record whose kind label was removed is noticed and dropped. After the cold load the cursor is GitHub's own clock (the Date header of the answer) less two minutes, never the local clock and not the newest record's timestamp: in a repository busy with unrelated issues the latter would fetch all of them once. The server's own writes are folded into the snapshot without a refetch; a write's REST response carries no links, so links are kept from the snapshot and the sub-issue tree is derived from each child's own parent, so the two ends of a link cannot disagree when only one was refreshed. Tool calls run one at a time, since they share the snapshot. Anything the server needs to remember (blocked reason, evidence, amendments) is written onto the issue as a label, body section or comment.

### Decision Drivers
- People edit issues directly, so the server must treat GitHub as authoritative on every read
- No sync means no conflicts to resolve
- Two machines or two agents on one repository must see the same tracker
- Rate limits and latency rule out per-record fetching

### Considered Options
- GitHub as the only store, with an in-memory read cache (chosen)
- SQLite as truth with two-way sync to issues: keeps lifecycle-mcp's query power and offline use, but needs conflict resolution and is wrong whenever someone edits on github.com
- GitHub as truth with a persistent on-disk cache: faster cold start, but adds invalidation, a file to corrupt, and a second place state can hide
- No cache at all: simplest, but a dashboard costs a request per record

### Consequences
**Positive**:
- No migrations, no dump/restore, no schema: the three largest non-handler modules of lifecycle-mcp have no counterpart
- Restarting the server loses nothing
- The tracker is shared, reviewable and backed up by being on GitHub
**Negative**:
- No offline use
- Queries are limited to what can be computed over the snapshot; there is no SQL
- Every rule the original enforced with triggers and constraints is now advisory: a person can break it on github.com, so the server has to detect and report drift instead of preventing it
- Write latency is network latency

### Validation Criteria
- No file is created by the server other than an opted-in call log and requested exports
- Request-count assertions in REQ-0002-NFUNC-00 pass against the fake

### Risk Assessment
- Risk: the incremental refresh misses a change (sub-issue and dependency edits may not bump an issue's updated_at). Likelihood: medium. Impact: stale links in the dashboard. Mitigation: verify in the live run; if links do not bump updated_at, re-fetch link fields for open records on refresh, or fall back to a full refetch with a short time-to-live
- Risk: trackers of thousands of issues make the cold fetch slow. Likelihood: low for v1. Impact: slow first call. Mitigation: only issues carrying a lifecycle kind label are fetched; closed records older than a cut-off can be left out later

### Linked Requirements
- REQ-0001-FUNC-00: Requirements, decisions and tasks are GitHub issues a person can read and edit
- REQ-0001-TECH-00: GitHub is the only store, reached through one access layer aimed at an explicitly named repository
- REQ-0002-NFUNC-00: The tracker reads fast and stays inside GitHub's rate limits

---

## ADR-0002: Records are encoded as labels plus Markdown body sections, read tolerantly

- **Type**: ADR
- **Status**: Proposed
- **Created**: 2026-10-02 18:53:23
- **Updated**: 2026-10-02 18:59:08

- **Authors**: Claude

### Context
An issue has a title, a free-text body, labels, a state with a reason, a milestone and comments. A lifecycle record has a kind, a status, a priority and a dozen structured fields. The encoding decides whether records are pleasant for a person on github.com and whether the server survives that person's edits. Issue types would be the natural home for kind but exist only for organisations, and the target account is a user account. Projects v2 custom fields could hold status and priority but need the `project` token scope, live outside the repository, and do not appear in the issue list.

### Decision
Kind is a label (`requirement`, `decision`, `task`). Priority is a label (`P0`..`P3`). Status is derived, never stored twice: a closed issue's status comes from its close reason (completed: Validated / Complete / Accepted; not planned: Deprecated / Abandoned / Rejected; plus the `status:superseded` label for decisions); an open issue's status comes from its single `status:...` label, and an open issue with none is at the kind's first status. Label names take a configurable prefix. Structured fields live in the body as `## Heading` sections, with list fields as bullets and acceptance criteria / definition of done as task-list checkboxes; scalar attributes that are not worth a label (requirement type, risk, effort, origin) sit in one leading attribute line. The body codec splits a body into segments (the text before the first heading, then one segment per `##` section) and keeps every segment's original text: reading never normalises, and an edit re-renders only the segments of the fields it names, so anything a person wrote, in a known section or an unknown one, is untouched until that field itself is edited. Facts that are current rather than historical are body sections too, because the body is in the snapshot and comments are not: a Blocked task's `Blocked reason`, and a task's `Evidence` (commit and evidence). Every status move also posts a comment with a recognisable first line (the path, reason, commit, evidence) as the trail, and a decision amendment is a comment of its own kind.

### Decision Drivers
- A person must be able to read and edit a record with no knowledge of the server
- One copy of each fact, so there is nothing to reconcile
- Status must be filterable in GitHub's issue list
- Closing an issue from a pull request should complete a task without the server

### Considered Options
- Labels for kind/status/priority, Markdown sections for fields (chosen)
- A hidden JSON or YAML block in an HTML comment as the machine copy with rendered Markdown beside it: exact round trips, but two copies that disagree the moment a person edits the visible one
- YAML front matter: machine-friendly, renders as an ugly code block on github.com
- GitHub issue forms: produce exactly this section layout for human-created issues, and can be added later as templates that match the codec
- Projects v2 fields for status and priority: richer boards, wrong scope and not visible in the issue list
- Title prefixes such as [REQ]: redundant with the label and noisy

### Consequences
**Positive**:
- Records look like well-written issues, not machine output
- `Closes #12` in a pull request completes a task natively
- Hand-made issues become records by adding a label
- Issue form templates can later produce bodies the codec already understands
**Negative**:
- Parsing Markdown is looser than reading columns: a renamed heading turns a field into an unrecognised block, which the dashboard reports as drift rather than fixing
- Status is spread over a label and the open/closed state, so every reader must go through one derivation function
- Blocked reason and evidence are read back from comments, costing a comments fetch for details
- A user-chosen label named like one of ours collides; the prefix setting is the way out

### Implementation Notes
One module owns the codec (`body.py`) and one owns status derivation (`status.py`); nothing else reads labels or headings directly. Heading matching is case-insensitive and ignores trailing colons. The codec is covered by property-based round-trip tests.

### Validation Criteria
- render(parse(body)) == body for every body the server renders, under property-based tests
- Editing one field preserves unrecognised blocks byte for byte
- Each of the 15 kind/status combinations derives from exactly one label-and-state combination, tested in both directions

### Linked Requirements
- REQ-0001-FUNC-00: Requirements, decisions and tasks are GitHub issues a person can read and edit
- REQ-0002-FUNC-00: Status lifecycles with human gates, held in labels and issue state
- REQ-0006-FUNC-00: Every change leaves its trail on the issue

---

## ADR-0005: Kind-generic tools on the MCP SDK 2.x low-level server, with a size budget

- **Type**: ADR
- **Status**: Proposed
- **Created**: 2026-10-02 18:53:23
- **Updated**: 2026-10-02 18:53:23

- **Authors**: Claude

### Context
lifecycle-mcp lists 25 tools in about 17,000 characters. Its usage evidence shows the per-kind pattern (create/update/update_status/query for each of three kinds) repeating field lists, with the three update tools alone at 23% of the surface for 5 calls, and status moves at 47% of calls. It is pinned to `mcp<2` because 2.x removed the decorator API it was written against; it also had to disable the SDK's input validation to log and explain refusals. MCP SDK 2.2.0 is current, and its low-level `Server` takes `on_list_tools` and `on_call_tool` callables directly.

### Decision
Build on `mcp>=2.2,<3` using the low-level `Server` with our own `on_list_tools` / `on_call_tool`, so schema validation, refusal messages, structured results and the call log are all in one routing function we own. Tools are declared in a registry as (name, description, JSON schema, async handler); the registry is the single source for listing, validation and routing. The surface is generic over kind wherever behaviour is shared, and specific only where the fields differ: `create_requirement`, `create_decision`, `create_task`, `update_record`, `set_status`, `get_record`, `query_records`, `link_records`, `unlink_records`, `add_comment`, `save_project`, `get_status`, `export_docs`, `setup_repository` (14 tools). `update_record` takes a `fields` object validated against the record's kind at call time rather than restating every field in its schema. Capture and reconciliation are MCP prompts. A budget file holds the allowed tool count and total definition size, and a test fails when either is exceeded.

### Decision Drivers
- Definition size is paid on every client request
- Refused calls must be logged and explained by our code
- One declaration per tool so docs, schema and handler cannot drift apart
- A ground-up build should not start on a pinned-back SDK

### Considered Options
- Low-level Server with a tool registry and kind-generic tools (chosen)
- MCPServer (the renamed FastMCP) with decorated functions: least code, but schemas and validation messages are generated for us, additionalProperties and refusal logging are harder to control, and the original's lesson was to own that path
- Pin `mcp<2` and reuse the original's server.py: fastest start, begins life on a superseded API
- Per-kind tools as in the original: more discoverable names, roughly double the definition size
- A single `record` tool with an `action` parameter: smallest listing, but one schema cannot say which arguments go with which action, so refusals move from the schema into prose

### Consequences
**Positive**:
- About half the original's tool count and definition size
- No parameter can be declared and ignored, or read and undeclared: the handler receives exactly the validated schema's properties
- The 2.x SDK is supported going forward
**Negative**:
- `update_record`'s `fields` object is validated at call time, so its allowed keys are documented in the description and in refusals rather than visible in the listing schema
- Generic names (`get_record`) say less than `get_requirement_details`; descriptions must carry the weight
- The low-level API is more code than decorators and tracks SDK changes more closely

### Validation Criteria
- Budget test passes at no more than 16 tools and 9,000 characters
- A handshake smoke test lists tools and calls one through a real stdio client from the same SDK
- Every tool has at least one test calling it through the routing function, not the handler directly

### Risk Assessment
- Risk: an agent fails to discover which fields `update_record` accepts for a kind. Likelihood: medium. Impact: refused calls. Mitigation: the refusal lists the kind's fields; measure with the call log in the live run and split the tool if refusals are common

### Linked Requirements
- REQ-0001-INTF-00: A small, strict tool surface with prompts for capture and reconciliation
- REQ-0002-TECH-00: Installable package with CI, documentation and a working first run

---

## ADR-0004: One async GitHub port: an httpx client for real use, an in-memory fake for tests

- **Type**: ADR
- **Status**: Proposed
- **Created**: 2026-10-02 18:53:23
- **Updated**: 2026-10-02 18:53:23

- **Authors**: Claude

### Context
lifecycle-mcp reaches GitHub by spawning `gh` for each operation from static methods that return None on failure, infers the repository from the working directory, and had no test double: its fixtures drove the real path and created 1,049 issues upstream. Here every tool call is a GitHub call, so how the server talks to GitHub, and what tests talk to instead, is the central structural choice.

### Decision
Define a small async interface (`GitHub`, a typing Protocol) in terms of the operations the server needs: fetch snapshot pages, get issue with comments, create/update issue, set labels, close/reopen with reason, comment, sub-issue add/remove, blocked-by add/remove, milestone CRUD, timeline, ensure labels. Two implementations: `HttpGitHub` over httpx, using GraphQL for the snapshot read and REST for writes, and `FakeGitHub`, an in-memory repository that enforces GitHub's own constraints (one parent, unknown label, 404 on a missing issue) and counts requests. Handlers receive the port; nothing else imports httpx. The repository is taken only from `GH_PROJECT_REPO`, never inferred from a git remote. The token comes from `GH_TOKEN`/`GITHUB_TOKEN`, else one `gh auth token` call at first use. Failures raise a typed `GitHubError` carrying status, GitHub's message and the operation, which the server turns into an isError result. A suite-wide pytest fixture blocks sockets and subprocesses; the same contract tests run against the fake always and against `HttpGitHub` only under the `github_live` marker and a sandbox-named repository.

### Decision Drivers
- Tests must be unable to reach GitHub by construction, not by convention
- The request budget needs something that counts requests
- Drift scenarios need a store tests can mutate behind the server's back
- A wrong target repository is the most damaging mistake available, so it must be stated, not guessed

### Considered Options
- httpx behind a port with an in-memory fake (chosen)
- Shelling out to `gh api`: no token handling and no HTTP dependency, but 100-300 ms of process start per request, no connection reuse, and errors as stderr text
- PyGithub or githubkit: typed REST coverage, but sub-issues and dependencies are too new to rely on, GraphQL still needs raw calls, and tests would mock a third-party object model
- Recorded HTTP cassettes instead of a fake: faithful, but cannot express 'then someone closed it on github.com' scenarios and go stale silently
- Inferring the repository from the origin remote: convenient, and the cause of the original's issue spam

### Consequences
**Positive**:
- Handlers are tested end to end with no network and no mocks of HTTP
- Request counts are assertable
- Connection reuse and HTTP/2 make writes as fast as GitHub allows
- GitHub Enterprise needs only a base URL
**Negative**:
- The fake is a second implementation that can disagree with GitHub; only the live contract run closes that gap, and it needs a sandbox repository and the owner's go-ahead
- httpx is a runtime dependency the original did not have
- Setting GH_PROJECT_REPO is one more step than doing nothing

### Implementation Notes
The port speaks in plain dataclasses (IssueData, CommentData, MilestoneData), not GitHub JSON, so the fake stays small. REST calls send `X-GitHub-Api-Version`. Rate-limit responses (403/429 with remaining 0 or a retry-after header) raise GitHubError with the reset time; no automatic sleeping.

### Validation Criteria
- The default test run opens no socket and spawns no process (guard fixture)
- The contract test module passes against FakeGitHub, and against HttpGitHub in the live run
- No module outside `github/` imports httpx or subprocess, checked by a test

### Linked Requirements
- REQ-0001-NFUNC-00: Tests and development can never touch a real repository
- REQ-0001-TECH-00: GitHub is the only store, reached through one access layer aimed at an explicitly named repository
- REQ-0002-NFUNC-00: The tracker reads fast and stays inside GitHub's rate limits

---

## ADR-0006: Rules are checked on the server's own writes and reported as drift on reads

- **Type**: ADR
- **Status**: Proposed
- **Created**: 2026-10-02 18:53:23
- **Updated**: 2026-10-02 18:53:23

- **Authors**: Claude

### Context
lifecycle-mcp can guarantee its rules because every write passes through it: transition maps, the Validated gate and the Superseded link are always on, and the rest warn or refuse under `LIFECYCLE_RULES`. With GitHub as the store (ADR-0001) anyone with write access can close a requirement or relabel a task on github.com, so no rule can be guaranteed. The original also holds that the tracker should report and let the person decide: nothing moves on its own, and a contradiction is reported rather than resolved.

### Decision
Split rules by where they can act. On the server's own writes, the rules are as strict as the original: each kind has a transition map in one module (`rules.py`), a move walks the shortest allowed path, Approved and Validated are stop statuses that can end a path but never sit inside one, and three rules are always on (the transition map, no Validated with an open task, Superseded only through a supersedes link). The remaining checks (unfinished dependencies, open sub-tasks, skipped or reopened tasks, the Implemented gate, thin records) follow `GH_PROJECT_RULES` = off, warn (default) or enforce. On reads, the same predicates run over the snapshot as drift checks: any record whose labels and state could not have been produced by an allowed sequence is listed on the dashboard with what is wrong. The server never repairs drift; the fix is a person's edit or an explicit tool call. A multi-step move is applied as its final state in one label-and-state write with one comment recording the path, since intermediate label flips would only add timeline noise and API calls.

### Decision Drivers
- GitHub edits cannot be prevented, only seen
- A read must never write
- The owner's approval and validation decisions must not be reachable as a side effect
- One definition of each rule, used both to refuse and to report

### Considered Options
- Strict on own writes, reported as drift on reads (chosen)
- Refuse to operate on a record that is in a drifted state until it is repaired: strict, but turns one stray click on github.com into a blocked agent
- Auto-repair drift on read (re-open, strip labels): keeps invariants, but overrides a person's deliberate edit and makes a read have side effects
- Enforce with a GitHub Action or webhook that reverts illegal changes: real enforcement, but needs deployed infrastructure, which is out of scope
- No rules, only conventions: simplest, and loses the reason to use this over plain issues

### Consequences
**Positive**:
- The agent is held to the lifecycle while people stay free to override it
- Each rule is one predicate with two uses, so the dashboard and the refusals cannot disagree
- Status moves cost one write regardless of path length
**Negative**:
- The server's guarantees are weaker than the original's: 'cannot' becomes 'cannot through this server, and will be reported otherwise'
- Intermediate statuses of a walked path appear only in the comment, not as separate timeline events
- Approval is a label anyone with triage rights can add; there is no proof a person, rather than an agent with a token, applied it

### Validation Criteria
- Every always-on rule has a test that the write is refused and a test that the same state created behind the server's back is reported as drift
- No read tool issues a write request, asserted by the fake's request log

### Linked Requirements
- REQ-0002-FUNC-00: Status lifecycles with human gates, held in labels and issue state
- REQ-0005-FUNC-00: A dashboard that says what needs attention, including drift made on github.com

---

## ADR-0003: Links use sub-issues and blocked-by; projects are milestones

- **Type**: ADR
- **Status**: Proposed
- **Created**: 2026-10-02 18:53:23
- **Updated**: 2026-10-02 18:53:23

- **Authors**: Claude

### Context
lifecycle-mcp has one relationships table and twelve link types, with many-to-many links between tasks and requirements and between requirements and projects. GitHub offers typed native links: sub-issues (one parent per issue, up to 100 children and eight levels, with a completed/total summary), blocked-by / blocking dependencies, and milestones (one per issue, with a description and progress). Both link features were confirmed reachable with the current token through REST and GraphQL on 2026-10-02. Everything else is an untyped cross-reference created by mentioning an issue.

### Decision
Use the native feature wherever one exists and accept its cardinality. Requirement to task, and task to subtask, are sub-issue links: a task has exactly one parent. Dependencies between tasks (and between requirements) are blocked-by links; the original's depends, requires and blocks collapse into this one, stored once and read from either end. A project is a milestone whose description is rendered and parsed by the same body codec (purpose, success criteria, out of scope); a requirement is in at most one project and tasks inherit their requirement's milestone at creation. The two links with no native form are kept in the decision's own body, in an `Addresses` section and a `Supersedes` section holding issue references, which GitHub also turns into cross-references on the target's timeline. A supersedes link closes the older decision with the superseded label and a comment naming its successor.

### Decision Drivers
- The trace should be visible and clickable on github.com
- Native progress summaries replace the original's counter triggers
- Fewer link types means a smaller tool and fewer wrong choices for an agent
- In the original's usage evidence, parent and depends were the links actually created

### Considered Options
- Native sub-issues, blocked-by and milestones, with decision links in the body (chosen)
- All links as issue references in body sections: uniform and many-to-many, but invisible to GitHub's progress bars, dependency UI and filters
- Projects as a parent 'epic' issue with requirements as sub-issues: allows nesting, but spends the single parent slot and has no purpose/progress presentation of its own
- Projects as labels: allows several per requirement, but a label has no description long enough for a purpose and no open/closed state
- Tasks tied to requirements by label or body reference to keep many-to-many: loses the native progress summary, the thing that makes the trace visible

### Consequences
**Positive**:
- Requirement progress, leaf counting and dependency state come from GitHub
- Twelve link types become four: parent, blocked_by, addresses, supersedes
- A person can restructure work by dragging sub-issues on github.com and the server sees it
**Negative**:
- A task implements exactly one requirement and a requirement belongs to one project; the original allowed several of each
- A decision reached through `Addresses` is found by scanning decision bodies, so decision bodies are part of the snapshot
- Sub-issue and dependency writes need issue database IDs, which costs a lookup the snapshot must provide
- Limits of 100 sub-issues per parent and eight levels apply

### Validation Criteria
- Creating a task under a requirement shows it in the requirement's sub-issue list on github.com (live run)
- A blocked-by link added on github.com appears in the dashboard's waiting section
- A second parent is refused naming the existing one

### Risk Assessment
- Risk: the sub-issue or dependency API changes shape; both are recent. Likelihood: low. Impact: link tools fail. Mitigation: all calls sit behind the access layer and are covered by live contract tests
- Risk: one requirement per task proves too tight. Likelihood: medium. Impact: awkward modelling of cross-cutting tasks. Mitigation: a `Also implements` body section listing further requirements, read by trace

### Linked Requirements
- REQ-0003-FUNC-00: Traceability through GitHub's native links
- REQ-0004-FUNC-00: Projects are milestones with a stated purpose
- REQ-0005-FUNC-00: A dashboard that says what needs attention, including drift made on github.com

---

