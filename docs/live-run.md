# Live run against GitHub

The fake GitHub the test suite uses is only as good as its agreement with the real one. This is the record of
checking that agreement. Run it again after any change to `src/gh_project_mcp/github/http.py`,
`src/gh_project_mcp/tracker.py` or the contract tests:

```bash
GH_PROJECT_LIVE_REPO=heffrey78/gh-project-sandbox uv run --extra test pytest -m github_live
uv run python scripts/live_run.py heffrey78/gh-project-sandbox docs/live-run-transcript.md
```

Both write real issues. They refuse any repository whose name does not contain `sandbox`.

## 2026-10-03, heffrey78/gh-project-sandbox (private)

**Contract tests:** 16 pass, and passed three runs in a row after the fixes below.

**Whole lifecycle over stdio:** 41 calls to all 14 tools in about 47 seconds, median call just under a second.
The only errors were the two refusals the script asks for: Draft to Implemented (passes through Approved) and
rewriting an Accepted decision. A requirement given two status labels by hand with `gh issue edit` was reported
as drift. The full output is in [live-run-transcript.md](live-run-transcript.md).

**Read paths on a busy repository** (heffrey78/lifecycle-mcp, about 2,170 issues, read-only, 2026-10-02): a cold
dashboard cost 2 requests and a warm one 1.

### What it found

| Found | Effect | Fixed by |
|---|---|---|
| GitHub does not bump `updated_at` when a sub-issue or blocked-by link is added, on either issue | A link made on github.com was never seen by the incremental refresh. The fake bumped it, so the offline tests could not notice | The refresh is one GraphQL query for every open record with its links plus every issue changed since. The fake now leaves `updated_at` alone on link changes. ADR-0001's open risk is closed |
| The timeline names a link's other end under `sub_issue`, `parent_issue`, `blocked_by` or `blocking` | History showed link events without saying which issue | `_event` in `http.py` reads those keys |
| Events in the same second come back in any order | A contract test that assumed strict order failed one run in three | The test asserts only what GitHub guarantees: oldest first, to the second |
| The contract tests labelled their throwaway issues `task` | The sandbox's dashboard counted them and reported them as drift | The tests use labels outside the server's vocabulary |
| Drift fired on hand-written bodies of closed issues, and "never started" on a parent finished through its subtasks | Warnings that are always true teach the reader to skip them | Both rules now look only at work that is still live |

### What it costs

A warm refresh is now one request per 100 open records, not one request whatever the size: the price of seeing
links changed by hand. A link changed by hand on a *closed* record is still not seen until that issue changes in
some other way.
