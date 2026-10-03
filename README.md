# gh-project-mcp

An MCP server that tracks a software project's requirements, architecture decisions and tasks as GitHub issues.

It gives an agent a lifecycle to work within: a requirement is written, approved by a person, decided on, broken
into tasks, implemented and validated, and every step is traceable. Unlike a private tracker, every record is an
ordinary issue. You can read it, edit it, comment on it and link to it on github.com with nothing installed.

It is a ground-up successor to [lifecycle-mcp](https://github.com/heffrey78/lifecycle-mcp), in spirit rather than
feature for feature. See [How it differs from lifecycle-mcp](#how-it-differs-from-lifecycle-mcp).

## Quick start

You need Python 3.11 or later, [uv](https://docs.astral.sh/uv/), and a GitHub token with the `repo` scope. If the
`gh` CLI is logged in, its token is used and you need set nothing.

```bash
git clone https://github.com/heffrey78/gh-project-mcp.git
cd gh-project-mcp
uv tool install .

# Check the install: starts the server and performs the MCP handshake, touching nothing on GitHub
python3 scripts/mcp_handshake_smoke.py gh-project-mcp

# Register it with Claude Code, naming the repository whose issues hold the tracker
claude mcp add gh-project gh-project-mcp -e GH_PROJECT_REPO=owner/name
```

Then ask your agent to call `get_status`. On an empty repository it says so and points at `create_requirement`.

**The repository is always named, never guessed.** The server does not look at the directory it runs in or at any
git remote. Until `GH_PROJECT_REPO` is set it starts, lists its tools and answers every call with how to set it,
sending nothing to GitHub.

To look before you leap, add `-e GH_PROJECT_READ_ONLY=on`: every tool that writes is refused before any request is
made, and the dashboard, queries and export work as normal.

## How records are stored

Nothing is stored anywhere but GitHub. The server has no database and writes no state to disk; restarting it loses
nothing, and two machines pointed at one repository see the same tracker.

| | On GitHub |
|---|---|
| Kind | A label: `requirement`, `decision` or `task` |
| Priority | A label: `P0` to `P3` |
| Status | A `status:...` label while the issue is open; the close reason once it is closed |
| Fields | `## Heading` sections of the issue body |
| A requirement's tasks, a task's subtasks | Sub-issues |
| A dependency | A "blocked by" link |
| A project | A milestone, whose description opens with the project's purpose |
| History | The issue's own timeline and comments |

A requirement looks like this on github.com:

```markdown
**Type:** NFUNC · **Risk:** Medium

## Current state

Search runs unindexed over every note; at 10k notes a query takes about 900 ms.

## Desired state

Search stays quick as the collection grows.

## Acceptance criteria

- [ ] A search over 10k notes returns in under 50 ms at p95

## Validation metrics

- Search p95 under 50 ms at 10k notes, measured by the benchmark task
```

**You can edit any of it by hand.** The server reads a body as segments and rewrites only the section of the field
being changed. A note you add, a section it does not recognise, and the boxes you tick all stay exactly as you left
them. An issue you write yourself becomes a record when you give it a kind label.

### Statuses

| Kind | Open, by label | Closed as completed | Closed as not planned |
|---|---|---|---|
| Requirement | Draft (no label), Under Review, Approved, Implemented | Validated | Deprecated |
| Task | Not Started (no label), In Progress, Blocked | Complete | Abandoned |
| Decision | Proposed (no label) | Accepted | Rejected, or Superseded with `status:superseded` |

Because closing is a status, a pull request that says `Closes #12` completes task 12 with no help from the server.

`setup_repository` creates the labels with colours and descriptions. It is optional: the first write does the
same. If the names collide with labels your repository already uses, set `GH_PROJECT_LABEL_PREFIX`.

## Tools

The server lists 14 tools. Records are addressed by issue number: `12` and `"#12"` both work. Every tool refuses
arguments it does not declare and says which it does take. Results are text for the model, with the same facts as
data in `structuredContent`.

**Writing records**
- `create_requirement` - Create a requirement. It starts in Draft
- `create_decision` - Record an architecture decision (ADR). It starts Proposed
- `create_task` - Create a task as a sub-issue of the requirement it implements, or of a parent task
- `update_record` - Edit a record in place; only what you name changes
- `add_comment` - Comment on a record's issue

**Status and links**
- `set_status` - Move one record or several to a status, along the allowed path
- `link_records` - Link two records: `child_of`, `blocked_by`, `addresses`, `supersedes`
- `unlink_records` - Remove a link

**Reading**
- `get_status` - The dashboard: what is ready, blocked, waiting, awaiting a decision, and what has drifted
- `get_record` - One record in full, with its links, and its comments and timeline on request; or one project
- `query_records` - Find records by kind, status, priority, project or text; or the ready and work-complete sets

**Projects, export, setup**
- `save_project` - Create, edit, close or reopen a project
- `export_docs` - Write requirements, decisions and tasks as Markdown, and a Mermaid diagram of the links
- `setup_repository` - Create the labels the server uses

It also offers two MCP prompts, which cost nothing against the tool listing: `capture_requirement`, a guide to
writing a well-formed requirement, and `reconcile_requirements`, which compares a transcript, document or codebase
with the stored requirements and sorts what it finds into new, amends, already covered and contradicted.

### Fields

`create_requirement` takes `title`, `type` (FUNC, NFUNC, TECH, BUS, INTF), `priority`, `current_state` and
`desired_state`, and optionally `risk`, `origin`, `business_value`, `functional_requirements`,
`acceptance_criteria`, `nonfunctional_requirements`, `technical_constraints`, `business_rules`,
`validation_metrics`, `out_of_scope` and `project`.

`create_decision` takes `title`, `context` and `decision`, and optionally `decision_drivers`,
`considered_options`, `positive_consequences`, `negative_consequences`, `risks`, `implementation_notes`,
`validation_criteria`, `addresses` (the requirements it addresses) and `project`.

`create_task` takes `title`, `parent` and `priority`, and optionally `effort` (XS to XL), `user_story`,
`acceptance_criteria`, `implementation_plan`, `test_plan`, `definition_of_done`, `blocked_by` and `assignee`.

`update_record` takes the same names inside `fields`, with `null` to remove one; `title`, `priority`, `project`
and `assignee` are parameters of their own.

## The rules

The server holds its own writes to the lifecycle. Three rules are always on:

- **A status move follows the kind's path.** Draft to Approved goes through Under Review in one call, and the
  result reports the path.
- **Approved and Validated are never passed through.** A move may end at one of them but cannot cross one on the
  way elsewhere: Draft to Implemented is refused, and says to approve it first. These are a person's decisions.
- **A requirement cannot be Validated while a task under it is open.**

Other moves are legal but risky: starting a task whose blockers are unfinished, completing a task with open
subtasks or one that was never started, marking a requirement Implemented while its tasks are open, creating a
task under a requirement nobody has approved, and creating a record that is thin for its kind (a requirement with
no acceptance criteria, an NFUNC requirement with no validation metrics, a P0 or P1 task with no test plan).
`GH_PROJECT_RULES` decides what happens then:

- `warn` (the default): the call goes ahead and the result says why it was risky
- `enforce`: the call is refused before anything is written
- `off`: nothing is checked

**Decisions are not rewritten.** A decision is editable while Proposed. Once Accepted, correct it with
`update_record(amendment=...)`, which adds a dated comment shown directly beneath the decision and leaves its text
alone, or replace it: create a new decision and `link_records(source=new, type="supersedes", target=old)`, which
moves the old one to Superseded.

**Editing an approved requirement needs a reason**, which is posted on the issue.

**Nothing moves on its own.** When every task under a requirement is finished, the dashboard lists it under *Work
complete, decision pending*. Saying it is implemented is still yours to do.

### Drift

Anyone with access can close an issue or change its labels on github.com, so the server cannot guarantee its
rules the way a private database could. It does the next best thing: the same rules run over what it reads, and
`get_status` lists whatever breaks them under *Drift*. For example, a requirement closed as completed while a task
under it is open, an issue with two status labels, a task in progress under a requirement that is still a draft,
or a decision marked superseded that nothing supersedes.

Drift is reported and never repaired. A read never writes, and the server does not overrule a person's edit.

### Evidence

`set_status` takes `comment`, `commit` and `evidence`. They are posted as a comment, so the reasoning is on the
issue's timeline, and for a task the commit and evidence are also kept in its body, where they stay until replaced.
A move to Blocked keeps its comment as the task's blocked reason until the task leaves Blocked. To add evidence to
a task that is already Complete (closed by a pull request, say), call `set_status` with its current status: the
facts are recorded and the status is left alone.

## Configuration

| Variable | Meaning |
|---|---|
| `GH_PROJECT_REPO` | The repository, as `owner/name`. Required |
| `GH_TOKEN`, `GITHUB_TOKEN` | A token with the `repo` scope. If neither is set, `gh auth token` is used |
| `GH_PROJECT_RULES` | `warn` (default), `enforce` or `off`. See [The rules](#the-rules) |
| `GH_PROJECT_READ_ONLY` | `on` refuses every tool that writes, before any request is made |
| `GH_PROJECT_LABEL_PREFIX` | Put before every label the server uses, for example `lc:` gives `lc:task` |
| `GH_PROJECT_API_URL` | The API base URL, for GitHub Enterprise. Default `https://api.github.com` |
| `GH_PROJECT_CALL_LOG` | A file to append one JSON line per tool call to: tool, argument names (never values), duration, whether it failed and why, response size |

## Limits

These follow from keeping records in GitHub's own features:

- **A task implements one requirement**, because an issue has one parent.
- **A requirement is in one project**, because an issue has one milestone.
- **A parent holds at most 100 sub-issues**, eight levels deep. That is GitHub's limit.
- **No offline use.** Every call talks to GitHub. Reading the whole tracker costs one request per 100 records the
  first time and one request per call after that.
- **Records are not deleted.** Close a mistake as Deprecated, Abandoned or Rejected.
- **A status label is only a label.** The server cannot tell whether a person or an agent applied `status:approved`.
- **Personal and organisation repositories both work.** GitHub Projects boards and organisation issue types are
  not used.

## How it differs from lifecycle-mcp

| | lifecycle-mcp | gh-project-mcp |
|---|---|---|
| Store | A local SQLite file | GitHub issues; no local state |
| Seeing the tracker | An exported HTML snapshot | github.com |
| Record IDs | `REQ-0001-FUNC-00`, `TASK-0001-00-00`, `ADR-0001` | Issue numbers |
| Links | Twelve types in one table | Sub-issues, blocked-by, and two decision links |
| Requirement statuses | Eight | Six: Architecture and Ready are gone |
| Rules | Guaranteed: every write goes through the server | Held on the server's writes; reported as drift otherwise |
| History | Its own event table, with before and after values | The issue timeline and comments |
| Tools | 25, about 17,000 characters of definitions | 14, under 9,000 |
| MCP SDK | 1.x | 2.x |

Not carried over: short-ID aliases, the SQL dump and restore, the HTML viewer, revision counters, deleting
records, and tasks or projects with several parents.

## Development

```bash
uv sync --extra test --extra dev
make test      # the suite; runs with no network and cannot reach GitHub
make lint      # what CI runs
make smoke     # start the server over stdio and check the handshake and stdout
make surface   # tool definition sizes against the budget
```

The suite runs against an in-memory GitHub. A fixture fails any test that opens a network connection or starts a
process, so the tests cannot create an issue anywhere.

To run the same contract tests against real GitHub, name a repository you do not mind filling with test issues.
Its name must contain `sandbox`:

```bash
GH_PROJECT_LIVE_REPO=you/gh-project-sandbox uv run --extra test pytest -m github_live
```

See [CLAUDE.md](CLAUDE.md) for the module map and the rules a change has to keep.

## Troubleshooting

**"MCP error -32000: Connection closed"**: the server exited or wrote something other than protocol messages to
stdout. Run `python3 scripts/mcp_handshake_smoke.py gh-project-mcp`; it reports which.

**"No repository is configured"**: set `GH_PROJECT_REPO` where the server is registered, as in
[Quick start](#quick-start).

**"no GitHub token"** or **"the token was rejected"**: set `GH_TOKEN`, or run `gh auth login`. The token needs the
`repo` scope.

**"#12 is not a lifecycle record"**: issue 12 exists but carries no kind label, or does not exist. Give it one of
`requirement`, `decision` or `task` to make it a record.

**"rate limit exhausted"**: the message says when it resets. The server does not retry on its own.

## License

MIT. See [LICENSE](LICENSE).
