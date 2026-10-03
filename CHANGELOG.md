# Changelog

## 0.1.0 - unreleased

First version. A ground-up successor to lifecycle-mcp that keeps its records as GitHub issues.

- Requirements, architecture decisions and tasks as issues: kind and priority as labels, status as a label while
  open and the close reason once closed, fields as Markdown sections of the body
- A body codec that rewrites only the section of the field being edited, leaving anything a person wrote
- Status lifecycles with a transition map per kind; Approved and Validated are never passed through
- Workflow rules in `warn`, `enforce` and `off` modes, and three that are always on
- Links through GitHub's own features: sub-issues, blocked-by, and decision links in the decision's body
- Projects as milestones with a stated purpose
- A dashboard: ready, blocked, waiting, work complete with the decision pending, and drift
- Export to Markdown documents and a Mermaid diagram, deterministic
- 14 tools within a budget of 16 tools and 9,000 characters, and two prompts
- A read-only mode, a label prefix, a call log, GitHub Enterprise by base URL
- A test suite that runs against an in-memory GitHub and cannot open a connection or spawn a process

Read paths have been run against real GitHub; writes have not. See "What has and has not been run against real
GitHub" in CLAUDE.md.
