# CLAUDE.md

Guidance for working in this repository. README.md says what the server does and lists its tools; this file holds
what a change has to keep and cannot be inferred from the code.

## Commands

```bash
uv sync --extra test --extra dev
make test        # the suite; no network, cannot reach GitHub
make lint        # CI's lint step exactly; run before pushing
make smoke       # start the server over stdio: handshake and clean stdout
make surface     # tool definition sizes against tests/tool_surface_budget.json

uv run --extra test pytest tests/test_body.py -k round_trip     # one test
GH_PROJECT_LIVE_REPO=you/some-sandbox uv run --extra test pytest -m github_live   # against real GitHub
```

## What this is

An MCP server that keeps requirements, architecture decisions and tasks as GitHub issues. GitHub is the only
store (ADR-0001): there is no database, no migration, no file of state. It succeeds lifecycle-mcp in spirit, and
where GitHub has a native feature the server uses it rather than re-creating a table.

The requirements, the decisions behind the design (ADR-0001 to ADR-0006) and the tasks are in `docs/planning/`,
exported from the lifecycle-mcp tracker this project was planned in (`lifecycle.db`, local and gitignored). Read
the architecture document before changing how records are stored; the README's "How records are stored" and
"The rules" sections are its user-facing form. Those files are generated: change the tracker and export again.

## Module map

- `kinds.py` - the fields of each kind and how each is written in a body. The one description of the fields: the
  codec, the tool schemas and the README's field lists all come from it
- `body.py` - the body codec. A body is segments (text before the first `## ` heading, then one per section) and
  every segment keeps its original text; setting a field re-renders that field's segment only
- `status.py` - labels and state to status and back, and the label vocabulary. Nothing else reads a label name or
  a close reason
- `rules.py` - transition maps, stop statuses, the rules mode, and the predicates (ready, work complete, unmet
  blockers, drift). Each rule is one predicate used both to refuse a write and to report drift
- `github/port.py` - the `GitHub` protocol and its dataclasses. `github/http.py` implements it over httpx
  (GraphQL for the snapshot, REST for writes), `github/fake.py` in memory, `github/readonly.py` wraps either
- `tracker.py` - the in-memory snapshot of every lifecycle issue and its links: a read cache, refreshed before
  every tool call and updated in place by the server's own writes
- `registry.py` - `@tool(...)`: one declaration gives a tool its listing, its validation schema and its handler
- `server.py` - the low-level MCP server: validation, refusal messages, routing, the call log
- `tools/` - the handlers, one module per area. `tools/trail.py` holds the comment formats the server writes
- `prompts.py` - the two prompts
- `app.py`, `config.py` - what a call runs against, and the environment variables

## Rules

- **stdout is the protocol channel.** Never `print()` in `src/` (ruff T20 enforces it); log to stderr.
  `make smoke` checks a running server
- **Tests cannot leave the process.** `tests/conftest.py` fails any test that opens a connection or spawns a
  process. Do not weaken it to make a test pass: lifecycle-mcp's suite once created 1,049 real issues upstream.
  Tests that need real GitHub are marked `github_live` and refuse any repository whose name lacks `sandbox`
- **Only `github/` touches the network.** Nothing outside it imports httpx or subprocess; a test reads the imports
- **The repository is named, never inferred.** `GH_PROJECT_REPO` only. Do not add a fallback to the git remote
- **A read never writes.** Drift is reported and never repaired; tests assert the fake's write log is empty
- **Rules are checked before anything is written.** A refused call leaves GitHub untouched, and its test says so
  with `github.writes == []`
- **One codec, one status derivation.** A handler that inspects `issue.labels` for a status, or searches a body
  for a heading, is a bug waiting for the conventions to change. Go through `status.derive`/`encode` and `Document`
- **The body is not ours.** Never re-render a whole body. `edit_body` changes the named fields and nothing else,
  and the property tests in `tests/test_body.py` hold that
- **Strict inputs.** Every schema has `additionalProperties: false`. Declare every parameter a handler reads;
  `tests/test_tool_surface.py` reads the handlers' source for undeclared ones
- **The tool surface has a budget.** Adding a tool or parameter means raising `tests/tool_surface_budget.json` in
  the same change, and it may not exceed 16 tools or 9,000 characters (REQ-0001-INTF-00). Prefer a parameter on an
  existing kind-generic tool to a new tool
- **Refusals reach the client as errors.** Handlers raise `ToolError` (or `StatusRefused`, `NotARecord`,
  `GitHubError`, `ConfigError`); the server returns them with `isError` true. Say what to do instead
- **A signal that always fires teaches the reader to ignore it.** No dashboard section may list a record merely
  for being new. `test_a_new_record_is_not_reported_for_being_new` holds that for drift

## How it works

- **The snapshot.** The first refresh lists the issues carrying a kind label (one GraphQL page per 100) and the
  milestones. Later refreshes are one GraphQL query with two halves: every open record with its current links, and
  every issue updated since the cursor, labelled or not (which is how a closed record, or one whose kind label was
  removed, is seen). Both halves are needed: GitHub does not bump `updated_at` when a sub-issue or blocked-by link
  changes, so `since` alone never sees a link someone made on github.com. A link changed by hand on a *closed*
  record is still missed until that issue changes some other way. After the cold load the cursor is GitHub's own clock (the `Date` header
  of the answer) less two minutes, not the newest record's `updated_at`: in a repository busy with other issues
  that would fetch all of them once. Never the local clock. A write's REST response carries no links, so
  `Tracker.put` keeps the links the snapshot holds; link writes update them with `set_parent`/`set_blocked_by`
- **The tree comes from the child.** `Tracker.children` reads each record's own `parent`, not the parent's
  sub-issue list, so the two ends cannot disagree when only one was refreshed
- **Status moves are one write.** `set_status` computes the path, runs the always-on rules and the mode rules for
  each step, then sets the final labels and state in a single issue update. A comment is posted only when it says
  more than the label change does: a multi-step path, a comment, a commit or evidence
- **Current facts live in the body, the trail in comments.** A task's blocked reason, commit and evidence are body
  sections because the body is in the snapshot and comments are not; the dashboard and export would otherwise cost
  a request per task. Amendments are comments, so a decided decision costs one request to read in full
- **Decision links are in the decision's body** (`Addresses`, `Supersedes`), found by scanning decisions. GitHub
  has no native link for them
- **Projects are milestones.** The description goes through the same codec with the `project` field spec, whose
  purpose is the text before the first heading, so a hand-written milestone reads as a project

## What has been run against real GitHub

`heffrey78/gh-project-sandbox` is the sandbox: private, and filled with test issues by design. On 2026-10-03:

- the contract tests (`pytest -m github_live`) pass against it
- the script `scripts/live_run.py` drove a whole lifecycle through the server over stdio: 41 calls to all 14 tools, the only
  errors the two refusals it asks for, and drift made by hand with `gh issue edit` reported. See `docs/live-run.md`
- it found what the fake had wrong: link changes do not bump `updated_at`, and the timeline names a link's other
  end under `sub_issue`, `parent_issue`, `blocked_by` or `blocking`. `FakeGitHub` now behaves the same way. When the
  live run and the fake disagree, fix the fake and add a contract test that pins the behaviour

Run both after any change to `github/http.py`, `tracker.py` or the contract tests:

```bash
GH_PROJECT_LIVE_REPO=heffrey78/gh-project-sandbox uv run --extra test pytest -m github_live
uv run python scripts/live_run.py heffrey78/gh-project-sandbox
```
